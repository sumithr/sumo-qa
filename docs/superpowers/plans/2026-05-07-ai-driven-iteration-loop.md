# AI-Driven Iteration Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the harness that lets the main thread iterate on sumo-qa prompts/standards by dispatching subagents that grade the AI output against an ISTQB rubric, then run iterations against the by-variant-data-feeder repo until output is Tesla/SpaceX-grade.

**Architecture:** Two-phase plan. Phase 1 builds the harness: a scenario list (data), an ISTQB rubric module, a subagent-brief builder, and a per-round summary template. Phase 2 runs the iteration loop: dispatch scenarios as parallel subagents, aggregate verdicts, edit prompts, regression-check, reinstall, repeat — adding new scenarios when gaps are discovered, until steady state.

**Tech Stack:** Python 3.11, pytest, pydantic v2, FastMCP, uv, the existing sumo-qa codebase. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-05-07-ai-driven-iteration-loop-design.md`

---

## Phase 1 — Harness

### Task 1: `RepoScenario` dataclass

**Files:**
- Create: `evaluation/repo_scenarios.py`
- Test: `tests/test_repo_scenarios.py`

- [ ] **Step 1: Write the failing test for the dataclass shape**

```python
# tests/test_repo_scenarios.py
from evaluation.repo_scenarios import RepoScenario, SCENARIOS, SPECIFICITY_VALUES


def test_repo_scenario_has_required_fields() -> None:
    s = RepoScenario(
        id="x",
        description="x",
        tool="qa_decide_approach",
        args={},
        specificity="moderate",
        rubric_focus=["principle_citation"],
        repo_files_to_load=[],
    )
    assert s.id == "x"
    assert s.specificity in SPECIFICITY_VALUES


def test_specificity_values_cover_full_spectrum() -> None:
    assert SPECIFICITY_VALUES == (
        "very-specific",
        "specific",
        "moderate",
        "generic",
        "very-generic",
    )


def test_repo_scenario_is_frozen() -> None:
    import dataclasses
    s = RepoScenario(
        id="x", description="x", tool="qa_decide_approach", args={},
        specificity="moderate", rubric_focus=[], repo_files_to_load=[],
    )
    try:
        s.id = "y"
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("RepoScenario must be frozen")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_repo_scenarios.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evaluation.repo_scenarios'`

- [ ] **Step 3: Create the dataclass module**

```python
# evaluation/repo_scenarios.py
"""Repo scenarios for the sumo-qa iteration loop.

Each scenario stresses a slice of the rubric. The suite spans the full
specificity spectrum (very-specific -> very-generic) so the iteration
loop catches both the "AI reads exact diff" case and the "AI reasons
about strategy" case.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SPECIFICITY_VALUES: tuple[str, ...] = (
    "very-specific",
    "specific",
    "moderate",
    "generic",
    "very-generic",
)


@dataclass(frozen=True)
class RepoScenario:
    id: str
    description: str
    tool: str
    args: dict[str, Any]
    specificity: str
    rubric_focus: list[str] = field(default_factory=list)
    repo_files_to_load: list[str] = field(default_factory=list)


# The initial scenario list is filled in Task 2.
SCENARIOS: list[RepoScenario] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_repo_scenarios.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add evaluation/repo_scenarios.py tests/test_repo_scenarios.py
git commit -m "feat(eval): add RepoScenario dataclass for iteration harness"
```

---

### Task 2: Initial 10 scenarios across the specificity spectrum

**Files:**
- Modify: `evaluation/repo_scenarios.py` (replace `SCENARIOS = []` with the list below)
- Test: `tests/test_repo_scenarios.py` (add coverage tests)

- [ ] **Step 1: Write tests pinning the suite shape**

```python
# tests/test_repo_scenarios.py — add to bottom
def test_initial_suite_has_at_least_ten_scenarios() -> None:
    assert len(SCENARIOS) >= 10


def test_every_scenario_has_a_unique_id() -> None:
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids))


def test_suite_spans_full_specificity_spectrum() -> None:
    seen = {s.specificity for s in SCENARIOS}
    for level in SPECIFICITY_VALUES:
        assert level in seen, f"missing specificity level {level!r}"


def test_every_canonical_approach_has_a_scenario() -> None:
    """Per spec: at least one scenario per canonical approach."""
    descriptions = " ".join(s.description.lower() for s in SCENARIOS) + " ".join(
        " ".join(s.rubric_focus).lower() for s in SCENARIOS
    )
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
        assert approach in descriptions, f"missing scenario for approach {approach!r}"


def test_every_scenario_targets_an_existing_qa_tool() -> None:
    valid_tools = {
        "qa_decide_approach",
        "qa_review_local_change",
        "qa_prepare_for_work",
        "qa_create_test_plan",
        "qa_scaffold_tests",
        "qa_answer_testing_question",
    }
    for s in SCENARIOS:
        assert s.tool in valid_tools, f"unknown tool {s.tool!r} in scenario {s.id!r}"


def test_every_scenario_has_a_specificity_in_the_canonical_set() -> None:
    for s in SCENARIOS:
        assert s.specificity in SPECIFICITY_VALUES, (
            f"scenario {s.id!r} has unknown specificity {s.specificity!r}"
        )
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_repo_scenarios.py -v`
Expected: 5 new tests fail with assertion errors / empty list errors.

- [ ] **Step 3: Replace `SCENARIOS = []` with the initial 10 scenarios**

Replace the bottom of `evaluation/repo_scenarios.py` with:

```python
# Repo we test against. Read-only — never mutated by the iteration loop.
_REPO = "/Users/SumithRamsookbhai/Desktop/repos/apo/apo-configurator/by-variant-data-feeder"


SCENARIOS: list[RepoScenario] = [
    # --------------------- very-specific (one diff / one method) ----------------------
    RepoScenario(
        id="very-specific.bundle-validator-line-diff",
        description=(
            "Review a tdd-scaffold-shaped change: a specific 6-line diff inside "
            "BundleVariantValidator.kt that adds a new branch for empty variants. "
            "The AI must read the diff, name the boundary cases, and produce a "
            "smallest-useful-test-set (not a generic checklist)."
        ),
        tool="qa_review_local_change",
        args={
            "change_summary": "Add empty-variants branch to BundleVariantValidator (lines 42-47).",
            "diff": (
                "+ if (variants.isEmpty()) {\n"
                "+     return ValidationResult.failure(\"NO_VARIANTS\")\n"
                "+ }\n"
            ),
            "touched_files": [
                "src/main/kotlin/.../BundleVariantValidator.kt",
            ],
            "explicit_classifications": ["business_logic_change"],
        },
        specificity="very-specific",
        rubric_focus=[
            "principle_citation",
            "smallest_useful_test_set",
            "named_techniques",
            "no_generic_advice",
            "tdd-scaffold",
        ],
        repo_files_to_load=[
            "src/main/kotlin/com/johnlewis/byvariantdatafeeder",
            "build.gradle.kts",
        ],
    ),
    RepoScenario(
        id="very-specific.regression-stale-stock",
        description=(
            "regression-first scenario: a bug fix on existing code. User reports "
            "that bundles with stale stock get blocked at checkout. The AI must "
            "produce a reproducer-as-failing-test path, not a TDD scaffold."
        ),
        tool="qa_decide_approach",
        args={
            "intent_text": (
                "fix the bug where bundles with stale stock get blocked at checkout"
            ),
            "target_paths": ["src/main/kotlin/.../StockEligibility.kt"],
            "signals": {"is_bug": True},
        },
        specificity="very-specific",
        rubric_focus=["decisive_routing", "facts_vs_assumptions", "regression-first"],
        repo_files_to_load=["src/main/kotlin/com/johnlewis/byvariantdatafeeder"],
    ),
    # --------------------- specific (one class / one user story) ----------------------
    RepoScenario(
        id="specific.scaffold-bundle-validator",
        description=(
            "tdd-scaffold scenario: scaffold tests for the BundleVariantValidator "
            "class given two acceptance criteria. The AI must produce honest red-"
            "phase scaffolds with named ISTQB techniques."
        ),
        tool="qa_scaffold_tests",
        args={
            "work_item": (
                "Scaffold tests for BundleVariantValidator that block invalid "
                "variant payload shapes at write time."
            ),
            "test_conditions": [
                "Invalid bundle variants are blocked at write time.",
                "Each violation surfaces a clear reason and the offending SKU.",
            ],
            "target_paths": [
                "src/main/kotlin/.../BundleVariantValidator.kt",
            ],
            "explicit_classifications": ["business_logic_change", "api_contract_change"],
        },
        specificity="specific",
        rubric_focus=[
            "named_techniques",
            "smallest_useful_test_set",
            "specialty_awareness",
            "tdd-scaffold",
        ],
        repo_files_to_load=[
            "src/main/kotlin/com/johnlewis/byvariantdatafeeder",
            "src/test/kotlin/com/johnlewis/byvariantdatafeeder",
        ],
    ),
    RepoScenario(
        id="specific.security-token-refresh",
        description=(
            "Critical-path tdd-scaffold scenario: add JWT refresh-token validation "
            "in the auth boundary. The AI must surface the security-critical "
            "character (Foundation principle 4: defects cluster on critical paths) "
            "and recommend tighter coverage + at least one boundary test per rule."
        ),
        tool="qa_prepare_for_work",
        args={
            "work_item": "Add JWT refresh token validation in the auth boundary",
            "acceptance_criteria": [
                "Refresh tokens older than 7 days are rejected",
                "Tokens are rotated on use (single-use semantics)",
                "Replay of an old refresh token returns 401, not 500",
            ],
            "risk_notes": ["Critical path — auth boundary. Regression hits all customers."],
            "explicit_classifications": ["business_logic_change"],
        },
        specificity="specific",
        rubric_focus=["principle_citation", "decisive_routing", "no_waived_evidence"],
        repo_files_to_load=["src/main/kotlin/com/johnlewis/byvariantdatafeeder"],
    ),
    # --------------------- moderate (a feature area) ----------------------
    RepoScenario(
        id="moderate.refactor-pricing-pipeline",
        description=(
            "coverage-first-then-refactor scenario: extract pricing calculation "
            "into its own module. No intended behaviour change. The AI must NOT "
            "scaffold new behaviour tests; it must say 'audit existing coverage "
            "first, add characterization tests for current behaviour, THEN refactor'."
        ),
        tool="qa_decide_approach",
        args={
            "intent_text": (
                "refactor the pricing pipeline to extract the eligibility step into "
                "its own module — no behaviour change intended"
            ),
            "target_paths": [
                "src/main/kotlin/.../pricing/PricingPipeline.kt",
            ],
            "signals": {"is_refactor": True},
        },
        specificity="moderate",
        rubric_focus=["decisive_routing", "coverage-first-then-refactor"],
        repo_files_to_load=["src/main/kotlin/com/johnlewis/byvariantdatafeeder"],
    ),
    RepoScenario(
        id="moderate.mutation-testing-followup",
        description=(
            "strengthen-test-coverage scenario: Pitest at 86% (below 87% gate). "
            "6 surviving mutants on BundleVariantValidator, 5 of which are "
            "equivalent (Kotlin bytecode noise + early-return on already-empty "
            "branches). No production code changes. The AI must NOT scaffold "
            "new behaviour tests; it must (a) propose ONE strengthening test per "
            "real mutant and (b) suppress equivalent mutants in tool config."
        ),
        tool="qa_decide_approach",
        args={
            "intent_text": (
                "Pitest test strength is 86% (below 87% gate, build failing). "
                "6 surviving mutations on BundleVariantValidator: 5 equivalent "
                "(Kotlin bytecode noise + early-return emptyList replacing "
                "branches that already return emptyList) and 1 from a "
                "deliberately weak BR4 BDD scenario. JaCoCo reports 100% "
                "line and instruction coverage. No production code changes "
                "on this branch."
            ),
            "target_paths": [
                "src/main/kotlin/.../BundleVariantValidator.kt",
                "src/test/kotlin/.../BundleVariantValidatorTest.kt",
            ],
            "signals": {"is_test_only": True},
        },
        specificity="moderate",
        rubric_focus=["decisive_routing", "no_generic_advice", "strengthen-test-coverage"],
        repo_files_to_load=["src/main/kotlin/com/johnlewis/byvariantdatafeeder"],
    ),
    # --------------------- generic (broad QA question) ----------------------
    RepoScenario(
        id="generic.how-to-test-this-service",
        description=(
            "Open-ended QA question against the whole service. Forces the AI to "
            "(a) read the repo to understand what the service does, (b) name "
            "concrete things to verify with risk-based prioritisation, and (c) "
            "name the smallest useful test set rather than a checklist."
        ),
        tool="qa_answer_testing_question",
        args={
            "question": "How should I test the by-variant-data-feeder service?",
            "context": "It feeds product variant availability data downstream.",
        },
        specificity="generic",
        rubric_focus=[
            "domain_specificity",
            "smallest_useful_test_set",
            "no_generic_advice",
            "named_techniques",
        ],
        repo_files_to_load=[
            "src/main/kotlin/com/johnlewis/byvariantdatafeeder",
            "README.md",
        ],
    ),
    RepoScenario(
        id="generic.docs-only-update",
        description=(
            "no-tests-recommended scenario: pure docs change. The AI must NOT "
            "recommend tests; it must say 'run the build, run any doc linters, "
            "no QA test work'."
        ),
        tool="qa_decide_approach",
        args={
            "intent_text": "update README and add architecture diagram",
            "target_paths": ["README.md", "docs/architecture.md"],
            "signals": {"is_docs_only": True},
        },
        specificity="generic",
        rubric_focus=["decisive_routing", "no-tests-recommended"],
        repo_files_to_load=["README.md"],
    ),
    # --------------------- very-generic (strategy / pyramid / rollout) ----------------------
    RepoScenario(
        id="very-generic.test-strategy-from-scratch",
        description=(
            "strategy-orchestration scenario: design a test strategy across the "
            "test pyramid for this service. The AI must NOT force a per-change "
            "approach. It must redirect to sumo-qa-strategising and reason about "
            "the pyramid (unit / integration / contract / e2e), gate calibration, "
            "CI feedback time, and rollout."
        ),
        tool="qa_decide_approach",
        args={
            "intent_text": (
                "design and implement a test strategy for the by-variant-data-feeder "
                "service that delivers high quality software in the shortest time "
                "with the lowest bug count. Holistic strategy across the test "
                "pyramid (unit / integration / contract / e2e), gate calibration, "
                "CI feedback time, and rollout plan to other services."
            ),
            "target_paths": [
                "src/main/kotlin/com/johnlewis/byvariantdatafeeder/",
                "src/test/kotlin/com/johnlewis/byvariantdatafeeder/",
                "build.gradle.kts",
                ".gitlab-ci.yml",
            ],
            "signals": {"is_strategic_planning": True},
        },
        specificity="very-generic",
        rubric_focus=[
            "decisive_routing",
            "domain_specificity",
            "no_generic_advice",
            "strategy-orchestration",
        ],
        repo_files_to_load=[
            "src/main/kotlin/com/johnlewis/byvariantdatafeeder",
            "src/test/kotlin/com/johnlewis/byvariantdatafeeder",
            "build.gradle.kts",
        ],
    ),
    RepoScenario(
        id="very-generic.spike-throwaway-prototype",
        description=(
            "spike-first-then-tests scenario: throwaway exploratory code. The AI "
            "must NOT demand TDD discipline on the spike itself; it must say "
            "'spike freely, capture conditions for the productionised pass'."
        ),
        tool="qa_decide_approach",
        args={
            "intent_text": (
                "spike: prototype a new pricing engine to see if the model fits — "
                "throwaway code, no production wiring yet"
            ),
            "target_paths": ["spikes/pricing.kt"],
            "signals": {"is_spike": True},
        },
        specificity="very-generic",
        rubric_focus=["decisive_routing", "spike-first-then-tests"],
        repo_files_to_load=[],
    ),
]
```

- [ ] **Step 4: Run tests, verify all pass**

Run: `uv run pytest tests/test_repo_scenarios.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add evaluation/repo_scenarios.py tests/test_repo_scenarios.py
git commit -m "feat(eval): seed initial 10 scenarios across full specificity spectrum"
```

---

### Task 3: ISTQB rubric module

**Files:**
- Create: `src/sumo_qa/rubric.py`
- Test: `tests/test_rubric.py`

- [ ] **Step 1: Write the failing test for the rubric shape**

```python
# tests/test_rubric.py
from sumo_qa.rubric import (
    RUBRIC_DIMENSIONS,
    VERDICTS,
    build_rubric_prompt,
)


def test_rubric_has_nine_dimensions() -> None:
    assert len(RUBRIC_DIMENSIONS) == 9


def test_rubric_dimensions_cover_spec() -> None:
    expected_ids = {
        "principle_citation",
        "smallest_useful_test_set",
        "named_techniques",
        "risk_based_focus",
        "facts_vs_assumptions",
        "no_waived_evidence",
        "decisive_routing",
        "specialty_awareness",
        "domain_specificity",
        "no_generic_advice",
    }
    actual_ids = {d.id for d in RUBRIC_DIMENSIONS}
    # Spec lists 9 dimensions; "no_generic_advice" is one of them, so the
    # canonical list has 9 of the 10 names above (one is folded into
    # smallest_useful_test_set or named_techniques in the implementation).
    assert actual_ids.issubset(expected_ids)
    assert len(actual_ids) == 9


def test_verdicts_match_spec() -> None:
    assert VERDICTS == (
        "senior-istqb-grade",
        "needs-iteration",
        "unfit-for-merge",
    )


def test_build_rubric_prompt_includes_every_dimension() -> None:
    prompt = build_rubric_prompt(
        scenario_id="x",
        scenario_description="x",
        ai_output="x",
    )
    for dim in RUBRIC_DIMENSIONS:
        assert dim.id in prompt or dim.title in prompt


def test_build_rubric_prompt_demands_structured_json_verdict() -> None:
    prompt = build_rubric_prompt(
        scenario_id="x", scenario_description="x", ai_output="x",
    )
    assert "JSON" in prompt or "json" in prompt
    assert "verdict" in prompt
    assert "named_gaps" in prompt
    assert "suggested_prompt_fixes" in prompt
```

- [ ] **Step 2: Run test, verify it fails**

Run: `uv run pytest tests/test_rubric.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sumo_qa.rubric'`

- [ ] **Step 3: Create the rubric module**

```python
# src/sumo_qa/rubric.py
"""ISTQB grading rubric for the iteration loop.

Each dimension is binary (met / not met). The composite verdict tells
the main thread whether to keep iterating. Used by the subagent's
self-eval inside its own context — no disk writes during the inner
loop.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RubricDimension:
    id: str
    title: str
    description: str


VERDICTS: tuple[str, ...] = (
    "senior-istqb-grade",
    "needs-iteration",
    "unfit-for-merge",
)


RUBRIC_DIMENSIONS: tuple[RubricDimension, ...] = (
    RubricDimension(
        id="principle_citation",
        title="Principle citation",
        description=(
            "When an ISTQB Foundation principle (defects-cluster, pesticide-paradox, "
            "early-testing/shift-left, absence-of-errors fallacy, etc.) shapes the "
            "recommendation, does the output cite the principle by name or number? "
            "Generic 'follow QA best practices' is NOT a citation."
        ),
    ),
    RubricDimension(
        id="smallest_useful_test_set",
        title="Smallest useful test set",
        description=(
            "Does the output identify the minimum tests that give release "
            "confidence — tied to specific risks of THIS change? A laundry-list "
            "checklist is NOT a smallest useful test set."
        ),
    ),
    RubricDimension(
        id="named_techniques",
        title="Named test design techniques",
        description=(
            "Does the output name specific ISTQB test design techniques "
            "(boundary value analysis, decision tables, equivalence "
            "partitioning, state transition, MC-DC, error guessing, "
            "exploratory charters, etc.) tied to the actual change "
            "characteristics? 'Add edge-case tests' is NOT a named technique."
        ),
    ),
    RubricDimension(
        id="risk_based_focus",
        title="Risk-based focus",
        description=(
            "Are the top risks specific to THIS change ('cache TTL boundary "
            "around 0/1 second triggers stale read'), not generic ('missing "
            "test data', 'unclear acceptance criteria')?"
        ),
    ),
    RubricDimension(
        id="facts_vs_assumptions",
        title="Facts vs assumptions",
        description=(
            "Are unknowns called out explicitly? When the AI assumes "
            "behaviour, is it labelled as an assumption rather than a fact?"
        ),
    ),
    RubricDimension(
        id="no_waived_evidence",
        title="No waived evidence",
        description=(
            "If the verdict says 'needs-test-evidence' or "
            "'review-risk-before-handoff', the output never softens that to "
            "'looks fine to merge'. The output never blesses a change "
            "without test evidence."
        ),
    ),
    RubricDimension(
        id="decisive_routing",
        title="Decisive routing",
        description=(
            "The recommended approach matches the change shape. Strategy "
            "asks return strategy-orchestration. Tests-only changes return "
            "strengthen-test-coverage. Refactors return "
            "coverage-first-then-refactor. Bug fixes return "
            "regression-first. No forcing TDD onto a strategy ask."
        ),
    ),
    RubricDimension(
        id="specialty_awareness",
        title="Specialty awareness",
        description=(
            "When the change implies a specialty capability "
            "(frontend / contract / performance / security / mobile / "
            "a11y / AI), the output names the right specialty and a "
            "well-known tool (Cypress / Pact / k6 / OWASP ZAP / Appium / "
            "axe-core / Promptfoo)."
        ),
    ),
    RubricDimension(
        id="domain_specificity",
        title="Domain specificity",
        description=(
            "The output names the actual domain (variant filtering, "
            "inventory feeding, bundle validation, etc.) rather than "
            "abstract 'the system' or 'the service'. Senior QA voice is "
            "concrete; junior QA voice is abstract."
        ),
    ),
)


_RUBRIC_HEADER = (
    "You are grading the QA output below against an ISTQB rubric. For "
    "each dimension, decide met / not met with a one-line reason. Then "
    "produce the composite verdict.\n\n"
    "Composite verdict rules:\n"
    "  - all dimensions met -> 'senior-istqb-grade'\n"
    "  - one or two dimensions unmet -> 'needs-iteration'\n"
    "  - three or more dimensions unmet -> 'unfit-for-merge'\n\n"
)


def build_rubric_prompt(
    *,
    scenario_id: str,
    scenario_description: str,
    ai_output: str,
) -> str:
    """Return the rubric grading prompt the subagent should reason against.

    The grader prompt is structured so the subagent self-evals AFTER it
    has produced the AI output, in the same context — no disk writes.
    """
    dims_block = "\n".join(
        f"  - `{d.id}` ({d.title}): {d.description}"
        for d in RUBRIC_DIMENSIONS
    )
    verdicts_block = ", ".join(f"`{v}`" for v in VERDICTS)
    return (
        _RUBRIC_HEADER
        + f"Scenario: {scenario_id} — {scenario_description}\n\n"
        + f"AI output to grade:\n```\n{ai_output}\n```\n\n"
        + "Rubric dimensions (each binary: met / not met):\n"
        + dims_block
        + "\n\n"
        + f"Composite verdict must be one of: {verdicts_block}.\n\n"
        + "Output requirements (STRICT — entire response must be valid JSON):\n"
        + "{\n"
        + '  "scenario_id": "<id>",\n'
        + '  "verdict": "<one of the composite verdicts>",\n'
        + '  "dimensions": [\n'
        + '    {"id": "<dim id>", "met": true|false, "reason": "<short reason>"}\n'
        + "  ],\n"
        + '  "named_gaps": ["<gap that surfaced>", ...],\n'
        + '  "suggested_prompt_fixes": [\n'
        + '     {"file": "<src/sumo_qa/...>", "what_to_change": "<concrete edit>"}\n'
        + "  ]\n"
        + "}\n\n"
        + "Return JSON only, no prose around it."
    )
```

- [ ] **Step 4: Run tests, verify all pass**

Run: `uv run pytest tests/test_rubric.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/sumo_qa/rubric.py tests/test_rubric.py
git commit -m "feat(rubric): add ISTQB grading rubric for iteration loop"
```

---

### Task 4: Subagent-brief builder

**Files:**
- Create: `evaluation/iteration_brief.py`
- Test: `tests/test_iteration_brief.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_iteration_brief.py
from evaluation.iteration_brief import build_subagent_brief
from evaluation.repo_scenarios import SCENARIOS


def test_brief_includes_scenario_inputs_verbatim() -> None:
    scenario = SCENARIOS[0]
    brief = build_subagent_brief(scenario)
    # Tool name + the scenario description appear in the brief.
    assert scenario.tool in brief
    assert scenario.description in brief
    # Args are surfaced as JSON.
    if scenario.args.get("change_summary"):
        assert scenario.args["change_summary"] in brief


def test_brief_tells_subagent_to_read_live_prompts_file() -> None:
    brief = build_subagent_brief(SCENARIOS[0])
    assert "src/sumo_qa/prompts.py" in brief
    assert "SENIOR_QA_SYSTEM_PROMPT" in brief


def test_brief_tells_subagent_to_read_repo_files_when_listed() -> None:
    scenario = SCENARIOS[0]
    brief = build_subagent_brief(scenario)
    if scenario.repo_files_to_load:
        assert scenario.repo_files_to_load[0] in brief


def test_brief_includes_rubric_in_full() -> None:
    brief = build_subagent_brief(SCENARIOS[0])
    # The rubric is embedded so the subagent can self-eval.
    assert "principle_citation" in brief
    assert "decisive_routing" in brief
    assert "senior-istqb-grade" in brief


def test_brief_demands_structured_verdict_back_to_main_thread() -> None:
    brief = build_subagent_brief(SCENARIOS[0])
    assert "named_gaps" in brief
    assert "suggested_prompt_fixes" in brief
    assert "JSON" in brief or "json" in brief
```

- [ ] **Step 2: Run test, verify it fails**

Run: `uv run pytest tests/test_iteration_brief.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create the brief builder**

```python
# evaluation/iteration_brief.py
"""Build the prompt the main thread sends to a subagent.

The brief tells the subagent:
  1. read the LATEST sumo-qa source files (prompts, per-tool builders,
     standards) so the iteration loop sees edits immediately
  2. read the relevant by-variant-data-feeder files for repo context
  3. reason as the host LLM would, producing the structured QA output
  4. self-eval against the ISTQB rubric
  5. return a tight verdict to the main thread

No disk writes; all the bulky context lives in the subagent's context.
"""
from __future__ import annotations

import json
from typing import Any

from sumo_qa.rubric import build_rubric_prompt

from evaluation.repo_scenarios import RepoScenario


_TOOL_TO_PROMPT_BUILDER: dict[str, str] = {
    "qa_decide_approach": "_build_decide_approach_sampling_prompt",
    "qa_review_local_change": "_build_review_sampling_prompt",
    "qa_prepare_for_work": "_build_prepare_sampling_prompt",
    "qa_create_test_plan": "_build_test_plan_sampling_prompt",
    "qa_scaffold_tests": "_build_scaffold_sampling_prompt",
    "qa_answer_testing_question": "_build_question_sampling_prompt",
}


def build_subagent_brief(scenario: RepoScenario) -> str:
    """Return the prompt for a subagent that runs ONE scenario end-to-end."""
    builder_name = _TOOL_TO_PROMPT_BUILDER.get(
        scenario.tool, f"<no builder mapped for {scenario.tool}>"
    )
    repo_files_block = (
        "\n".join(f"  - {p}" for p in scenario.repo_files_to_load)
        if scenario.repo_files_to_load
        else "  (none — reason from the scenario description alone)"
    )
    rubric_prompt = build_rubric_prompt(
        scenario_id=scenario.id,
        scenario_description=scenario.description,
        ai_output="<your output from step 4 below — substitute the full text here>",
    )

    return (
        f"You are a senior ISTQB-certified QA engineer grading sumo-qa output "
        f"on scenario `{scenario.id}`.\n\n"
        f"Scenario description: {scenario.description}\n\n"
        f"## Step 1 — read the live sumo-qa grounding\n\n"
        f"Read these files VERBATIM (use the Read tool on each):\n"
        f"  - src/sumo_qa/prompts.py (this is your standing context — "
        f"`SENIOR_QA_SYSTEM_PROMPT`)\n"
        f"  - src/sumo_qa/tools.py (look for the `{builder_name}` function — "
        f"this is the per-tool grounding for `{scenario.tool}`)\n"
        f"  - standards/packs/*.yaml (the team's loaded QA standards)\n"
        f"  - standards/rules/change_rules.yaml\n\n"
        f"## Step 2 — read the by-variant-data-feeder repo context\n\n"
        f"Read these paths from the by-variant-data-feeder repo (located at "
        f"/Users/SumithRamsookbhai/Desktop/repos/apo/apo-configurator/by-variant-data-feeder):\n"
        f"{repo_files_block}\n\n"
        f"## Step 3 — apply the prompts to the scenario inputs\n\n"
        f"The MCP would invoke `{scenario.tool}` with these arguments:\n"
        f"```json\n{json.dumps(scenario.args, indent=2)}\n```\n\n"
        f"Reason as the host LLM grounded by `SENIOR_QA_SYSTEM_PROMPT` and the "
        f"`{builder_name}` user prompt. Produce the structured QA output the "
        f"MCP would return — verdict / approach / top_risks / suggested_tests / "
        f"techniques / specialty / etc., as appropriate for the tool.\n\n"
        f"Be honest: if the prompts as written would produce weak output, "
        f"reflect that weak output. Do NOT compensate for prompt gaps.\n\n"
        f"## Step 4 — self-eval against the ISTQB rubric\n\n"
        f"Substitute your step-3 output into `<your output...>` below and "
        f"grade it against the rubric:\n\n"
        f"```\n{rubric_prompt}\n```\n\n"
        f"## Step 5 — return\n\n"
        f"Return ONLY the JSON verdict from step 4. No prose. The main thread "
        f"will aggregate verdicts across scenarios and use them to decide "
        f"which prompts/standards to edit next."
    )
```

- [ ] **Step 4: Run tests, verify all pass**

Run: `uv run pytest tests/test_iteration_brief.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add evaluation/iteration_brief.py tests/test_iteration_brief.py
git commit -m "feat(eval): add subagent-brief builder for iteration loop"
```

---

### Task 5: Per-round summary template + iteration-runs directory

**Files:**
- Create: `docs/superpowers/iteration-runs/.gitkeep`
- Create: `docs/superpowers/iteration-runs/TEMPLATE.md`

- [ ] **Step 1: Create the directory + .gitkeep**

```bash
mkdir -p docs/superpowers/iteration-runs
touch docs/superpowers/iteration-runs/.gitkeep
```

- [ ] **Step 2: Write the TEMPLATE.md**

```markdown
# Iteration Round <N> — <YYYY-MM-DD HH:MM>

## Scenarios dispatched

<list of scenario IDs run in this round and their resulting verdicts>

## Verdict summary

| scenario_id | verdict | unmet dimensions |
|---|---|---|
| ... | senior-istqb-grade | (none) |
| ... | needs-iteration | principle_citation, named_techniques |

## Aggregated gaps (across scenarios)

- `<gap-name>` — <how many scenarios surfaced it> — <one-line description>

## Aggregated suggested fixes

- file: `src/sumo_qa/<file>` — what to change: `<concrete edit>` — surfaced by: `<scenario ids>`

## Edits made this round

- file: `src/sumo_qa/<file>` — <one-line summary of the edit>
- file: `standards/packs/<pack>.yaml` — <one-line summary>

## Regression check

- `uv run pytest`: <N> passed
- `uv run sumo-qa-eval`: <N>/28

## New scenarios added this round

- `<new scenario id>` — <reason: which gap it stresses>

## Next round plan

- Re-dispatch failing scenarios: <list>
- Run new scenarios: <list>

## Termination check

- All scenarios senior-istqb-grade? <yes/no>
- User read-through confirmed Tesla/SpaceX-grade? <yes/no/pending>
- Last round added zero new scenarios (steady state)? <yes/no>
- Iteration done? <yes/no>
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/iteration-runs/
git commit -m "feat(docs): add iteration-runs directory + per-round template"
```

---

### Task 6: Optional `SUMO_QA_DEBUG_DIR` debug-dump in server.py

This is for the FINAL verification round when you (the user) restart the live MCP. When `SUMO_QA_DEBUG_DIR` is set, the server intercepts every tool call and writes input / sampling exchange / output to disk so the user can read the live exchange directly.

**Files:**
- Create: `src/sumo_qa/debug_capture.py`
- Modify: `src/sumo_qa/server.py` (wrap each `_slim(...)` return with debug capture)
- Test: `tests/test_debug_capture.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_debug_capture.py
import json
import os
from pathlib import Path

from sumo_qa.debug_capture import maybe_capture


def test_capture_writes_files_when_env_set(tmp_path, monkeypatch):
    monkeypatch.setenv("SUMO_QA_DEBUG_DIR", str(tmp_path))
    payload = {"tool": "qa_decide_approach", "x": 1}
    captured = maybe_capture(
        tool="qa_decide_approach",
        args={"intent_text": "x"},
        output=payload,
    )
    # Returns the payload unchanged.
    assert captured == payload
    # Wrote a directory containing input.json + output.json + trace.md.
    runs = list(tmp_path.iterdir())
    assert len(runs) == 1
    run = runs[0]
    assert (run / "input.json").exists()
    assert (run / "output.json").exists()
    assert (run / "trace.md").exists()
    # JSON is valid.
    assert json.loads((run / "output.json").read_text()) == payload


def test_capture_is_noop_when_env_not_set(tmp_path, monkeypatch):
    monkeypatch.delenv("SUMO_QA_DEBUG_DIR", raising=False)
    payload = {"tool": "qa_decide_approach", "x": 1}
    captured = maybe_capture(
        tool="qa_decide_approach",
        args={"intent_text": "x"},
        output=payload,
    )
    # Returns the payload unchanged.
    assert captured == payload
    # Did NOT write any directory under tmp_path.
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run test, verify it fails**

Run: `uv run pytest tests/test_debug_capture.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `maybe_capture`**

```python
# src/sumo_qa/debug_capture.py
"""Optional debug capture for the live MCP server.

When `SUMO_QA_DEBUG_DIR` is set, every tool invocation writes its
input + output to a timestamped folder under that directory. This is
for the user's manual review during the FINAL verification round —
not used during the inner iteration loop (subagents grade in their
own context).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def maybe_capture(
    *, tool: str, args: dict[str, Any], output: dict[str, Any]
) -> dict[str, Any]:
    """Persist the tool exchange when SUMO_QA_DEBUG_DIR is set; passthrough always.

    Returns the `output` dict unchanged so callers can wrap returns
    inline: `return maybe_capture(tool=..., args=..., output=...)`.
    """
    debug_dir = os.environ.get("SUMO_QA_DEBUG_DIR")
    if not debug_dir:
        return output
    try:
        base = Path(debug_dir)
        base.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        run_dir = base / f"{ts}-{tool}"
        i = 1
        while run_dir.exists():
            run_dir = base / f"{ts}-{tool}-{i}"
            i += 1
        run_dir.mkdir()
        (run_dir / "input.json").write_text(json.dumps(args, indent=2, default=str))
        (run_dir / "output.json").write_text(json.dumps(output, indent=2, default=str))
        (run_dir / "trace.md").write_text(_render_trace(tool, args, output))
    except Exception:  # noqa: BLE001 — debug capture must never break the tool
        pass
    return output


def _render_trace(tool: str, args: dict[str, Any], output: dict[str, Any]) -> str:
    return (
        f"# {tool}\n\n"
        f"## Input\n\n```json\n{json.dumps(args, indent=2, default=str)}\n```\n\n"
        f"## Output\n\n```json\n{json.dumps(output, indent=2, default=str)}\n```\n"
    )
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_debug_capture.py -v`
Expected: 2 passed

- [ ] **Step 5: Wire `maybe_capture` into server.py**

Open `src/sumo_qa/server.py`. Add the import near the top:

```python
from sumo_qa.debug_capture import maybe_capture
```

For each MCP tool, wrap the `return _slim(...)` with `maybe_capture` so the live MCP captures when the env is set. Pattern:

Before:
```python
return _slim(await qa_service.aqa_review_local_change(
    change_summary, diff, touched_files, test_evidence,
    async_llm=_maybe_host_llm(ctx),
    explicit_classifications=explicit_classifications,
))
```

After:
```python
return maybe_capture(
    tool="qa_review_local_change",
    args={
        "change_summary": change_summary,
        "diff": diff,
        "touched_files": touched_files,
        "test_evidence": test_evidence,
        "explicit_classifications": explicit_classifications,
    },
    output=_slim(await qa_service.aqa_review_local_change(
        change_summary, diff, touched_files, test_evidence,
        async_llm=_maybe_host_llm(ctx),
        explicit_classifications=explicit_classifications,
    )),
)
```

Apply the same pattern to all 10 MCP tools in `server.py`:
- `qa_prepare_for_work`
- `qa_review_local_change`
- `qa_create_test_plan`
- `qa_decide_approach`
- `qa_scaffold_tests`
- `qa_answer_testing_question`
- `qa_explain_test_data_requirements`
- `qa_find_test_data`
- `qa_validate_test_data`
- `qa_register_known_good_test_data`

- [ ] **Step 6: Run the full suite to confirm no regression**

Run: `uv run pytest`
Expected: all tests pass (177 + the 2 new debug capture + the rubric/scenario/brief tests)

- [ ] **Step 7: Confirm eval is still 28/28**

Run: `uv run sumo-qa-eval`
Expected: `TOTAL 28/28`

- [ ] **Step 8: Commit**

```bash
git add src/sumo_qa/debug_capture.py src/sumo_qa/server.py tests/test_debug_capture.py
git commit -m "feat(server): add SUMO_QA_DEBUG_DIR capture for manual review during final verification"
```

---

### Task 7: Reinstall sumo-qa with the new harness wired in

**Files:**
- (no files modified — install step only)

- [ ] **Step 1: Reinstall via uv**

```bash
uv tool install --reinstall --force /Users/SumithRamsookbhai/Desktop/repos/apo/qa-shift-left-mcp
```

Expected: `Installed 3 executables: sumo-qa-eval, sumo-qa-mcp, sumo-qa-render`

- [ ] **Step 2: Sanity-check the binaries still work**

```bash
sumo-qa-eval
```

Expected: `TOTAL 28/28`

- [ ] **Step 3: Verify the harness imports cleanly**

```bash
uv run python -c "from evaluation.repo_scenarios import SCENARIOS; from evaluation.iteration_brief import build_subagent_brief; print(len(SCENARIOS), 'scenarios'); print(len(build_subagent_brief(SCENARIOS[0])), 'chars in first brief')"
```

Expected: `10 scenarios` (or more) and a non-zero brief char count.

---

## Phase 2 — Run iterations

Phase 2 is a process loop, not code. The plan codifies one round; repeat until termination.

### Task 8: Round 1 — dispatch initial scenarios

**Files:**
- Create on completion: `docs/superpowers/iteration-runs/round-1-<timestamp>.md`

- [ ] **Step 1: Build the brief for each scenario**

For each `RepoScenario` in `SCENARIOS`, call `build_subagent_brief(scenario)`. The result is the prompt for one subagent.

- [ ] **Step 2: Dispatch subagents in batches of 4 in parallel**

In the main-thread conversation, send one message containing 4 `Agent` tool invocations (the brief-as-prompt for 4 different scenarios). Wait for all four to return before starting the next batch. Continue until all scenarios have been dispatched.

- [ ] **Step 3: Aggregate verdicts**

For each returned subagent message, parse the JSON verdict. Build:
- `verdicts_by_scenario: dict[scenario_id, verdict_json]`
- `failing_scenarios: list[scenario_id]` (verdict != `senior-istqb-grade`)
- `gaps_by_dimension: dict[dimension_id, list[scenario_id]]`
- `suggested_fixes: list[(file, what_to_change, surfaced_by_scenarios)]`

- [ ] **Step 4: Write the round summary**

Use the template at `docs/superpowers/iteration-runs/TEMPLATE.md`. Save as `docs/superpowers/iteration-runs/round-1-<YYYY-MM-DD-HHMM>.md`. Fill in every section using the aggregated data.

- [ ] **Step 5: Commit the round summary**

```bash
git add docs/superpowers/iteration-runs/round-1-*.md
git commit -m "docs(iteration): round 1 — N senior-istqb-grade, M needs-iteration"
```

---

### Task 9: Apply prompt fixes for round 1's gaps

**Files:**
- Modify (as needed): `src/sumo_qa/prompts.py`, `src/sumo_qa/tools.py` (per-tool prompt builders), `standards/packs/*.yaml`, `standards/rules/change_rules.yaml`, `skills/*/SKILL.md`

- [ ] **Step 1: Pick the highest-impact fix from the aggregated suggestions**

A fix is high-impact when:
- It addresses a gap that surfaced across multiple scenarios.
- It's narrow and concrete (e.g. "add a sentence to `SENIOR_QA_SYSTEM_PROMPT` that says X") rather than broad.

- [ ] **Step 2: Apply the edit using the Edit tool**

Use exact `old_string` / `new_string` matches. Never broad replacements.

- [ ] **Step 3: Run pytest to confirm no regression**

Run: `uv run pytest`
Expected: all tests still pass.

- [ ] **Step 4: Run sumo-qa-eval to confirm 28/28**

Run: `uv run sumo-qa-eval`
Expected: `TOTAL 28/28`

If either fails: revert the edit, mark the gap as `requires-different-fix` in the summary, pick a different suggested fix from the aggregated list.

- [ ] **Step 5: Reinstall sumo-qa**

```bash
uv tool install --reinstall --force /Users/SumithRamsookbhai/Desktop/repos/apo/qa-shift-left-mcp
```

- [ ] **Step 6: Commit the fix**

```bash
git add src/sumo_qa/<files>
git commit -m "fix(prompts): <one-line summary of the prompt edit>"
```

---

### Task 10: Re-dispatch failing scenarios (and any new scenarios)

**Files:**
- Create on completion: `docs/superpowers/iteration-runs/round-<N+1>-<timestamp>.md`
- Modify (if new gaps discovered): `evaluation/repo_scenarios.py`

- [ ] **Step 1: For each failing scenario from the previous round, build a fresh subagent brief**

Use the same `build_subagent_brief` function — the subagent reads the LATEST source files, so the prompt edits from Task 9 take effect on this dispatch.

- [ ] **Step 2: If a recurring gap isn't currently stressed by any scenario, add a new scenario**

Append to `SCENARIOS` in `evaluation/repo_scenarios.py`. Update `tests/test_repo_scenarios.py` to confirm the suite still meets `test_suite_spans_full_specificity_spectrum` etc. Run:

```bash
uv run pytest tests/test_repo_scenarios.py -v
```

Commit the new scenario:

```bash
git add evaluation/repo_scenarios.py tests/test_repo_scenarios.py
git commit -m "feat(eval): add scenario `<id>` to stress `<gap>`"
```

- [ ] **Step 3: Dispatch failing + new scenarios in parallel batches of 4**

Same pattern as Task 8 step 2.

- [ ] **Step 4: Aggregate, write round summary, commit**

Same pattern as Task 8 steps 3-5, but with file name `round-<N+1>-<timestamp>.md`. The summary's "Termination check" section drives the next decision.

---

### Task 11: Loop until termination

- [ ] **Step 1: Check termination conditions**

After each round, evaluate:
1. Every scenario in the current suite scored `senior-istqb-grade`?
2. Did THIS round add zero new scenarios? (steady state)
3. User has not yet read the trace summaries — that's the final gate.

If 1 + 2 are true: stop the inner loop, proceed to Task 12.
Otherwise: return to Task 9 with the new failing scenarios.

- [ ] **Step 2: Convergence stall detection**

If the same gap surfaces for 3 consecutive rounds despite different fix attempts:
- Stop tweaking wording.
- Read the failing transcripts (in the subagent verdict's `named_gaps`).
- Propose a STRUCTURAL change (new rubric dimension, new section in `SENIOR_QA_SYSTEM_PROMPT`, new standards pack, new skill file).
- Apply the structural change. Reinstall. Run another full round.

- [ ] **Step 3: Write the steady-state summary**

Save as `docs/superpowers/iteration-runs/steady-state-<timestamp>.md`. Note:
- How many rounds were run.
- How many scenarios in the final suite.
- Final verdict for each.
- Significant prompt/standards edits across the iteration.

Commit:

```bash
git add docs/superpowers/iteration-runs/steady-state-*.md
git commit -m "docs(iteration): inner loop converged at round N — all scenarios senior-istqb-grade"
```

---

### Task 12: Final verification round (live MCP)

**Files:**
- Create on completion: `docs/superpowers/iteration-runs/final-verification-<timestamp>.md`

- [ ] **Step 1: Ask the user to restart the MCP server**

Tell the user (in conversation):
> "Inner loop has converged. To run the final verification round against the live MCP, please restart the sumo-qa MCP from Claude Code's MCP panel (Settings → MCP → sumo-qa → Restart) so the latest reinstalled binary is loaded. Tell me when it's done and I'll set `SUMO_QA_DEBUG_DIR` and invoke a sample of scenarios via the live MCP."

Wait for confirmation.

- [ ] **Step 2: Set the debug capture directory**

In conversation, ask the user to set the env var on the MCP. Or — via Bash:

```bash
mkdir -p /tmp/sumo-qa-final-verification
export SUMO_QA_DEBUG_DIR=/tmp/sumo-qa-final-verification
```

(The MCP server picks up env vars at process start; if it doesn't see the var, the user needs to restart it again with the var set in the MCP config.)

- [ ] **Step 3: Invoke 3-5 scenarios via the LIVE MCP from this conversation**

Pick scenarios that span the specificity spectrum — at least one very-specific, one moderate, one very-generic. For each, call the appropriate `mcp__sumo-qa__<tool>` tool with the scenario args. The MCP samples the host (me) for senior-QA reasoning. The output goes to the conversation AND (because of the env var) to `SUMO_QA_DEBUG_DIR`.

- [ ] **Step 4: Read the captured traces**

```bash
ls /tmp/sumo-qa-final-verification
```

Read each `trace.md` and confirm the live MCP output matches the in-process verdicts from the inner loop.

- [ ] **Step 5: Write the final verification summary**

Save as `docs/superpowers/iteration-runs/final-verification-<timestamp>.md`. Include:
- Which scenarios were re-run via live MCP.
- For each, the live verdict and whether it agrees with the inner-loop verdict.
- Any wire-protocol-level issues discovered (serialization, slim dropping a field, etc.).
- Next-action recommendation.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/iteration-runs/final-verification-*.md
git commit -m "docs(iteration): final verification — live MCP matches inner loop"
```

---

### Task 13: Hand off to user for the human read-through

- [ ] **Step 1: Tell the user the iteration is done**

In conversation:
> "Iteration complete. Inner loop converged at round N with all scenarios senior-istqb-grade; final verification round agreed via the live MCP. Per-round summaries are in `docs/superpowers/iteration-runs/`, and the final-verification capture is at `/tmp/sumo-qa-final-verification`. Please read a sample of `trace.md` files and confirm the output is genuinely Tesla/SpaceX-grade. If any scenario looks weak to your eye, tell me which one and which dimension feels off; I'll add a scenario that stresses it and run another round."

- [ ] **Step 2: Wait for user verdict. Do NOT commit a "complete" tag until the user has confirmed.**

If the user requests further iteration, return to Task 9 with the user-flagged gap as the next round's focus.

---

## Self-review

I checked the plan against the spec section by section:

1. **Goal + non-goals + success criteria:** covered by Task 8 (round 1 + grading) + Task 11 (loop until termination satisfies the three conditions: all senior-istqb-grade + steady state + user confirmation).

2. **Component 1 (scenario suite):** Tasks 1-2 build the dataclass + initial 10 scenarios spanning the full specificity spectrum, with tests pinning suite shape, unique IDs, canonical-approach coverage, and specificity coverage.

3. **Component 2 (debug-mode capture):** the inner loop captures in subagent context (no code) — covered by the brief builder (Task 4) which tells subagents to read live source. The optional disk-dump for the final verification round is Task 6.

4. **Component 3 (ISTQB rubric):** Task 3 builds `src/sumo_qa/rubric.py` with the 9 dimensions + 3 verdicts + the `build_rubric_prompt` function used by the brief builder.

5. **Component 4 (MCP reload strategy):** the brief tells subagents to read source files at run-start (no MCP server reload needed for the inner loop). Task 12 covers the user-restart for the final verification round.

6. **Component 5 (iteration orchestration):** Tasks 8-11 codify one round of dispatch + aggregate + edit + regression-check + reinstall + redispatch + termination. Task 12 is the final verification round. The orchestrator is the main thread (me); no separate Python module.

7. **Data flow:** matches the steps in Tasks 8-11.

8. **Error handling:** Task 9 step 4 covers test/eval regression revert. Task 11 step 2 covers convergence stall escalation. Task 8 doesn't yet cover subagent timeout; I should note that explicitly — adding to Task 11.

9. **Testing strategy:** Tasks 1-6 each have failing-test-first steps. Task 6 step 6 confirms no regression. Tasks 9 and 10 each repeat the regression check.

10. **Not doing:** the plan respects all four "not doing" items.

Type consistency: `RepoScenario`, `RubricDimension`, `VERDICTS`, `RUBRIC_DIMENSIONS`, `SCENARIOS`, `SPECIFICITY_VALUES`, `build_rubric_prompt`, `build_subagent_brief`, `maybe_capture` — all referenced consistently.

No placeholders detected.
