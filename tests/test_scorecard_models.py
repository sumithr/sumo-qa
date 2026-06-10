# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the QA readiness scorecard evidence semantics (issue #151).

The heart of the scorecard is ``QaScorecard.recommendation`` — a DERIVED verdict,
never a caller-asserted one. These tests pin the derivation as a decision table:
the recommendation is a conjunction of several input conditions (is there an
uncovered blocker? is the test evidence fresh and passing? is any risk only an
accepted residual?), so every combination maps to exactly one of the four states.

The load-bearing rows are the two the acceptance criteria call out explicitly:
an uncovered high-impact risk must yield ``blocked`` (never ``ready``), and stale
test evidence must yield ``insufficient_evidence`` (never ``ready``).
"""

from __future__ import annotations

import pytest

from sumo_qa.context_bundle_models import ContextBundle, EvidenceFact
from sumo_qa.ledger_models import RiskLedger, RiskLedgerRow
from sumo_qa.scorecard_models import (
    CoverageSignal,
    MutationSignal,
    QaScorecard,
)


def _row(**overrides) -> RiskLedgerRow:
    base = {
        "risk_id": "R1",
        "risk": "Refund issued twice on retry.",
        "source_anchor": "refund.py:47",
        "test": "tests/test_refund.py::test_idempotent",
        "evidence_status": "passing",
        "residual": "open",
    }
    base.update(overrides)
    return RiskLedgerRow(**base)


def _ledger(*rows: RiskLedgerRow) -> RiskLedger:
    return RiskLedger(schema_version="1.0", rows=list(rows))


def _fact(result="passing", freshness="fresh", source="local_git") -> EvidenceFact:
    return EvidenceFact(result=result, freshness=freshness, source=source)


def _bundle(**overrides) -> ContextBundle:
    return ContextBundle(**overrides)


# --- the decision table: every input combination → exactly one verdict --------


def test_uncovered_blocker_yields_blocked_not_ready():
    # R1 evidence=failing, residual=blocker → is_uncovered_blocker() is True →
    # a hard stop. Even with otherwise-fine inputs the verdict must be blocked.
    card = QaScorecard(
        ledger=_ledger(_row(evidence_status="failing", residual="blocker")),
        context_bundle=_bundle(test_evidence=_fact()),
    )
    assert card.recommendation() == "blocked"
    assert card.blocking_reasons()  # non-empty


def test_stale_test_evidence_yields_insufficient_not_ready():
    # The only test signal is a PASSING result captured stale → not safety-
    # supporting → readiness cannot be asserted. Stale must not read as ready.
    card = QaScorecard(
        context_bundle=_bundle(test_evidence=_fact(result="passing", freshness="stale")),
    )
    assert card.recommendation() == "insufficient_evidence"
    assert not card.blocking_reasons()
    assert card.insufficiency_reasons()


def test_fresh_passing_no_residuals_yields_ready():
    # R1 passing/open, fresh passing test evidence, no accepted residual,
    # no uncovered blocker → ready.
    card = QaScorecard(
        ledger=_ledger(_row(evidence_status="passing", residual="open")),
        context_bundle=_bundle(test_evidence=_fact()),
    )
    assert card.recommendation() == "ready"


def test_accepted_residual_yields_ready_with_accepted_residuals():
    # Same as the ready case but one extra row is an accepted residual (a
    # deliberate accept, not a passing test). The ONLY difference from the
    # plain-ready case is the accepted residual — so it must flip the verdict.
    card = QaScorecard(
        ledger=_ledger(
            _row(risk_id="R1", evidence_status="passing", residual="open"),
            _row(risk_id="R2", evidence_status="accepted_residual", residual="accepted"),
        ),
        context_bundle=_bundle(test_evidence=_fact()),
    )
    assert card.recommendation() == "ready_with_accepted_residuals"


def test_no_evidence_at_all_yields_insufficient():
    assert QaScorecard().recommendation() == "insufficient_evidence"


def test_planned_only_risk_yields_insufficient_not_ready():
    # A risk whose test is only planned (not executed) with fresh-passing CI
    # is still not ready — the named risk has no executed coverage yet.
    card = QaScorecard(
        ledger=_ledger(_row(evidence_status="planned", residual="open")),
        context_bundle=_bundle(ci_status=_fact()),
    )
    assert card.recommendation() == "insufficient_evidence"


def test_coverage_and_mutation_do_not_outweigh_an_uncovered_blocker():
    # AC: optional coverage/mutation artifacts must NOT outweigh an uncovered
    # high-impact risk. 95% fresh coverage + 0 fresh survivors alongside an
    # uncovered blocker must STILL be blocked, never ready.
    card = QaScorecard(
        ledger=_ledger(_row(evidence_status="failing", residual="blocker")),
        coverage=CoverageSignal(line_percent=95.0, freshness="fresh"),
        mutation=MutationSignal(survivors=0, killed=120, freshness="fresh"),
    )
    assert card.recommendation() == "blocked"


def test_failing_ci_result_blocks_even_without_a_ledger():
    card = QaScorecard(context_bundle=_bundle(ci_status=_fact(result="failing")))
    assert card.recommendation() == "blocked"


def test_failing_non_blocker_row_is_a_blocking_reason():
    # A failing covering test on a non-"blocker" residual still blocks.
    card = QaScorecard(ledger=_ledger(_row(evidence_status="failing", residual="open")))
    reasons = card.blocking_reasons()
    assert any("covering test is failing" in r for r in reasons)
    assert card.recommendation() == "blocked"


def test_stale_ledger_row_is_an_insufficiency():
    card = QaScorecard(ledger=_ledger(_row(evidence_status="stale", residual="open")))
    reasons = card.insufficiency_reasons()
    assert any("covering evidence is stale" in r for r in reasons)
    assert card.recommendation() == "insufficient_evidence"


def test_accepted_residual_row_is_skipped_in_insufficiency():
    # R1 is an accepted residual (skipped); R2 is planned (an insufficiency).
    card = QaScorecard(
        ledger=_ledger(
            _row(risk_id="R1", evidence_status="accepted_residual", residual="accepted"),
            _row(risk_id="R2", evidence_status="planned", residual="open"),
        ),
        context_bundle=_bundle(test_evidence=_fact()),
    )
    reasons = card.insufficiency_reasons()
    assert any("R2" in r for r in reasons)
    assert not any("R1" in r for r in reasons)


def test_insufficiency_does_not_relist_a_failing_bundle_fact():
    # A failing fact is a blocker, surfaced by blocking_reasons. When
    # insufficiency_reasons is computed directly it must SKIP it (not double-list
    # it as an insufficiency).
    card = QaScorecard(context_bundle=_bundle(test_evidence=_fact(result="failing")))
    reasons = card.insufficiency_reasons()
    assert not any("not fresh-passing" in r for r in reasons)
    assert card.blocking_reasons()  # it is a blocker


def test_bundle_local_conflict_is_an_insufficiency():
    # Fresh passing evidence, but the bundle's head differs from the live local
    # head → the bundle is stale relative to the tree → cannot assert ready.
    card = QaScorecard(
        context_bundle=_bundle(head_sha="1111111aaaa", test_evidence=_fact()),
    )
    reasons = card.insufficiency_reasons(local_head_sha="2222222bbbb")
    assert any("stale relative to the local tree" in r for r in reasons)
    assert card.recommendation(local_head_sha="2222222bbbb") == "insufficient_evidence"


# --- helper methods -----------------------------------------------------------


def test_accepted_residual_rows_key_on_evidence_status_only():
    # Only the dedicated accepted_residual evidence state counts. A canonical
    # covered risk (passing/accepted) is NOT a residual, and neither is a
    # planned/accepted row — the residual decision is a separate axis.
    card = QaScorecard(
        ledger=_ledger(
            _row(risk_id="R1", evidence_status="passing", residual="accepted"),
            _row(risk_id="R2", evidence_status="accepted_residual", residual="open"),
            _row(risk_id="R3", evidence_status="planned", residual="accepted"),
        )
    )
    ids = {row.risk_id for row in card.accepted_residual_rows()}
    assert ids == {"R2"}


def test_canonical_passing_accepted_row_is_ready_not_residuals():
    # The canonical ledger form for a fully covered risk is passing/accepted
    # (the residual question is closed). It must derive `ready`, NOT
    # `ready_with_accepted_residuals` — the bug a passing/open fixture masked.
    card = QaScorecard(
        ledger=_ledger(_row(evidence_status="passing", residual="accepted")),
        context_bundle=_bundle(test_evidence=_fact()),
    )
    assert card.accepted_residual_rows() == []
    assert card.recommendation() == "ready"


def test_uncovered_blocker_rows_reuse_ledger_logic():
    card = QaScorecard(
        ledger=_ledger(
            _row(risk_id="R1", evidence_status="failing", residual="blocker"),
            _row(risk_id="R2", evidence_status="passing", residual="open"),
        )
    )
    assert [row.risk_id for row in card.uncovered_blocker_rows()] == ["R1"]


# --- dimensions ---------------------------------------------------------------


def test_absent_coverage_and_mutation_are_not_measured_not_ok():
    card = QaScorecard(context_bundle=_bundle(test_evidence=_fact()))
    by_name = {dim.name: dim.status for dim in card.dimensions()}
    assert by_name["Coverage"] == "not_measured"
    assert by_name["Mutation"] == "not_measured"


def test_uncovered_blocker_dimension_status_is_blocker():
    card = QaScorecard(ledger=_ledger(_row(evidence_status="failing", residual="blocker")))
    by_name = {dim.name: dim.status for dim in card.dimensions()}
    assert by_name["Risk coverage"] == "blocker"


def test_stale_test_evidence_dimension_status_is_stale():
    card = QaScorecard(
        context_bundle=_bundle(test_evidence=_fact(result="passing", freshness="stale"))
    )
    by_name = {dim.name: dim.status for dim in card.dimensions()}
    assert by_name["Test evidence"] == "stale"


def test_risk_coverage_dimension_stale_when_only_stale_rows():
    card = QaScorecard(ledger=_ledger(_row(evidence_status="stale", residual="open")))
    by_name = {dim.name: dim.status for dim in card.dimensions()}
    assert by_name["Risk coverage"] == "stale"


def test_risk_coverage_dimension_gap_when_only_planned_rows():
    card = QaScorecard(ledger=_ledger(_row(evidence_status="planned", residual="open")))
    by_name = {dim.name: dim.status for dim in card.dimensions()}
    assert by_name["Risk coverage"] == "gap"


def test_failing_test_evidence_dimension_status_is_blocker():
    card = QaScorecard(context_bundle=_bundle(test_evidence=_fact(result="failing")))
    by_name = {dim.name: dim.status for dim in card.dimensions()}
    assert by_name["Test evidence"] == "blocker"


def test_sha_mismatched_fresh_pass_dimension_is_stale_not_ok():
    # A fresh-labelled pass captured against a DIFFERENT sha than head is not
    # trustworthy; the dimension must read stale (matching the verdict), not ok.
    fact = EvidenceFact(
        result="passing", freshness="fresh", source="local_git", captured_against_sha="aaaaaaa"
    )
    card = QaScorecard(context_bundle=_bundle(head_sha="bbbbbbb", test_evidence=fact))
    by_name = {dim.name: dim.status for dim in card.dimensions()}
    assert by_name["Test evidence"] == "stale"
    assert card.recommendation() == "insufficient_evidence"


def test_local_head_conflict_marks_evidence_dimension_stale():
    # When the bundle's head differs from the live local head, its facts are
    # stale relative to the tree — the dimension must reflect that, not read ok.
    card = QaScorecard(context_bundle=_bundle(head_sha="1111111", test_evidence=_fact()))
    by_name = {dim.name: dim.status for dim in card.dimensions(local_head_sha="2222222")}
    assert by_name["Test evidence"] == "stale"


def test_clean_fresh_pass_evidence_dimension_is_ok():
    card = QaScorecard(context_bundle=_bundle(test_evidence=_fact()))
    by_name = {dim.name: dim.status for dim in card.dimensions()}
    assert by_name["Test evidence"] == "ok"


def test_unknown_freshness_evidence_dimension_is_stale():
    card = QaScorecard(context_bundle=_bundle(test_evidence=_fact(freshness="unknown")))
    by_name = {dim.name: dim.status for dim in card.dimensions()}
    assert by_name["Test evidence"] == "stale"


def test_failing_fact_under_local_conflict_stays_blocker():
    # Precedence: a failing result is a blocker even when the bundle also
    # conflicts with the local head — the blocker branch is checked before stale.
    card = QaScorecard(
        context_bundle=_bundle(head_sha="1111111", test_evidence=_fact(result="failing"))
    )
    by_name = {dim.name: dim.status for dim in card.dimensions(local_head_sha="2222222")}
    assert by_name["Test evidence"] == "blocker"


def test_coverage_and_mutation_detail_is_rendered_in_dimensions():
    card = QaScorecard(
        coverage=CoverageSignal(line_percent=80.0, freshness="stale", detail="2 files uncovered"),
        mutation=MutationSignal(survivors=4, killed=10, freshness="fresh", detail="run 2026-06"),
    )
    by_name = {dim.name: dim.detail for dim in card.dimensions()}
    assert "2 files uncovered" in by_name["Coverage"]
    assert "run 2026-06" in by_name["Mutation"]


# --- signal validators --------------------------------------------------------


def test_coverage_percent_out_of_range_rejected():
    with pytest.raises(ValueError, match="between 0 and 100"):
        CoverageSignal(line_percent=150.0)


def test_negative_mutant_count_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        MutationSignal(survivors=-1)
