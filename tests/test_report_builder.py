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
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sumo_qa.context_bundle_models import ContextBundle
from sumo_qa.ledger_models import LEDGER_SCHEMA_VERSION, RiskLedger, RiskLedgerRow
from sumo_qa.report_builder import build_report, generate_report, load_report_inputs

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
    assert report.readiness.state == "incomplete"
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
    assert report.readiness.state == "incomplete"
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
    assert report.readiness.state == "incomplete"


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


def test_present_scorecard_file_is_unsupported_until_151(tmp_path):
    _write_artifact(tmp_path, "readiness-scorecard.json", {"anything": 1})
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "readiness_scorecard")
    assert entry.status == "invalid"
    assert entry.detail is not None and "#151" in entry.detail


def test_absent_scorecard_names_the_pending_issue(tmp_path):
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "readiness_scorecard")
    assert entry.status == "missing"
    assert entry.detail is not None and "#151" in entry.detail


def test_coverage_mutation_names_the_pending_issue(tmp_path):
    report = generate_report(tmp_path, generator_version=_VERSION, now=_NOW)
    entry = next(a for a in report.artifacts if a.kind == "coverage_mutation")
    assert entry.status == "missing"
    assert entry.detail is not None and "#147" in entry.detail


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
    assert report.readiness.state == "stale_evidence"


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
    assert report.readiness.state == "stale_evidence"


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
