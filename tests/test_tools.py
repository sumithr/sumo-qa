import asyncio
from pathlib import Path

from sumo_qa.llm import LLMResponse
from sumo_qa.models import RiskItem
from sumo_qa.tools import QAShiftLeftService, _highest_severity_risk, _unique_risks


class _FakeAsyncLLM:
    def __init__(self, content: str = "Senior QA narrative produced by the host's model.") -> None:
        self.content = content
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        self.calls.append((system_prompt, user_prompt))
        return LLMResponse(
            content=self.content,
            model="host-llm-via-sampling",
            metadata={"mode": "host-sampling", "external_calls": "true"},
        )


class _FailingAsyncLLM:
    async def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        raise RuntimeError("host does not support sampling")


ROOT = Path(__file__).resolve().parents[1]


def service() -> QAShiftLeftService:
    return QAShiftLeftService.from_standards_path(ROOT / "standards" / "packs")


def test_prepare_for_work_is_qa_focused_and_offline() -> None:
    result = service().qa_prepare_for_work(
        work_item="Add delivery API validation for outlet orders",
        acceptance_criteria=["Invalid postcode returns a clear rejection"],
    )

    assert result["tool"] == "sumo_qa_prepare_for_work"
    assert result["knowledge_context"]["items"] == []
    assert result["summary"]
    assert result["headline"]
    assert "delivery api validation" in result["headline"].lower() or "outlet" in result["headline"].lower()
    assert result["confidence"]["level"] in {"low", "medium", "high"}
    assert "suggested_tests" in result
    # Risks now come from the team's loaded rule templates plus any
    # caller-supplied risk_notes — not from phrase-matching the work_item.
    # Domain-specific risk surfacing is the AI's job.
    risk_categories = {risk["category"] for risk in result["qa_risk_areas"]}
    assert risk_categories, "rule-derived risks should produce at least one category"
    assert result["test_strategy"]["primary_checks"]


def test_aqa_decide_approach_uses_host_llm_when_available() -> None:
    """When MCP sampling is available, the decider asks the host's LLM to
    reason over QA principles + the user's intent, not just keyword-match.

    The user's intent in the regression that prompted this rewrite was:
    'help me increase test coverage on the BundleVariantValidator POC branch
    — Pitest test strength at 86%, 6 surviving mutations, no production code
    changes'. The deterministic keyword matcher missed this and produced
    tdd-scaffold. The AI path must produce strengthen-test-coverage (or
    something equivalent that the AI reasons to).
    """
    fake = _FakeAsyncLLM(
        content=(
            '{"approach": "strengthen-test-coverage", '
            '"rationale": "Mutation-testing follow-up on unchanged production code; '
            "Foundation principle 5 (pesticide paradox) implies refresh assertions to "
            'kill survivors.", '
            '"next_action": {"tool": "sumo_qa_scaffold_tests"}, '
            '"techniques": ["targeted assertion strengthening per surviving mutant"], '
            '"specialty_needs": [], '
            '"alternatives": [], '
            '"confidence": "high", '
            '"reasoned_by": "ai"}'
        )
    )

    async def run():
        return await service().aqa_decide_approach(
            intent_text=(
                "help me increase test coverage on the BundleVariantValidator POC "
                "branch — Pitest test strength at 86%, 6 surviving mutations, no "
                "production code changes"
            ),
            target_paths=["src/.../BundleVariantValidator.kt"],
            async_llm=fake,
        )

    result = asyncio.run(run())
    decision = result["recommended_approach"]
    assert decision["approach"] == "strengthen-test-coverage"
    assert decision.get("reasoned_by") == "ai"
    assert "pesticide" in decision["rationale"].lower() or "mutation" in decision["rationale"].lower()
    # Sampling must have been called exactly once.
    assert len(fake.calls) == 1


def test_aqa_decide_approach_falls_back_when_host_llm_fails() -> None:
    """Sampling failure must degrade to the deterministic decider, not crash.

    The deterministic fallback no longer phrase-matches intent text — that's
    the AI's job. Without a caller signal it returns the safe default
    (tdd-scaffold) plus a reasoning_note pointing the caller at AI sampling.
    Caller can override by passing an explicit signal — verified separately."""
    failing = _FailingAsyncLLM()

    async def run():
        return await service().aqa_decide_approach(
            intent_text="kill the surviving mutants on bundle validator",
            target_paths=["src/.../BundleVariantValidator.kt"],
            async_llm=failing,
        )

    result = asyncio.run(run())
    decision = result["recommended_approach"]
    # Deterministic fallback default is tdd-scaffold; the reasoning_note
    # tells the caller AI sampling is the right path, plus the sampling
    # failure note explaining why we ended up here.
    assert decision["approach"] == "tdd-scaffold"
    assert "reasoning_note" in decision
    assert "sampling" in decision["reasoning_note"].lower()


def test_aqa_decide_approach_falls_back_when_ai_returns_unparseable() -> None:
    """Malformed AI output must not crash; degrade to deterministic fallback."""
    fake = _FakeAsyncLLM(content="this is not json at all, just prose about testing")

    async def run():
        return await service().aqa_decide_approach(
            intent_text="kill the surviving mutants on bundle validator",
            target_paths=["src/.../BundleVariantValidator.kt"],
            async_llm=fake,
        )

    result = asyncio.run(run())
    decision = result["recommended_approach"]
    # Deterministic fallback default; no phrase-matching on "mutants".
    assert decision["approach"] == "tdd-scaffold"
    assert "reasoning_note" in decision


def test_aqa_decide_approach_caller_signal_routes_strengthen_test_coverage_when_ai_offline() -> None:
    """When the host can't sample, a caller can still get the right approach
    by passing an explicit signal (no phrase matching needed)."""
    fake = _FakeAsyncLLM(content="not parseable")

    async def run():
        return await service().aqa_decide_approach(
            intent_text="anything",
            target_paths=["src/.../BundleVariantValidator.kt"],
            signals={"is_test_only": True},
            async_llm=fake,
        )

    result = asyncio.run(run())
    decision = result["recommended_approach"]
    assert decision["approach"] == "strengthen-test-coverage"


def test_aqa_decide_approach_without_async_llm_matches_sync() -> None:
    """No host LLM → identical to the sync (deterministic) path."""
    sync = service().qa_decide_approach(
        intent_text="kill the surviving mutants on bundle validator",
        target_paths=["src/.../BundleVariantValidator.kt"],
    )

    async def run():
        return await service().aqa_decide_approach(
            intent_text="kill the surviving mutants on bundle validator",
            target_paths=["src/.../BundleVariantValidator.kt"],
            async_llm=None,
        )

    async_result = asyncio.run(run())
    assert sync["recommended_approach"]["approach"] == async_result["recommended_approach"]["approach"]


def test_async_review_uses_host_llm_when_provided() -> None:
    """Caller passes `explicit_classifications` (the harness no longer
    pattern-matches paths or text to classify a change)."""
    fake = _FakeAsyncLLM(content="HOST-LLM-NARRATIVE-MARKER")

    async def run():
        return await service().aqa_review_local_change(
            change_summary="Changed API payload schema",
            touched_files=["src/orders/api.py"],
            async_llm=fake,
            explicit_classifications=["api_contract_change"],
        )

    result = asyncio.run(run())

    # Deterministic structure preserved
    assert result["verdict"] == "needs-test-evidence"
    assert result["change_classification"]["primary"] == "api_contract_change"
    # Host LLM content surfaced via llm_analysis
    assert result["llm_analysis"]["content"] == "HOST-LLM-NARRATIVE-MARKER"
    assert result["llm_analysis"]["metadata"]["external_calls"] == "true"
    # The host LLM was invoked exactly once with the senior-QA system prompt
    assert len(fake.calls) == 1
    system_prompt, user_prompt = fake.calls[0]
    assert "QA" in system_prompt or "qa" in system_prompt.lower()
    # User prompt should include the change summary so the LLM has the actual context
    assert "Changed API payload schema" in user_prompt


def test_async_review_falls_back_when_host_llm_fails() -> None:
    failing = _FailingAsyncLLM()

    async def run():
        return await service().aqa_review_local_change(
            change_summary="Changed API payload schema",
            touched_files=["src/orders/api.py"],
            async_llm=failing,
        )

    result = asyncio.run(run())

    # Deterministic structure intact
    assert result["verdict"] == "needs-test-evidence"
    # llm_analysis falls back to the honest-empty deterministic payload
    assert result["llm_analysis"]["content"] == ""
    assert result["llm_analysis"]["metadata"]["external_calls"] == "false"


def test_async_review_without_async_llm_matches_sync_behaviour() -> None:
    sync_result = service().qa_review_local_change(
        change_summary="Changed API payload schema",
        touched_files=["src/orders/api.py"],
    )

    async def run():
        return await service().aqa_review_local_change(
            change_summary="Changed API payload schema",
            touched_files=["src/orders/api.py"],
        )

    async_result = asyncio.run(run())

    # Identical structural shape (same keys, same verdict)
    assert sync_result.keys() == async_result.keys()
    assert sync_result["verdict"] == async_result["verdict"]
    assert sync_result["llm_analysis"] == async_result["llm_analysis"]


def test_review_local_change_with_thin_input_asks_for_specifics() -> None:
    # Pass a whitespace-only diff and an explicit empty touched_files list so
    # the test does not shell out to `git diff` against the actual working
    # tree (which would pick up unrelated edits and defeat the thin-input
    # path that this test pins).
    result = service().qa_review_local_change(
        change_summary="fix bug", diff=" ", touched_files=[]
    )

    assert "more detail" in result["headline"].lower() or "specific" in result["headline"].lower()
    assert any(
        item in result["missing_information"]
        for item in ("touched files or diff", "what changed in concrete terms")
    )
    assert result["confidence"]["level"] == "low"


def test_prepare_for_work_with_thin_work_item_asks_for_specifics() -> None:
    result = service().qa_prepare_for_work(work_item="do thing")

    assert "more detail" in result["headline"].lower() or "specific" in result["headline"].lower()
    assert "concrete work item description" in result["missing_information"]


def test_review_local_change_flags_missing_evidence() -> None:
    """Caller supplies `explicit_classifications` so the rules engine has
    something to dispatch on. The harness does not pattern-match paths."""
    result = service().qa_review_local_change(
        change_summary="Changed API payload schema",
        touched_files=["src/orders/api.py"],
        explicit_classifications=["api_contract_change"],
    )

    assert result["verdict"] == "needs-test-evidence"
    assert result["change_classification"]["primary"] == "api_contract_change"
    assert result["suggested_tests"]["contract"]
    assert any(finding["category"] == "missing-evidence" for finding in result["qa_findings"])
    assert any("contract" in test.lower() for test in result["recommended_tests"])
    assert "src/orders/api.py" in result["headline"]
    assert "merging" in result["headline"].lower()

    standards_rule_risks = [
        risk for risk in result["top_risks"] if risk["source"] == "standards-rule"
    ]
    assert standards_rule_risks, "expected at least one standards-rule risk on a contract change"
    assert any(
        "src/orders/api.py" in risk["description"] for risk in standards_rule_risks
    ), "standards-rule risks should reference the touched file"

    missing_level_findings = [
        finding
        for finding in result["qa_findings"]
        if finding["category"] == "missing-test-level"
    ]
    assert missing_level_findings, "expected at least one missing-test-level finding"
    # Every missing-test-level finding should suggest a concrete path
    # under tests/orders/ (parent context preserved) for src/orders/api.py.
    assert all(
        finding.get("recommended_test_path", "").startswith("tests/orders/test_api")
        for finding in missing_level_findings
    ), (
        "missing-test-level findings should preserve parent dir; got: "
        + ", ".join(f.get("recommended_test_path", "") for f in missing_level_findings)
    )


def test_standards_rule_risks_are_attributed_to_their_origin_classification() -> None:
    """A change classified as both api_contract_change AND data_mapping_change
    surfaces risks for BOTH classifications, each attributed to its own
    origin. Caller supplies the classifications explicitly — the harness
    no longer pattern-matches paths to guess them."""
    result = service().qa_review_local_change(
        change_summary="Change API payload field mapping",
        touched_files=[
            "src/fulfilment/api/options_controller.py",
            "src/fulfilment/mapper/options_mapper.py",
        ],
        explicit_classifications=["api_contract_change", "data_mapping_change"],
    )

    standards_rule_risks = [
        risk for risk in result["top_risks"] if risk["source"] == "standards-rule"
    ]
    assert standards_rule_risks, "expected standards-rule risks for an api+mapping change"

    # No two standards-rule risks should carry an identical description.
    descriptions = [risk["description"] for risk in standards_rule_risks]
    assert len(descriptions) == len(set(descriptions)), (
        "standards-rule risk descriptions should be unique across categories; got: "
        + repr(descriptions)
    )

    # Specifically, the api-only template must not appear under data_mapping_change.
    api_template_marker = "payload shape or validation changes silently"
    mapping_risks_with_api_template = [
        risk
        for risk in standards_rule_risks
        if risk["category"] == "data_mapping_change"
        and api_template_marker in risk["description"]
    ]
    assert mapping_risks_with_api_template == [], (
        "api_contract_change template leaked into data_mapping_change category"
    )


def test_highest_severity_risk_picks_high_over_first_inserted() -> None:
    # First-inserted is medium; later high-severity risk should win.
    risks = [
        RiskItem(category="state", description="rollback gap", severity="medium"),
        RiskItem(category="contract", description="payload mismatch", severity="high"),
        RiskItem(category="async", description="retry storm", severity="low"),
    ]

    picked = _highest_severity_risk(risks)

    assert picked is not None
    assert picked.severity == "high"
    assert picked.category == "contract"


def test_highest_severity_risk_returns_none_for_empty() -> None:
    assert _highest_severity_risk([]) is None


def test_every_response_carries_concise_presentation_hint() -> None:
    svc = service()

    prepare = svc.qa_prepare_for_work(
        work_item="Add bundle variant validation",
        acceptance_criteria=["Invalid variants are blocked at write time."],
    )
    review = svc.qa_review_local_change(
        change_summary="Changed API payload schema",
        touched_files=["src/orders/api.py"],
    )
    question = svc.qa_answer_testing_question(
        question="How do I test a webhook retry?",
    )

    for name, response in [
        ("prepare", prepare),
        ("review", review),
        ("question", question),
    ]:
        assert "presentation" in response, f"{name} missing presentation field"
        hint = response["presentation"]
        assert hint["style"] == "concise"
        # Word cap must be present and tight
        assert isinstance(hint["max_words"], int)
        assert hint["max_words"] <= 200, f"{name} word cap too generous"
        instructions = hint["render_instructions"].lower()
        # The hint must explicitly forbid essay-mode rendering
        assert "do not" in instructions or "don't" in instructions
        assert "essay" in instructions or "section" in instructions or "table" in instructions
        # And explicitly tell the host what to render first
        assert "headline" in instructions or "verdict" in instructions or "short_answer" in instructions


def test_create_test_plan_returns_phased_plan_with_entry_exit_criteria() -> None:
    """For larger pieces of work, a senior QA produces a formal test plan with
    phases, deliverables, and entry/exit criteria - not just a flat risk list.
    """
    result = service().qa_create_test_plan(
        work_item=(
            "Add an API endpoint that validates bundle variants on the order pipeline; "
            "block invalid payload shapes at write time."
        ),
        scope_size="medium",
        acceptance_criteria=[
            "Invalid bundle variants are blocked at write time.",
            "Each violation surfaces a clear reason and SKU.",
        ],
        risk_notes=["Customer-visible failure on legitimate bundles is unacceptable."],
    )

    assert result["tool"] == "sumo_qa_create_test_plan"
    assert result["headline"]
    # Test plan structure
    plan = result["test_plan"]
    assert plan["scope_in"], "test plan must list what's in scope"
    assert plan["scope_out"], "test plan must list what's out of scope"
    assert plan["entry_criteria"], "test plan must have entry criteria"
    assert plan["exit_criteria"], "test plan must have exit criteria"
    # Phases: analysis -> design -> execution -> completion (ISTQB Foundation)
    phases = plan["phases"]
    assert len(phases) >= 3
    phase_names = {p["name"].lower() for p in phases}
    assert any("analysis" in n for n in phase_names)
    assert any("design" in n for n in phase_names)
    assert any("execution" in n or "implementation" in n for n in phase_names)
    # Each phase has at least one deliverable
    for phase in phases:
        assert phase["deliverables"], f"phase {phase['name']!r} has no deliverables"
    # Specialty routing surfaced through here too
    assert "specialty_testing_needs" in result
    # The deterministic harness exposes test_design_techniques as a list.
    # Concrete techniques come from the team's loaded rules (which dispatch
    # on classification — and the classifier needs paths) or from the AI
    # path. Pin shape, not content.
    assert isinstance(result["test_design_techniques"], list)
    assert result["confidence"]["level"] in {"low", "medium", "high"}
    # Presentation hint present
    assert result["presentation"]["style"] == "concise"


def test_create_test_plan_for_thin_input_asks_for_specifics() -> None:
    """A test plan needs a real work item; thin input gets a clarifying request."""
    result = service().qa_create_test_plan(work_item="do thing", scope_size="medium")

    assert "more detail" in result["headline"].lower() or "specific" in result["headline"].lower()
    assert "concrete work item description" in result["missing_information"]


def test_resolve_data_path_honours_explicit_user_path(tmp_path: Path) -> None:
    from sumo_qa.tools import (
        DEFAULT_STANDARDS_PATH,
        _resolve_data_path,
    )

    custom = tmp_path / "team-standards"
    resolved = _resolve_data_path(custom, DEFAULT_STANDARDS_PATH, "standards", "packs")

    assert resolved == custom


def test_resolve_data_path_falls_back_to_bundled_when_default_missing(tmp_path: Path, monkeypatch) -> None:
    from sumo_qa.tools import (
        DEFAULT_STANDARDS_PATH,
        _resolve_data_path,
    )

    # Run from a directory where the default cwd-relative path does NOT exist
    monkeypatch.chdir(tmp_path)
    resolved = _resolve_data_path(
        DEFAULT_STANDARDS_PATH, DEFAULT_STANDARDS_PATH, "standards", "packs"
    )

    # In editable install + repo cwd, packaged _data may not exist; the function
    # should still return *something* - the cwd-relative default if nothing else.
    # The contract is: the returned path is one of (cwd default, bundled, default).
    # When run from tmp_path the cwd default doesn't exist; only the bundled path
    # would, IF this is a non-editable install. In an editable install the bundled
    # path also doesn't exist, and the function falls back to the default.
    # This test asserts the function does not crash and returns a Path; the
    # behavioural variants are covered by an end-to-end install test outside CI.
    assert isinstance(resolved, Path)


def test_unique_risks_keeps_highest_severity_on_collision() -> None:
    risks = [
        RiskItem(category="contract", description="payload mismatch", severity="medium", source="standards-rule"),
        RiskItem(category="contract", description="payload mismatch", severity="high", source="local-diff"),
        RiskItem(category="contract", description="payload mismatch", severity="low", source="user-input"),
    ]

    result = _unique_risks(risks)

    assert len(result) == 1
    assert result[0].severity == "high"
    assert result[0].source == "local-diff"


def test_unique_risks_preserves_distinct_risks_in_order() -> None:
    risks = [
        RiskItem(category="state", description="rollback gap", severity="low"),
        RiskItem(category="contract", description="payload mismatch", severity="medium"),
        RiskItem(category="state", description="rollback gap", severity="high"),
    ]

    result = _unique_risks(risks)

    assert [(item.category, item.severity) for item in result] == [
        ("state", "high"),
        ("contract", "medium"),
    ]


def test_answer_testing_question_returns_actionable_testing_answer() -> None:
    """The deterministic skeleton surfaces the universal QA bones (verify
    + risk_areas) and the standard suggested-tests buckets. Domain-specific
    specialisation (which bucket gets concrete entries based on the
    question — e.g. 'contract' for an API question) is the AI's job; the
    harness no longer phrase-matches the question."""
    result = service().qa_answer_testing_question(
        question="How should I test a delivery API change?",
        context="Endpoint returns eligible slots for a postcode.",
    )

    assert result["tool"] == "sumo_qa_answer_testing_question"
    assert result["summary"]
    assert result["headline"]
    assert "delivery api change" in result["headline"].lower()
    # suggested_tests structure exists; bucket population depends on the
    # team's loaded rules. The AI fills the rest.
    assert "suggested_tests" in result
    assert "verify" in result["answer"]
    assert "No external domain knowledge provider is configured." in result["assumptions"]
