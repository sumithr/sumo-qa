# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.gate_evidence_models — the gate-evidence schema (issue #213).

These tests pin the schema contract: the five gate statuses, the six evidence
source types, the "an execution-outcome claim must cite evidence or mark itself
unverified" rule, the ``unverified``-must-cite-nothing rule, and the
``extra="forbid"`` strictness that keeps a drifting producer loud rather than
silent.
"""

from __future__ import annotations

import typing

import pytest
from pydantic import ValidationError

from sumo_qa.gate_evidence_models import (
    EVIDENCE_REQUIRED_STATUSES,
    GATE_EVIDENCE_SCHEMA_VERSION,
    EvidenceItem,
    EvidenceSource,
    GateClaim,
    GateReport,
    GateStatus,
    status_requires_evidence,
)


def _evidence(**overrides) -> EvidenceItem:
    base = dict(source="command", detail="$ uv run pytest -q -> 512 passed, 0 failed")
    base.update(overrides)
    return EvidenceItem(**base)


def _claim(**overrides) -> GateClaim:
    base = dict(
        gate="tests",
        status="passed",
        statement="The full suite passed this turn.",
        evidence=[_evidence()],
    )
    base.update(overrides)
    return GateClaim(**base)


# --- constants / vocabulary ------------------------------------------------


def test_schema_version_constant_is_one_dot_zero():
    assert GATE_EVIDENCE_SCHEMA_VERSION == "1.0"


def test_gate_status_literal_exposes_the_five_documented_statuses():
    assert set(typing.get_args(GateStatus)) == {
        "passed",
        "failed",
        "skipped",
        "blocked",
        "unverified",
    }


def test_evidence_source_literal_exposes_the_six_documented_sources():
    assert set(typing.get_args(EvidenceSource)) == {
        "command",
        "tool_call",
        "file_read",
        "user_fact",
        "external_ci",
        "manual_observation",
    }


def test_evidence_required_statuses_are_the_execution_outcome_ones():
    assert EVIDENCE_REQUIRED_STATUSES == frozenset({"passed", "failed", "blocked"})


@pytest.mark.parametrize("status", ["passed", "failed", "blocked"])
def test_status_requires_evidence_true_for_outcome_statuses(status: str):
    assert status_requires_evidence(status) is True


@pytest.mark.parametrize("status", ["skipped", "unverified"])
def test_status_requires_evidence_false_for_non_outcome_statuses(status: str):
    assert status_requires_evidence(status) is False


# --- EvidenceItem ----------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    ["command", "tool_call", "file_read", "user_fact", "external_ci", "manual_observation"],
)
def test_evidence_item_accepts_each_source(source: str):
    item = _evidence(source=source)
    assert item.source == source


def test_evidence_item_rejects_out_of_vocab_source():
    with pytest.raises(ValidationError):
        _evidence(source="vibes")


def test_evidence_item_rejects_blank_detail():
    with pytest.raises(ValidationError) as excinfo:
        _evidence(detail="   ")
    assert "detail" in str(excinfo.value)


def test_evidence_item_rejects_unknown_field():
    with pytest.raises(ValidationError):
        _evidence(rogue=True)


def test_evidence_item_round_trips():
    item = _evidence(
        source="file_read", detail="read coverage.xml -> refund.py 0% on the new branch"
    )
    rebuilt = EvidenceItem.model_validate(item.model_dump(mode="json"))
    assert rebuilt == item


# --- GateClaim: the evidence-requirement rule ------------------------------


@pytest.mark.parametrize("status", ["passed", "failed", "blocked"])
def test_outcome_claim_requires_evidence(status: str):
    # The heart of the schema: an execution-outcome claim with no cited
    # evidence is the unsupported "tests passed" the issue exists to reject.
    with pytest.raises(ValidationError) as excinfo:
        _claim(status=status, evidence=[])
    assert "must cite at least one evidence item" in str(excinfo.value)


@pytest.mark.parametrize("status", ["passed", "failed", "blocked"])
def test_outcome_claim_with_evidence_is_accepted(status: str):
    claim = _claim(status=status, evidence=[_evidence()])
    assert claim.status == status
    assert claim.evidence


def test_skipped_claim_may_have_no_evidence():
    claim = _claim(status="skipped", evidence=[])
    assert claim.status == "skipped"
    assert claim.evidence == []


def test_skipped_claim_may_still_carry_evidence():
    claim = _claim(
        status="skipped",
        evidence=[_evidence(source="user_fact", detail="feature flag off in prod")],
    )
    assert claim.status == "skipped"


def test_unverified_claim_with_no_evidence_is_the_honest_state():
    claim = _claim(status="unverified", statement="Tests not run this turn.", evidence=[])
    assert claim.status == "unverified"
    assert claim.evidence == []


def test_unverified_claim_with_evidence_is_rejected():
    # Citing evidence contradicts "unverified"; the producer should have used a
    # passed/failed/blocked status instead.
    with pytest.raises(ValidationError) as excinfo:
        _claim(status="unverified", evidence=[_evidence()])
    assert "must not cite evidence" in str(excinfo.value)


def test_claim_rejects_out_of_vocab_status():
    with pytest.raises(ValidationError):
        _claim(status="probably_fine")


def test_claim_rejects_blank_gate():
    with pytest.raises(ValidationError) as excinfo:
        _claim(gate="  ")
    assert "non-blank" in str(excinfo.value)


def test_claim_rejects_blank_statement():
    with pytest.raises(ValidationError) as excinfo:
        _claim(statement="")
    assert "non-blank" in str(excinfo.value)


def test_claim_rejects_unknown_field():
    with pytest.raises(ValidationError):
        _claim(rogue=True)


def test_claim_defaults_evidence_to_empty_list():
    claim = GateClaim(gate="lint", status="skipped", statement="No linter configured.")
    assert claim.evidence == []


def test_claim_round_trips():
    claim = _claim()
    rebuilt = GateClaim.model_validate(claim.model_dump(mode="json"))
    assert rebuilt == claim


# --- GateReport ------------------------------------------------------------


def test_report_requires_explicit_schema_version():
    with pytest.raises(ValidationError):
        GateReport.model_validate({"claims": []})


def test_report_rejects_drifted_schema_version():
    with pytest.raises(ValidationError):
        GateReport.model_validate({"schema_version": "2.0", "claims": []})


def test_report_rejects_unknown_top_level_field():
    with pytest.raises(ValidationError):
        GateReport.model_validate({"schema_version": "1.0", "claims": [], "rogue": True})


def test_report_defaults_claims_to_empty():
    report = GateReport(schema_version=GATE_EVIDENCE_SCHEMA_VERSION)
    assert report.claims == []


def test_report_round_trips():
    report = GateReport(
        schema_version=GATE_EVIDENCE_SCHEMA_VERSION,
        claims=[
            _claim(),
            _claim(
                gate="safe_to_merge",
                status="unverified",
                statement="Not yet verified.",
                evidence=[],
            ),
        ],
    )
    rebuilt = GateReport.model_validate(report.model_dump(mode="json"))
    assert rebuilt == report


def test_unresolved_gates_lists_failed_blocked_and_unverified():
    report = GateReport(
        schema_version=GATE_EVIDENCE_SCHEMA_VERSION,
        claims=[
            _claim(gate="tests", status="passed"),
            _claim(gate="lint", status="skipped", evidence=[]),
            _claim(gate="mutation", status="failed", statement="2 survivors."),
            _claim(
                gate="ci",
                status="blocked",
                statement="Upstream job errored.",
                evidence=[_evidence(source="external_ci", detail="deploy-gate: infra failure")],
            ),
            _claim(
                gate="safe_to_merge", status="unverified", statement="No verdict yet.", evidence=[]
            ),
        ],
    )
    unresolved = {c.gate for c in report.unresolved_gates()}
    assert unresolved == {"mutation", "ci", "safe_to_merge"}


def test_is_clean_true_when_all_passed_or_skipped():
    report = GateReport(
        schema_version=GATE_EVIDENCE_SCHEMA_VERSION,
        claims=[
            _claim(gate="tests", status="passed"),
            _claim(gate="lint", status="skipped", evidence=[]),
        ],
    )
    assert report.is_clean() is True


def test_is_clean_false_when_a_gate_is_unverified():
    report = GateReport(
        schema_version=GATE_EVIDENCE_SCHEMA_VERSION,
        claims=[_claim(gate="safe_to_merge", status="unverified", statement="n/a", evidence=[])],
    )
    assert report.is_clean() is False
