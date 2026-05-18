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

import pytest

from sumo_qa.knowledge_loaders import (
    sumo_qa_load_approaches,
    sumo_qa_load_classifications,
    sumo_qa_load_principles,
    sumo_qa_load_rules,
    sumo_qa_load_standards,
    sumo_qa_load_techniques,
)


def _approx_tokens(text: str) -> int:
    """Approximate token count: length / 4, rounded up."""
    return (len(text) + 3) // 4


PER_CALL_BUDGET = 1500
# Phase 4: with the 6 heavy tools deleted, the create-test-plan flow now
# uses only the knowledge_loader catalogues. Measured baseline was ~2432
# tokens with 8 canonical approaches; adding the 9th canonical approach
# (`recommend-removal`, established by the removability gate in
# sumo-qa-deciding-approach) raised the baseline to ~2610. Budget gives a
# small regression cushion above the current catalogue. For comparison the
# old heavy single-shot path emitted >10k tokens for one call, which is
# what broke IntelliJ AI Assistant in the first place.
PER_FLOW_BUDGET = 2700


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
