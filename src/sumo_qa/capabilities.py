# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Static data + builder for the ``sumo_qa_capabilities`` discovery tool (issue #87).

A compact, read-only "what can sumo-qa do?" map. Each entry names a core QA
workflow, a sample prompt that triggers it, the existing skill it routes to, and
a one-line outcome. Discovery only — this is not a replacement for the
``using-sumo-qa`` entry router or ``sumo_qa_deciding_approach``, and it carries
no internal classification labels.
"""

from __future__ import annotations

from sumo_qa.server_schemas import CapabilitiesOutput, CapabilityWorkflow

# (workflow, sample_prompt, target_skill, outcome). Every target_skill MUST be an
# existing skills/<name>/ — enforced by tests/test_capabilities.py. Keep the prose
# tight: the whole serialised output must stay under 500 approx tokens.
_CORE_WORKFLOWS: tuple[tuple[str, str, str, str], ...] = (
    (
        "Review before merge",
        "review my changes",
        "sumo-qa-reviewing-before-merge",
        "Diff risks and test-backed verdict.",
    ),
    (
        "Fix a bug",
        "fix this bug regression-first",
        "sumo-qa-implementing-with-tdd",
        "Red regression, fix, green.",
    ),
    (
        "Prep QA for a change",
        "what should I test for this change?",
        "sumo-qa-preparing-for-work",
        "Named risks plus minimal tests.",
    ),
    (
        "Write a test plan",
        "create a formal test plan",
        "sumo-qa-creating-test-plan",
        "Phases, entry/exit, residuals.",
    ),
    (
        "Strengthen tests",
        "kill surviving mutants",
        "sumo-qa-strengthening-tests",
        "Kill real survivors; prod stays.",
    ),
    (
        "Find test data",
        "what test data do I need?",
        "sumo-qa-finding-test-data",
        "Find and freshness-check data.",
    ),
    (
        "Triage failing tests",
        "red in CI, green locally",
        "sumo-qa-triaging-test-failures",
        "Classify cause before fixing.",
    ),
    (
        "Focus security testing",
        "security test this change",
        "sumo-qa-security-testing",
        "Grounded risk and evidence.",
    ),
    (
        "Set QA strategy",
        "audit our coverage",
        "sumo-qa-strategising",
        "Repo-anchored strategy.",
    ),
    (
        "Discover external fit",
        "is there a tool or skill for X?",
        "sumo-qa-suggesting-external-skill",
        "Find gated external skill/tool.",
    ),
)


def build_capabilities() -> CapabilitiesOutput:
    """Return the compact, typed map of core QA workflows.

    Static and read-only; never raises. Discovery only — the entry router
    remains ``using-sumo-qa`` / ``sumo_qa_deciding_approach``.
    """
    return CapabilitiesOutput(
        workflows=[
            CapabilityWorkflow(
                workflow=workflow,
                sample_prompt=sample_prompt,
                target_skill=target_skill,
                outcome=outcome,
            )
            for workflow, sample_prompt, target_skill, outcome in _CORE_WORKFLOWS
        ]
    )
