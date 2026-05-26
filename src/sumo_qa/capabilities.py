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
        "Diff-grounded review with named risks and a verdict backed by fresh tests.",
    ),
    (
        "Fix a bug regression-first",
        "fix this bug with a failing test first",
        "sumo-qa-implementing-with-tdd",
        "The bug reproduced as a red test, then driven green under TDD.",
    ),
    (
        "Prep QA for a change",
        "what should I test for this change?",
        "sumo-qa-preparing-for-work",
        "Named risks anchored in the change plus the smallest useful test set.",
    ),
    (
        "Write a formal test plan",
        "create a test plan with entry and exit criteria",
        "sumo-qa-creating-test-plan",
        "A phased plan with explicit entry/exit criteria and residual risks.",
    ),
    (
        "Strengthen tests / kill mutants",
        "kill these surviving mutants / strengthen these tests",
        "sumo-qa-strengthening-tests",
        "Stronger assertions that kill real survivors; production code untouched.",
    ),
    (
        "Find test data",
        "find a known-good record for X / what data do I need?",
        "sumo-qa-finding-test-data",
        "Catalogue test data, freshness-validated against the source this turn.",
    ),
    (
        "Audit coverage / set QA strategy",
        "audit our test coverage / design our QA strategy",
        "sumo-qa-strategising",
        "A risk-prioritised, repo-anchored QA strategy and phased rollout.",
    ),
    (
        "Discover an external skill or tool",
        "is there a tool or skill for X?",
        "sumo-qa-suggesting-external-skill",
        "A fitting external skill found, installed, and run via the MCP, behind a gate.",
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
