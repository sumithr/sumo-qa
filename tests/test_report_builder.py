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
    _detect_report_head,
    _load_run_summary,
    _readiness_from_scorecard,
    _repo_map_is_stale,
    build_report,
    generate_report,
    load_report_inputs,
    write_run_summary,
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
        "schema_version": "1.0",
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
        "coverage": "missing",
        "mutation": "missing",
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


def test_diff_impact_without_schema_version_is_invalid(tmp_path):
    # An unversioned overlay is untrustworthy: it must read as invalid, not be
    # silently composed as if current. Mirrors the repo-map versioning gate.
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))
    payload = _diff_impact_payload()
    payload.pop("schema_version", None)
    _write_artifact(tmp_path, "diff-impact.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "diff_impact")
    assert entry.status == "invalid"
    assert report.changed_components == []


def test_schema_drifted_diff_impact_is_invalid(tmp_path):
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))
    payload = {**_diff_impact_payload(), "schema_version": "9.9"}
    _write_artifact(tmp_path, "diff-impact.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "diff_impact")
    assert entry.status == "invalid"


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


def test_scorecard_is_derived_when_composed_from_ledger(tmp_path):
    """A risk ledger (or bundle) is enough to derive the scorecard, so the
    inventory row reads 'derived' (computed in-report, never an on-disk
    artifact) and says so — in product terms, never internal tracker
    references."""
    _write_artifact(tmp_path, "risk-ledger.json", _ledger_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "readiness_scorecard")
    assert entry.status == "derived"
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


def test_coverage_and_mutation_are_separate_optional_rows(tmp_path):
    # Two persisted producers = two inventory rows, not one combined row.
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    kinds = [a.kind for a in report.artifacts]
    assert "coverage" in kinds and "mutation" in kinds and "coverage_mutation" not in kinds
    for kind in ("coverage", "mutation"):
        entry = next(a for a in report.artifacts if a.kind == kind)
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
    entry = next(a for a in report.artifacts if a.kind == "coverage")
    assert entry.status == "available"
    # The split row carries its own file path and the per-signal measurement.
    assert entry.path == ".sumo-qa/coverage.json"
    assert entry.detail is not None
    assert "100% lines" in entry.detail and "freshness=fresh" in entry.detail
    # The evidence stream carries the measurement, reported never gated.
    stream = next(s for s in report.evidence if s.name == "coverage")
    assert stream.status == "not_run"
    assert stream.trustworthy is True
    assert stream.detail is not None and "100% lines" in stream.detail


def test_stale_coverage_artifact_renders_stale(tmp_path):
    _write_artifact(tmp_path, "coverage.json", _coverage_payload(freshness="stale"))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "coverage")
    assert entry.status == "stale"
    stream = next(s for s in report.evidence if s.name == "coverage")
    assert stream.trustworthy is False


def test_both_coverage_and_mutation_render_available(tmp_path):
    _write_artifact(tmp_path, "coverage.json", _coverage_payload())
    _write_artifact(tmp_path, "mutation.json", _mutation_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    cov = next(a for a in report.artifacts if a.kind == "coverage")
    mut = next(a for a in report.artifacts if a.kind == "mutation")
    assert cov.status == "available" and mut.status == "available"
    assert mut.path == ".sumo-qa/mutation.json"
    assert "2 survivor(s)" in (mut.detail or "")
    mstream = next(s for s in report.evidence if s.name == "mutation")
    assert mstream.status == "not_run"
    assert mstream.detail is not None and "2 survivor(s)" in mstream.detail


def test_invalid_coverage_artifact_renders_invalid(tmp_path):
    _write_artifact(tmp_path, "coverage.json", _coverage_payload(line_percent=150.0))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "coverage")
    assert entry.status == "invalid"
    assert "unreadable" in (entry.detail or "")


def test_coverage_and_mutation_rows_are_independent_no_aggregation(tmp_path):
    # The split's whole point: two separate files = two independent rows. A
    # fresh coverage signal stays `available` on its own row while a stale
    # mutation sibling is `stale` on its — no combined row can mask which
    # sibling is which (the old weakest-wins aggregation is gone).
    _write_artifact(tmp_path, "coverage.json", _coverage_payload(freshness="fresh"))
    _write_artifact(tmp_path, "mutation.json", _mutation_payload(freshness="stale"))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    cov = next(a for a in report.artifacts if a.kind == "coverage")
    mut = next(a for a in report.artifacts if a.kind == "mutation")
    assert cov.status == "available"
    assert mut.status == "stale"


def test_corrupt_mutation_sibling_does_not_drag_down_fresh_coverage(tmp_path):
    # A present-but-corrupt mutation artifact is `invalid` on ITS row only; the
    # fresh coverage row stays `available` instead of being masked into one
    # combined "invalid" verdict.
    _write_artifact(tmp_path, "coverage.json", _coverage_payload(freshness="fresh"))
    _write_artifact(tmp_path, "mutation.json", _mutation_payload(survivors=-5))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    cov = next(a for a in report.artifacts if a.kind == "coverage")
    mut = next(a for a in report.artifacts if a.kind == "mutation")
    assert cov.status == "available"
    assert mut.status == "invalid"
    assert "unreadable" in (mut.detail or "")


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
    entry = next(a for a in report.artifacts if a.kind == "coverage")
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
    # A verified bundle (head_sha == the live HEAD): trust follows freshness.
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    payload = _bundle_payload()
    payload["head_sha"] = _git_init_commit(tmp_path)
    _write_artifact(tmp_path, "context-bundle.json", payload)
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
    # Caller-supplied (never on disk) → `inline`, not `available`.
    assert entry.status == "inline"
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
    # Caller-supplied (never on disk) → `inline`, not `available`.
    assert entry.status == "inline"
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


# ===========================================================================
# Mutation-strengthening (bring report_builder.py under the mutation gate).
# Each test below names the survivors it kills. Equivalent / dead-branch mutants
# are suppressed at the source with `# pragma: no mutate` + rationale, never with
# a tautological test (see report_builder.py). Production code is unchanged.
# ===========================================================================


# --- detail strings: exact product copy (equivalence partitioning) ----------


def test_missing_artifact_details_are_exact(tmp_path):
    """Each absent artifact's inventory detail is product copy the reader uses to
    know what to run next; assert the EXACT string so wording/case mutants in the
    missing_detail arguments can't survive (equivalence partitioning over the
    absent class). Kills missing_detail mutants in _repo_map_artifact (_5/_11/_12),
    _diff_impact_artifact (_5/_11/_12), _ledger_artifact (_4/_10/_11/_12/_13),
    _bundle_artifact (_4/_10/_11/_12/_13)."""
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    by_kind = {a.kind: a for a in report.artifacts}
    assert by_kind["repo_map"].detail == "not generated yet; run `sumo-qa analyze` to create it"
    assert (
        by_kind["diff_impact"].detail
        == "no diff-impact overlay; run the diff-impact analysis to create one"
    )
    assert by_kind["risk_ledger"].detail == (
        "no persisted risk ledger; persist one to .sumo-qa/risk-ledger.json or pass rows inline"
    )
    assert by_kind["context_bundle"].detail == (
        "no persisted context bundle; persist one to .sumo-qa/context-bundle.json or pass it inline"
    )


# --- artifact path is threaded onto present / invalid rows -------------------


def test_present_artifact_rows_carry_their_path(tmp_path):
    """A present artifact row names the repo-relative path it was read from so the
    page can point the reader at the file. Kills path mutants in _repo_map_artifact
    (_25/_31), _diff_impact_artifact (_25/_29), _ledger_artifact (_16/_20),
    _bundle_artifact (_26/_30)."""
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))
    _write_artifact(tmp_path, "diff-impact.json", _diff_impact_payload())
    _write_artifact(tmp_path, "risk-ledger.json", _ledger_payload())
    _write_artifact(tmp_path, "context-bundle.json", _bundle_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    by_kind = {a.kind: a for a in report.artifacts}
    assert by_kind["repo_map"].path == ".sumo-qa/repo-map.json"
    assert by_kind["diff_impact"].path == ".sumo-qa/diff-impact.json"
    assert by_kind["risk_ledger"].path == ".sumo-qa/risk-ledger.json"
    assert by_kind["context_bundle"].path == ".sumo-qa/context-bundle.json"


def test_invalid_artifact_row_keeps_path_and_real_parser_message(tmp_path):
    """An invalid (present-but-unreadable) artifact still names its path and the
    REAL parser message. Kills _artifact_from_source invalid-branch path mutants
    (_4/_8), _load_json_artifact malformed path mutants (_9/_11) and the malformed
    detail mutant (_13: `_first_line(None)` would render the literal 'None')."""
    target = tmp_path / ".sumo-qa" / "repo-map.json"
    target.parent.mkdir(parents=True)
    target.write_text("{not json", encoding="utf-8")
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "repo_map")
    assert entry.status == "invalid"
    assert entry.path == ".sumo-qa/repo-map.json"
    assert entry.detail is not None and entry.detail.startswith("[malformed_json] ")
    # The real json error carries position info ("line 1 ..."); the _first_line(None)
    # mutant would render "[malformed_json] None".
    assert "line 1" in entry.detail


def test_non_object_json_is_invalid_with_path_and_actual_type(tmp_path):
    """Top-level JSON that is not an object (a list/scalar) is a type_error invalid
    state naming its path and the ACTUAL type read. Kills _load_json_artifact
    type_error path mutants (_15/_17) and the type-name mutant (_19: would say
    'NoneType' instead of 'list')."""
    target = tmp_path / ".sumo-qa" / "diff-impact.json"
    target.parent.mkdir(parents=True)
    target.write_text("[]", encoding="utf-8")
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "diff_impact")
    assert entry.status == "invalid"
    assert entry.path == ".sumo-qa/diff-impact.json"
    assert entry.detail == "[type_error] expected a JSON object, got list"


def test_schema_drifted_artifact_keeps_path(tmp_path):
    """A loader-rejected (schema-drift) artifact still names its path. Kills
    _load_json_artifact loader-error path mutants (_22/_24)."""
    _write_artifact(tmp_path, "repo-map.json", {"schema_version": "9.9"})
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "repo_map")
    assert entry.status == "invalid"
    assert entry.path == ".sumo-qa/repo-map.json"


# --- read/write encoding is explicit lowercase utf-8 ------------------------


def test_load_json_artifact_reads_with_explicit_lowercase_utf8(tmp_path, monkeypatch):
    """Artifacts are read with encoding="utf-8" exactly — `None` silently mangles
    UTF-8 bytes under Windows cp1252. Kills _load_json_artifact _6 (None) and _8
    ("UTF-8", registry-equivalent but caught by the exact-literal assertion)."""
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))
    captured: list[object] = []
    original_read_text = Path.read_text

    def spy_read_text(self, *args, **kwargs):
        captured.append(
            kwargs.get("encoding") if "encoding" in kwargs else (args[0] if args else "MISSING")
        )
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy_read_text)
    generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert captured == ["utf-8"]


def test_write_run_summary_writes_with_explicit_lowercase_utf8(tmp_path, monkeypatch):
    """The run summary is written with encoding="utf-8" exactly. Kills
    write_run_summary _29 (None), _31 (drop) and _38 ("UTF-8")."""
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    captured: list[object] = []
    original_write_text = Path.write_text

    def spy_write_text(self, *args, **kwargs):
        captured.append(
            kwargs.get("encoding")
            if "encoding" in kwargs
            else (args[1] if len(args) > 1 else "MISSING")
        )
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", spy_write_text)
    write_run_summary(tmp_path, report)
    assert captured == ["utf-8"]


# --- write_run_summary: parents, count, pretty-print ------------------------


def test_write_run_summary_creates_nested_parents(tmp_path):
    """write_run_summary must create intermediate dirs (mkdir parents=True); with
    parents falsy a multi-level-missing root raises FileNotFoundError. Kills
    write_run_summary _4 (None), _6 (drop->False), _8 (False)."""
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    nested = tmp_path / "deep" / "nested" / "root"  # none of these dirs exist yet
    out = write_run_summary(nested, report)
    assert out.is_file()


def test_write_run_summary_counts_present_sources_not_missing(tmp_path):
    """sources_available counts PRESENT artifacts only; doubling it or counting the
    missing ones must fail. With just a ledger on disk exactly two rows are present
    (the ledger + the derived scorecard). Kills write_run_summary _12 (sum 2 each)
    and _13 (status NOT in PRESENT_STATUSES)."""
    _write_artifact(tmp_path, "risk-ledger.json", _ledger_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    write_run_summary(tmp_path, report)
    data = json.loads(
        (tmp_path / ".sumo-qa" / "qa-report-summary.json").read_text(encoding="utf-8")
    )
    assert data["sources_available"] == 2  # risk_ledger (available) + scorecard (derived)


def test_write_run_summary_is_pretty_printed_two_space_indent(tmp_path):
    """The persisted summary is indent=2 JSON (human-diffable). Kills
    write_run_summary _33 (None), _35 (drop), _36 (indent=3)."""
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    write_run_summary(tmp_path, report)
    text = (tmp_path / ".sumo-qa" / "qa-report-summary.json").read_text(encoding="utf-8")
    assert '\n  "schema_version"' in text  # exactly two leading spaces
    assert '\n   "schema_version"' not in text  # not three (indent=3)
    assert '\n"schema_version"' not in text  # not zero/compact (indent=None)


# --- _load_run_summary schema gate ------------------------------------------


def test_load_run_summary_rejects_unsupported_schema_naming_the_value(tmp_path):
    """_load_run_summary raises on a non-1.0 schema, naming the offending value so
    a future-version summary is ignored, never half-parsed. Kills the schema-gate
    mutants _6 (ValueError(None)), _7 (.get(None)), _8/_9 (wrong key -> value None)."""
    with pytest.raises(ValueError) as exc:
        _load_run_summary({"schema_version": "9.9", "readiness_state": "ready"})
    assert "9.9" in str(exc.value)


# --- _repo_map_is_stale -----------------------------------------------------


def test_missing_repo_map_is_not_stale(tmp_path):
    """A missing repo-map is not 'stale' — staleness is undetectable, not asserted.
    Kills _repo_map_is_stale _3 (None map -> return True)."""
    inputs = load_report_inputs(tmp_path)
    assert inputs.repo_map is None
    assert _repo_map_is_stale(inputs) is False


# --- repo-map stale detail + sha boundary (boundary value analysis) ---------


def test_stale_repo_map_detail_names_both_8char_shas(tmp_path):
    """The stale repo-map detail names the recorded and current commits as 8-char
    prefixes. Boundary value analysis on the [:8] slice: assert exactly 8 chars so
    [:9]/None and the ternary-precedence mutants die. Kills _repo_map_artifact
    _13/_14/_15/_16/_17/_20/_21 (and _26/_32 — the shared detail kwarg)."""
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    head = _git_init_commit(tmp_path)
    recorded = "0123456789" + "a" * 30  # distinct chars so [:8] != [:9]
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path, git_commit=recorded))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "repo_map")
    assert entry.status == "stale"
    assert entry.detail == (f"recorded commit {recorded[:8]} differs from current HEAD {head[:8]}")
    assert recorded[:9] not in entry.detail  # the [:9] mutant would include the 9th char


def test_fresh_repo_map_detail_is_not_the_stale_differs_string(tmp_path):
    """A fresh (matching-commit) repo-map must not claim the commits differ. Kills
    the ternary-precedence mutants _repo_map_artifact _18/_19 that would render the
    stale 'differs' string for a fresh map."""
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    head = _git_init_commit(tmp_path)
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path, git_commit=head))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "repo_map")
    assert entry.status == "available"
    assert "differs from current HEAD" not in (entry.detail or "")


# --- diff-impact stale detail (equivalence partitioning + decision table) ----


def test_diff_impact_inherited_stale_detail_is_exact(tmp_path):
    """When a stale repo-map taints an overlay with no warning of its own, the
    overlay's detail is the exact inherited message (case-sensitive 'HEAD'). Kills
    _diff_impact_artifact _20/_21/_22."""
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    _git_init_commit(tmp_path)
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path, git_commit="0" * 40))
    _write_artifact(tmp_path, "diff-impact.json", _diff_impact_payload())  # no own warning
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "diff_impact")
    assert entry.status == "stale"
    assert entry.detail == (
        "repo-map is stale relative to HEAD; this overlay likely predates the current state"
    )


def test_overlay_own_stale_warning_survives_even_when_map_also_stale(tmp_path):
    """An overlay with its OWN stale warning keeps that message even when the
    repo-map is also stale — the inherited string only fills in for an overlay with
    no warning of its own. Kills _diff_impact_artifact _17 (and->or)."""
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    _git_init_commit(tmp_path)
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path, git_commit="0" * 40))
    _write_artifact(tmp_path, "diff-impact.json", _diff_impact_payload(stale_warning=True))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "diff_impact")
    assert entry.status == "stale"
    assert entry.detail == "repo-map git_commit differs from HEAD"  # its OWN message
    assert "predates the current state" not in entry.detail


def test_diff_impact_multiple_stale_messages_join_with_semicolon(tmp_path):
    """Two persisted stale warnings join with '; '. Kills _diff_impact_artifact
    _38 (join separator) — observable only with more than one message."""
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))
    payload = _diff_impact_payload()
    payload["warnings"] = [
        {"kind": "stale", "message": "first stale reason"},
        {"kind": "stale", "message": "second stale reason"},
    ]
    _write_artifact(tmp_path, "diff-impact.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "diff_impact")
    assert entry.status == "stale"
    assert entry.detail == "first stale reason; second stale reason"


# --- bundle conflict detail (decision table) --------------------------------


def test_conflicted_bundle_artifact_detail_is_the_conflict_message(tmp_path):
    """A bundle whose head conflicts with the local tree is stale, and its row
    detail is the conflict message (not the source detail, not None). Kills
    _bundle_artifact _27/_31/_34 and build_report _32 (drops the conflict arg, so
    the row would read 'available')."""
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    _git_init_commit(tmp_path)
    payload = _bundle_payload()
    payload["head_sha"] = _SHA_B  # never a real local HEAD
    _write_artifact(tmp_path, "context-bundle.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "context_bundle")
    assert entry.status == "stale"
    assert entry.detail is not None
    assert entry.detail.startswith("Context bundle describes commit")


# --- readiness scorecard derivation (decision table) ------------------------


@pytest.mark.parametrize(
    "signal_field,signal_value",
    [
        ("test_evidence", {"result": "passing", "freshness": "fresh", "source": "local_git"}),
        ("ci_status", {"result": "passing", "freshness": "fresh", "source": "ci_provider"}),
        ("changed_files", [{"path": "src/x.py", "change_kind": "modified"}]),
    ],
)
def test_any_single_bundle_signal_derives_scorecard(tmp_path, signal_field, signal_value):
    """Decision table over the bundle-signal predicate: ANY one of test_evidence /
    ci_status / changed_files is enough to derive the scorecard. Kills
    _scorecard_artifact _1 (bundle->None), _2 (signal->None), _5/_6 (or->and flips),
    _9 (bool(changed_files)->bool(None))."""
    payload = {"schema_version": "1.0", "head_sha": _SHA_A, signal_field: signal_value}
    _write_artifact(tmp_path, "context-bundle.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "readiness_scorecard")
    assert entry.status == "derived", signal_field


def test_derived_scorecard_detail_is_exact(tmp_path):
    """Kills _scorecard_artifact _24 (derived detail wording)."""
    _write_artifact(tmp_path, "risk-ledger.json", _ledger_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "readiness_scorecard")
    assert entry.detail == (
        "derived in-report from the risk ledger + context bundle (readiness engine)"
    )


def test_not_derivable_scorecard_detail_is_exact(tmp_path):
    """Kills _scorecard_artifact _37 (missing detail wording)."""
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "readiness_scorecard")
    assert entry.detail == "not derivable; supply a risk ledger and/or context bundle"


def test_signals_and_scope_are_threaded_into_the_scorecard_engine(tmp_path, monkeypatch):
    """report_builder must thread coverage, mutation and scope into the QaScorecard
    engine — its docstring contract is that "the report and the scorecard can never
    disagree" and the scorecard "surfaces them as dimensions", so a future scorecard
    rule on those signals is reflected without touching the report. Spy on the
    collaborator's constructor (an interaction contract, not the report's own output)
    to kill the threading mutants in _readiness_from_scorecard (_2/_5/_6/_7/_10/_11)
    and build_report (_5/_138/_140/_141/_146/_147), which pass None instead of the
    real signal/scope."""
    import sumo_qa.report_builder as rb

    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))  # supplies the scope
    _write_artifact(tmp_path, "risk-ledger.json", _ledger_payload())
    _write_artifact(tmp_path, "coverage.json", _coverage_payload())
    _write_artifact(tmp_path, "mutation.json", _mutation_payload())

    captured: dict[str, object] = {}
    real_init = rb.QaScorecard.__init__

    def spy_init(self, *args, **kwargs):
        captured.update(kwargs)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(rb.QaScorecard, "__init__", spy_init)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)

    coverage = captured["coverage"]
    mutation = captured["mutation"]
    assert coverage is not None and coverage.line_percent == 100.0  # threaded, not None
    assert mutation is not None and mutation.survivors == 2 and mutation.killed == 145
    assert captured["scope"] == report.project.name  # the project scope, not None


# --- evidence streams: trust, ordering, threading (branch coverage) ----------


def test_all_missing_evidence_streams_are_untrustworthy(tmp_path):
    """Absent evidence streams are never trustworthy. Kills _evidence_streams _33
    and _measurement_stream _12 (missing stream trustworthy=True)."""
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    for stream in report.evidence:
        assert stream.status == "missing"
        assert stream.trustworthy is False


def test_missing_test_evidence_still_emits_ci_stream(tmp_path):
    """A bundle missing test_evidence but carrying ci_status must still emit BOTH
    streams — a `break` instead of `continue` would drop ci. Kills _evidence_streams
    _34."""
    payload = {
        "schema_version": "1.0",
        "head_sha": _SHA_A,
        "ci_status": {"result": "passing", "freshness": "fresh", "source": "ci_provider"},
    }
    _write_artifact(tmp_path, "context-bundle.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    names = [s.name for s in report.evidence]
    assert "tests" in names and "ci" in names
    assert next(s for s in report.evidence if s.name == "ci").status == "passing"


def test_bundle_evidence_threads_source_captured_at_and_detail(tmp_path):
    """A present evidence fact threads its source, captured_at and detail into the
    stream. Kills _evidence_streams _40/_41/_42 (->None) and _47/_48/_49 (drop)."""
    payload = _bundle_payload()
    payload["test_evidence"] = {
        "result": "passing",
        "freshness": "fresh",
        "source": "local_git",
        "captured_at": "2026-06-07T10:00:00+00:00",
        "detail": "42 passed in 3.1s",
    }
    _write_artifact(tmp_path, "context-bundle.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    tests = next(s for s in report.evidence if s.name == "tests")
    assert tests.source == "local_git"
    assert tests.captured_at == "2026-06-07T10:00:00+00:00"
    assert tests.detail == "42 passed in 3.1s"


def test_fresh_fact_not_in_stale_set_keeps_its_freshness(tmp_path):
    """A fresh fact NOT in the bundle's stale set keeps 'fresh' (not coerced to
    stale). Kills _evidence_streams _52 (stale-set membership inversion)."""
    _write_artifact(tmp_path, "context-bundle.json", _bundle_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    tests = next(s for s in report.evidence if s.name == "tests")
    assert tests.freshness == "fresh"


# --- measurement streams + rows (equivalence partitioning) ------------------


def test_missing_measurement_stream_detail_is_exact(tmp_path):
    """The absent coverage/mutation stream detail is exact product copy. Kills
    _measurement_stream _5/_9 (detail->None / drop) and _13/_14 (wording/case)."""
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    for name in ("coverage", "mutation"):
        stream = next(s for s in report.evidence if s.name == name)
        assert stream.detail == (
            "not supplied — optional readiness-scorecard signal (run sumo-qa-measuring-coverage)"
        )


def test_available_measurement_stream_carries_freshness(tmp_path):
    """A present coverage signal's stream reports its freshness. Kills
    _measurement_stream _18/_23 (freshness->None / drop)."""
    _write_artifact(tmp_path, "coverage.json", _coverage_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    stream = next(s for s in report.evidence if s.name == "coverage")
    assert stream.freshness == "fresh"


def test_missing_measurement_row_detail_is_exact(tmp_path):
    """Absent coverage/mutation inventory rows say exactly 'not supplied — reported,
    not gated'. Kills _measurement_artifact _19 (wording mutant slips the loose
    substring check)."""
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    for name in ("coverage", "mutation"):
        entry = next(a for a in report.artifacts if a.kind == name)
        assert entry.detail == "not supplied — reported, not gated"


def test_mutation_row_detail_lists_survivors_and_killed(tmp_path):
    """A mutation row's detail lists survivors AND killed, joined with ', '. Kills
    _mutation_measure _7 (killed-bit guard) and _11 (join separator)."""
    _write_artifact(tmp_path, "mutation.json", _mutation_payload())  # survivors=2, killed=145
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    mut = next(a for a in report.artifacts if a.kind == "mutation")
    assert mut.detail == "2 survivor(s), 145 killed, freshness=fresh — reported, not gated"


# --- readiness reasons: falsifiable counts (boundary value analysis) ---------


def test_blocked_failing_headline_counts_only_failing_rows(tmp_path):
    """The 'failing covering tests' headline counts ONLY failing non-blocker rows.
    A ledger with two failing + one passing row must read '2 of 3'. Kills
    _readiness_from_scorecard _29 (== 'failing' inverted)."""
    payload = {
        "schema_version": "1.0",
        "rows": [
            {
                "risk_id": "R1",
                "risk": "a",
                "source_anchor": "src/a.py:1",
                "test": "t::a",
                "evidence_status": "failing",
                "residual": "mitigated",
            },
            {
                "risk_id": "R2",
                "risk": "b",
                "source_anchor": "src/b.py:1",
                "test": "t::b",
                "evidence_status": "failing",
                "residual": "mitigated",
            },
            {
                "risk_id": "R3",
                "risk": "c",
                "source_anchor": "src/c.py:1",
                "test": "t::c",
                "evidence_status": "passing",
                "residual": "mitigated",
            },
        ],
    }
    _write_artifact(tmp_path, "risk-ledger.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.readiness.state == "blocked"
    assert report.readiness.reasons[0] == "risks with failing covering tests: 2 of 3 (required: 0)"


def test_insufficient_headline_counts_non_passing_rows(tmp_path):
    """The 'without fresh passing evidence' headline counts NON-passing rows. A
    ledger with two stale + one passing row must read '2 of 3'. Kills
    _readiness_from_scorecard _44 (== 'passing' inverted)."""
    payload = {
        "schema_version": "1.0",
        "rows": [
            {
                "risk_id": "R1",
                "risk": "a",
                "source_anchor": "src/a.py:1",
                "test": "t::a",
                "evidence_status": "stale",
                "residual": "mitigated",
            },
            {
                "risk_id": "R2",
                "risk": "b",
                "source_anchor": "src/b.py:1",
                "test": "t::b",
                "evidence_status": "stale",
                "residual": "mitigated",
            },
            {
                "risk_id": "R3",
                "risk": "c",
                "source_anchor": "src/c.py:1",
                "test": "t::c",
                "evidence_status": "passing",
                "residual": "mitigated",
            },
        ],
    }
    _write_artifact(tmp_path, "risk-ledger.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.readiness.state == "insufficient_evidence"
    assert (
        report.readiness.reasons[0] == "risks without fresh passing evidence: 2 of 3 (required: 0)"
    )


def test_head_conflict_surfaces_stale_bundle_readiness_reason(tmp_path):
    """A bundle whose head conflicts with the local tree adds an explicit readiness
    reason (sourced from QaScorecard with the real local head). Kills
    _readiness_from_scorecard _4/_9 (bundle dropped) and _40 (local_head_sha dropped
    from insufficiency_reasons), and build_report _137."""
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    _git_init_commit(tmp_path)
    payload = _bundle_payload()
    payload["head_sha"] = _SHA_B
    payload["ci_status"]["freshness"] = "fresh"
    _write_artifact(tmp_path, "context-bundle.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.readiness.state == "insufficient_evidence"
    assert "context bundle is stale relative to the local tree" in report.readiness.reasons


# --- build_report: validation, projection, identity -------------------------


def test_build_report_rejects_aware_datetime_with_none_utcoffset(tmp_path):
    """`now` must carry a real UTC offset; a tzinfo whose utcoffset() returns None
    is rejected too, not just a naive datetime. Kills build_report _1 (or->and) and
    _4/_5/_6 (the error message)."""
    from datetime import tzinfo

    class _NoOffset(tzinfo):
        def utcoffset(self, dt):
            return None

        def tzname(self, dt):
            return "NOOFF"

        def dst(self, dt):
            return None

    inputs = load_report_inputs(tmp_path)
    bad = datetime(2026, 6, 8, 8, 0, 0, tzinfo=_NoOffset())
    with pytest.raises(ValueError) as exc:
        build_report(inputs, now=bad, generator_version=_VERSION)
    # exact message (not a substring search) so the "XX...XX" wording mutant dies too
    assert str(exc.value) == "now must be timezone-aware"


def test_ledger_repo_map_node_id_threads_into_risk(tmp_path):
    """A ledger row's repo_map_node_id threads into the projected risk. Kills
    build_report _66 (->None) and _74 (drop)."""
    payload = _ledger_payload()
    payload["rows"][0]["repo_map_node_id"] = "src/demo.py"
    _write_artifact(tmp_path, "risk-ledger.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.risks[0].repo_map_node_id == "src/demo.py"


def test_project_name_prefers_repo_map_name(tmp_path):
    """Project name comes from the repo-map's project.name when present. Kills
    build_report _79 (repo_map->None), _80 (project_name->None), _114 (name->None),
    _119 (drop name)."""
    payload = _repo_map_payload(tmp_path)
    payload["project"]["name"] = "my-cool-project"
    _write_artifact(tmp_path, "repo-map.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.project.name == "my-cool-project"


def test_project_name_falls_back_to_dir_name_without_repo_map(tmp_path):
    """With no repo-map, project name falls back to the root directory name. Kills
    build_report _83 (fallback -> None)."""
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.project.name == tmp_path.name


def test_risk_surface_is_threaded(tmp_path):
    """The diff-impact risk_surface threads into the report. Kills build_report _106
    (drops risk_surface, which would default to [])."""
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(tmp_path))
    _write_artifact(tmp_path, "diff-impact.json", _diff_impact_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.risk_surface == ["src/demo.py"]


# --- load_report_inputs: foreign rejection + inline detail ------------------


def test_foreign_repo_map_invalid_row_keeps_path(tmp_path):
    """A foreign-root repo-map is invalid but still names its path. Kills
    load_report_inputs _21 (->None) and _23 (drop)."""
    foreign = tmp_path / "elsewhere"
    foreign.mkdir()
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(foreign))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "repo_map")
    assert entry.status == "invalid"
    assert entry.path == ".sumo-qa/repo-map.json"


def test_foreign_overlay_invalid_row_keeps_path_and_exact_detail(tmp_path):
    """The diff-impact overlay rejected in lockstep with a foreign repo-map names
    its path and the exact reason. Kills load_report_inputs _36/_38 (path) and
    _40/_42/_43 (detail wording/case)."""
    foreign = tmp_path / "elsewhere"
    foreign.mkdir()
    _write_artifact(tmp_path, "repo-map.json", _repo_map_payload(foreign))
    _write_artifact(tmp_path, "diff-impact.json", _diff_impact_payload())
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "diff_impact")
    assert entry.status == "invalid"
    assert entry.path == ".sumo-qa/diff-impact.json"
    assert entry.detail == (
        "[foreign_root] overlay derives from a repo-map describing a different "
        "repository; regenerate with `sumo-qa analyze`"
    )


def test_inline_bundle_override_detail_marks_inline_source(tmp_path):
    """An inline (caller-supplied) bundle's row carries the inline-source detail.
    Kills load_report_inputs _64 (->None) and _66 (drop)."""
    override = ContextBundle.model_validate(_bundle_payload())
    report = generate_report(
        tmp_path, generator_version=_VERSION, now=_NOW, bundle_override=override
    )
    entry = next(a for a in report.artifacts if a.kind == "context_bundle")
    assert entry.status == "inline"
    assert entry.detail == "supplied inline by the caller (not read from disk)"


# ---------------------------------------------------------------------------
# #401 — readiness honesty when the bundle HEAD cannot be verified locally
# ---------------------------------------------------------------------------
#
# Report-time HEAD detection resolves the CONTAINING repository (a report run
# from a subdirectory still sees HEAD) — unlike the repo-map scanner's exact-
# root rule, which must stay strict. When HEAD is unavailable (non-git root,
# git failure) a head_sha-bearing bundle is UNVERIFIABLE: its fresh-passing
# test/CI facts cannot support ready, so any such fact yields
# insufficient_evidence with an "unverifiable, not stale" reason. A bundle
# carrying no test/CI facts contributes nothing either way (ledger-only
# evidence keeps its contract; pinned below).


def _fresh_bundle_payload(head_sha: str) -> dict:
    payload = _bundle_payload()
    payload["head_sha"] = head_sha
    payload["ci_status"]["freshness"] = "fresh"
    return payload


def _subdir_of_git_repo(tmp_path: Path) -> tuple[Path, str]:
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    head = _git_init_commit(tmp_path)
    sub = tmp_path / "pkg"
    sub.mkdir()
    return sub, head


# --- _detect_report_head partitions: toplevel / subdir / non-git / git failure


def test_detect_report_head_at_toplevel(tmp_path):
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    head = _git_init_commit(tmp_path)
    assert _detect_report_head(tmp_path) == (head, None)


def test_detect_report_head_resolves_containing_repo_from_subdir(tmp_path):
    sub, head = _subdir_of_git_repo(tmp_path)
    assert _detect_report_head(sub) == (head, None)


def test_detect_report_head_non_git_root_reports_reason(tmp_path):
    sha, reason = _detect_report_head(tmp_path)
    assert sha is None
    assert reason  # actionable: says why HEAD was unavailable
    assert "git" in reason.lower()


def test_detect_report_head_git_failure_reports_reason(tmp_path, monkeypatch):
    import sumo_qa.report_builder as rb

    def _boom(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(rb.subprocess, "run", _boom)
    sha, reason = _detect_report_head(tmp_path)
    assert sha is None
    assert reason == "git executable not found"


def test_detect_report_head_invokes_exactly_git_rev_parse_head(tmp_path, monkeypatch):
    """Pins the argv verbatim. On a case-insensitive filesystem ``GIT`` still
    resolves to git and ``git rev-parse head`` still finds HEAD, so only an
    exact-argv spy discriminates those mutants (Linux CI would reject them)."""
    import sumo_qa.report_builder as rb

    seen: list[list[str]] = []
    real_run = rb.subprocess.run

    def _spy(cmd, *args, **kwargs):
        seen.append(list(cmd))
        return real_run(cmd, *args, **kwargs)

    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    head = _git_init_commit(tmp_path)
    monkeypatch.setattr(rb.subprocess, "run", _spy)
    assert _detect_report_head(tmp_path) == (head, None)
    assert seen == [["git", "-C", str(tmp_path), "rev-parse", "HEAD"]]


@pytest.mark.parametrize(
    "stderr,expected",
    [
        (b"fatal: not a git repository\nhint: more", "fatal: not a git repository"),
        (b"fatal: \xff undecodable but still first line", "fatal:"),  # never crashes
        (b"", "git rev-parse HEAD exited 128"),  # no stderr ⇒ exit-code fallback
        (None, "git rev-parse HEAD exited 128"),
    ],
)
def test_detect_report_head_git_error_reason_is_first_stderr_line(
    tmp_path, monkeypatch, stderr, expected
):
    import subprocess as _sp

    import sumo_qa.report_builder as rb

    def _fail(*args, **kwargs):
        raise _sp.CalledProcessError(128, ["git"], output=b"", stderr=stderr)

    monkeypatch.setattr(rb.subprocess, "run", _fail)
    sha, reason = _detect_report_head(tmp_path)
    assert sha is None
    assert reason is not None and reason.startswith(expected)
    assert "\n" not in reason


def test_detect_report_head_ignores_inherited_git_dir(tmp_path, monkeypatch):
    # Inherited GIT_DIR/GIT_WORK_TREE (pre-commit's stash mechanism) must not
    # make a non-git report root resolve some OTHER repository's HEAD.
    outer = tmp_path / "outer"
    outer.mkdir()
    (outer / "README.md").write_text("# outer\n", encoding="utf-8")
    _git_init_commit(outer)
    target = tmp_path / "plain"
    target.mkdir()
    monkeypatch.setenv("GIT_DIR", str(outer / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(outer))
    sha, reason = _detect_report_head(target)
    assert sha is None and reason


# --- the six focused scenarios from the issue ------------------------------


def test_stale_bundle_from_subdir_is_a_real_conflict_not_ready(tmp_path):
    """Scenario 1: repo at B, report root is a child dir, bundle at A ⇒ the
    containing repo's HEAD is resolved and the mismatch is a genuine conflict."""
    sub, head = _subdir_of_git_repo(tmp_path)
    _write_artifact(sub, "context-bundle.json", _fresh_bundle_payload(_SHA_A))
    report = generate_report(sub, generator_version=_VERSION, now=_NOW)
    assert report.project.head_commit == head
    assert report.readiness.state == "insufficient_evidence"
    assert "context bundle is stale relative to the local tree" in report.readiness.reasons
    assert any(_SHA_A in w and head in w for w in report.warnings)


def test_matching_bundle_from_subdir_remains_ready(tmp_path):
    """Scenario 2: same setup, bundle at B ⇒ ready-eligible."""
    sub, head = _subdir_of_git_repo(tmp_path)
    _write_artifact(sub, "context-bundle.json", _fresh_bundle_payload(head))
    report = generate_report(sub, generator_version=_VERSION, now=_NOW)
    assert report.readiness.state == "ready"
    assert report.warnings == []


def test_non_git_root_with_sha_bundle_is_unverifiable_not_ready(tmp_path):
    """Scenario 3: non-git root + fresh-passing bundle naming a head_sha ⇒
    insufficient_evidence with a local-HEAD-unavailable reason. The reason
    says UNVERIFIABLE, not stale — the bundle is not known to be out of date."""
    _write_artifact(tmp_path, "context-bundle.json", _fresh_bundle_payload(_SHA_A))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.project.head_commit is None
    assert report.readiness.state == "insufficient_evidence"
    reasons = " | ".join(report.readiness.reasons)
    assert "not verified" in reasons or "could not be determined" in reasons
    assert "stale relative to the local tree" not in reasons
    # The page-level warning names the bundle commit + why HEAD was unavailable
    # (git's own reason is threaded through so the reader knows what to fix).
    assert any(
        _SHA_A in w
        and "could not be determined" in w
        and "not verified" in w
        and "not a git repository" in w
        for w in report.warnings
    )
    assert not any("stale" in w.lower() for w in report.warnings)


def test_git_failure_with_sha_bundle_is_unverifiable_not_ready(tmp_path, monkeypatch):
    """Scenario 4: a git lookup failure yields the same unverifiable result."""
    import sumo_qa.report_builder as rb

    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    _git_init_commit(tmp_path)
    _write_artifact(tmp_path, "context-bundle.json", _fresh_bundle_payload(_SHA_A))

    def _boom(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(rb.subprocess, "run", _boom)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.project.head_commit is None
    assert report.readiness.state == "insufficient_evidence"
    assert any("not verified" in w for w in report.warnings)


def test_accepted_residual_plus_unverifiable_bundle_is_insufficient(tmp_path):
    """Scenario 5: an accepted residual cannot promote an unverifiable bundle to
    ready_with_accepted_residuals."""
    _write_artifact(tmp_path, "context-bundle.json", _fresh_bundle_payload(_SHA_A))
    _write_artifact(
        tmp_path,
        "risk-ledger.json",
        {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "rows": [
                {
                    "risk_id": "R1",
                    "risk": "demo risk",
                    "source_anchor": "src/demo.py:1",
                    "test": "tests/test_demo.py::test_demo",
                    "evidence_status": "accepted_residual",
                    "residual": "accepted",
                }
            ],
        },
    )
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.readiness.state == "insufficient_evidence"


def test_abbreviated_bundle_sha_from_subdir_remains_ready(tmp_path):
    """Scenario 6: prefix-equivalent abbreviated/full shas stay non-conflicting
    through the report-time HEAD path too."""
    sub, head = _subdir_of_git_repo(tmp_path)
    _write_artifact(sub, "context-bundle.json", _fresh_bundle_payload(head[:12]))
    report = generate_report(sub, generator_version=_VERSION, now=_NOW)
    assert report.readiness.state == "ready"


def test_bundle_without_head_sha_keeps_partial_contract_on_non_git_root(tmp_path):
    """head_sha stays optional: a partial bundle with no sha has nothing to
    verify, so the existing contract (fresh pass ⇒ ready) is unchanged."""
    payload = _fresh_bundle_payload(_SHA_A)
    del payload["head_sha"]
    _write_artifact(tmp_path, "context-bundle.json", payload)
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.readiness.state == "ready"
    assert report.warnings == []


def test_unverifiable_bundle_evidence_stream_is_not_trustworthy(tmp_path):
    """The evidence table must not vouch for a fact the verdict refuses: an
    unverifiable fresh pass renders trustworthy=False (the page reads
    "trustworthy: no"), while its freshness stays as supplied (not stale)."""
    _write_artifact(tmp_path, "context-bundle.json", _fresh_bundle_payload(_SHA_A))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    by_name = {e.name: e for e in report.evidence}
    assert by_name["tests"].trustworthy is False
    assert by_name["ci"].trustworthy is False
    assert by_name["tests"].freshness == "fresh"
    assert report.readiness.state == "insufficient_evidence"


def test_other_spawn_failure_is_unverifiable_not_a_crash(tmp_path, monkeypatch):
    """A git spawn failure other than not-found (permission denied, exec format)
    is still "HEAD unavailable": the report degrades honestly instead of raising."""
    import sumo_qa.report_builder as rb

    def _denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(rb.subprocess, "run", _denied)
    sha, reason = _detect_report_head(tmp_path)
    assert sha is None
    assert reason == "git could not be executed (PermissionError: denied)"
    _write_artifact(tmp_path, "context-bundle.json", _fresh_bundle_payload(_SHA_A))
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.readiness.state == "insufficient_evidence"
    assert any("PermissionError: denied" in w for w in report.warnings)


def test_ledger_only_evidence_keeps_its_contract_beside_a_factless_sha_bundle(tmp_path):
    """Decision-table row pinned on purpose: a bundle that names a head_sha but
    carries NO test/CI facts contributes nothing to readiness, so ledger-only
    passing evidence still derives ready (the same as with no bundle at all).
    #401 scopes the unverifiable rule to bundle-supplied evidence."""
    _write_artifact(
        tmp_path,
        "context-bundle.json",
        {
            "schema_version": "1.0",
            "head_sha": _SHA_A,
            "changed_files": [{"path": "src/demo.py", "change_kind": "modified"}],
        },
    )
    _write_artifact(
        tmp_path,
        "risk-ledger.json",
        {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "rows": [
                {
                    "risk_id": "R1",
                    "risk": "demo risk",
                    "source_anchor": "src/demo.py:1",
                    "test": "tests/test_demo.py::test_demo",
                    "evidence_status": "passing",
                    "residual": "accepted",
                }
            ],
        },
    )
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    assert report.readiness.state == "ready"
    # ...but the page still warns that the bundle itself was not verified.
    assert any("not verified" in w for w in report.warnings)


def test_unverifiable_bundle_evidence_dimension_is_not_ok(tmp_path):
    """The scorecard dimensions the report is built from must not read ok for
    bundle evidence that was never verified against the local tree."""
    from sumo_qa.scorecard_models import QaScorecard

    inputs = load_report_inputs(
        tmp_path, bundle_override=ContextBundle.model_validate(_fresh_bundle_payload(_SHA_A))
    )
    assert inputs.current_commit is None
    card = QaScorecard(context_bundle=inputs.bundle)
    by_name = {d.name: d.status for d in card.dimensions(local_head_sha=inputs.current_commit)}
    assert by_name["Test evidence"] == "unverified"
    assert by_name["CI status"] == "unverified"
