# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.report_models — the render-ready QA report model (#157).

The readiness derivation is the highest-risk logic in the report: a wrong
severity ordering would let a blocked repo read as ready, or let missing data
masquerade as passing evidence (the exact distinction the issue's acceptance
criteria require). The derivation is specified here as a decision table —
every rule row plus the default arm — so each condition combination has an
enumerated expected state.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from sumo_qa.report_models import (
    ARTIFACT_KINDS,
    REPORT_SCHEMA_VERSION,
    QAReport,
    ReportArtifact,
    ReportEvidence,
    ReportProject,
    ReportReadiness,
    ReportRisk,
    derive_readiness,
)

_NOW = datetime(2026, 6, 8, 8, 0, 0, tzinfo=timezone.utc)


def _artifact(kind: str, status: str, **overrides) -> ReportArtifact:
    data = {"kind": kind, "status": status, "path": None, "detail": None}
    data.update(overrides)
    return ReportArtifact(**data)


def _baseline_artifacts(**status_overrides) -> list[ReportArtifact]:
    """All-green artifact inventory; coverage/mutation and the scorecard stay
    'missing' because no producer for them exists yet (#147 / #151 open)."""
    statuses = {
        "repo_map": "available",
        "diff_impact": "available",
        "risk_ledger": "available",
        "context_bundle": "available",
        "readiness_scorecard": "missing",
        "coverage_mutation": "missing",
    }
    statuses.update(status_overrides)
    return [_artifact(kind, status) for kind, status in statuses.items()]


def _risk(
    risk_id: str = "R1",
    evidence_status: str = "passing",
    residual: str = "mitigated",
    uncovered_blocker: bool = False,
) -> ReportRisk:
    return ReportRisk(
        risk_id=risk_id,
        risk="demo risk",
        source_anchor="src/demo.py:1",
        test="tests/test_demo.py::test_demo",
        evidence_status=evidence_status,
        residual=residual,
        repo_map_node_id=None,
        uncovered_blocker=uncovered_blocker,
    )


def _evidence(
    name: str = "tests",
    status: str = "passing",
    freshness: str | None = "fresh",
    trustworthy: bool = True,
) -> ReportEvidence:
    return ReportEvidence(
        name=name,
        status=status,
        freshness=freshness,
        trustworthy=trustworthy,
        source="ci_provider",
        captured_at=None,
        detail=None,
    )


def _green_inputs() -> tuple[list[ReportArtifact], list[ReportRisk], list[ReportEvidence]]:
    """The all-green baseline: every rule test perturbs exactly one signal."""
    return (
        _baseline_artifacts(),
        [_risk()],
        [_evidence("tests"), _evidence("ci")],
    )


# ---------------------------------------------------------------------------
# derive_readiness — decision table
# ---------------------------------------------------------------------------


def test_readiness_all_green_is_ready():
    artifacts, risks, evidence = _green_inputs()
    readiness = derive_readiness(artifacts, risks, evidence)
    assert readiness.state == "ready"


def test_readiness_uncovered_blocker_is_blocked():
    artifacts, risks, evidence = _green_inputs()
    risks.append(_risk("R2", evidence_status="planned", residual="blocker", uncovered_blocker=True))
    readiness = derive_readiness(artifacts, risks, evidence)
    assert readiness.state == "blocked"
    assert any("R2" in reason for reason in readiness.reasons)


def test_readiness_failing_risk_row_is_blocked():
    artifacts, risks, evidence = _green_inputs()
    risks.append(_risk("R2", evidence_status="failing", residual="open"))
    assert derive_readiness(artifacts, risks, evidence).state == "blocked"


def test_readiness_failing_evidence_is_blocked():
    artifacts, risks, evidence = _green_inputs()
    evidence[0] = _evidence("tests", status="failing", trustworthy=False)
    assert derive_readiness(artifacts, risks, evidence).state == "blocked"


def test_readiness_mixed_evidence_is_blocked():
    artifacts, risks, evidence = _green_inputs()
    evidence[1] = _evidence("ci", status="mixed", trustworthy=False)
    assert derive_readiness(artifacts, risks, evidence).state == "blocked"


def test_readiness_blocked_wins_over_stale():
    """Severity ordering: a blocker plus stale evidence must read blocked, not
    stale — the more severe state wins."""
    artifacts, risks, evidence = _green_inputs()
    artifacts = _baseline_artifacts(repo_map="stale")
    risks.append(_risk("R2", evidence_status="failing", residual="blocker", uncovered_blocker=True))
    assert derive_readiness(artifacts, risks, evidence).state == "blocked"


def test_readiness_stale_repo_map_is_stale_evidence():
    artifacts, risks, evidence = _green_inputs()
    artifacts = _baseline_artifacts(repo_map="stale")
    readiness = derive_readiness(artifacts, risks, evidence)
    assert readiness.state == "stale_evidence"
    assert any("repo_map" in reason for reason in readiness.reasons)


def test_readiness_stale_risk_row_is_stale_evidence():
    artifacts, risks, evidence = _green_inputs()
    risks.append(_risk("R2", evidence_status="stale", residual="open"))
    assert derive_readiness(artifacts, risks, evidence).state == "stale_evidence"


def test_readiness_stale_evidence_fact_is_stale_evidence():
    artifacts, risks, evidence = _green_inputs()
    evidence[0] = _evidence("tests", status="passing", freshness="stale", trustworthy=False)
    assert derive_readiness(artifacts, risks, evidence).state == "stale_evidence"


def test_readiness_stale_wins_over_incomplete():
    """A stale repo-map plus a missing ledger must read stale_evidence — the
    re-verify signal outranks the gather-more-data signal."""
    artifacts, risks, evidence = _green_inputs()
    artifacts = _baseline_artifacts(repo_map="stale", risk_ledger="missing")
    assert derive_readiness(artifacts, [], evidence).state == "stale_evidence"


@pytest.mark.parametrize("kind", ["repo_map", "risk_ledger", "context_bundle"])
@pytest.mark.parametrize("status", ["missing", "invalid"])
def test_readiness_core_artifact_gap_is_incomplete(kind, status):
    """Missing or unreadable core artifacts mean the report cannot claim
    readiness — missing data is NOT passing evidence (AC)."""
    artifacts, risks, evidence = _green_inputs()
    artifacts = _baseline_artifacts(**{kind: status})
    readiness = derive_readiness(artifacts, risks, evidence)
    assert readiness.state == "incomplete"
    assert any(kind in reason for reason in readiness.reasons)


def test_readiness_planned_risk_row_is_incomplete():
    artifacts, risks, evidence = _green_inputs()
    risks.append(_risk("R2", evidence_status="planned", residual="open"))
    assert derive_readiness(artifacts, risks, evidence).state == "incomplete"


def test_readiness_empty_ledger_rows_is_incomplete():
    """An available ledger with zero recorded risks is weak evidence, not a
    green light."""
    artifacts, _, evidence = _green_inputs()
    readiness = derive_readiness(artifacts, [], evidence)
    assert readiness.state == "incomplete"
    assert any("no risks" in reason for reason in readiness.reasons)


@pytest.mark.parametrize("status", ["not_run", "missing"])
def test_readiness_unrun_core_evidence_is_incomplete(status):
    artifacts, risks, evidence = _green_inputs()
    evidence[0] = _evidence("tests", status=status, freshness="absent", trustworthy=False)
    assert derive_readiness(artifacts, risks, evidence).state == "incomplete"


def test_readiness_missing_coverage_does_not_block_ready():
    """coverage/mutation have no producer yet (#147) — their 'missing' status
    must not drag an otherwise-green repo to incomplete."""
    artifacts, risks, evidence = _green_inputs()
    evidence.append(_evidence("coverage", status="missing", freshness=None, trustworthy=False))
    evidence.append(_evidence("mutation", status="missing", freshness=None, trustworthy=False))
    assert derive_readiness(artifacts, risks, evidence).state == "ready"


def test_readiness_accepted_residual_row_is_ready_with_residuals():
    artifacts, risks, evidence = _green_inputs()
    risks.append(_risk("R2", evidence_status="accepted_residual", residual="accepted"))
    readiness = derive_readiness(artifacts, risks, evidence)
    assert readiness.state == "ready_with_residuals"
    assert any("R2" in reason for reason in readiness.reasons)


def test_readiness_open_residual_on_passing_row_is_ready_with_residuals():
    artifacts, risks, evidence = _green_inputs()
    risks.append(_risk("R2", evidence_status="passing", residual="open"))
    assert derive_readiness(artifacts, risks, evidence).state == "ready_with_residuals"


def test_readiness_reasons_are_deterministic():
    artifacts, risks, evidence = _green_inputs()
    risks.append(_risk("R2", evidence_status="failing", residual="blocker", uncovered_blocker=True))
    first = derive_readiness(artifacts, risks, evidence)
    second = derive_readiness(artifacts, risks, evidence)
    assert first == second
    assert first.reasons  # a non-ready state must say why


def test_readiness_ready_state_has_reasonless_or_explanatory_shape():
    artifacts, risks, evidence = _green_inputs()
    readiness = derive_readiness(artifacts, risks, evidence)
    assert isinstance(readiness, ReportReadiness)


# ---------------------------------------------------------------------------
# model contracts
# ---------------------------------------------------------------------------


def test_report_schema_version_is_1_0():
    assert REPORT_SCHEMA_VERSION == "1.0"


def test_artifact_kinds_cover_the_issue_inventory():
    """#157 names six consumable sources; the inventory must track all of them
    so absent ones render an explicit 'not available' state."""
    assert set(ARTIFACT_KINDS) == {
        "repo_map",
        "diff_impact",
        "risk_ledger",
        "context_bundle",
        "readiness_scorecard",
        "coverage_mutation",
    }


def test_qa_report_requires_schema_version():
    project = ReportProject(
        root="/repo",
        name=None,
        head_commit=None,
        generated_at=_NOW,
        generator_version="sumo-qa 0.0.0-test",
    )
    with pytest.raises(ValidationError):
        QAReport(
            project=project,
            artifacts=_baseline_artifacts(),
            readiness=ReportReadiness(state="incomplete", reasons=[]),
        )


def test_qa_report_rejects_unknown_fields():
    project = ReportProject(
        root="/repo",
        name=None,
        head_commit=None,
        generated_at=_NOW,
        generator_version="sumo-qa 0.0.0-test",
    )
    with pytest.raises(ValidationError):
        QAReport(
            schema_version=REPORT_SCHEMA_VERSION,
            project=project,
            artifacts=_baseline_artifacts(),
            readiness=ReportReadiness(state="incomplete", reasons=[]),
            surprise="nope",
        )


def test_report_project_rejects_naive_generated_at():
    """Freshness math is meaningless on a naive datetime — mirror the repo-map
    model's timezone-aware requirement."""
    with pytest.raises(ValidationError):
        ReportProject(
            root="/repo",
            name=None,
            head_commit=None,
            generated_at=datetime(2026, 6, 8, 8, 0, 0),
            generator_version="sumo-qa 0.0.0-test",
        )


def test_report_artifact_rejects_unknown_status():
    with pytest.raises(ValidationError):
        _artifact("repo_map", "sparkling")


def test_report_artifact_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        _artifact("crystal_ball", "missing")
