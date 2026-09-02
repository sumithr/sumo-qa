# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""POC boundary tests for issue #557's code-enforced review gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from experiments.issue_557.compare_results import (
    CONFIGS,
    EVAL_ROOT,
    FULL_REVIEW_GROUP_NAMES,
    GROUPS,
    _direct_positive_usage,
    compare_evidence,
)
from experiments.issue_557.run_candidate import (
    FULL_REVIEW_GROUPS,
    PINNED_GROUPS,
    _render_prompt,
    build_direct_config,
    build_prompts,
    build_review_context,
    candidate_prompt,
    candidate_prompt_for_group,
    load_group,
    validate_result_record,
    write_grade_config,
)
from experiments.issue_557.run_subscription_eval import (
    codex_command,
    parse_codex_jsonl,
    render_llm_rubric,
    repair_prompt,
    subscription_environment,
    summarize,
)
from sumo_qa.review_gate_poc import (
    InventoryDrift,
    ReviewContext,
    ReviewFeedback,
    ReviewGateValidationError,
    validate_review_response,
)


def _response(
    *,
    scope: str = "passed",
    risks: str = "passed",
    verification: str = "passed",
    review: str = ("Command: pytest tests/auth -q -> 42 passed, 2 skipped\nVerdict: SAFE TO MERGE"),
    extra_claims: list[dict] | None = None,
) -> str:
    def claim(gate: str, status: str) -> dict:
        evidence = []
        if status in {"passed", "failed", "blocked"}:
            evidence = [{"source": "manual_observation", "detail": f"observed {gate}"}]
        return {
            "gate": gate,
            "status": status,
            "statement": f"{gate} is {status}",
            "evidence": evidence,
        }

    report = {
        "schema_version": "1.0",
        "claims": [
            claim("scope", scope),
            claim("risks", risks),
            claim("verification", verification),
            *(extra_claims or []),
        ],
    }
    return f"<GATE_REPORT>\n{json.dumps(report)}\n</GATE_REPORT>\n<REVIEW>\n{review}\n</REVIEW>"


def _grading_result(
    output: str,
    assertion: dict,
    *,
    success: bool,
    score: float,
) -> dict:
    tokens = {"prompt": 10, "completion": 5, "total": 15, "numRequests": 1}
    return {
        "pass": success,
        "score": score,
        "tokensUsed": tokens,
        "componentResults": [
            {
                "assertion": assertion,
                "pass": success,
                "score": score,
                "tokensUsed": tokens,
                "metadata": {
                    "renderedGradingPrompt": (
                        f"--- CANDIDATE RESPONSE ---\n{output}\n--- END CANDIDATE RESPONSE ---"
                    )
                },
            }
        ],
    }


def test_clean_report_allows_evidence_backed_safe_verdict() -> None:
    validated = validate_review_response(_response())

    assert validated.safe_to_merge is True
    assert validated.review.endswith("Verdict: SAFE TO MERGE")
    assert {claim.gate for claim in validated.report.claims} == {
        "scope",
        "risks",
        "verification",
    }


@pytest.mark.parametrize("gate", ["scope", "risks", "verification"])
def test_unresolved_mandatory_gate_rejects_safe_verdict(gate: str) -> None:
    kwargs = {gate: "unverified"}

    with pytest.raises(ReviewGateValidationError, match=gate):
        validate_review_response(_response(**kwargs))


def test_unresolved_gate_allows_not_safe_verdict() -> None:
    review = "Verification remains unverified.\nVerdict: NOT SAFE TO MERGE"

    validated = validate_review_response(_response(verification="unverified", review=review))

    assert validated.safe_to_merge is False
    assert validated.review == review


def test_safe_verdict_without_visible_evidence_source_is_rejected() -> None:
    with pytest.raises(ReviewGateValidationError, match="unsupported_claim"):
        validate_review_response(_response(review="Verdict: SAFE TO MERGE"))


def test_missing_required_gate_is_rejected() -> None:
    raw = _response()
    raw = raw.replace('"gate": "scope", ', '"gate": "not_scope", ', 1)

    with pytest.raises(ReviewGateValidationError, match="missing required gate.*scope"):
        validate_review_response(raw)


def test_duplicate_gate_is_rejected() -> None:
    duplicate = {
        "gate": "scope",
        "status": "passed",
        "statement": "duplicate",
        "evidence": [{"source": "file_read", "detail": "read diff"}],
    }

    with pytest.raises(ReviewGateValidationError, match="duplicate gate.*scope"):
        validate_review_response(_response(extra_claims=[duplicate]))


def test_invalid_gate_report_uses_existing_typed_validation() -> None:
    raw = _response().replace('"schema_version": "1.0"', '"schema_version": "2.0"')

    with pytest.raises(ReviewGateValidationError, match="schema_version_mismatch"):
        validate_review_response(raw)


def test_invalid_gate_report_json_is_rejected() -> None:
    raw = _response().replace('{"schema_version": "1.0"', "not-json", 1)

    with pytest.raises(ReviewGateValidationError, match="gate report is not valid JSON"):
        validate_review_response(raw)


def test_model_owned_judgment_is_returned_byte_for_byte() -> None:
    review = (
        "Risk: retry duplication at worker.py:41.\n"
        "Technique: state transition testing.\n"
        "Depth: exercise two deliveries with one side effect.\n"
        "Verdict: NOT SAFE TO MERGE"
    )

    validated = validate_review_response(
        _response(risks="failed", verification="unverified", review=review)
    )

    assert validated.review == review
    assert "retry duplication" in validated.review
    assert "state transition testing" in validated.review


def _nonblank_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def test_scorecard_emitted_before_the_verdict_is_normalised_below_it() -> None:
    # The contract layer buys this ordering rule with prompt tokens ("the
    # literal `Verdict: ...` line must appear before the scorecard heading or
    # table").  It is pure structure, so code can enforce it for free.
    review = (
        "## Readiness scorecard\n"
        "| Signal | Result |\n"
        "| --- | --- |\n"
        "| Coverage | not measured |\n"
        "Risk: stale changelog anchor at CHANGELOG.md:12.\n"
        "Verdict: NOT SAFE TO MERGE"
    )

    validated = validate_review_response(_response(risks="failed", review=review))

    assert validated.review.index("Verdict: NOT SAFE TO MERGE") < validated.review.index(
        "## Readiness scorecard"
    )
    # Only the ordering may change: every model-authored line survives verbatim,
    # so the normaliser cannot drop or invent judgment.
    assert sorted(_nonblank_lines(validated.review)) == sorted(_nonblank_lines(review))


def test_review_already_in_contract_order_is_returned_unchanged() -> None:
    # Adjacent class: correctly-ordered output must pass through untouched, or
    # the normaliser is scrambling reviews that were already right.
    review = (
        "Risk: stale changelog anchor at CHANGELOG.md:12.\n"
        "Verdict: NOT SAFE TO MERGE\n"
        "## Readiness scorecard\n"
        "| Signal | Result |\n"
        "| --- | --- |\n"
        "| Coverage | not measured |"
    )

    validated = validate_review_response(_response(risks="failed", review=review))

    assert validated.review == review


def test_ledger_table_emitted_before_the_verdict_is_normalised_below_it() -> None:
    review = (
        "Risk ledger:\n"
        "| Risk | Statement | Source | Test / check | Evidence | Residual |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| R1 | retry duplication | worker.py:41 | none | planned | blocker |\n"
        "Verdict: NOT SAFE TO MERGE"
    )

    validated = validate_review_response(_response(risks="failed", review=review))

    assert validated.review.index("Verdict: NOT SAFE TO MERGE") < validated.review.index(
        "Risk ledger:"
    )
    assert sorted(_nonblank_lines(validated.review)) == sorted(_nonblank_lines(review))


def test_supplied_context_is_carried_onto_the_validated_review() -> None:
    context = ReviewContext()

    validated = validate_review_response(_response(), context=context)

    assert validated.context is context


def test_review_context_is_built_from_the_real_ac_scenario_fixtures() -> None:
    # The eval fixture plays the host. If this stops extracting, the boundary
    # silently validates nothing and the stripped prompt rules go unenforced.
    _, tests, _ = load_group("full-ac-coverage")

    counts = [len(build_review_context(test["vars"]).acceptance_criteria) for test in tests]

    assert counts == [3, 2, 2]


def test_review_context_tracks_saved_feedback_presence_per_scenario() -> None:
    _, tests, _ = load_group("full-feedback-memory")

    contexts = [build_review_context(test["vars"]) for test in tests]

    assert [context.saved_review_feedback is not None for context in contexts] == [True, False]
    supplied = contexts[0].saved_review_feedback
    assert supplied is not None
    assert "timezone or day-boundary logic" in supplied.trigger


def test_repair_prompt_omits_the_scenario_task_but_carries_the_contract() -> None:
    # A repair fixes response shape, not judgment. Resending the scenario task
    # made each repair cost a second full generation (25.41 points of the 46
    # scenario run's token reduction).
    _, tests, _ = load_group("full-ac-coverage")
    _, candidate_prompts, _ = build_prompts(
        "full-ac-coverage", candidate_profile="repaired-compact"
    )
    scenario_prompt = candidate_prompts[0][1]
    skill_body = str(tests[0]["vars"]["skill_content"])

    prompt = repair_prompt("<GATE_REPORT>...</GATE_REPORT>", "an 'unverified' gate claim must...")

    assert "## Machine-enforced response contract" in prompt
    assert "an 'unverified' gate claim must..." in prompt
    assert "<GATE_REPORT>...</GATE_REPORT>" in prompt
    assert skill_body not in prompt
    assert len(prompt) < len(scenario_prompt) // 2


def test_review_context_is_empty_without_ground_truth() -> None:
    assert build_review_context({}) == ReviewContext()


def test_supplied_context_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ReviewContext(acceptance_critera=["typo in the field name"])  # type: ignore[call-arg]


def test_missing_row_for_a_supplied_acceptance_criterion_is_rejected() -> None:
    context = ReviewContext(
        acceptance_criteria=[
            "refund reverses the ledger entry",
            "audit log records the actor",
        ]
    )
    review = (
        "AC1: refund reverses the ledger entry | Classification: MET | Anchor: refund.py:22\n"
        "Verdict: NOT SAFE TO MERGE"
    )

    with pytest.raises(ReviewGateValidationError, match="acceptance criterion"):
        validate_review_response(_response(risks="failed", review=review), context=context)


def test_acceptance_criterion_the_host_did_not_supply_is_rejected() -> None:
    context = ReviewContext(acceptance_criteria=["refund reverses the ledger entry"])
    review = (
        "AC1: refund reverses the ledger entry | Classification: MET | Anchor: refund.py:22\n"
        "AC2: invented criterion | Classification: UNMET | Anchor: none\n"
        "Verdict: NOT SAFE TO MERGE"
    )

    with pytest.raises(ReviewGateValidationError, match="acceptance criterion"):
        validate_review_response(_response(risks="failed", review=review), context=context)


def test_one_row_per_supplied_acceptance_criterion_is_accepted() -> None:
    context = ReviewContext(
        acceptance_criteria=[
            "refund reverses the ledger entry",
            "audit log records the actor",
        ]
    )
    review = (
        "AC1: refund reverses the ledger entry | Classification: MET | Anchor: refund.py:22\n"
        "AC2: audit log records the actor | Classification: UNMET | Anchor: none\n"
        "Verdict: NOT SAFE TO MERGE"
    )

    validated = validate_review_response(_response(risks="failed", review=review), context=context)

    assert validated.safe_to_merge is False


def test_inventory_drift_row_paraphrasing_the_supplied_pair_is_rejected() -> None:
    context = ReviewContext(
        inventory_drift=[InventoryDrift(path="docs/tools.md", old="48 tools", new="52 tools")]
    )
    review = (
        "Inventory drift anchor: docs/tools.md:12 (still 48 tools) | Coverage: UNCOVERED\n"
        "Verdict: NOT SAFE TO MERGE"
    )

    with pytest.raises(ReviewGateValidationError, match="inventory drift"):
        validate_review_response(_response(risks="failed", review=review), context=context)


def test_inventory_drift_row_copying_the_supplied_pair_verbatim_is_accepted() -> None:
    context = ReviewContext(
        inventory_drift=[InventoryDrift(path="docs/tools.md", old="48 tools", new="52 tools")]
    )
    review = (
        "Inventory drift anchor: docs/tools.md:12 (48 tools → 52 tools) | Coverage: UNCOVERED\n"
        "Verdict: NOT SAFE TO MERGE"
    )

    validated = validate_review_response(_response(risks="failed", review=review), context=context)

    assert validated.safe_to_merge is False


def test_absent_memory_line_is_rejected_when_feedback_was_supplied() -> None:
    context = ReviewContext(
        saved_review_feedback=ReviewFeedback(trigger="hook change", probe="run the hook end to end")
    )
    review = (
        "no saved review feedback supplied, advisory-hint check skipped\nVerdict: NOT SAFE TO MERGE"
    )

    with pytest.raises(ReviewGateValidationError, match="absent-memory"):
        validate_review_response(_response(risks="failed", review=review), context=context)


def test_advisory_hint_line_is_rejected_when_no_feedback_was_supplied() -> None:
    context = ReviewContext()
    review = (
        "advisory hint from saved review feedback (trigger: hook change): rerun the hook\n"
        "Verdict: NOT SAFE TO MERGE"
    )

    with pytest.raises(ReviewGateValidationError, match="advisory-hint"):
        validate_review_response(_response(risks="failed", review=review), context=context)


@pytest.mark.parametrize(
    "value",
    [
        "NONE",
        "**NONE**",
        "`NONE`",
        "_NONE_",
        "~~NONE~~",
        "(NONE)",
        "<em>NONE</em>",
        "&nbsp;NONE",
        "&#160;NONE",
    ],
)
def test_none_is_rejected_as_a_coverage_status(value: str) -> None:
    review = f"Risk: retry duplication | Coverage: {value}\nVerdict: NOT SAFE TO MERGE"

    with pytest.raises(ReviewGateValidationError, match="not a coverage status"):
        validate_review_response(_response(risks="failed", review=review))


@pytest.mark.parametrize(
    "value",
    [
        "UNVERIFIED",
        "**UNMET**",
        "`UNMET`",
        "_UNMET_",
        "**UNCOVERED**",
        "_UNPROVEN_",
        "~~UNMET~~",
        "(UNMET)",
        '"UNMET"',
        "[UNMET]",
        "<strong>UNMET</strong>",
        "&nbsp;UNMET",
        "&#160;&nbsp;UNVERIFIED",
    ],
)
def test_safe_verdict_with_an_unresolved_classification_is_rejected(value: str) -> None:
    review = (
        "Command: pytest tests/auth -q -> 42 passed\n"
        f"AC1: refund reverses the ledger entry | Classification: {value} | Anchor: none\n"
        "Verdict: SAFE TO MERGE"
    )

    with pytest.raises(ReviewGateValidationError, match="unresolved"):
        validate_review_response(_response(review=review))


@pytest.mark.parametrize(
    "row",
    [
        # A longer word or an identifier is not the bare value.
        "AC1: metering | Classification: MET | Anchor: Coverage: COVERED (UNMETERED path)",
        "AC1: metering | Classification: UNMET_BY_DESIGN | Anchor: documented exclusion",
        "Risk: retry | Coverage: UNCOVERED_BY_DESIGN | Anchor: documented exclusion",
    ],
)
def test_resolved_classification_is_not_mistaken_for_an_unresolved_one(row: str) -> None:
    review = f"Command: pytest tests/auth -q -> 42 passed\n{row}\nVerdict: SAFE TO MERGE"
    validated = validate_review_response(_response(review=review))
    assert validated.safe_to_merge is True


def test_internal_declination_naming_an_external_producer_is_rejected() -> None:
    context = ReviewContext(external_producers=["mutmut"])
    review = (
        "External-contract axis: NOT FIRED (internal/self-produced) | Producer: mutmut runner\n"
        "Verdict: NOT SAFE TO MERGE"
    )

    with pytest.raises(ReviewGateValidationError, match="internal/self-produced"):
        validate_review_response(_response(risks="failed", review=review), context=context)


def test_internal_declination_without_an_external_producer_is_accepted() -> None:
    context = ReviewContext(external_producers=["mutmut"])
    review = (
        "External-contract axis: NOT FIRED (internal/self-produced) | Producer: parse_fence\n"
        "Verdict: NOT SAFE TO MERGE"
    )

    validated = validate_review_response(_response(risks="failed", review=review), context=context)

    assert validated.safe_to_merge is False


@pytest.mark.parametrize(
    "review",
    [
        "No exact verdict line.",
        "Verdict: SAFE TO MERGE\nVerdict: NOT SAFE TO MERGE",
        "Verdict: MAYBE",
        "Verdict: SAFE TO MERGE only if a future test passes",
        "Verdict: NOT SAFE TO MERGE, pending a rerun",
        "Verdict:\nSAFE TO MERGE",
        "Verdict:\nSAFE TO MERGE\nonly if a future test passes",
        "Verdict: safe to merge",
        "Command: pytest -q -> 1 passed\nverdict: not safe to merge\nVerdict: SAFE TO MERGE",
        "Verdict:\nNOT SAFE TO MERGE\nVerdict: SAFE TO MERGE",
        "**Verdict:** NOT SAFE TO MERGE\nCommand: pytest -q -> 1 passed\nVerdict: SAFE TO MERGE",
        "**Verdict**: NOT SAFE TO MERGE\nVerdict: SAFE TO MERGE",
        "> Verdict: NOT SAFE TO MERGE\nVerdict: SAFE TO MERGE",
        "Final verdict: NOT SAFE TO MERGE\nVerdict: SAFE TO MERGE",
        "Verdict (final): NOT SAFE TO MERGE\nCommand: pytest -q -> 1 passed\nVerdict: SAFE TO MERGE",
        "<strong>Verdict</strong>: NOT SAFE TO MERGE\nVerdict: SAFE TO MERGE",
        "The overall verdict is not safe to merge.\nVerdict: SAFE TO MERGE",
        "Verdict (final): NOT SAFE  TO MERGE\nVerdict: SAFE TO MERGE",
        "The overall verdict is NOT SAFE\nTO MERGE.\nVerdict: SAFE TO MERGE",
        "NOT SAFE TO MERGE is the final verdict.\nVerdict: SAFE TO MERGE",
        "The final verdict is\nNOT SAFE TO MERGE.\nVerdict: SAFE TO MERGE",
        "This change is safe to merge once the flag ships.\nVerdict: SAFE TO MERGE",
        "Command: pytest -q -> 1 passed\n_NOT SAFE TO MERGE_\nVerdict: SAFE TO MERGE",
        "_Verdict:_ NOT SAFE TO MERGE\nVerdict: SAFE TO MERGE",
        "_Verdict:_\nVerdict: SAFE TO MERGE",
        "<strong>Verdict</strong>:\nVerdict: SAFE TO MERGE",
        "~~Verdict~~:\nVerdict: SAFE TO MERGE",
    ],
)
def test_exactly_one_supported_verdict_is_required(review: str) -> None:
    with pytest.raises(ReviewGateValidationError, match="exactly one verdict"):
        validate_review_response(_response(review=review))


def test_content_outside_envelopes_is_rejected() -> None:
    with pytest.raises(ReviewGateValidationError, match="outside the envelopes"):
        validate_review_response(f"preamble\n{_response()}")


def test_second_envelope_pair_is_rejected() -> None:
    # The lazy REVIEW group would otherwise absorb a second GATE_REPORT/REVIEW
    # pair, validating the first report while the second is never parsed.
    single = _response()
    with pytest.raises(ReviewGateValidationError, match="exactly one GATE_REPORT"):
        validate_review_response(f"{single}\n{single}")


@pytest.mark.parametrize(
    "prose",
    [
        "AC1: verdict discipline | Classification: MET | Anchor: the verdict line below",
        # Letter-adjacent characters are an identifier, not the phrase.
        "Renamed enum member UNSAFE to MERGED.",
        # Letter-adjacent "Verdict:" is an identifier, not a label.
        "The reviewVerdict: field is serialized.",
        # A decorated label with no phrase states no direction.
        "Verdict (final):",
    ],
)
def test_review_prose_may_name_the_verdict_without_declaring_one(prose: str) -> None:
    review = f"Command: pytest -q -> 1 passed\n{prose}\nVerdict: SAFE TO MERGE"
    validated = validate_review_response(_response(review=review))
    assert validated.review == review
    assert validated.safe_to_merge is True


@pytest.mark.parametrize("tag", ["</REVIEW>", "<REVIEW>", "<GATE_REPORT>", "</GATE_REPORT>"])
def test_review_prose_may_mention_an_envelope_tag(tag: str) -> None:
    review = (
        "Command: pytest -q -> 1 passed\n"
        f"The parser rejected a stray {tag} as expected.\n"
        "Verdict: SAFE TO MERGE"
    )
    validated = validate_review_response(_response(review=review))
    assert validated.review == review
    assert validated.safe_to_merge is True


def test_single_presentation_fence_around_envelopes_is_accepted() -> None:
    validated = validate_review_response(f"```text\n{_response()}\n```")

    assert validated.safe_to_merge is True


def test_pinned_candidate_set_contains_exactly_seven_scenarios() -> None:
    rendered = [scenario for group in PINNED_GROUPS for scenario in build_prompts(group)[1]]

    assert len(rendered) == 7
    assert len({description for description, _ in rendered}) == 7


def test_full_review_candidate_set_covers_every_behavior_config_and_scenario() -> None:
    expected_configs = {
        path.name
        for path in EVAL_ROOT.glob("skill-reviewing-before-merge*.yaml")
        if not path.name.endswith(".ab.yaml")
    }
    rendered = [
        scenario for group in FULL_REVIEW_GROUP_NAMES for scenario in build_prompts(group)[1]
    ]

    assert len(FULL_REVIEW_GROUPS) == 19
    assert {selection.config for selection in FULL_REVIEW_GROUPS.values()} == expected_configs
    assert len(rendered) == 46


def test_candidate_prompts_replace_only_the_skill_with_compact_contract() -> None:
    compact_contract = Path("experiments/issue_557/compact_review_prompt.md").read_text(
        encoding="utf-8"
    )
    full_skill = Path("skills/sumo-qa-reviewing-before-merge/SKILL.md").read_text(encoding="utf-8")
    for group in (*PINNED_GROUPS, *FULL_REVIEW_GROUP_NAMES):
        _, scenarios, _ = build_prompts(group)
        _, baseline_scenarios, _ = build_prompts(group, skill_content=full_skill)
        for (_, prompt), (_, baseline_prompt) in zip(scenarios, baseline_scenarios, strict=True):
            assert prompt == baseline_prompt.replace(full_skill.rstrip(), compact_contract.rstrip())

    _, scenarios, _ = build_prompts("unproven")
    _, prompt = scenarios[0]
    assert compact_contract in prompt
    assert "SEED unproven-substring" not in prompt
    assert "incident records" in prompt
    assert "{{" not in prompt


def test_compact_contract_is_bounded() -> None:
    compact_contract = Path("experiments/issue_557/compact_review_prompt.md").read_text(
        encoding="utf-8"
    )

    assert len(compact_contract) <= 5_500


def test_repaired_compact_adds_only_targeted_precision_contracts() -> None:
    compact = candidate_prompt("compact")
    repaired = candidate_prompt("repaired-compact")
    full = candidate_prompt("full-plain")

    assert compact.split("## Machine-enforced response contract")[-1] in repaired
    assert "## Precision contracts for review edge cases" in repaired
    assert "4-backtick outer fence" in repaired
    assert len(compact) < len(repaired) < len(full) // 4


def test_quality_sweep_profiles_use_current_skill_content() -> None:
    full_skill = Path("skills/sumo-qa-reviewing-before-merge/SKILL.md").read_text(encoding="utf-8")
    full_gated = candidate_prompt("full-gated")
    core_gated = candidate_prompt("core-gated")

    assert full_skill.rstrip() in full_gated
    assert "## Machine-enforced response contract" in full_gated
    assert core_gated.startswith(full_skill.split("### Risk-to-test ledger appendix")[0])
    assert "### Risk-to-test ledger appendix" not in core_gated
    assert "## Red Flags" not in core_gated
    assert len(core_gated) < len(full_gated)

    full_plain = candidate_prompt("full-plain")
    routed_root_plain = candidate_prompt("routed-root-plain")
    balanced_plain = candidate_prompt("balanced-plain")
    warm_plain = candidate_prompt("warm-plain")
    core_plain = candidate_prompt("core-plain")
    assert full_plain == full_skill
    assert "### Risk-to-test ledger appendix" not in routed_root_plain
    assert "## Red Flags — STOP and rework" in routed_root_plain
    assert "## Examples" in routed_root_plain
    assert "Residual concerns are omitted or stated as `none`" in balanced_plain
    assert "## Examples" in balanced_plain
    assert "## Red Flags" not in warm_plain
    assert "## Next skill in the chain" in warm_plain
    assert "### Risk-to-test ledger appendix" not in core_plain
    assert (
        len(core_plain)
        < len(warm_plain)
        < len(balanced_plain)
        < len(routed_root_plain)
        < len(full_plain)
    )


def test_direct_config_replaces_test_level_skill_overrides() -> None:
    direct = build_direct_config("full-ac-coverage", candidate_profile="warm-plain")
    expected_skill = candidate_prompt("warm-plain").rstrip()

    assert direct["defaultTest"]["vars"]["skill_content"] == expected_skill
    assert all("skill_content" not in test["vars"] for test in direct["tests"])
    assert len(direct["tests"]) == 3
    assert direct["providers"] == load_group("full-ac-coverage")[0]["providers"]


def test_repaired_compact_can_be_screened_with_direct_config() -> None:
    direct = build_direct_config("full-fence-parser", candidate_profile="repaired-compact")

    assert (
        direct["defaultTest"]["vars"]["skill_content"]
        == candidate_prompt("repaired-compact").rstrip()
    )


def test_subscription_environment_removes_every_metered_key() -> None:
    env = subscription_environment(
        {
            "PATH": "/bin",
            "OPENAI_API_KEY": "openai-secret",
            "GEMINI_API_KEY": "gemini-secret",
            "CODEX_API_KEY": "codex-secret",
        }
    )

    assert env["PATH"] == "/bin"
    assert env["CODEX_NON_INTERACTIVE"] == "1"
    assert "OPENAI_API_KEY" not in env
    assert "GEMINI_API_KEY" not in env
    assert "CODEX_API_KEY" not in env


def test_subscription_codex_command_is_ephemeral_and_read_only(tmp_path: Path) -> None:
    command = codex_command(
        model="gpt-5.6-luna",
        reasoning_effort="low",
        runner_dir=tmp_path,
    )

    assert command[:2] == ["codex", "exec"]
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[-1] == "-"


def test_subscription_jsonl_requires_tool_free_output_and_usage() -> None:
    stdout = "\n".join(
        (
            json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "review"},
                }
            ),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 20,
                        "output_tokens": 10,
                        "reasoning_output_tokens": 2,
                    },
                }
            ),
        )
    )

    result = parse_codex_jsonl(stdout)

    assert result.output == "review"
    assert result.usage["input_tokens"] == 100
    with pytest.raises(ValueError, match="forbidden item"):
        parse_codex_jsonl(
            stdout.replace(
                '"agent_message", "text": "review"',
                '"command_execution", "text": "review"',
            )
        )


def test_subscription_rubric_renderer_preserves_native_lists_and_context() -> None:
    base = render_llm_rubric("full-base", 0, "candidate output")
    security = render_llm_rubric("full-security-relevance", 0, "candidate output")

    assert "--- CANDIDATE RESPONSE ---\ncandidate output" in base
    assert "Declares safe-to-merge without referencing fresh test output." in base
    assert "SECURITY SHOULD BE CALLED OUT" in security
    assert "--- LOADED CLASSIFICATIONS ---" in security
    assert "--- SCENARIO GROUND TRUTH ---" in base
    assert "Apply the existing rubric and decision table unchanged." in base
    assert "[object Object]" in render_llm_rubric("full-ac-coverage", 1, "candidate output")
    assert "{{" not in base + security
    assert "{%" not in base + security


def test_subscription_summary_requires_all_46_and_quality_preservation() -> None:
    records = []
    for index in range(46):
        records.append(
            {
                "scenario_id": f"full-base:{index}",
                "group": "full-base",
                "index": index,
                "baseline": {
                    "usage": {
                        "input_tokens": 200,
                        "output_tokens": 20,
                        "reasoning_output_tokens": 0,
                    },
                    "grade": {"pass": True},
                },
                "candidate": {
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "reasoning_output_tokens": 0,
                    },
                    "grade": {"pass": True},
                },
                "quality_preserved": True,
            }
        )

    result = summarize(records, minimum_input_reduction=0.01)

    assert result["verdict"] == "PROVEN"
    assert result["quality"]["regressions"] == 0
    assert result["tokens"]["input_reduction_percent"] == 50.0
    records[0]["quality_preserved"] = False
    assert summarize(records, minimum_input_reduction=0.01)["verdict"] == "NOT PROVEN"


def test_direct_config_preserves_rubric_lists_and_stringifies_cold_context() -> None:
    base = build_direct_config("full-base", candidate_profile="full-plain")
    adversarial = build_direct_config("full-adversarial", candidate_profile="full-plain")
    base_variables = base["defaultTest"]["vars"]
    adversarial_variables = adversarial["defaultTest"]["vars"]

    assert isinstance(base_variables["anti_patterns"], list)
    assert isinstance(adversarial_variables["loaded_rules"], str)
    assert isinstance(json.loads(adversarial_variables["loaded_rules"]), dict)
    assert all(isinstance(test["vars"]["anti_patterns"], list) for test in adversarial["tests"])


def test_direct_usage_includes_hidden_reasoning_and_allows_retries() -> None:
    usage = {
        "prompt": 100,
        "completion": 20,
        "total": 150,
        "numRequests": 3,
    }

    assert _direct_positive_usage(usage, minimum_requests=2) == (100, 50)
    assert _direct_positive_usage(usage, minimum_requests=4) is None


def test_routed_root_loads_optional_appendices_only_for_explicit_requests() -> None:
    root = candidate_prompt("routed-root-plain")
    full = candidate_prompt("full-plain")

    assert candidate_prompt_for_group("routed-root-plain", "full-base") == root
    assert candidate_prompt_for_group("routed-root-plain", "full-ledger") == full
    assert candidate_prompt_for_group("routed-root-plain", "full-scorecard") == full


def test_direct_candidate_prompts_replace_only_the_skill_body() -> None:
    profile = "warm-plain"
    for group in FULL_REVIEW_GROUP_NAMES:
        direct = build_direct_config(group, candidate_profile=profile)
        defaults = direct["defaultTest"]["vars"]
        actual = [
            (
                test["description"],
                _render_prompt(direct["prompts"][0], defaults | test.get("vars", {})),
            )
            for test in direct["tests"]
        ]
        expected = build_prompts(group, skill_content=candidate_prompt(profile))[1]

        assert actual == expected


def test_grade_config_uses_echo_with_original_rubric(tmp_path: Path) -> None:
    grade_path = write_grade_config("core", ["Verdict: NOT SAFE TO MERGE"], tmp_path)
    grade_config = yaml.safe_load(grade_path.read_text(encoding="utf-8"))

    assert grade_config["providers"] == ["echo"]
    assert grade_config["prompts"] == ["{{output}}"]
    assert grade_config["tests"][0]["vars"]["output"] == "Verdict: NOT SAFE TO MERGE"
    assert grade_config["defaultTest"]["assert"][0]["type"] == "llm-rubric"
    assert grade_config["defaultTest"]["options"]["provider"]["id"] == "openai:chat:gpt-5.5"


def test_deterministically_rejected_candidate_record_is_not_releasable() -> None:
    with pytest.raises(ValueError, match="did not pass deterministic validation"):
        validate_result_record(
            {
                "validation_passed": False,
                "attempts": [],
                "review": None,
            }
        )


def test_comparison_requires_quality_and_token_reduction(tmp_path: Path) -> None:
    baseline_dir = tmp_path / "baseline"
    candidate_dir = tmp_path / "candidate"
    baseline_dir.mkdir()
    candidate_dir.mkdir()
    prompt_hash = hashlib.sha256(candidate_prompt("compact").encode()).hexdigest()
    raw_response = _response()
    validated = validate_review_response(raw_response)
    for index, group in enumerate(GROUPS):
        model, scenarios, metadata = build_prompts(group)
        _, baseline_scenarios, _ = build_prompts(
            group,
            skill_content=Path("skills/sumo-qa-reviewing-before-merge/SKILL.md").read_text(
                encoding="utf-8"
            ),
        )
        config, current_tests, _ = load_group(group)
        default_test = config["defaultTest"]
        baseline_rows = []
        candidate_results = []
        candidate_grade_rows = []
        for (description, rendered_prompt), (_, baseline_prompt), current_test in zip(
            scenarios, baseline_scenarios, current_tests, strict=True
        ):
            baseline_vars = default_test.get("vars", {}) | current_test.get("vars", {})
            baseline_test_case = {
                "description": description,
                "vars": baseline_vars,
                "assert": default_test["assert"],
                "options": default_test["options"],
            }
            baseline_rows.append(
                {
                    "testCase": baseline_test_case,
                    "prompt": {"raw": baseline_prompt},
                    "provider": {"id": f"openai:chat:{model}"},
                    "response": {
                        "output": validated.review,
                        "tokenUsage": {
                            "prompt": 1_000,
                            "completion": 100,
                            "total": 1_100,
                            "numRequests": 1,
                        },
                    },
                    "success": index > 0,
                    "score": 0.8,
                    "gradingResult": _grading_result(
                        validated.review,
                        default_test["assert"][0],
                        success=index > 0,
                        score=0.8,
                    ),
                }
            )
            candidate_results.append(
                {
                    "description": description,
                    "rendered_prompt_sha256": hashlib.sha256(rendered_prompt.encode()).hexdigest(),
                    "attempts": [
                        {
                            "number": 1,
                            "usage": {
                                "prompt_tokens": 100,
                                "completion_tokens": 90,
                                "total_tokens": 190,
                            },
                            "response": raw_response,
                        }
                    ],
                    "gate_report": validated.report.model_dump(),
                    "safe_to_merge": validated.safe_to_merge,
                    "review": validated.review,
                }
            )
            grade_vars = {
                key: value
                for key, value in default_test.get("vars", {}).items()
                if key
                not in {
                    "skill_content",
                    "loaded_classifications",
                    "loaded_rules",
                    "loaded_techniques",
                }
            } | current_test.get("vars", {})
            candidate_grade_rows.append(
                {
                    "provider": {"id": "echo"},
                    "prompt": {"raw": validated.review},
                    "response": {
                        "output": validated.review,
                        "raw": validated.review,
                    },
                    "testCase": {
                        "description": description,
                        "vars": grade_vars | {"output": validated.review},
                        "assert": default_test["assert"],
                        "options": default_test["options"],
                    },
                    "success": True,
                    "score": 0.9,
                    "gradingResult": _grading_result(
                        validated.review,
                        default_test["assert"][0],
                        success=True,
                        score=0.9,
                    ),
                }
            )
        (baseline_dir / f"issue557-baseline-{group}.json").write_text(
            json.dumps(
                {
                    "config": config,
                    "results": {
                        "stats": {
                            "tokenUsage": {
                                "prompt": 1_000 * len(scenarios),
                                "completion": 100 * len(scenarios),
                                "total": 1_100 * len(scenarios),
                                "numRequests": len(scenarios),
                            }
                        },
                        "results": baseline_rows,
                    },
                }
            ),
            encoding="utf-8",
        )
        (candidate_dir / f"candidate-{group}.json").write_text(
            json.dumps(
                {
                    "group": group,
                    "config": metadata["config"],
                    "compact_prompt_sha256": prompt_hash,
                    "config_sha256": hashlib.sha256(
                        (EVAL_ROOT / CONFIGS[group]).read_bytes()
                    ).hexdigest(),
                    "model": model,
                    "results": candidate_results,
                }
            ),
            encoding="utf-8",
        )
        (candidate_dir / f"candidate-{group}-grade.json").write_text(
            json.dumps(
                {
                    "config": {
                        "description": f"Issue #557 unchanged-rubric grading: {group}",
                        "providers": ["echo"],
                        "prompts": ["{{output}}"],
                        "defaultTest": {
                            "assert": default_test["assert"],
                            "options": default_test["options"],
                        },
                        "tests": [
                            {
                                "description": row["testCase"]["description"],
                                "vars": row["testCase"]["vars"],
                            }
                            for row in candidate_grade_rows
                        ],
                    },
                    "results": {
                        "results": candidate_grade_rows,
                    },
                }
            ),
            encoding="utf-8",
        )

    comparison = compare_evidence(baseline_dir, candidate_dir)

    assert comparison["verdict"] == "PROVEN"
    assert comparison["quality"]["baseline_passed"] == 6
    assert comparison["quality"]["candidate_passed"] == 7
    assert comparison["tokens"]["input_reduction_percent"] == 90.0

    insufficient_savings = compare_evidence(
        baseline_dir,
        candidate_dir,
        minimum_input_reduction_percent=91.0,
    )
    assert insufficient_savings["verdict"] == "NOT PROVEN"
    assert insufficient_savings["tokens"]["target_met"] is False

    candidate_path = candidate_dir / "candidate-core.json"
    original_candidate = candidate_path.read_text(encoding="utf-8")
    tampered_candidate = json.loads(original_candidate)
    tampered_candidate["results"][0]["review"] = "Verdict: SAFE TO MERGE"
    candidate_path.write_text(json.dumps(tampered_candidate), encoding="utf-8")
    stale_review = compare_evidence(baseline_dir, candidate_dir)
    assert stale_review["verdict"] == "NOT PROVEN"
    assert stale_review["integrity"]["candidate_responses_revalidate"] is False
    candidate_path.write_text(original_candidate, encoding="utf-8")

    missing_attempts = json.loads(original_candidate)
    missing_attempts["results"][0]["attempts"] = []
    candidate_path.write_text(json.dumps(missing_attempts), encoding="utf-8")
    invalid_usage = compare_evidence(baseline_dir, candidate_dir)
    assert invalid_usage["verdict"] == "NOT PROVEN"
    assert invalid_usage["integrity"]["usage_is_valid"] is False
    candidate_path.write_text(original_candidate, encoding="utf-8")

    for malformed in (1, [1], [None]):
        malformed_attempts_record = json.loads(original_candidate)
        malformed_attempts_record["results"][0]["attempts"] = malformed
        candidate_path.write_text(json.dumps(malformed_attempts_record), encoding="utf-8")
        malformed_attempts = compare_evidence(baseline_dir, candidate_dir)
        assert malformed_attempts["verdict"] == "NOT PROVEN"
        assert malformed_attempts["integrity"]["candidate_responses_revalidate"] is False
    candidate_path.write_text(original_candidate, encoding="utf-8")

    grade_path = candidate_dir / "candidate-core-grade.json"
    original_grade = grade_path.read_text(encoding="utf-8")
    stale_grade = json.loads(original_grade)
    stale_grade["results"]["results"][0]["testCase"]["vars"]["output"] = "stale review"
    grade_path.write_text(json.dumps(stale_grade), encoding="utf-8")
    unbound_grade = compare_evidence(baseline_dir, candidate_dir)
    assert unbound_grade["verdict"] == "NOT PROVEN"
    assert unbound_grade["integrity"]["grades_bind_validated_reviews"] is False
    grade_path.write_text(original_grade, encoding="utf-8")

    wrong_graded_output = json.loads(original_grade)
    wrong_graded_output["results"]["results"][0]["prompt"]["raw"] = "other output"
    wrong_graded_output["results"]["results"][0]["response"]["output"] = "other output"
    grade_path.write_text(json.dumps(wrong_graded_output), encoding="utf-8")
    mismatched_grade = compare_evidence(baseline_dir, candidate_dir)
    assert mismatched_grade["verdict"] == "NOT PROVEN"
    assert mismatched_grade["integrity"]["grades_bind_validated_reviews"] is False
    grade_path.write_text(original_grade, encoding="utf-8")

    inconsistent_grade = json.loads(original_grade)
    inconsistent_grade["results"]["results"][0]["gradingResult"]["pass"] = False
    grade_path.write_text(json.dumps(inconsistent_grade), encoding="utf-8")
    invalid_grade_result = compare_evidence(baseline_dir, candidate_dir)
    assert invalid_grade_result["verdict"] == "NOT PROVEN"
    assert invalid_grade_result["integrity"]["grading_results_are_consistent"] is False
    grade_path.write_text(original_grade, encoding="utf-8")

    unrelated_candidate = json.loads(original_candidate)
    unrelated_candidate["model"] = "unrelated-model"
    candidate_path.write_text(json.dumps(unrelated_candidate), encoding="utf-8")
    baseline_path = baseline_dir / "issue557-baseline-core.json"
    original_baseline = baseline_path.read_text(encoding="utf-8")
    unrelated_baseline = json.loads(original_baseline)
    unrelated_baseline["results"]["results"][0]["provider"]["id"] = "openai:chat:unrelated-model"
    baseline_path.write_text(json.dumps(unrelated_baseline), encoding="utf-8")
    stale_model = compare_evidence(baseline_dir, candidate_dir)
    assert stale_model["verdict"] == "NOT PROVEN"
    assert stale_model["integrity"]["current_configs_match"] is False
    assert stale_model["integrity"]["candidate_models_match"] is False
    candidate_path.write_text(original_candidate, encoding="utf-8")
    baseline_path.write_text(original_baseline, encoding="utf-8")

    wrong_prompt = json.loads(original_baseline)
    wrong_prompt["results"]["results"][0]["prompt"]["raw"] = Path(
        "skills/sumo-qa-reviewing-before-merge/SKILL.md"
    ).read_text(encoding="utf-8")
    baseline_path.write_text(json.dumps(wrong_prompt), encoding="utf-8")
    stale_prompt = compare_evidence(baseline_dir, candidate_dir)
    assert stale_prompt["verdict"] == "NOT PROVEN"
    assert stale_prompt["integrity"]["baseline_contains_current_context"] is False
    baseline_path.write_text(original_baseline, encoding="utf-8")

    wrong_embedded_config = json.loads(original_baseline)
    wrong_embedded_config["config"]["providers"] = [{"id": "openai:chat:stale"}]
    baseline_path.write_text(json.dumps(wrong_embedded_config), encoding="utf-8")
    stale_embedded_config = compare_evidence(baseline_dir, candidate_dir)
    assert stale_embedded_config["verdict"] == "NOT PROVEN"
    assert stale_embedded_config["integrity"]["embedded_configs_match"] is False
    baseline_path.write_text(original_baseline, encoding="utf-8")

    repaired_candidate = json.loads(original_candidate)
    repaired_candidate["results"][0]["attempts"] = [
        {
            "number": 1,
            "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
            "response": "not an envelope",
        },
        {
            "number": 2,
            "usage": {"prompt_tokens": 150, "completion_tokens": 90, "total_tokens": 240},
            "response": raw_response,
        },
    ]
    candidate_path.write_text(json.dumps(repaired_candidate), encoding="utf-8")
    repaired = compare_evidence(baseline_dir, candidate_dir)
    # The repaired answer came from an extra corrective turn the baseline never
    # received, so it cannot support the one-prompt quality claim even though
    # the rubric graded the final response as a pass.
    assert repaired["verdict"] == "NOT PROVEN"
    assert repaired["integrity"]["preserved"] is True
    repaired_row = next(row for row in repaired["quality"]["scenarios"] if row["repaired"])
    assert repaired_row["candidate_pass"] is True
    assert repaired_row["first_attempt_pass"] is False
    assert repaired_row["quality_preserved"] is False
    assert repaired["quality"]["repaired_count"] == 1
    assert repaired["quality"]["candidate_passed"] == 7
    assert repaired["quality"]["candidate_passed_first_attempt"] == 6
    assert repaired["quality"]["preserved"] is False
    assert all(row["repaired"] is False for row in comparison["quality"]["scenarios"])
    assert comparison["quality"]["repaired_count"] == 0
    assert comparison["quality"]["candidate_passed_first_attempt"] == 7
    candidate_path.write_text(original_candidate, encoding="utf-8")

    failing_grade_path = candidate_dir / "candidate-adversarial-grade.json"
    failing_grade = json.loads(failing_grade_path.read_text(encoding="utf-8"))
    failing_grade["results"]["results"][0]["success"] = False
    failing_grade["results"]["results"][0]["score"] = 0.7
    failing_grade_path.write_text(json.dumps(failing_grade), encoding="utf-8")

    regressed_quality = compare_evidence(baseline_dir, candidate_dir)
    assert regressed_quality["verdict"] == "NOT PROVEN"
    assert regressed_quality["quality"]["preserved"] is False
