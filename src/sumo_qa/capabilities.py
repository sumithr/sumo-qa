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
        "Review changes before merge",
        "review my changes / is this safe to merge?",
        "sumo-qa-reviewing-before-merge",
        "Diff-grounded review, named risks, a test-backed verdict.",
    ),
    (
        "Fix a bug regression-first",
        "fix this bug with a failing test first",
        "sumo-qa-implementing-with-tdd",
        "The bug reproduced as a red test, then driven green.",
    ),
    (
        "Prep QA for a change",
        "what should I test for this change?",
        "sumo-qa-preparing-for-work",
        "Named risks anchored in the change plus minimal tests.",
    ),
    (
        "Write a formal test plan",
        "create a test plan with entry/exit criteria",
        "sumo-qa-creating-test-plan",
        "A phased plan with entry/exit criteria and residuals.",
    ),
    (
        "Strengthen tests / kill mutants",
        "kill these surviving mutants / strengthen these tests",
        "sumo-qa-strengthening-tests",
        "Stronger assertions kill real survivors; production stays.",
    ),
    (
        "Find test data",
        "find a known-good record for X / what data do I need?",
        "sumo-qa-finding-test-data",
        "Catalogue test data, freshness-validated.",
    ),
    (
        "Triage a failing or flaky test",
        "this test keeps failing / red in CI, green locally",
        "sumo-qa-triaging-test-failures",
        "Cause classified, smallest isolation step before a fix.",
    ),
    (
        "Audit coverage / set QA strategy",
        "audit our coverage / design our QA strategy",
        "sumo-qa-strategising",
        "A risk-prioritised, repo-anchored strategy and rollout.",
    ),
    (
        "Discover an external skill or tool",
        "is there a tool or skill for X?",
        "sumo-qa-suggesting-external-skill",
        "A fitting external skill found, installed, run via the MCP.",
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
