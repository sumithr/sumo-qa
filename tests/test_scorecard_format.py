# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Snapshot-style tests for the scorecard projections (issue #151).

Pins the three load-bearing states the acceptance criteria name — ready,
blocked, insufficient-evidence — plus the "not measured" rendering for absent
optional signals, the no-fake-numeric-score guard, the one-line compact summary,
and the JSON-able serialized snapshot #157 consumes.
"""

from __future__ import annotations

import json

from sumo_qa.context_bundle_models import ContextBundle, EvidenceFact
from sumo_qa.ledger_models import RiskLedger, RiskLedgerRow
from sumo_qa.scorecard_format import (
    compact_summary,
    format_scorecard_markdown,
    serialize_scorecard,
)
from sumo_qa.scorecard_models import CoverageSignal, MutationSignal, QaScorecard


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


# --- markdown snapshots -------------------------------------------------------


def test_blocked_scorecard_markdown():
    card = QaScorecard(
        scope="PR 42",
        ledger=_ledger(_row(risk_id="R3", evidence_status="failing", residual="blocker")),
        context_bundle=ContextBundle(test_evidence=_fact()),
    )
    md = format_scorecard_markdown(card)
    assert "**QA readiness scorecard — PR 42**" in md
    assert "**BLOCKED**" in md
    assert "Blockers (resolve before ready):" in md
    assert "R3" in md
    assert "not a predictive quality score" in md


def test_ready_scorecard_markdown_has_no_blocker_block():
    card = QaScorecard(
        ledger=_ledger(_row(evidence_status="passing", residual="open")),
        context_bundle=ContextBundle(test_evidence=_fact()),
    )
    md = format_scorecard_markdown(card)
    assert "**READY**" in md
    assert "Blockers (resolve before ready):" not in md
    assert "Insufficient evidence" not in md


def test_insufficient_scorecard_markdown():
    card = QaScorecard(
        context_bundle=ContextBundle(test_evidence=_fact(result="passing", freshness="stale")),
    )
    md = format_scorecard_markdown(card)
    assert "**INSUFFICIENT EVIDENCE**" in md
    assert "Insufficient evidence" in md


def test_ready_with_accepted_residuals_markdown():
    card = QaScorecard(
        ledger=_ledger(
            _row(risk_id="R1", evidence_status="passing", residual="open"),
            _row(risk_id="R2", evidence_status="accepted_residual", residual="accepted"),
        ),
        context_bundle=ContextBundle(test_evidence=_fact()),
    )
    md = format_scorecard_markdown(card)
    assert "**READY (with accepted residuals)**" in md


def test_absent_signals_render_not_measured():
    card = QaScorecard(context_bundle=ContextBundle(test_evidence=_fact()))
    md = format_scorecard_markdown(card)
    assert "| Coverage | not measured |" in md
    assert "| Mutation | not measured |" in md


def test_no_invented_percentage_when_coverage_absent():
    # AC#2: avoid unsupported numeric scores. With no coverage signal supplied,
    # the markdown must not contain a percentage — nothing is invented.
    card = QaScorecard(context_bundle=ContextBundle(test_evidence=_fact()))
    md = format_scorecard_markdown(card)
    assert "%" not in md
    assert "not a predictive quality score" in md


def test_supplied_coverage_percentage_is_rendered():
    card = QaScorecard(
        context_bundle=ContextBundle(test_evidence=_fact()),
        coverage=CoverageSignal(line_percent=82.5, freshness="fresh"),
        mutation=MutationSignal(survivors=3, killed=97, freshness="fresh"),
    )
    md = format_scorecard_markdown(card)
    assert "82.5% lines" in md
    assert "3 survivor(s)" in md


def test_scope_with_pipe_is_escaped():
    card = QaScorecard(scope="a | b", context_bundle=ContextBundle(test_evidence=_fact()))
    md = format_scorecard_markdown(card)
    assert "a \\| b" in md


def test_reason_list_truncates_past_cap():
    rows = [
        _row(risk_id=f"R{i}", evidence_status="failing", residual="blocker") for i in range(1, 6)
    ]
    md = format_scorecard_markdown(QaScorecard(ledger=_ledger(*rows)), max_reasons=2)
    assert "more." in md


# --- compact summary ----------------------------------------------------------


def test_compact_summary_is_one_line():
    card = QaScorecard(
        ledger=_ledger(_row(evidence_status="failing", residual="blocker")),
        context_bundle=ContextBundle(test_evidence=_fact()),
    )
    summary = compact_summary(card)
    assert "\n" not in summary
    assert summary.startswith("QA readiness: BLOCKED")
    assert "uncovered blocker(s)" in summary


def test_compact_summary_single_not_measured_signal():
    # Coverage supplied, mutation absent → exactly one not-measured dimension.
    card = QaScorecard(
        context_bundle=ContextBundle(test_evidence=_fact()),
        coverage=CoverageSignal(line_percent=70.0, freshness="fresh"),
    )
    summary = compact_summary(card)
    assert "mutation not measured" in summary
    assert "coverage+mutation" not in summary


# --- serialization (the #157 contract) ----------------------------------------


def test_serialize_snapshot_is_json_able_and_complete():
    card = QaScorecard(
        scope="release 1.2",
        ledger=_ledger(_row(risk_id="R3", evidence_status="failing", residual="blocker")),
        context_bundle=ContextBundle(ci_status=_fact(result="passing", freshness="stale")),
    )
    snap = serialize_scorecard(card)
    # round-trips through JSON unchanged (the report renderer reads JSON).
    assert json.loads(json.dumps(snap)) == snap
    assert snap["recommendation"] == "blocked"
    assert snap["is_ready"] is False
    assert snap["uncovered_blocker_count"] == 1
    assert {d["name"] for d in snap["dimensions"]} == {
        "Risk coverage",
        "Test evidence",
        "CI status",
        "Coverage",
        "Mutation",
        "Residual risks",
    }
    assert "Coverage" in snap["not_measured"]
    assert snap["blocking_reasons"]


def test_serialized_ready_state_is_ready_true():
    card = QaScorecard(
        ledger=_ledger(_row(evidence_status="passing", residual="open")),
        context_bundle=ContextBundle(test_evidence=_fact()),
    )
    snap = serialize_scorecard(card)
    assert snap["recommendation"] == "ready"
    assert snap["is_ready"] is True


def test_stale_optional_coverage_is_not_gating_stale_evidence():
    # A stale coverage signal does NOT gate readiness, so the scorecard can be
    # ready and `stale_evidence` (the gating list) must not contain Coverage —
    # otherwise the "non-empty stale_evidence implies non-ready" contract breaks.
    # The dimension table still shows Coverage as stale.
    card = QaScorecard(
        ledger=_ledger(_row(evidence_status="passing", residual="accepted")),
        context_bundle=ContextBundle(test_evidence=_fact()),
        coverage=CoverageSignal(line_percent=70.0, freshness="stale"),
    )
    snap = serialize_scorecard(card)
    assert snap["recommendation"] == "ready"
    assert "Coverage" not in snap["stale_evidence"]
    assert any(d["name"] == "Coverage" and d["status"] == "stale" for d in snap["dimensions"])


def test_stale_mutation_signal_is_not_gating_stale_evidence():
    card = QaScorecard(
        ledger=_ledger(_row(evidence_status="passing", residual="accepted")),
        context_bundle=ContextBundle(test_evidence=_fact()),
        mutation=MutationSignal(survivors=2, freshness="stale"),
    )
    snap = serialize_scorecard(card)
    assert snap["recommendation"] == "ready"
    assert "Mutation" not in snap["stale_evidence"]


def test_gating_stale_risk_coverage_is_listed_in_stale_evidence():
    # The converse of the exclusion: a stale GATING dimension IS surfaced.
    card = QaScorecard(ledger=_ledger(_row(evidence_status="stale", residual="open")))
    snap = serialize_scorecard(card)
    assert snap["recommendation"] == "insufficient_evidence"
    assert "Risk coverage" in snap["stale_evidence"]


def test_is_ready_implies_no_gating_stale_evidence():
    # The output contract: a ready verdict never carries gating stale_evidence,
    # even with a stale optional signal present.
    card = QaScorecard(
        ledger=_ledger(_row(evidence_status="passing", residual="accepted")),
        context_bundle=ContextBundle(test_evidence=_fact()),
        coverage=CoverageSignal(line_percent=88.0, freshness="stale"),
    )
    snap = serialize_scorecard(card)
    assert snap["is_ready"] is True
    assert snap["stale_evidence"] == []


def test_serialized_unverified_status_ships_under_schema_1_1():
    # #401 widened the dimension-status enum with `unverified`. A consumer
    # validating the documented 1.0 enum (ok/gap/blocker/stale/not_measured)
    # must be able to tell from the stamp alone that the wider enum applies,
    # so the snapshot that can carry the new value advertises schema 1.1.
    card = QaScorecard(context_bundle=ContextBundle(head_sha="1111111aaaa", test_evidence=_fact()))
    snap = serialize_scorecard(card, local_head_sha=None)
    statuses = {d["name"]: d["status"] for d in snap["dimensions"]}
    assert statuses["Test evidence"] == "unverified"
    assert snap["schema_version"] == "1.1"
