"""approach_decision — pick the right QA approach for the change shape.

The PRIMARY decider is the AI-sampling path. The deterministic
`choose_approach` is a structural fallback only — no phrase matching on
intent text. These tests pin two things:

  1. The deterministic fallback's two structural recognisers (file
     extensions only) and its caller-supplied override signals.
  2. The AI prompt contract: every canonical approach must be listed
     with senior-QA guidance grounded in ISTQB principles, so the host
     LLM can pick the right shape without the harness leaning on a
     phrase table.
"""
from sumo_qa.approach_decision import choose_approach


# ----------------------------------------------------------------------------
# Deterministic fallback — structural recognisers only.
# ----------------------------------------------------------------------------


def test_is_docs_only_signal_routes_to_no_tests_recommended() -> None:
    """The deterministic harness no longer pattern-matches file extensions
    to detect docs changes — the AI reads the change directly. Callers can
    still force the verdict with the explicit `is_docs_only` signal."""
    decision = choose_approach(
        intent_text="update README and add architecture diagram",
        classifications=[],
        target_paths=["README.md", "docs/architecture.md"],
        signals={"is_docs_only": True},
    )

    assert decision["approach"] == "no-tests-recommended"
    assert decision["next_action"] is None


def test_is_config_only_signal_routes_to_verify_existing() -> None:
    """Same principle as is_docs_only — explicit caller signal, not pattern
    detection."""
    decision = choose_approach(
        intent_text="bump cache TTL from 300 to 600",
        classifications=["configuration_change", "caching_change"],
        target_paths=["config/cache.yaml"],
        signals={"is_config_only": True},
    )

    assert decision["approach"] == "verify-existing"
    rationale = decision["rationale"].lower()
    assert "existing" in rationale or "config" in rationale


def test_docs_paths_alone_no_longer_route_anywhere_special() -> None:
    """Without an explicit `is_docs_only` signal, even all-`.md` paths land
    on the generic tdd-scaffold fallback. Pattern-matching extensions is
    exactly the failure mode we're avoiding — the AI reads paths directly."""
    decision = choose_approach(
        intent_text="anything",
        classifications=[],
        target_paths=["README.md", "docs/architecture.md"],
    )

    assert decision["approach"] == "tdd-scaffold"
    assert decision["confidence"] == "low"
    assert "reasoning_note" in decision


def test_acceptance_criteria_signal_lifts_default_confidence_to_medium() -> None:
    """`has_acceptance_criteria=True` is a structural caller-supplied signal
    (not a phrase). It lifts the fallback default's confidence so the
    alternatives are still visible but the host knows TDD is well-founded."""
    decision = choose_approach(
        intent_text="add a new API endpoint that validates bundle variants",
        classifications=["api_contract_change"],
        target_paths=["src/orders/api.py"],
        signals={"has_acceptance_criteria": True},
    )

    assert decision["approach"] == "tdd-scaffold"
    assert decision["confidence"] == "medium"
    assert decision["next_action"]["tool"] == "sumo_qa_scaffold_tests"
    # Round-6: per-change approaches must also explicitly null out skill so
    # downstream parsers can branch cleanly on tool vs skill.
    assert decision["next_action"].get("skill") is None


def test_alternatives_are_listed_so_user_can_override() -> None:
    decision = choose_approach(
        intent_text="anything",
        classifications=[],
        target_paths=["src/orders/pipeline.py"],
    )
    alternatives = decision["alternatives"]
    assert isinstance(alternatives, list)
    assert alternatives, "decision should suggest at least one alternative"
    for alt in alternatives:
        assert "approach" in alt
        assert "when" in alt


def test_thin_input_with_no_signals_lands_on_low_confidence_fallback() -> None:
    """Thin input + no caller signals = honest low-confidence fallback. The
    fallback no longer phrase-matches "fix bug" to regression-first; that's
    the AI's job."""
    decision = choose_approach(
        intent_text="fix bug",
        classifications=[],
        target_paths=[],
    )
    assert decision["approach"] == "tdd-scaffold"
    assert decision["confidence"] == "low"
    # Fallback note steers the caller to enable AI sampling for accurate routing.
    assert "reasoning_note" in decision
    assert "sampling" in decision["reasoning_note"].lower()


def test_default_tdd_scaffold_does_not_claim_high_without_positive_signal() -> None:
    """Without `has_acceptance_criteria`, the default fallback caps at low
    so alternatives stay visible and the host knows AI sampling is the
    right path."""
    decision = choose_approach(
        intent_text="touch the order pipeline a bit",
        classifications=["business_logic_change"],
        target_paths=["src/orders/pipeline.py"],
    )
    assert decision["approach"] == "tdd-scaffold"
    assert decision["confidence"] != "high"


def test_decision_always_includes_required_fields() -> None:
    decision = choose_approach(
        intent_text="add a small helper function",
        classifications=["business_logic_change"],
        target_paths=["src/util/helper.py"],
    )
    for field in ("approach", "rationale", "next_action", "confidence", "alternatives"):
        assert field in decision
    assert decision["confidence"] in {"low", "medium", "high"}


# ----------------------------------------------------------------------------
# Caller-supplied override signals — explicit, not phrase-detected.
# ----------------------------------------------------------------------------


def test_is_bug_signal_routes_to_regression_first() -> None:
    decision = choose_approach(
        intent_text="anything",
        classifications=[],
        target_paths=["src/orders/bundle.py"],
        signals={"is_bug": True},
    )
    assert decision["approach"] == "regression-first"
    assert decision["next_action"]["tool"] == "sumo_qa_scaffold_tests"
    rationale = decision["rationale"].lower()
    assert "reproduce" in rationale or "failing test" in rationale or "regression" in rationale


def test_is_refactor_signal_routes_to_coverage_first_then_refactor() -> None:
    decision = choose_approach(
        intent_text="anything",
        classifications=[],
        target_paths=["src/orders/pipeline.py"],
        signals={"is_refactor": True},
    )
    assert decision["approach"] == "coverage-first-then-refactor"


def test_is_test_only_signal_routes_to_strengthen_test_coverage() -> None:
    decision = choose_approach(
        intent_text="anything",
        classifications=[],
        target_paths=["src/test/foo_test.py"],
        signals={"is_test_only": True},
    )
    assert decision["approach"] == "strengthen-test-coverage"
    assert decision["next_action"]["tool"] == "sumo_qa_scaffold_tests"


def test_is_spike_signal_routes_to_spike_first_then_tests() -> None:
    decision = choose_approach(
        intent_text="anything",
        classifications=[],
        target_paths=["spikes/pricing.py"],
        signals={"is_spike": True},
    )
    assert decision["approach"] == "spike-first-then-tests"


def test_is_strategic_planning_signal_routes_to_strategy_orchestration() -> None:
    decision = choose_approach(
        intent_text="anything",
        classifications=["api_contract_change", "business_logic_change"],
        target_paths=["src/main/kotlin/com/johnlewis/byvariantdatafeeder/"],
        signals={"is_strategic_planning": True},
    )

    assert decision["approach"] == "strategy-orchestration"
    # Round-6: strategy-orchestration must emit next_action with skill set
    # (NOT tool) so strict parsers route to the sumo-qa-strategising skill,
    # not a non-existent MCP tool of that name.
    next_action = decision["next_action"]
    assert isinstance(next_action, dict), (
        "strategy-orchestration must still expose a structured next_action"
    )
    assert next_action.get("tool") is None, (
        "strategy-orchestration must NOT name a per-change MCP tool"
    )
    assert next_action.get("skill") == "sumo-qa-strategising", (
        "strategy-orchestration must set next_action.skill to the sub-skill name"
    )
    follow_up = decision["follow_up"].lower()
    assert "sumo-qa-strategising" in follow_up or "strategising" in follow_up


def test_strategy_phrase_without_signal_falls_through_to_default() -> None:
    """The deterministic fallback deliberately does not phrase-match for
    strategy. Without the explicit signal, a strategy-shaped intent falls
    through to the per-change default — the AI-sampling path is the one
    responsible for picking strategy-orchestration."""
    decision = choose_approach(
        intent_text="audit our test coverage and design a QA strategy from scratch",
        classifications=[],
        target_paths=[],
    )
    assert decision["approach"] != "strategy-orchestration"


# ----------------------------------------------------------------------------
# AI-prompt contract — what senior-QA reasoning the host LLM is grounded in.
# These tests pin the prompt so the AI gets enough discipline to pick the
# right shape WITHOUT a keyword crutch in the harness.
# ----------------------------------------------------------------------------


def _decide_prompt(**overrides) -> str:
    """Return the full grounding the AI sees on a decide-approach call:
    the standing system prompt + the per-call user prompt joined together.
    The host LLM gets both; tests should pin the union."""
    from sumo_qa.prompts import SENIOR_QA_SYSTEM_PROMPT
    from sumo_qa.tools import _build_decide_approach_sampling_prompt

    defaults: dict = {
        "intent_text": "<intent>",
        "target_paths": [],
        "classifications": [],
        "rules": {"must_consider": []},
        "standards_prompts": [],
        "deterministic_decision": {"approach": "tdd-scaffold", "confidence": "low"},
    }
    defaults.update(overrides)
    user_prompt = _build_decide_approach_sampling_prompt(**defaults)
    return SENIOR_QA_SYSTEM_PROMPT + "\n\n" + user_prompt


def test_ai_prompt_lists_every_canonical_approach() -> None:
    """The AI must see all 8 canonical approaches as candidates."""
    prompt = _decide_prompt()
    for approach in (
        "tdd-scaffold",
        "regression-first",
        "coverage-first-then-refactor",
        "strengthen-test-coverage",
        "verify-existing",
        "no-tests-recommended",
        "spike-first-then-tests",
        "strategy-orchestration",
    ):
        assert approach in prompt, f"AI prompt missing canonical approach `{approach}`"


def test_ai_prompt_grounds_reasoning_in_istqb_foundation_principles() -> None:
    """The AI must be grounded in the seven Foundation principles so it can
    reason about novel asks without keyword tables. Pinning by principle
    text — not a phrase table — so the prompt evolves naturally."""
    prompt = _decide_prompt().lower()
    assert "presence of defects" in prompt, "principle 1 must be cited"
    assert "exhaustive" in prompt, "principle 2 must be cited"
    assert "early testing" in prompt or "shift left" in prompt, "principle 3 must be cited"
    assert "cluster" in prompt, "principle 4 must be cited"
    assert "pesticide" in prompt, "principle 5 must be cited"
    assert "context-dependent" in prompt or "context dependent" in prompt, "principle 6 must be cited"
    assert "absence-of-errors" in prompt or "absence of errors" in prompt, "principle 7 must be cited"


def test_ai_prompt_explains_strategy_vs_single_change_shape_decision() -> None:
    """The AI must be told to decide SHAPE first (strategy vs single change)
    so it doesn't force a per-change verdict on a repo-wide question."""
    prompt = _decide_prompt().lower()
    assert "shape" in prompt
    assert "repo-wide" in prompt or "single change" in prompt
    assert "strategy-orchestration" in prompt


def test_ai_prompt_explains_strengthen_vs_tdd_for_unchanged_production_code() -> None:
    """Senior-QA discipline: when production code is unchanged and the user
    is fixing test coverage / mutation testing, scaffold strengthening
    tests, not new-behaviour tests. The prompt must explain this so the
    AI can reason about it without us keyword-matching 'pitest' etc."""
    prompt = _decide_prompt().lower()
    assert "strengthen-test-coverage" in prompt
    assert "unchanged production code" in prompt or "no production code" in prompt or "production code stays unchanged" in prompt


def test_ai_prompt_explains_critical_path_handling() -> None:
    """The AI must know that critical paths (auth, payment, encryption)
    warrant tighter coverage — without us building a phrase table for them."""
    prompt = _decide_prompt().lower()
    assert "critical path" in prompt
    # Must name at least a couple of common critical-path domains so the
    # AI has concrete grounding.
    assert "auth" in prompt
    assert "payment" in prompt or "billing" in prompt or "money" in prompt


def test_ai_prompt_orders_reasoning_shape_first() -> None:
    """The AI must reason in order: (a) decide shape, (b) decide what is
    changing (prod / tests / config / docs), (c) apply loaded rules. This
    ordering is what produces senior-QA-shaped output."""
    prompt = _decide_prompt().lower()
    # Shape decision is described before the per-change reasoning.
    shape_idx = prompt.find("shape")
    assert shape_idx >= 0
    rules_idx = prompt.find("loaded team rules")
    if rules_idx >= 0:
        assert shape_idx < rules_idx, "AI prompt should ask for shape before rules"


def test_ai_prompt_passes_loaded_rules_when_supplied() -> None:
    """The AI must see the team's loaded rules when they exist."""
    prompt = _decide_prompt(
        rules={"must_consider": ["MUST add contract test for new API endpoint"]},
    )
    assert "MUST add contract test for new API endpoint" in prompt


def test_ai_prompt_passes_loaded_standards_when_supplied() -> None:
    """The AI must see the team's loaded QA standards when they exist."""
    prompt = _decide_prompt(
        standards_prompts=["Coverage gate: 80% line, 70% branch on changed files."],
    )
    assert "Coverage gate: 80% line, 70% branch on changed files." in prompt


def test_ai_prompt_passes_target_paths_for_classifier_grounding() -> None:
    """Target paths (and the deterministic classifier output) feed the AI
    structural grounding so the senior-QA reasoning has something to point at."""
    prompt = _decide_prompt(
        target_paths=["src/auth/refresh.py"],
        classifications=["business_logic_change"],
    )
    assert "src/auth/refresh.py" in prompt
    assert "business_logic_change" in prompt


def test_senior_qa_system_prompt_grounds_the_persona_in_istqb_principles() -> None:
    """The standing system prompt must establish the senior-QA persona in
    ISTQB Foundation, Advanced, and specialty terms so the AI can reason
    about novel cases without the harness leaning on phrase tables."""
    from sumo_qa.prompts import SENIOR_QA_SYSTEM_PROMPT

    sp = SENIOR_QA_SYSTEM_PROMPT.lower()
    assert "senior qa" in sp
    assert "istqb" in sp
    # Foundation principles get cited.
    assert "presence of defects" in sp
    assert "shift left" in sp or "early testing" in sp
    assert "defects cluster" in sp or "cluster" in sp
    # Discipline cues that replace the keyword tables.
    assert "shape" in sp
    assert "strategy" in sp
    assert "unchanged production code" in sp or "doesn't change production code" in sp
    assert "critical path" in sp
