# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""POC boundary tests for issue #557's code-enforced review gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from experiments.issue_557.compare_results import (
    CONFIGS,
    EVAL_ROOT,
    GROUPS,
    PROMPT_PATH,
    compare_evidence,
)
from experiments.issue_557.run_candidate import (
    PINNED_GROUPS,
    build_prompts,
    load_group,
    write_grade_config,
)
from sumo_qa.review_gate_poc import ReviewGateValidationError, validate_review_response


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


@pytest.mark.parametrize(
    "review",
    [
        "No exact verdict line.",
        "Verdict: SAFE TO MERGE\nVerdict: NOT SAFE TO MERGE",
        "Verdict: MAYBE",
    ],
)
def test_exactly_one_supported_verdict_is_required(review: str) -> None:
    with pytest.raises(ReviewGateValidationError, match="exactly one verdict"):
        validate_review_response(_response(review=review))


def test_content_outside_envelopes_is_rejected() -> None:
    with pytest.raises(ReviewGateValidationError, match="outside the envelopes"):
        validate_review_response(f"preamble\n{_response()}")


def test_single_presentation_fence_around_envelopes_is_accepted() -> None:
    validated = validate_review_response(f"```text\n{_response()}\n```")

    assert validated.safe_to_merge is True


def test_pinned_candidate_set_contains_exactly_seven_scenarios() -> None:
    rendered = [scenario for group in PINNED_GROUPS for scenario in build_prompts(group)[1]]

    assert len(rendered) == 7
    assert len({description for description, _ in rendered}) == 7


def test_candidate_prompts_replace_only_the_skill_with_compact_contract() -> None:
    compact_contract = Path("experiments/issue_557/compact_review_prompt.md").read_text(
        encoding="utf-8"
    )
    full_skill = Path("skills/sumo-qa-reviewing-before-merge/SKILL.md").read_text(encoding="utf-8")
    for group in PINNED_GROUPS:
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


def test_grade_config_uses_echo_with_original_rubric(tmp_path: Path) -> None:
    grade_path = write_grade_config("core", ["Verdict: NOT SAFE TO MERGE"], tmp_path)
    grade_config = yaml.safe_load(grade_path.read_text(encoding="utf-8"))

    assert grade_config["providers"] == ["echo"]
    assert grade_config["prompts"] == ["{{output}}"]
    assert grade_config["tests"][0]["vars"]["output"] == "Verdict: NOT SAFE TO MERGE"
    assert grade_config["defaultTest"]["assert"][0]["type"] == "llm-rubric"
    assert grade_config["defaultTest"]["options"]["provider"]["id"] == "openai:chat:gpt-5.5"


def test_comparison_requires_quality_and_token_reduction(tmp_path: Path) -> None:
    baseline_dir = tmp_path / "baseline"
    candidate_dir = tmp_path / "candidate"
    baseline_dir.mkdir()
    candidate_dir.mkdir()
    prompt_hash = hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()
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

    failing_grade_path = candidate_dir / "candidate-adversarial-grade.json"
    failing_grade = json.loads(failing_grade_path.read_text(encoding="utf-8"))
    failing_grade["results"]["results"][0]["success"] = False
    failing_grade["results"]["results"][0]["score"] = 0.7
    failing_grade_path.write_text(json.dumps(failing_grade), encoding="utf-8")

    regressed_quality = compare_evidence(baseline_dir, candidate_dir)
    assert regressed_quality["verdict"] == "NOT PROVEN"
    assert regressed_quality["quality"]["preserved"] is False
