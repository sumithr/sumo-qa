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
    RubricDimension(
        id="no_generic_advice",
        title="No generic advice",
        description=(
            "Every recommendation is tied to a specific risk of THIS change. "
            "Boilerplate ('write more tests', 'consider edge cases', 'follow "
            "QA best practices') is NOT a recommendation."
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
