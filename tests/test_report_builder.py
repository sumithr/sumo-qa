# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.report_builder — artifact ingestion for the QA report (#157).

Equivalence partitioning over each artifact source: present-valid /
present-invalid / absent / stale classes, plus subset-only combinations —
the report must work when only a subset of artifacts exists and must render
honest states for the rest (AC), never crash on a bad file.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sumo_qa.context_bundle_models import ContextBundle
from sumo_qa.ledger_models import LEDGER_SCHEMA_VERSION, RiskLedger, RiskLedgerRow
from sumo_qa.report_builder import (
    _readiness_from_scorecard,
    build_report,
    generate_report,
    load_report_inputs,
)

_NOW = datetime(2026, 6, 8, 8, 0, 0, tzinfo=timezone.utc)
_VERSION = "sumo-qa 0.0.0-test"
_SHA_A = "a" * 40
_SHA_B = "b" * 40


def _clean_git_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git_init_commit(path: Path) -> str:
    env = _clean_git_env()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, env=env)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True, env=env)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True, env=env)
    subprocess.run(["git", "config", "core.hooksPath", "/dev/null"], cwd=path, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, env=env)
    subprocess.run(
        ["git", "commit", "--no-verify", "-q", "-m", "init", "--no-gpg-sign"],
        cwd=path,
        check=True,
        env=env,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, check=True, env=env
    )
    return head.stdout.decode().strip()


def _repo_map_payload(root: Path, *, git_commit: str | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "project": {
            "root": str(root),
            "name": root.name,
            "git_commit": git_commit,
            "generated_at": "2026-06-01T12:00:00+00:00",
            "generator_version": _VERSION,
        },
        "nodes": [
            {"id": "src/demo.py", "type": "source_file", "path": "src/demo.py"},
            {"id": "tests/test_demo.py", "type": "test_file", "path": "tests/test_demo.py"},
        ],
        "edges": [],
        "commands": [],
        "warnings": [],
    }


def _diff_impact_payload(*, stale_warning: bool = False) -> dict:
    warnings = []
    if stale_warning:
        warnings.append({"kind": "stale", "message": "repo-map git_commit differs from HEAD"})
    return {
        "changed_nodes": [
            {
                "id": "src/demo.py",
                "type": "source_file",
                "path": "src/demo.py",
                "has_mapped_tests": True,
            }
        ],
        "affected_nodes": [
            {
                "id": "tests/test_demo.py",
                "type": "test_file",
                "path": "tests/test_demo.py",
                "has_mapped_tests": False,
            }
        ],
        "related_tests": ["tests/test_demo.py"],
        "unmapped_files": ["docs/notes.md"],
        "risk_surface": ["src/demo.py"],
        "suggested_inspections": [],
        "warnings": warnings,
        "probable_mapping_gap": False,
    }


def _ledger_payload() -> dict:
    return {
        "schema_version": "1.0",
        "rows": [
            {
                "risk_id": "R1",
                "risk": "demo regression",
                "source_anchor": "src/demo.py:1",
                "test": "tests/test_demo.py::test_demo",
                "evidence_status": "passing",
                "residual": "mitigated",
            },
            {
                "risk_id": "R2",
                "risk": "unhandled edge",
                "source_anchor": "src/demo.py:9",
                "test": "planned: boundary sweep",
                "evidence_status": "planned",
                "residual": "blocker",
            },
        ],
    }


def _bundle_payload() -> dict:
    return {
        "schema_version": "1.0",
        "head_sha": _SHA_A,
        "changed_files": [{"path": "src/demo.py", "change_kind": "modified"}],
        "test_evidence": {
            "result": "passing",
            "freshness": "fresh",
            "source": "local_git",
        },
        "ci_status": {
            "result": "passing",
            "freshness": "stale",
            "source": "ci_provider",
        },
    }


def _write_artifact(root: Path, name: str, payload: dict) -> Path:
    target = root / ".sumo-qa" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def _statuses(report) -> dict[str, str]:
    return {a.kind: a.status for a in report.artifacts}


# ---------------------------------------------------------------------------
# absent / subset partitions
# ---------------------------------------------------------------------------


def test_empty_repo_reports_all_sources_missing(tmp_path):
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    statuses = _statuses(report)
    assert statuses == {
        "repo_map": "missing",
        "diff_impact": "missing",
        "risk_ledger": "missing",
        "context_bundle": "missing",
        "readiness_scorecard": "missing",
        "coverage_mutation": "missing",
    }
    assert report.readiness.state == "insufficient_evidence"
    assert report.changed_components == []
    assert report.risks == []
    # Missing data is reported as missing — never as passing evidence (AC).
    assert all(e.status == "missing" for e in report.evidence)


def test_subset_only_repo_map_present(tmp_path):
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    statuses = _statuses(report)
    assert statuses["repo_map"] == "available"
    assert statuses["diff_impact"] == "missing"
    assert report.readiness.state == "insufficient_evidence"
    repo_map_entry = next(a for a in report.artifacts if a.kind == "repo_map")
    assert repo_map_entry.generated_at is not None
    assert repo_map_entry.age_days == 6  # 2026-06-01T12:00 → 2026-06-08T08:00


# ---------------------------------------------------------------------------
# invalid partitions — a bad file is an honest state, not a crash
# ---------------------------------------------------------------------------


def test_malformed_repo_map_is_invalid(tmp_path):
    target = tmp_path / ".sumo-qa" / "repo-map.json"
    target.parent.mkdir(parents=True)
    target.write_text("{not json", encoding="utf-8")
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "repo_map")
    assert entry.status == "invalid"
    assert entry.detail is not None and "malformed_json" in entry.detail


def test_schema_drifted_repo_map_is_invalid(tmp_path):
    _write_artifact(tmp_path, "repo-map.json", {"schema_version": "9.9"})
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "repo_map")
    assert entry.status == "invalid"
    assert entry.detail is not None and "schema_version_mismatch" in entry.detail


def test_malformed_diff_impact_is_invalid(tmp_path):
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))
    target = tmp_path / ".sumo-qa" / "diff-impact.json"
    target.write_text("[]", encoding="utf-8")  # wrong shape: list, not object
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "diff_impact")
    assert entry.status == "invalid"
    assert report.changed_components == []


def test_invalid_ledger_is_invalid_state(tmp_path):
    _write_artifact(
        tmp_path,
        "risk-ledger.json",
        {"schema_version": "1.0", "rows": [{"risk_id": ""}]},
    )
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "risk_ledger")
    assert entry.status == "invalid"
    assert report.risks == []


def test_invalid_bundle_is_invalid_state(tmp_path):
    _write_artifact(tmp_path, "context-bundle.json", {"schema_version": "1.0", "nope": True})
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "context_bundle")
    assert entry.status == "invalid"


def test_foreign_root_repo_map_is_invalid_not_evidence(tmp_path):
    """A repo-map copied from ANOTHER repository measures a different tree —
    composing it would present foreign evidence as local. Mirror the
    `_load_map_with_fallback` rejection precedent (server.py)."""
    foreign = tmp_path / "elsewhere"
    foreign.mkdir()
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(foreign))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "repo_map")
    assert entry.status == "invalid"
    assert entry.detail is not None and "foreign_root" in entry.detail
    assert report.readiness.state == "insufficient_evidence"


def test_foreign_root_repo_map_also_rejects_its_diff_impact_overlay(tmp_path):
    """The diff-impact overlay's nodes are repo-map node ids — when the map is
    rejected as foreign, the overlay describes the same foreign tree. It must
    be rejected in lockstep: neither composed into the report body nor counted
    as evidence. Without this the overlay (no own stale warning) reads
    `available` and its foreign components leak into the report."""
    foreign = tmp_path / "elsewhere"
    foreign.mkdir()
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(foreign))
    _write_artifact(tmp_path, "diff-impact.json", _diff_impact_payload())  # no own stale warning
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "diff_impact")
    assert entry.status == "invalid"
    assert entry.detail is not None and "foreign_root" in entry.detail
    # the foreign overlay's components must NOT leak into the report body
    assert report.changed_components == []
    assert report.affected_components == []
    assert report.related_tests == []
    assert report.risk_surface == []


def test_pathologically_nested_artifact_is_invalid_not_a_crash(tmp_path):
    """A hostile deeply-nested JSON file overflows the recursive parser —
    that must surface as an honest invalid state, never a RecursionError."""
    target = tmp_path / ".sumo-qa" / "risk-ledger.json"
    target.parent.mkdir(parents=True)
    depth = 50_000
    target.write_text("[" * depth + "]" * depth, encoding="utf-8")
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "risk_ledger")
    assert entry.status == "invalid"


def test_present_scorecard_file_is_ignored_not_read(tmp_path):
    """The scorecard is derived in-report (#151 engine) from the ledger +
    bundle, not read from disk — there is no readiness-scorecard.json
    convention. A leftover file is ignored, NOT treated as an artifact, so with
    no ledger/bundle the row is 'missing' (not derivable), never 'invalid'."""
    _write_artifact(tmp_path, "readiness-scorecard.json", {"anything": 1})
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "readiness_scorecard")
    assert entry.status == "missing"
    assert entry.path is None
    assert entry.detail is not None and "not derivable" in entry.detail


def test_scorecard_is_available_when_derived_from_ledger(tmp_path):
    """A risk ledger (or bundle) is enough to derive the scorecard, so the
    inventory row reads 'available' and says it was derived in-report — in
    product terms, never internal tracker references."""
    _write_artifact(tmp_path, "risk-ledger.json", _ledger_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "readiness_scorecard")
    assert entry.status == "available"
    assert entry.detail is not None and "derived in-report" in entry.detail


def test_empty_ledger_does_not_mark_scorecard_available(tmp_path):
    """An empty ledger (zero rows) is not QA evidence: the derived scorecard
    stays 'missing' so it never counts as an available source, while the verdict
    honestly reads insufficient_evidence."""
    _write_artifact(tmp_path, "risk-ledger.json", {"schema_version": "1.0", "rows": []})
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "readiness_scorecard")
    assert entry.status == "missing"
    assert report.readiness.state == "insufficient_evidence"


def test_evidence_free_bundle_does_not_mark_scorecard_available(tmp_path):
    """A valid but evidence-free context bundle (no test evidence, no CI
    status, no changed files) is not QA evidence either — the bundle twin of
    the empty-ledger case. The derived scorecard stays 'missing' so it never
    counts as an available source while the verdict reads insufficient."""
    _write_artifact(tmp_path, "context-bundle.json", {"schema_version": "1.0"})
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "readiness_scorecard")
    assert entry.status == "missing"
    assert report.readiness.state == "insufficient_evidence"


def test_absent_scorecard_reports_not_derivable(tmp_path):
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "readiness_scorecard")
    assert entry.status == "missing"
    assert entry.detail is not None and "not derivable" in entry.detail


def test_coverage_mutation_is_an_optional_scorecard_signal(tmp_path):
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "coverage_mutation")
    assert entry.status == "missing"
    assert entry.detail is not None
    assert "not supplied" in entry.detail
    assert "reported, not gated" in entry.detail


def _coverage_payload(**overrides) -> dict:
    payload = {
        "schema_version": "1.0",
        "generated_at": "2026-06-08T00:00:00Z",
        "source_tool": "pytest-cov",
        "line_percent": 100.0,
        "freshness": "fresh",
    }
    payload.update(overrides)
    return payload


def _mutation_payload(**overrides) -> dict:
    payload = {
        "schema_version": "1.0",
        "generated_at": "2026-06-08T00:00:00Z",
        "source_tool": "mutmut",
        "survivors": 2,
        "killed": 145,
        "freshness": "fresh",
    }
    payload.update(overrides)
    return payload


def test_fresh_coverage_artifact_renders_available(tmp_path):
    _write_artifact(tmp_path, "coverage.json", _coverage_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "coverage_mutation")
    assert entry.status == "available"
    assert entry.detail is not None and "coverage: fresh" in entry.detail
    # The evidence stream carries the measurement, reported never gated.
    stream = next(s for s in report.evidence if s.name == "coverage")
    assert stream.status == "not_run"
    assert stream.trustworthy is True
    assert stream.detail is not None and "100% lines" in stream.detail


def test_stale_coverage_artifact_renders_stale(tmp_path):
    _write_artifact(tmp_path, "coverage.json", _coverage_payload(freshness="stale"))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "coverage_mutation")
    assert entry.status == "stale"
    stream = next(s for s in report.evidence if s.name == "coverage")
    assert stream.trustworthy is False


def test_both_coverage_and_mutation_render_available(tmp_path):
    _write_artifact(tmp_path, "coverage.json", _coverage_payload())
    _write_artifact(tmp_path, "mutation.json", _mutation_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "coverage_mutation")
    assert entry.status == "available"
    assert "mutation: fresh" in (entry.detail or "")
    mstream = next(s for s in report.evidence if s.name == "mutation")
    assert mstream.status == "not_run"
    assert mstream.detail is not None and "2 survivor(s)" in mstream.detail


def test_invalid_coverage_artifact_renders_invalid(tmp_path):
    _write_artifact(tmp_path, "coverage.json", _coverage_payload(line_percent=150.0))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "coverage_mutation")
    assert entry.status == "invalid"
    assert "unreadable" in (entry.detail or "")


def test_measurementless_coverage_artifact_stays_missing(tmp_path):
    # A payload with provenance + freshness but no line_percent carries no
    # measurement, so the dimension is not_measured and the row stays missing.
    _write_artifact(
        tmp_path,
        "coverage.json",
        {
            "schema_version": "1.0",
            "generated_at": "2026-06-08T00:00:00Z",
            "source_tool": "pytest-cov",
            "freshness": "fresh",
        },
    )
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "coverage_mutation")
    assert entry.status == "missing"


def test_coverage_never_flips_an_insufficient_verdict(tmp_path):
    # No risk ledger / bundle ⇒ insufficient_evidence. A fresh 100% coverage
    # signal must NOT move it — coverage is reported, never gated.
    _write_artifact(tmp_path, "coverage.json", _coverage_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.readiness.state == "insufficient_evidence"


def test_artifact_details_carry_no_tracker_issue_references(tmp_path):
    """Inventory detail strings are product copy rendered on ANY target repo —
    a '#N' there reads as the TARGET repo's issue number, so sumo-qa's internal
    tracker references must never leak into them (provenance lives in code
    comments and repo docs instead)."""
    _write_artifact(tmp_path, "risk-ledger.json", _ledger_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    for artifact in report.artifacts:
        assert artifact.detail is None or not re.search(r"#\d+", artifact.detail), (
            f"{artifact.kind}: tracker reference leaked into user-facing detail: "
            f"{artifact.detail!r}"
        )


# ---------------------------------------------------------------------------
# readiness verdict — sourced from #151's QaScorecard engine
# ---------------------------------------------------------------------------

_CLEAN_BUNDLE = ContextBundle.model_validate(
    {
        "schema_version": "1.0",
        "head_sha": _SHA_A,
        "changed_files": [{"path": "src/demo.py", "change_kind": "modified"}],
        "test_evidence": {"result": "passing", "freshness": "fresh", "source": "local_git"},
        "ci_status": {"result": "passing", "freshness": "fresh", "source": "ci_provider"},
    }
)


def _row(risk_id: str, evidence_status: str, residual: str) -> RiskLedgerRow:
    return RiskLedgerRow(
        risk_id=risk_id,
        risk="demo risk",
        source_anchor="src/demo.py:1",
        test="tests/test_demo.py::test_demo",
        evidence_status=evidence_status,
        residual=residual,
    )


def _ledger(*rows: RiskLedgerRow) -> RiskLedger:
    return RiskLedger(schema_version=LEDGER_SCHEMA_VERSION, rows=list(rows))


@pytest.mark.parametrize(
    "ledger,bundle,head,expected",
    [
        (_ledger(_row("R1", "passing", "mitigated")), _CLEAN_BUNDLE, _SHA_A, "ready"),
        (
            _ledger(
                _row("R1", "passing", "mitigated"), _row("R2", "accepted_residual", "accepted")
            ),
            _CLEAN_BUNDLE,
            _SHA_A,
            "ready_with_accepted_residuals",
        ),
        (_ledger(_row("R3", "planned", "blocker")), None, None, "blocked"),
        (None, None, None, "insufficient_evidence"),
    ],
)
def test_readiness_from_scorecard_maps_each_state(ledger, bundle, head, expected):
    """The report's verdict is exactly #151's QaScorecard.recommendation() for
    the same ledger + bundle — single source of truth, no re-derivation."""
    readiness = _readiness_from_scorecard(ledger, bundle, scope="demo", local_head_sha=head)
    assert readiness.state == expected
    if expected == "ready":
        assert readiness.reasons == []
    else:
        assert readiness.reasons  # a non-ready verdict must explain itself


# ---------------------------------------------------------------------------
# valid partitions — content mapped through to the report
# ---------------------------------------------------------------------------


def test_diff_impact_components_are_mapped_and_sorted(tmp_path):
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))
    payload = _diff_impact_payload()
    payload["changed_nodes"].insert(
        0,
        {
            "id": "zzz/last.py",
            "type": "source_file",
            "path": "zzz/last.py",
            "has_mapped_tests": False,
        },
    )
    _write_artifact(tmp_path, "diff-impact.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    ids = [c.id for c in report.changed_components]
    assert ids == sorted(ids)
    assert report.affected_components[0].id == "tests/test_demo.py"
    assert report.related_tests == ["tests/test_demo.py"]
    assert report.unmapped_files == ["docs/notes.md"]


def test_run_summary_round_trips_into_next_report(tmp_path):
    """Move 7 (delta): generating writes a compact run summary; the next
    generation reads it back as previous_run so the page can show the trend."""
    from sumo_qa.report_builder import write_run_summary

    first = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert first.previous_run is None
    write_run_summary(tmp_path, first)
    assert (tmp_path / ".sumo-qa" / "qa-report-summary.json").is_file()

    _write_artifact(tmp_path, "risk-ledger.json", _ledger_payload())
    second = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert second.previous_run is not None
    assert second.previous_run.readiness_state == "insufficient_evidence"
    assert second.previous_run.risk_count == 0
    assert second.previous_run.generated_at == _NOW


def test_corrupt_run_summary_is_ignored(tmp_path):
    target = tmp_path / ".sumo-qa" / "qa-report-summary.json"
    target.parent.mkdir(parents=True)
    target.write_text("{not json", encoding="utf-8")
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.previous_run is None


def test_unsupported_run_summary_schema_is_ignored(tmp_path):
    _write_artifact(
        tmp_path,
        "qa-report-summary.json",
        {
            "schema_version": "9.9",
            "generated_at": "2026-06-07T08:00:00+00:00",
            "readiness_state": "ready",
            "risk_count": 0,
            "uncovered_blocker_count": 0,
            "sources_available": 0,
        },
    )
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.previous_run is None


def test_blocked_verdict_leads_with_falsifiable_threshold_reason(tmp_path):
    """Reasons are falsifiable, SonarQube-style: count vs required threshold
    first, the engine's per-risk itemisation after."""
    _write_artifact(tmp_path, "risk-ledger.json", _ledger_payload())  # R2 = blocker
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.readiness.state == "blocked"
    assert report.readiness.reasons[0] == "uncovered blocker risks: 1 of 2 (required: 0)"
    assert any(r.startswith("R2:") for r in report.readiness.reasons[1:])


def test_blocked_by_failing_test_never_claims_zero_blockers(tmp_path):
    """A report blocked by a FAILING covering test (no uncovered blockers)
    must not carry the contradictory 'uncovered blocker risks: 0 of N
    (required: 0)' headline — the headline names what actually blocks."""
    payload = _ledger_payload()
    payload["rows"][1]["evidence_status"] = "failing"
    payload["rows"][1]["residual"] = "mitigated"
    _write_artifact(tmp_path, "risk-ledger.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.readiness.state == "blocked"
    assert report.readiness.reasons[0] == (
        "risks with failing covering tests: 1 of 2 (required: 0)"
    )
    assert not any("uncovered blocker risks: 0" in r for r in report.readiness.reasons)


def test_insufficient_verdict_leads_with_evidence_count_when_ledger_present(tmp_path):
    payload = _ledger_payload()
    payload["rows"][1]["evidence_status"] = "stale"
    payload["rows"][1]["residual"] = "mitigated"
    _write_artifact(tmp_path, "risk-ledger.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.readiness.state == "insufficient_evidence"
    assert (
        report.readiness.reasons[0] == "risks without fresh passing evidence: 1 of 2 (required: 0)"
    )


def test_no_ledger_insufficiency_reason_stays_unprefixed(tmp_path):
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.readiness.state == "insufficient_evidence"
    assert report.readiness.reasons == ["no QA evidence supplied, so readiness cannot be assessed"]


def test_mapping_gap_warning_reaches_the_report(tmp_path):
    """A diff-impact 'probable mapping gap' warning is honesty-critical (the
    whole risk surface may be a missed convention, not zero coverage) — it
    must surface in the report's warnings, not silently vanish."""
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))
    payload = _diff_impact_payload()
    payload["probable_mapping_gap"] = True
    payload["warnings"].append(
        {
            "kind": "other",
            "message": (
                "probable mapping gap, not zero coverage: test files are present but "
                "the repo-map has no likely_tests edges"
            ),
        }
    )
    _write_artifact(tmp_path, "diff-impact.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert any("probable mapping gap" in w for w in report.warnings)


def test_stale_impact_warnings_do_not_duplicate_into_report_warnings(tmp_path):
    """kind='stale' overlay warnings drive the diff-impact artifact's stale
    STATE — they must not render a second time as page-level warnings."""
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))
    _write_artifact(tmp_path, "diff-impact.json", _diff_impact_payload(stale_warning=True))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "diff_impact")
    assert entry.status == "stale"
    assert not any("git_commit differs" in w for w in report.warnings)


def test_tristate_mapped_tests_carries_through_from_overlay(tmp_path):
    """A persisted overlay's ``has_mapped_tests: null`` on a non-source node
    survives the projection into report components — the builder must not
    coerce it back into a vacuous bool."""
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))
    payload = _diff_impact_payload()
    payload["changed_nodes"].append(
        {"id": "file:README.md", "type": "docs", "path": "README.md", "has_mapped_tests": None}
    )
    _write_artifact(tmp_path, "diff-impact.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    by_path = {c.path: c.has_mapped_tests for c in report.changed_components}
    assert by_path["README.md"] is None
    assert by_path["src/demo.py"] is True


def test_builder_normalises_vacuous_bool_from_old_overlays(tmp_path):
    """An overlay persisted before the tri-state change carries a vacuous
    bool on non-source rows. The builder normalises it to None on projection,
    so 'no' only ever appears where it indicts — for ANY input vintage."""
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))
    payload = _diff_impact_payload()
    payload["changed_nodes"].append(
        {"id": "file:README.md", "type": "docs", "path": "README.md", "has_mapped_tests": False}
    )
    _write_artifact(tmp_path, "diff-impact.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    by_path = {c.path: c.has_mapped_tests for c in report.changed_components}
    assert by_path["README.md"] is None
    affected = {c.path: c.has_mapped_tests for c in report.affected_components}
    assert affected["tests/test_demo.py"] is None  # old-shape False on a test row


def test_old_overlay_migrates_to_na_marker_in_rendered_html(tmp_path):
    """End-to-end vintage migration: a pre-tri-state overlay (vacuous bool on
    a test_file row) loaded from disk renders the muted 'n/a' marker in the
    page, not 'no': load -> projection -> HTML, the full path."""
    from sumo_qa.report_html import render_report_html

    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))
    _write_artifact(tmp_path, "diff-impact.json", _diff_impact_payload())  # test row: False
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    html = render_report_html(report)
    assert '<td class="brk">tests/test_demo.py</td><td><span class="na">n/a</span></td>' in html
    assert '<td class="brk">tests/test_demo.py</td><td>no</td>' not in html


def test_ledger_rows_become_risks_with_blocker_count(tmp_path):
    _write_artifact(tmp_path, "risk-ledger.json", _ledger_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert [r.risk_id for r in report.risks] == ["R1", "R2"]
    assert report.risks[1].uncovered_blocker is True
    assert report.uncovered_blocker_count == 1
    assert report.readiness.state == "blocked"


def test_bundle_evidence_is_mapped_with_trust(tmp_path):
    _write_artifact(tmp_path, "context-bundle.json", _bundle_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    by_name = {e.name: e for e in report.evidence}
    assert by_name["tests"].status == "passing"
    assert by_name["tests"].trustworthy is True
    assert by_name["ci"].freshness == "stale"
    assert by_name["ci"].trustworthy is False
    assert by_name["coverage"].status == "missing"
    assert by_name["mutation"].status == "missing"


# ---------------------------------------------------------------------------
# stale partitions
# ---------------------------------------------------------------------------


def test_repo_map_stale_when_recorded_commit_differs_from_head(tmp_path):
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    _git_init_commit(tmp_path)
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path, git_commit="0" * 40))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "repo_map")
    assert entry.status == "stale"
    assert report.readiness.state == "insufficient_evidence"


def test_repo_map_fresh_when_recorded_commit_matches_head(tmp_path):
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    head = _git_init_commit(tmp_path)
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path, git_commit=head))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "repo_map")
    assert entry.status == "available"
    assert report.project.head_commit == head


def test_repo_map_abbreviated_same_commit_sha_is_not_stale(tmp_path):
    """Sha comparison is prefix-aware (the context-bundle `_sha_equivalent`
    contract): an abbreviated recorded sha naming the SAME commit must not
    false-flag the map as stale."""
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    head = _git_init_commit(tmp_path)
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path, git_commit=head[:12]))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "repo_map")
    assert entry.status == "available"


def test_diff_impact_with_persisted_stale_warning_is_stale(tmp_path):
    _write_artifact(tmp_path, "diff-impact.json", _diff_impact_payload(stale_warning=True))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "diff_impact")
    assert entry.status == "stale"


def test_diff_impact_inherits_staleness_from_a_stale_repo_map(tmp_path):
    """The overlay carries no provenance of its own (schema 1.x): persisted
    warnings are frozen at generation time, so an overlay generated at commit
    A would read available after the repo moves to commit B. When the repo-map
    it was derived from is stale, the overlay is at least as suspect."""
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    _git_init_commit(tmp_path)
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path, git_commit="0" * 40))
    _write_artifact(tmp_path, "diff-impact.json", _diff_impact_payload())  # no persisted warning
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "diff_impact")
    assert entry.status == "stale"
    assert entry.detail is not None and "repo-map" in entry.detail.lower()


def test_bundle_head_sha_conflict_surfaces_warning_and_stale(tmp_path):
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    _git_init_commit(tmp_path)
    payload = _bundle_payload()
    payload["head_sha"] = _SHA_B  # never a real local HEAD
    payload["ci_status"]["freshness"] = "fresh"
    _write_artifact(tmp_path, "context-bundle.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert any("head" in w.lower() for w in report.warnings)
    assert report.readiness.state == "insufficient_evidence"


# ---------------------------------------------------------------------------
# inline overrides (MCP flow: chat-built artifacts without persistence)
# ---------------------------------------------------------------------------


def test_ledger_override_takes_precedence_over_disk(tmp_path):
    _write_artifact(tmp_path, "risk-ledger.json", {"schema_version": "9.9"})  # invalid on disk
    override = RiskLedger(
        schema_version=LEDGER_SCHEMA_VERSION,
        rows=[
            RiskLedgerRow(
                risk_id="R9",
                risk="inline risk",
                source_anchor="src/x.py:3",
                test="tests/test_x.py::test_x",
                evidence_status="passing",
                residual="mitigated",
            )
        ],
    )
    report = generate_report(
        tmp_path, generator_version=_VERSION, now=_NOW, ledger_override=override
    )
    entry = next(a for a in report.artifacts if a.kind == "risk_ledger")
    assert entry.status == "available"
    assert entry.path is None
    assert entry.detail is not None and "inline" in entry.detail.lower()
    assert [r.risk_id for r in report.risks] == ["R9"]


def test_bundle_override_takes_precedence_over_disk(tmp_path):
    _write_artifact(tmp_path, "context-bundle.json", "not even json")
    override = ContextBundle.model_validate(_bundle_payload())
    report = generate_report(
        tmp_path, generator_version=_VERSION, now=_NOW, bundle_override=override
    )
    entry = next(a for a in report.artifacts if a.kind == "context_bundle")
    assert entry.status == "available"
    assert entry.path is None
    by_name = {e.name: e for e in report.evidence}
    assert by_name["tests"].status == "passing"


# ---------------------------------------------------------------------------
# determinism and composition
# ---------------------------------------------------------------------------


def test_build_report_is_pure_and_deterministic(tmp_path):
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))
    _write_artifact(tmp_path, "diff-impact.json", _diff_impact_payload())
    _write_artifact(tmp_path, "risk-ledger.json", _ledger_payload())
    _write_artifact(tmp_path, "context-bundle.json", _bundle_payload())
    inputs = load_report_inputs(tmp_path)
    first = build_report(inputs, now=_NOW, generator_version=_VERSION)
    second = build_report(inputs, now=_NOW, generator_version=_VERSION)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_generate_report_defaults_now_to_utc(tmp_path):
    report = generate_report(tmp_path, generator_version=_VERSION)
    assert report.project.generated_at.tzinfo is not None


def test_generate_report_rejects_naive_now(tmp_path):
    with pytest.raises(ValueError):
        generate_report(tmp_path, generator_version=_VERSION, now=datetime(2026, 6, 8, 8, 0, 0))


def test_report_project_fields_are_threaded(tmp_path):
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.project.root == str(tmp_path.resolve())
    assert report.project.generated_at == _NOW
    assert report.project.generator_version == _VERSION
    assert report.schema_version == "1.0"
