# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.ledger_models — the risk-to-test traceability ledger schema.

The ledger is a structured appendix to the markdown-first verdict (issue #144).
These tests pin the schema contract: required fields, the distinct evidence-status
and residual-decision vocabularies, stable-within-document row ids, and the
``extra="forbid"`` strictness that keeps a producer that drifts loud rather than
silent.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sumo_qa.ledger_models import (
    LEDGER_SCHEMA_VERSION,
    EvidenceStatus,
    ResidualDecision,
    RiskLedger,
    RiskLedgerRow,
)


def _row(**overrides) -> RiskLedgerRow:
    base = dict(
        risk_id="R1",
        risk="Refund issued twice for the same charge on retry.",
        source_anchor="services/billing/refund.py:47",
        test="tests/billing/test_refund_idempotency.py::test_key_stable_across_retries",
        evidence_status="planned",
        residual="open",
    )
    base.update(overrides)
    return RiskLedgerRow(**base)


def test_schema_version_constant_is_one_dot_zero():
    assert LEDGER_SCHEMA_VERSION == "1.0"


def test_row_round_trip_preserves_required_fields():
    row = _row()
    rebuilt = RiskLedgerRow.model_validate(row.model_dump(mode="json"))
    assert rebuilt == row
    assert rebuilt.risk_id == "R1"
    assert rebuilt.source_anchor == "services/billing/refund.py:47"


def test_ledger_round_trip_preserves_rows():
    original = RiskLedger(
        schema_version=LEDGER_SCHEMA_VERSION,
        rows=[_row(), _row(risk_id="R2", risk="Float rounding rejects valid amount.")],
    )
    rebuilt = RiskLedger.model_validate(original.model_dump(mode="json"))
    assert rebuilt == original
    assert [r.risk_id for r in rebuilt.rows] == ["R1", "R2"]


def test_ledger_defaults_rows_to_empty():
    led = RiskLedger(schema_version=LEDGER_SCHEMA_VERSION)
    assert led.rows == []


def test_ledger_requires_explicit_schema_version():
    # A versioned artifact must carry its version stamp explicitly so a producer
    # that forgot to stamp the field can't sneak past validation.
    with pytest.raises(ValidationError):
        RiskLedger.model_validate({"rows": []})


def test_ledger_rejects_drifted_schema_version():
    with pytest.raises(ValidationError):
        RiskLedger.model_validate({"schema_version": "2.0", "rows": []})


def test_ledger_rejects_unknown_top_level_field():
    with pytest.raises(ValidationError):
        RiskLedger.model_validate({"schema_version": "1.0", "rows": [], "rogue_top_level": True})


def test_row_rejects_unknown_field():
    with pytest.raises(ValidationError):
        _row(rogue=True)


@pytest.mark.parametrize(
    "field",
    ["risk_id", "risk", "source_anchor", "test", "evidence_status", "residual"],
)
def test_row_requires_each_core_field(field: str):
    base = dict(
        risk_id="R1",
        risk="r",
        source_anchor="a:1",
        test="t",
        evidence_status="planned",
        residual="open",
    )
    del base[field]
    with pytest.raises(ValidationError) as excinfo:
        RiskLedgerRow(**base)  # type: ignore[arg-type]
    assert field in str(excinfo.value)


# The five distinct evidence states the issue's acceptance criteria require.
@pytest.mark.parametrize(
    "status",
    ["planned", "passing", "failing", "stale", "accepted_residual"],
)
def test_row_accepts_each_evidence_status(status: str):
    row = _row(evidence_status=status)
    assert row.evidence_status == status


def test_row_rejects_out_of_vocab_evidence_status():
    with pytest.raises(ValidationError):
        _row(evidence_status="probably_fine")


@pytest.mark.parametrize("decision", ["open", "accepted", "mitigated", "blocker"])
def test_row_accepts_each_residual_decision(decision: str):
    row = _row(residual=decision)
    assert row.residual == decision


def test_row_rejects_out_of_vocab_residual_decision():
    with pytest.raises(ValidationError):
        _row(residual="whenever")


def test_row_test_field_accepts_planned_check_phrase():
    # AC: a row must represent a *planned* check, not only an existing test id.
    row = _row(test="planned: boundary-value test on Decimal('10.10') vs float")
    assert row.test.startswith("planned:")


def test_row_optional_repo_map_node_id_defaults_none():
    # Per #154 scope update: optional repo-map node-id link; absence must not
    # block ledger creation.
    row = _row()
    assert row.repo_map_node_id is None


def test_row_optional_repo_map_node_id_round_trips():
    row = _row(repo_map_node_id="file:services/billing/refund.py")
    rebuilt = RiskLedgerRow.model_validate(row.model_dump(mode="json"))
    assert rebuilt.repo_map_node_id == "file:services/billing/refund.py"


def test_ledger_rejects_duplicate_risk_ids():
    # Row ids are the lookup key within a single document; duplicates would
    # silently collapse two risks into one when projected to markdown.
    with pytest.raises(ValidationError) as excinfo:
        RiskLedger(
            schema_version=LEDGER_SCHEMA_VERSION,
            rows=[_row(risk_id="R1"), _row(risk_id="R1")],
        )
    assert "duplicate risk id" in str(excinfo.value)


def test_ledger_rejects_blank_risk_id():
    # A blank id can't anchor a stable row reference.
    with pytest.raises(ValidationError) as excinfo:
        _row(risk_id="   ")
    assert "risk_id" in str(excinfo.value)


def test_high_risk_uncovered_helper_flags_planned_blocker():
    # A high-risk row whose evidence is not yet passing is "uncovered" — the
    # signal the review skill uses to refuse safe-to-merge.
    row = _row(evidence_status="planned", residual="blocker")
    assert row.is_uncovered_blocker() is True


def test_passing_row_is_not_uncovered_blocker():
    row = _row(evidence_status="passing", residual="accepted")
    assert row.is_uncovered_blocker() is False


def test_failing_blocker_row_is_uncovered_blocker():
    row = _row(evidence_status="failing", residual="blocker")
    assert row.is_uncovered_blocker() is True


def test_accepted_residual_status_is_not_blocker_even_if_unexecuted():
    # An explicitly accepted residual risk is a deliberate decision, not a gap.
    row = _row(evidence_status="accepted_residual", residual="accepted")
    assert row.is_uncovered_blocker() is False


def test_evidence_status_literal_exposes_full_vocabulary():
    import typing

    assert set(typing.get_args(EvidenceStatus)) == {
        "planned",
        "passing",
        "failing",
        "stale",
        "accepted_residual",
    }


def test_residual_decision_literal_exposes_full_vocabulary():
    import typing

    assert set(typing.get_args(ResidualDecision)) == {
        "open",
        "accepted",
        "mitigated",
        "blocker",
    }
