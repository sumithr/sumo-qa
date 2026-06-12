# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.report_models — the render-ready QA report model (#157).

The readiness verdict is NOT derived here — it is derived by #151's
``QaScorecard`` and mapped onto :class:`ReportReadiness` by
``report_builder._readiness_from_scorecard`` (tested in test_report_builder).
This module pins the document model's shape: the artifact inventory, the
four-state ``ReadinessState`` vocabulary, and the strict-validation contracts.
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
    ReportComponent,
    ReportProject,
    ReportReadiness,
)

_NOW = datetime(2026, 6, 8, 8, 0, 0, tzinfo=timezone.utc)


def _artifact(kind: str, status: str, **overrides) -> ReportArtifact:
    data = {"kind": kind, "status": status, "path": None, "detail": None}
    data.update(overrides)
    return ReportArtifact(**data)


def _baseline_artifacts(**status_overrides) -> list[ReportArtifact]:
    """All-green artifact inventory. The scorecard is ``available`` (derived
    in-report from the ledger + bundle); coverage/mutation stay ``missing``
    (#147 is guidance, not a persisted artifact)."""
    statuses = {
        "repo_map": "available",
        "diff_impact": "available",
        "risk_ledger": "available",
        "context_bundle": "available",
        "readiness_scorecard": "available",
        "coverage_mutation": "missing",
    }
    statuses.update(status_overrides)
    return [_artifact(kind, status) for kind, status in statuses.items()]


# ---------------------------------------------------------------------------
# ReadinessState vocabulary — adopted verbatim from #151's scorecard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    ["ready", "ready_with_accepted_residuals", "blocked", "insufficient_evidence"],
)
def test_readiness_state_vocabulary_matches_the_scorecard(state):
    """ReportReadiness accepts exactly the scorecard's four recommendation
    states — the report and the scorecard can never disagree on vocabulary."""
    assert ReportReadiness(state=state, reasons=[]).state == state


@pytest.mark.parametrize("state", ["stale_evidence", "incomplete", "ready_with_residuals"])
def test_readiness_rejects_the_retired_report_only_states(state):
    """The old report-only vocabulary (folded into the scorecard's states) is
    no longer valid — guards against a stale snapshot or caller drifting back."""
    with pytest.raises(ValidationError):
        ReportReadiness(state=state, reasons=[])


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
            readiness=ReportReadiness(state="insufficient_evidence", reasons=[]),
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
            readiness=ReportReadiness(state="insufficient_evidence", reasons=[]),
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


def test_component_mapped_tests_is_tristate():
    """``has_mapped_tests`` is a verdict only for source files; any other
    node type carries None (rendered as a muted 'n/a', never a vacuous 'no')."""
    doc = ReportComponent(id="file:README.md", path="README.md", type="docs")
    assert doc.has_mapped_tests is None
    src = ReportComponent(
        id="file:src/a.py", path="src/a.py", type="source_file", has_mapped_tests=False
    )
    assert src.has_mapped_tests is False
