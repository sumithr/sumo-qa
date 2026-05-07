"""Round-2 prompt-content guarantees.

The round-1 ISTQB rubric run showed five aggregated failures: every per-tool
output schema was missing an `assumptions` field, `qa_decide_approach` had
no `top_risks` or `suggested_tests`, no per-tool builder forced domain
anchoring, and `_testing_answer` was hard-coding generic risk strings the
host LLM then parroted. These tests pin those fixes so a regression cannot
silently slip back in.
"""

from __future__ import annotations

from typing import Any

from sumo_qa.prompts import SENIOR_QA_SYSTEM_PROMPT
from sumo_qa.tools import (
    _build_decide_approach_sampling_prompt,
    _build_prepare_sampling_prompt,
    _build_question_sampling_prompt,
    _build_review_sampling_prompt,
    _build_scaffold_sampling_prompt,
    _build_test_plan_sampling_prompt,
    _testing_answer,
)


# --- Fix 1: assumptions field everywhere ----------------------------------


def test_system_prompt_has_hard_assumptions_rule() -> None:
    """The standing system prompt must declare assumptions a hard requirement,
    not aspiration. Round-1 showed 11/11 scenarios failing because the rule
    only existed at the persona level — never as a hard contract."""
    sp = SENIOR_QA_SYSTEM_PROMPT.lower()
    assert "hard requirement" in sp
    assert "assumptions" in sp
    # The forbidden generic-language list must be present so the AI knows
    # "the service / the system / the codebase" are anti-patterns.
    assert '"the service"' in sp or "the service" in sp
    assert "the system" in sp


def _decide_prompt() -> str:
    return _build_decide_approach_sampling_prompt(
        intent_text="Add a small feature flag",
        target_paths=["src/foo/bar.py"],
        classifications=["business_logic_change"],
        rules={"must_consider": ["boundary values"]},
        standards_prompts=["team standard 1"],
        deterministic_decision={"approach": "tdd-scaffold", "confidence": "medium"},
    )


def _review_prompt() -> str:
    return _build_review_sampling_prompt(
        change_summary="Tweak validator threshold",
        payload={
            "change_classification": {"primary": "business_logic_change", "primary_confidence": "high"},
            "local_diff": {"touched_files": ["src/foo/validator.py"], "missing_test_levels": []},
            "qa_findings": [],
            "standards": {"checks": []},
            "applied_rules": {"must_consider": []},
        },
    )


def _prepare_prompt() -> str:
    return _build_prepare_sampling_prompt(
        work_item="Add expiry to refresh tokens",
        criteria=["tokens older than 30d are rejected"],
        risk_notes=["session continuity"],
        payload={
            "change_classification": {"primary": "auth_change", "primary_confidence": "high"},
            "standards": {"checks": []},
            "applied_rules": {"must_consider": []},
            "missing_information": [],
        },
    )


def _test_plan_prompt() -> str:
    return _build_test_plan_sampling_prompt(
        work_item="Refactor pricing pipeline",
        payload={
            "change_classification": {"primary": "refactor", "primary_confidence": "medium"},
            "scope_size": "medium",
            "standards": {"checks": []},
            "applied_rules": {"must_consider": []},
            "test_plan": {"scope_in": ["pricing math"], "approach": ["characterization tests"]},
        },
    )


def _scaffold_prompt() -> str:
    return _build_scaffold_sampling_prompt(
        work_item="Cover bundle validator edge cases",
        payload={
            "change_classification": {"primary": "business_logic_change", "primary_confidence": "high"},
            "standards": {"checks": []},
            "applied_rules": {"must_consider": []},
            "target_paths": ["src/bundle/validator.py"],
            "tasks": [
                {"id": "T1", "file_path": "tests/test_validator.py", "framework": "pytest"},
            ],
        },
    )


def _question_prompt() -> str:
    return _build_question_sampling_prompt(
        question="How should I test our new caching layer?",
        context="Context: cache layer in src/cache.py",
        payload={
            "change_classification": {"primary": "caching_change", "primary_confidence": "medium"},
            "standards": {"checks": []},
            "answer": {"verify": ["cache invalidation"], "risk_areas": []},
        },
    )


_BUILDER_PROMPTS = [
    ("decide_approach", _decide_prompt),
    ("review", _review_prompt),
    ("prepare", _prepare_prompt),
    ("test_plan", _test_plan_prompt),
    ("scaffold", _scaffold_prompt),
    ("question", _question_prompt),
]


def test_every_builder_requires_assumptions_in_output_schema() -> None:
    """Every per-tool sampling prompt must extend its JSON schema with an
    `assumptions` field and explicitly require the AI to populate it."""
    for name, builder in _BUILDER_PROMPTS:
        prompt = builder()
        assert '"assumptions"' in prompt, (
            f"Builder {name!r} must include `assumptions` in its JSON schema."
        )
        assert "assumptions" in prompt.lower()
        # The hard-requirement language must be present, not just the field.
        lower = prompt.lower()
        assert "behavioural claim" in lower or "behavioral claim" in lower, (
            f"Builder {name!r} must spell out the assumptions hard requirement."
        )


# --- Fix 2: top_risks in decide_approach ----------------------------------


def test_decide_approach_prompt_requires_top_risks_with_evidence_path() -> None:
    prompt = _decide_prompt()
    assert '"top_risks"' in prompt
    assert "why_specific_to_this_change" in prompt
    assert "evidence_path" in prompt
    # Must explicitly reject generic risks.
    assert "generic phrases" in prompt.lower()


# --- Fix 3: suggested_tests in decide_approach -----------------------------


def test_decide_approach_prompt_requires_suggested_tests_tied_to_top_risks() -> None:
    prompt = _decide_prompt()
    assert '"suggested_tests"' in prompt
    assert "covers_risk" in prompt
    assert "ISTQB technique" in prompt or "istqb technique" in prompt.lower()
    # Must reject laundry-list output.
    assert "laundry-list" in prompt.lower() or "laundry list" in prompt.lower()


# --- Fix 4: domain anchoring in every builder -----------------------------


def test_every_builder_forces_domain_anchoring() -> None:
    """The phrase 'Domain anchoring' must appear in every per-tool sampling
    prompt — round-1 showed 8/11 scenarios failing because the prompts let
    the AI talk about 'the service' / 'the system' abstractly."""
    for name, builder in _BUILDER_PROMPTS:
        prompt = builder()
        assert "Domain anchoring" in prompt, (
            f"Builder {name!r} must enforce Domain anchoring."
        )
        # The forbidden generic-language list must appear so the AI knows
        # exactly which phrases are anti-patterns.
        assert '"the service"' in prompt
        assert '"the system"' in prompt


# --- Fix 5: no hard-coded generic risks in _testing_answer ----------------


def test_testing_answer_does_not_hard_code_generic_risks() -> None:
    """The deterministic skeleton must NOT inject the rubric's stated
    anti-pattern strings as risks. They were the exact generic phrases the
    rubric calls out — the host LLM was parroting them."""
    answer = _testing_answer(
        question="How should I test the new caching layer?",
        context=None,
        classifications=[],
        rules={"must_consider": []},
    )
    risk_areas = answer.get("risk_areas", [])
    forbidden = {
        "unclear acceptance criteria",
        "missing test data",
        "unverified downstream behavior",
    }
    for risk in risk_areas:
        assert risk.lower() not in forbidden, (
            f"_testing_answer must not hard-code generic risk {risk!r}."
        )


def test_testing_answer_with_classifications_does_not_inject_generic_risks() -> None:
    """Even when classifications fire, the risk_areas list must stay free of
    the generic anti-pattern strings (they describe input gaps, not risks)."""
    answer = _testing_answer(
        question="API contract change for /v1/orders",
        context="src/api/orders.py",
        classifications=["api_contract_change", "data_mapping_change"],
        rules={"must_consider": []},
    )
    forbidden = {
        "unclear acceptance criteria",
        "missing test data",
        "unverified downstream behavior",
    }
    for risk in answer.get("risk_areas", []):
        assert risk.lower() not in forbidden


# --- Round 3 Fix A: scaffold prompt requires principle_citations + named_techniques ---


def test_scaffold_prompt_requires_principle_citations() -> None:
    """Round-3: the scaffold builder must enforce principle_citations as a
    HARD REQUIREMENT in the JSON schema."""
    prompt = _scaffold_prompt()
    assert '"principle_citations"' in prompt
    assert "applied_to_task_id" in prompt
    lower = prompt.lower()
    assert "hard requirement" in lower
    assert "named istqb principle" in lower or "istqb principle" in lower


def test_scaffold_prompt_requires_named_techniques() -> None:
    """Round-3: the scaffold builder must enforce named_techniques alongside
    principle_citations — generic "follow QA best practices" is rejected."""
    prompt = _scaffold_prompt()
    assert '"named_techniques"' in prompt
    lower = prompt.lower()
    assert "named istqb test design technique" in lower or "test design technique" in lower
    # Generic-language ban must be spelled out.
    assert "follow qa best practices" in lower or "add edge cases" in lower


# --- Round 3 Fix B: question prompt routing + minimum-set + principle slot ---


def test_question_prompt_has_recommended_approach() -> None:
    """Round-3: open-ended whole-service / strategy asks must route to
    strategy-orchestration via a structured recommended_approach slot."""
    prompt = _question_prompt()
    assert '"recommended_approach"' in prompt
    assert "strategy-orchestration" in prompt
    assert "sumo-qa-strategising" in prompt
    assert "next_action" in prompt


def test_question_prompt_caps_smallest_useful_tests() -> None:
    """Round-3: the question builder must reframe the unbounded `verify`
    checklist into `smallest_useful_tests` capped at 3-5 items."""
    prompt = _question_prompt()
    assert '"smallest_useful_tests"' in prompt
    lower = prompt.lower()
    # Cap must be explicit so the AI doesn't over-generate.
    assert "5 items" in prompt or "3-5" in prompt
    assert "smallest set" in lower or "minimum useful set" in lower


def test_question_prompt_has_principle_cited_slot() -> None:
    """Round-3: the question builder must require an explicit principle_cited
    field whenever the answer touches risk, prioritisation, or strategy."""
    prompt = _question_prompt()
    assert '"principle_cited"' in prompt
    assert '"named_techniques"' in prompt


# --- Round 3 Fix C: specialty + tool pairing as HARD REQUIREMENT ---


def test_system_prompt_has_specialty_tool_pairing() -> None:
    """Round-3: the standing system prompt must declare specialty + tool
    pairing as a HARD REQUIREMENT (round-2 left specialty named without a
    concrete tool)."""
    sp = SENIOR_QA_SYSTEM_PROMPT.lower()
    assert "specialty + tool pairing" in sp
    assert "hard requirement" in sp
    # At least one well-known tool name must appear so the AI knows the bar.
    well_known = ["owasp zap", "burp suite", "k6", "cypress", "playwright", "pact", "axe-core"]
    assert any(tool in sp for tool in well_known), (
        "System prompt must name at least one well-known tool by example."
    )


def test_every_builder_specialty_needs_pairs_specialty_with_tool() -> None:
    """Round-3: every per-tool builder's specialty_needs schema must be the
    {specialty, tool} pair, not a bare list of strings."""
    for name, builder in _BUILDER_PROMPTS:
        prompt = builder()
        assert '"specialty_needs"' in prompt, (
            f"Builder {name!r} must include specialty_needs."
        )
        # The schema must show the {specialty, tool} pair shape.
        assert '"specialty"' in prompt and '"tool"' in prompt, (
            f"Builder {name!r} must pair specialty with a concrete tool."
        )


# --- Round 3 Fix D: prepare gets target_paths + critical-path uplift ---


def test_prepare_prompt_supports_target_paths() -> None:
    """Round-3: _build_prepare_sampling_prompt must accept and surface
    target_paths so the AI can anchor to concrete files."""
    from sumo_qa.tools import _build_prepare_sampling_prompt

    prompt = _build_prepare_sampling_prompt(
        work_item="Add expiry to refresh tokens",
        criteria=["tokens older than 30d are rejected"],
        risk_notes=["session continuity"],
        payload={
            "change_classification": {"primary": "security_change", "primary_confidence": "high"},
            "standards": {"checks": []},
            "applied_rules": {"must_consider": []},
            "missing_information": [],
        },
        target_paths=["src/auth/token_service.py"],
    )
    assert "src/auth/token_service.py" in prompt


def test_prepare_prompt_emits_critical_path_uplift_for_auth_change() -> None:
    """Round-3: when risk_notes / acceptance_criteria / work_item mention
    a critical-path token (auth, payment, token, ...), the prepare prompt
    must emit the critical-path uplift block citing Foundation Principle 4."""
    from sumo_qa.tools import _build_prepare_sampling_prompt

    prompt = _build_prepare_sampling_prompt(
        work_item="Add expiry to refresh tokens",
        criteria=["tokens older than 30d are rejected"],
        risk_notes=["replay of an expired token"],
        payload={
            "change_classification": {"primary": "security_change", "primary_confidence": "high"},
            "standards": {"checks": []},
            "applied_rules": {"must_consider": []},
            "missing_information": [],
        },
    )
    assert "CRITICAL-PATH UPLIFT" in prompt
    assert "Principle 4" in prompt or "principle 4" in prompt.lower()
    assert "OWASP" in prompt or "owasp" in prompt.lower()


def test_prepare_prompt_omits_critical_path_uplift_when_no_tokens() -> None:
    """Round-3: the critical-path uplift must only fire when tokens match —
    a refactor with no security-adjacent language gets the standard block."""
    from sumo_qa.tools import _build_prepare_sampling_prompt

    prompt = _build_prepare_sampling_prompt(
        work_item="Refactor pricing pipeline for clarity",
        criteria=["pricing math output unchanged"],
        risk_notes=["regression risk on rounding"],
        payload={
            "change_classification": {"primary": "refactor", "primary_confidence": "medium"},
            "standards": {"checks": []},
            "applied_rules": {"must_consider": []},
            "missing_information": [],
        },
    )
    assert "CRITICAL-PATH UPLIFT" not in prompt


def test_security_change_classification_present_in_rules() -> None:
    """Round-3: standards/rules/change_rules.yaml must contain a
    `security_change` classification mirroring existing structure."""
    import yaml
    from pathlib import Path

    rules_path = Path(__file__).parent.parent / "standards" / "rules" / "change_rules.yaml"
    data = yaml.safe_load(rules_path.read_text())
    assert "security_change" in data
    sec = data["security_change"]
    assert sec.get("must_consider"), "security_change must declare must_consider items"
    assert sec.get("suggested_test_types"), "security_change must declare suggested_test_types"
    assert sec.get("test_design_techniques"), "security_change must declare test_design_techniques"
    assert sec.get("quality_characteristics"), "security_change must declare quality_characteristics"
    assert sec.get("risk_templates"), "security_change must declare risk_templates"
    # The token-lifecycle vocabulary that distinguishes this from generic
    # business_logic_change must be present.
    must_consider_blob = " ".join(sec["must_consider"]).lower()
    assert "token" in must_consider_blob or "ttl" in must_consider_blob


def test_qa_prepare_for_work_accepts_target_paths_parameter() -> None:
    """Round-3: the public service method must accept a target_paths kwarg so
    the AI prompt can anchor to concrete files."""
    import inspect
    from sumo_qa.tools import QAShiftLeftService

    sig = inspect.signature(QAShiftLeftService.qa_prepare_for_work)
    assert "target_paths" in sig.parameters, (
        "qa_prepare_for_work must accept target_paths to anchor the AI plan."
    )
    asig = inspect.signature(QAShiftLeftService.aqa_prepare_for_work)
    assert "target_paths" in asig.parameters, (
        "aqa_prepare_for_work must accept target_paths so the MCP tool can pass it."
    )


# --- Round 4 Fix 1: specialty pairing is CONDITIONAL --------------------


def test_system_prompt_marks_specialty_pairing_as_conditional() -> None:
    """Round-4: the system prompt must spell out that specialty pairing is
    CONDITIONAL on the change's actual surface — purely in-process work
    legitimately has `specialty_needs: []`. Round-3's blanket HARD
    REQUIREMENT was over-strict and forced fake specialties for
    in-process validators."""
    sp = SENIOR_QA_SYSTEM_PROMPT
    assert "Specialty pairing is CONDITIONAL" in sp
    lower = sp.lower()
    # Empty list explicitly allowed for in-process work.
    assert "in-process" in lower
    assert "[]" in sp
    # The fit-the-risk principle (JJWT vs OWASP ZAP) must be named so
    # the AI cannot pair a specialty with a non-fitting tool.
    assert "JJWT" in sp
    assert "OWASP ZAP" in sp


def test_every_builder_allows_empty_specialty_needs_for_in_process_work() -> None:
    """Round-4: every per-tool sampling prompt must spell out that
    specialty_needs MAY be `[]` for in-process unit-level work. Round-3's
    HARD REQUIREMENT forced a specialty even for pure validators."""
    for name, builder in _BUILDER_PROMPTS:
        prompt = builder()
        lower = prompt.lower()
        assert "in-process" in lower, (
            f"Builder {name!r} must mention in-process exemption."
        )
        assert "[]" in prompt, (
            f"Builder {name!r} must allow empty specialty_needs list."
        )
        # The fit-the-risk principle must be present in every builder so
        # the AI doesn't pair (e.g.) a JWT TTL bump with OWASP ZAP DAST.
        assert "JJWT" in prompt and "OWASP ZAP" in prompt, (
            f"Builder {name!r} must name the JJWT vs OWASP ZAP fit example."
        )


# --- Round 4 Fix 2: scaffold prompt has boundary_scaffolds slot ---------


def test_scaffold_prompt_has_boundary_scaffolds_slot() -> None:
    """Round-4: scaffold builder must surface boundary_scaffolds so the AI
    can produce caller-level enforcement scaffolds when an AC uses
    enforcement language ('blocked at write time', 'rejected at submit',
    etc.). task_refinements alone only sharpens unit-level assertions and
    misses the boundary above."""
    prompt = _scaffold_prompt()
    assert '"boundary_scaffolds":' in prompt
    assert '"ac_text"' in prompt
    assert '"boundary_layer"' in prompt
    assert '"scaffold_assertion"' in prompt
    lower = prompt.lower()
    # The trigger language must be spelled out so the AI knows when this
    # field is required versus when `[]` is acceptable.
    assert "blocked at write time" in lower
    assert "enforcement language" in lower
