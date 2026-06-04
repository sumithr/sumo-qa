# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Token-weight regression — the new architecture's per-flow MCP-call total
must stay under the budget that broke IntelliJ AI Assistant.

Three assertions:

1. The 4 always-thin knowledge catalogues (classifications, approaches,
   principles, techniques) must each stay under PER_CALL_BUDGET. They
   are loaded unfiltered in flows, so they have to be small.

2. Filtered standards / rules calls (the path skills actually use in
   flows) must stay under PER_CALL_BUDGET. Unfiltered standards/rules
   calls today exceed budget — that's flagged xfail until catalogues
   are split or carry per-classification metadata (Phase 2 concern).

3. A full create-test-plan flow stays under PER_FLOW_BUDGET tokens
   total. Phase 1: heavy tools still in place dominate the budget,
   so this is xfail. Phase 4: deletes the heavy path; un-xfail then.

Token estimation here is approximate (length / 4 chars-per-token). For
exact counts, hosts use their own tokenizers. The budget targets are
conservative.
"""

import json

import pytest

from sumo_qa.knowledge_loaders import (
    sumo_qa_load_approaches,
    sumo_qa_load_classifications,
    sumo_qa_load_principles,
    sumo_qa_load_rules,
    sumo_qa_load_standards,
    sumo_qa_load_techniques,
)
from sumo_qa.skill_manifest import list_skill_manifests, load_skill_context


def _approx_tokens(text: str) -> int:
    """Approximate token count: length / 4, rounded up."""
    return (len(text) + 3) // 4


PER_CALL_BUDGET = 1500
# Phase 4: with the 6 heavy tools deleted, the create-test-plan flow now
# uses only the knowledge_loader catalogues. Measured baseline was ~2432
# tokens with 8 canonical approaches; adding the 9th canonical approach
# (`recommend-removal`, established by the removability gate in
# sumo-qa-deciding-approach) raised the baseline to ~2610. #187 then added
# technique-keyed failure-mode hints to techniques.md (an optional
# `failure_modes` note per black-box technique — substring/token confusion,
# both-sides boundary, missing rule row — that the review skill surfaces when
# escalating an UNPROVEN risk into a discriminating-input test). The catalogue
# is still ~1014 approx-tokens, well under PER_CALL_BUDGET (1500); the flow
# baseline rose to ~2883. #299 then added the `real-capture fixtures for
# external-output matchers` experience-based technique (capture an external
# CLI/API's real output as the fixture before writing the matcher — an invented
# fixture is green-but-meaningless), raising techniques to ~1196 approx-tokens
# (still well under PER_CALL_BUDGET) and the flow baseline to ~3113. #184 then
# added the `build artifact contents verification` technique (a packaging-contract
# check on a wheel/sdist/package, container image, or bundle — assert the BUILT
# artifact's required/forbidden members, not the source tree), raising techniques
# to ~1301 approx-tokens (still well under PER_CALL_BUDGET) and the flow baseline
# to ~3218. Budget gives a small regression cushion above the current catalogue.
# For comparison the old heavy single-shot path emitted >10k tokens for one call,
# which is what broke IntelliJ AI Assistant in the first place.
PER_FLOW_BUDGET = 3250


def test_thin_catalogues_stay_under_per_call_budget():
    """The 4 always-thin catalogues must each stay under PER_CALL_BUDGET
    so they cannot break IntelliJ's SSE the way the old heavy tools did."""
    for name, fn in [
        ("classifications", sumo_qa_load_classifications),
        ("approaches", sumo_qa_load_approaches),
        ("principles", sumo_qa_load_principles),
        ("techniques", sumo_qa_load_techniques),
    ]:
        text = fn()
        tokens = _approx_tokens(text)
        assert tokens <= PER_CALL_BUDGET, (
            f"{name} returned ~{tokens} tokens (>{PER_CALL_BUDGET}); "
            f"split the catalogue or lighten content"
        )


def test_filtered_standards_and_rules_stay_under_per_call_budget():
    """In real flows, skills call standards/rules WITH a classification
    filter. The filtered output must stay under PER_CALL_BUDGET. The
    classification used here matches what the sumo-qa-creating-test-plan
    skill would use for a typical business-logic change."""
    classification = "business_logic_change"
    for name, fn in [
        ("standards", lambda: sumo_qa_load_standards(classification=classification)),
        ("rules", lambda: sumo_qa_load_rules(classification=classification)),
    ]:
        text = fn()
        tokens = _approx_tokens(text)
        assert tokens <= PER_CALL_BUDGET, (
            f"{name} (filtered by {classification}) returned ~{tokens} tokens "
            f"(>{PER_CALL_BUDGET}); the classification-filter path is too heavy"
        )


@pytest.mark.xfail(
    reason="Unfiltered standards/rules calls exceed per-call budget. "
    "Phase 2: standards packs gain classification metadata so unfiltered "
    "calls are deprecated in favour of filtered ones; un-xfail then."
)
def test_unfiltered_standards_and_rules_are_acknowledged_heavy():
    """Unfiltered standards / rules calls today exceed PER_CALL_BUDGET.
    They are explanatory/debug paths, not flow paths. Skills should call
    them with a classification filter."""
    for name, fn in [
        ("standards (unfiltered)", lambda: sumo_qa_load_standards()),
        ("rules (unfiltered)", lambda: sumo_qa_load_rules()),
    ]:
        text = fn()
        tokens = _approx_tokens(text)
        assert tokens <= PER_CALL_BUDGET, (
            f"{name} returned ~{tokens} tokens (>{PER_CALL_BUDGET}); "
            f"split the catalogue or require classification filter"
        )


def test_create_test_plan_flow_stays_under_token_budget():
    """A full create-test-plan flow via the new path uses these calls in
    sequence: classifications, approaches, techniques, standards (filtered),
    rules (filtered).

    Total MCP-returned tokens across the flow must stay under PER_FLOW_BUDGET.
    """
    flow_total = sum(
        _approx_tokens(t)
        for t in [
            sumo_qa_load_classifications(),
            sumo_qa_load_approaches(),
            sumo_qa_load_techniques(),
            sumo_qa_load_standards(classification="business_logic_change"),
            sumo_qa_load_rules(classification="business_logic_change"),
        ]
    )
    assert flow_total <= PER_FLOW_BUDGET, (
        f"create-test-plan flow returned ~{flow_total} tokens "
        f"(>{PER_FLOW_BUDGET}); the new path is too heavy"
    )


# --------------------------------------------------------------------------
# Cumulative session budget — the partial loader's reason to exist (#286).
#
# Per-call budgets above guard one call. They say nothing about the cost that
# broke IntelliJ in practice: a host that revisits the SAME few skills many
# times across one session. The partial loader (mode='manifest'/'section')
# exists so that revisiting a skill costs the routing slice, not the whole
# body each time. These tests lock that cumulative win in.
#
# Technique: boundary value analysis — the partial cumulative total must sit
# below the full-body cumulative total (the boundary a regression crosses).
# --------------------------------------------------------------------------


def _routing_minimal_section_ids(manifest: dict) -> list[str]:
    """The frontmatter + Iron Law + Flow slice a host loads to route/gate a
    skill before executing its body — the same routing-minimal set the
    partial-load saving test in test_skill_modules.py uses."""
    terms = ("frontmatter", "iron law", "flow")
    return [s["id"] for s in manifest["sections"] if any(t in s["heading"].lower() for t in terms)]


# A realistic mixed session: the router + the approach decider get revisited
# every workflow; a heavy executor skill is consulted a few times. Counts are
# deliberately repeated to model real cumulative pressure, not a single pass.
_SIMULATED_SESSION = [
    ("using-sumo-qa", 4),
    ("sumo-qa-deciding-approach", 4),
    ("sumo-qa-reviewing-before-merge", 3),
    ("sumo-qa-implementing-with-tdd", 2),
]


def test_repeated_skill_loads_cost_less_partial_than_full_body():
    """Across a simulated session that revisits a handful of skills several
    times, the cumulative cost of partial loads (manifest once + routing-
    minimal sections) must stay strictly below the cumulative cost of loading
    each skill's full body on every visit. If partial loading ever stops
    saving, this fails."""
    full_cumulative = 0
    partial_cumulative = 0
    for skill_name, visits in _SIMULATED_SESSION:
        full_body = load_skill_context(skill_name, "full")["content"]
        manifest = load_skill_context(skill_name, "manifest")
        section_ids = _routing_minimal_section_ids(manifest)
        assert section_ids, f"{skill_name} has no routing-minimal section to load"

        manifest_tokens = _approx_tokens(json.dumps(manifest))
        section_tokens = sum(
            _approx_tokens(load_skill_context(skill_name, "section", section=sid)["content"])
            for sid in section_ids
        )
        for _ in range(visits):
            full_cumulative += _approx_tokens(full_body)
            # A revisit pays the routing slice again; the manifest is the
            # one-time routing cost, counted once per skill, not per visit.
            partial_cumulative += section_tokens
        partial_cumulative += manifest_tokens

    assert partial_cumulative < full_cumulative, (
        f"cumulative partial-load cost ~{partial_cumulative} tokens is not "
        f"below the full-body cost ~{full_cumulative}; the partial loader is "
        f"not delivering a session-cumulative saving."
    )


def test_session_partial_saving_is_substantial_not_marginal():
    """A win of a few tokens would technically pass the strict-less-than test
    while being meaningless. Pin a floor: across the simulated session the
    partial path must save at least half the full-body cumulative cost."""
    full_cumulative = 0
    partial_cumulative = 0
    for skill_name, visits in _SIMULATED_SESSION:
        full_body = load_skill_context(skill_name, "full")["content"]
        manifest = load_skill_context(skill_name, "manifest")
        section_ids = _routing_minimal_section_ids(manifest)
        manifest_tokens = _approx_tokens(json.dumps(manifest))
        section_tokens = sum(
            _approx_tokens(load_skill_context(skill_name, "section", section=sid)["content"])
            for sid in section_ids
        )
        full_cumulative += _approx_tokens(full_body) * visits
        partial_cumulative += manifest_tokens + section_tokens * visits

    saving = (full_cumulative - partial_cumulative) / full_cumulative
    assert saving >= 0.50, (
        f"session partial-load saving is only {saving:.0%} of full-body cost; "
        f"expected >=50% — the cumulative win has eroded."
    )


def test_full_mode_in_session_matches_skill_body_byte_for_byte():
    """The cumulative comparison is only honest if mode='full' returns the
    real body (the thing a non-partial host actually pays for). Spot-check
    every skill in the simulated session against the manifest's full-body
    token estimate."""
    out = {m["skill_name"]: m for m in list_skill_manifests()["skills"]}
    for skill_name, _ in _SIMULATED_SESSION:
        full_body = load_skill_context(skill_name, "full")["content"]
        assert _approx_tokens(full_body) == out[skill_name]["estimated_tokens_full"]
