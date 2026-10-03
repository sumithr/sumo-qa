# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Static data + builder for the ``sumo_qa_capabilities`` discovery tool (issue #87).

A compact, read-only "what can sumo-qa do?" map. Each entry names a core QA
workflow, a sample prompt that triggers it, the existing skill it routes to, and
a one-line outcome. Discovery only — this is not a replacement for the
``using-sumo-qa`` entry router or ``sumo_qa_deciding_approach``, and it carries
no internal classification labels.
"""

from __future__ import annotations

from sumo_qa.server_schemas import CapabilitiesOutput, CapabilityWorkflow, UnavailableGroup
from sumo_qa.tool_registry import ACTIVATION, DEFAULT_PROFILE, TOOLS, group_availability

# (workflow, sample_prompt, target_skill, outcome). Every target_skill MUST be an
# existing skills/<name>/ — enforced by tests/test_capabilities.py. Keep the prose
# tight: the whole serialised output must stay under 500 approx tokens.
_CORE_WORKFLOWS: tuple[tuple[str, str, str, str], ...] = (
    (
        "Review before merge",
        "review my changes",
        "sumo-qa-reviewing-before-merge",
        "Diff-grounded risks and verdict.",
    ),
    (
        "Fix regression-first",
        "fix this bug with a failing test",
        "sumo-qa-implementing-with-tdd",
        "Red regression, then green fix.",
    ),
    (
        "Prep QA",
        "what should I test?",
        "sumo-qa-preparing-for-work",
        "Named risks plus minimal tests.",
    ),
    (
        "Formal test plan",
        "create a test plan",
        "sumo-qa-creating-test-plan",
        "Phases, gates, residuals.",
    ),
    (
        "Strengthen tests",
        "kill surviving mutants",
        "sumo-qa-strengthening-tests",
        "Kill real survivors; prod stays.",
    ),
    (
        "Find test data",
        "what data do I need?",
        "sumo-qa-finding-test-data",
        "Freshness-validated records.",
    ),
    (
        "Triage failing test",
        "red in CI, green locally",
        "sumo-qa-triaging-test-failures",
        "Cause and smallest isolation step.",
    ),
    (
        "Security evidence",
        "security-test this flow",
        "sumo-qa-security-testing",
        "Grounded risk to right evidence.",
    ),
    (
        "QA strategy",
        "audit coverage",
        "sumo-qa-strategising",
        "Repo-anchored strategy.",
    ),
    (
        "External skill/tool",
        "tool or skill for X?",
        "sumo-qa-suggesting-external-skill",
        "Gated discovery/setup.",
    ),
)


def build_capabilities(profile: str = DEFAULT_PROFILE) -> CapabilitiesOutput:
    """Return the compact, typed map of core QA workflows, plus which
    capability groups ``profile`` serves and how to enable the rest.

    Read-only. Discovery only — the entry router remains ``using-sumo-qa`` /
    ``sumo_qa_deciding_approach``.
    """
    enabled, unavailable = group_availability(profile)
    return CapabilitiesOutput(
        active_profile=profile,
        enabled_groups=enabled,
        unavailable_groups=[
            UnavailableGroup(
                group=group,
                open_world=any(t.open_world for t in TOOLS if t.group == group),
                activate=ACTIVATION,
            )
            for group in unavailable
        ],
        workflows=[
            CapabilityWorkflow(
                workflow=workflow,
                sample_prompt=sample_prompt,
                target_skill=target_skill,
                outcome=outcome,
            )
            for workflow, sample_prompt, target_skill, outcome in _CORE_WORKFLOWS
        ],
    )
