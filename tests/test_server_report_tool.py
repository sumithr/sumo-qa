# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the sumo_qa_generate_qa_report MCP tool (#157).

The tool composes the same report builder + renderer the CLI uses. Contract
pinned here: registration + writer-local annotation, side-effect-free by
default (no ``write_to`` ⇒ nothing lands on disk), relative ``write_to``
resolving against the TARGET root (not the MCP server's cwd — the scan_repo
precedent), a compact summary response that never carries the HTML body, and
error envelopes for a missing root and invalid inline ledger rows.
"""

from __future__ import annotations

import json

import pytest

from sumo_qa.server import build_mcp_server
from sumo_qa.server_schemas import GenerateQAReportOutput


@pytest.fixture
def server():
    return build_mcp_server()


@pytest.fixture
def tool(server):
    return server._tool_manager._tools["sumo_qa_generate_qa_report"].fn


def _ledger_rows() -> list[dict]:
    return [
        {
            "risk_id": "R1",
            "risk": "demo regression",
            "source_anchor": "src/demo.py:1",
            "test": "tests/test_demo.py::test_demo",
            "evidence_status": "failing",
            "residual": "blocker",
        }
    ]


def test_tool_is_registered(server):
    assert "sumo_qa_generate_qa_report" in server._tool_manager._tools


def test_tool_advertises_writer_local_annotation(server):
    ann = server._tool_manager._tools["sumo_qa_generate_qa_report"].annotations
    assert ann.read_only_hint is False
    assert ann.destructive_hint is False
    assert ann.open_world_hint is False


def test_default_call_is_side_effect_free(tool, tmp_path):
    out = tool(root=str(tmp_path))
    assert isinstance(out, GenerateQAReportOutput)
    assert out.artifact_path is None
    assert out.artifact_bytes is None
    assert not (tmp_path / ".sumo-qa").exists()


def test_write_to_also_persists_the_run_summary(tool, tmp_path):
    """A page-writing call persists the compact run summary beside it, so the
    NEXT report can render the run-over-run delta; the side-effect-free call
    (no write_to) writes neither (pinned by the side-effect-free test)."""
    out = tool(root=str(tmp_path), write_to="qa-report.html")
    assert out.artifact_path is not None
    assert (tmp_path / ".sumo-qa" / "qa-report-summary.json").is_file()


def test_summary_shape_is_compact_and_complete(tool, tmp_path):
    out = tool(root=str(tmp_path))
    assert out.readiness_state == "insufficient_evidence"
    assert isinstance(out.readiness_reasons, list) and out.readiness_reasons
    assert set(out.artifact_statuses) == {
        "repo_map",
        "diff_impact",
        "risk_ledger",
        "context_bundle",
        "readiness_scorecard",
        "coverage",
        "mutation",
    }
    assert out.risk_count == 0
    assert out.uncovered_blocker_count == 0
    # Compact contract: the HTML body never rides back to the host.
    assert "html" not in out.model_dump()


def test_relative_write_to_lands_under_target_root(tool, tmp_path, monkeypatch):
    elsewhere = tmp_path / "server-cwd"
    elsewhere.mkdir()
    target_repo = tmp_path / "repo"
    target_repo.mkdir()
    monkeypatch.chdir(elsewhere)

    out = tool(root=str(target_repo), write_to=".sumo-qa/qa-report.html")
    written = target_repo / ".sumo-qa" / "qa-report.html"
    assert written.is_file()
    assert out.artifact_path == str(written.resolve())
    assert out.artifact_bytes == written.stat().st_size
    assert out.artifact_bytes > 0
    # Nothing leaked into the server's own cwd.
    assert not (elsewhere / ".sumo-qa").exists()


def test_absolute_write_to_is_honoured(tool, tmp_path):
    target = tmp_path / "out" / "report.html"
    out = tool(root=str(tmp_path), write_to=str(target))
    assert target.is_file()
    assert out.artifact_path == str(target.resolve())
    assert target.read_text(encoding="utf-8").lower().startswith("<!doctype html>")


def test_inline_ledger_rows_flow_into_the_report(tool, tmp_path):
    out = tool(root=str(tmp_path), risk_ledger_rows=_ledger_rows())
    assert out.risk_count == 1
    assert out.uncovered_blocker_count == 1
    assert out.readiness_state == "blocked"
    # Inline-supplied rows are `inline` (never on disk), not `available`.
    assert out.artifact_statuses["risk_ledger"] == "inline"


def test_inline_context_bundle_flows_into_the_report(tool, tmp_path):
    bundle = {"test_evidence": {"result": "passing", "freshness": "fresh", "source": "local_git"}}
    out = tool(root=str(tmp_path), context_bundle=bundle)
    assert out.artifact_statuses["context_bundle"] == "inline"


def test_invalid_inline_rows_return_error_envelope(tool, tmp_path):
    out = tool(root=str(tmp_path), risk_ledger_rows=[{"risk_id": ""}])
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "error" in out and out["error"]["actionable_hint"]
    assert not (tmp_path / ".sumo-qa").exists()


def test_validation_precedes_write(tool, tmp_path):
    """The discriminating ordering case: invalid inline rows WITH a write_to
    request must return an envelope and leave nothing on disk."""
    out = tool(
        root=str(tmp_path),
        risk_ledger_rows=[{"risk_id": ""}],
        write_to=".sumo-qa/qa-report.html",
    )
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert not (tmp_path / ".sumo-qa").exists()


def test_relative_write_to_escaping_the_root_is_refused(tool, tmp_path):
    """A relative write_to is confined to the target root: `..` traversal is
    an error envelope, and nothing is written outside the repo."""
    target_repo = tmp_path / "repo"
    target_repo.mkdir()
    out = tool(root=str(target_repo), write_to="../escaped.html")
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert not (tmp_path / "escaped.html").exists()


def test_missing_root_returns_error_envelope(tool, tmp_path):
    out = tool(root=str(tmp_path / "does-not-exist"))
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert out["error"]["type"] == "NotADirectoryError"


def test_write_failure_after_validation_is_an_envelope_not_a_crash(tool, tmp_path):
    blocker = tmp_path / ".sumo-qa"
    blocker.write_text("a file where the directory must go", encoding="utf-8")
    out = tool(root=str(tmp_path), write_to=".sumo-qa/qa-report.html")
    assert isinstance(out, dict)
    assert out["isError"] is True


def test_written_report_round_trips_against_the_builder(tool, tmp_path):
    """The persisted page is the same renderer output the CLI produces — pin
    the integration by checking the readiness label matches the summary."""
    (tmp_path / "src").mkdir()
    out = tool(
        root=str(tmp_path),
        risk_ledger_rows=_ledger_rows(),
        write_to=".sumo-qa/qa-report.html",
    )
    html = (tmp_path / ".sumo-qa" / "qa-report.html").read_text(encoding="utf-8")
    assert "blocked" in html.lower()
    assert out.readiness_state == "blocked"


def test_args_round_trip_through_json(tool, tmp_path):
    """All tool args must be JSON-typed (host transport contract)."""
    rows = _ledger_rows()
    assert json.loads(json.dumps(rows)) == rows


def test_unverifiable_bundle_reads_the_same_through_the_mcp_tool(tool, tmp_path):
    """#401: the MCP report output carries the same insufficient_evidence state
    and "not verified" reason as the CLI/HTML for a non-git root whose bundle
    names a head_sha — one readiness engine, three identical projections."""
    out = tool(
        root=str(tmp_path),
        context_bundle={
            "schema_version": "1.0",
            "head_sha": "a" * 40,
            "test_evidence": {"result": "passing", "freshness": "fresh", "source": "local_git"},
        },
    )
    assert isinstance(out, GenerateQAReportOutput)
    assert out.readiness_state == "insufficient_evidence"
    reasons = " | ".join(out.readiness_reasons)
    assert "not verified" in reasons
    assert "stale relative" not in reasons
