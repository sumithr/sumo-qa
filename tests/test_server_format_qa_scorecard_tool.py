# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the sumo_qa_format_qa_scorecard MCP tool (#151).

The tool composes a readiness scorecard from already-produced evidence and
DERIVES the recommendation — it never infers risk and never lets the caller
assert "ready". These tests pin registration, the read-only annotation, the
derived verdict for each load-bearing state, the not-measured / stale-evidence
surfacing, the JSON-able snapshot, and the error envelope.
"""

from __future__ import annotations

import json

import pytest

from sumo_qa.server import build_mcp_server
from sumo_qa.server_schemas import FormatQaScorecardOutput


@pytest.fixture
def server():
    return build_mcp_server()


@pytest.fixture
def tool(server):
    return server._tool_manager._tools["sumo_qa_format_qa_scorecard"].fn


def _row(**overrides) -> dict:
    base = {
        "risk_id": "R1",
        "risk": "Refund issued twice on retry.",
        "source_anchor": "refund.py:47",
        "test": "tests/test_refund.py::test_idempotent",
        "evidence_status": "passing",
        "residual": "open",
    }
    base.update(overrides)
    return base


def _fresh_tests() -> dict:
    return {"test_evidence": {"result": "passing", "freshness": "fresh", "source": "local_git"}}


def test_tool_is_registered(server):
    assert "sumo_qa_format_qa_scorecard" in server._tool_manager._tools


def test_tool_advertises_read_only_annotation(server):
    ann = server._tool_manager._tools["sumo_qa_format_qa_scorecard"].annotations
    assert ann.read_only_hint is True
    assert ann.destructive_hint is False
    assert ann.open_world_hint is False


def test_tool_description_is_declarative(server):
    desc = (server._tool_manager._tools["sumo_qa_format_qa_scorecard"].description or "").lower()
    for forbidden in ("use this when", "use this before"):
        assert forbidden not in desc


def test_uncovered_blocker_is_blocked(tool):
    out = tool(ledger_rows=[_row(evidence_status="failing", residual="blocker")])
    assert isinstance(out, FormatQaScorecardOutput)
    assert out.recommendation == "blocked"
    assert out.is_ready is False
    assert out.uncovered_blocker_count == 1
    assert "**BLOCKED**" in out.markdown


def test_fresh_passing_is_ready(tool):
    out = tool(
        ledger_rows=[_row(evidence_status="passing", residual="open")],
        context_bundle=_fresh_tests(),
    )
    assert out.recommendation == "ready"
    assert out.is_ready is True


def test_empty_payload_is_insufficient(tool):
    out = tool()
    assert isinstance(out, FormatQaScorecardOutput)
    assert out.recommendation == "insufficient_evidence"
    assert out.is_ready is False


def test_stale_evidence_is_surfaced(tool):
    out = tool(
        context_bundle={
            "ci_status": {"result": "passing", "freshness": "stale", "source": "ci_provider"}
        }
    )
    assert out.recommendation == "insufficient_evidence"
    assert "CI status" in out.stale_evidence


def test_not_measured_lists_absent_signals(tool):
    out = tool(context_bundle=_fresh_tests())
    assert "Coverage" in out.not_measured
    assert "Mutation" in out.not_measured


def test_coverage_and_mutation_do_not_outweigh_blocker(tool):
    out = tool(
        ledger_rows=[_row(evidence_status="failing", residual="blocker")],
        coverage={"line_percent": 99.0, "freshness": "fresh"},
        mutation={"survivors": 0, "killed": 200, "freshness": "fresh"},
    )
    assert out.recommendation == "blocked"


def test_serialized_snapshot_is_json_able(tool):
    out = tool(ledger_rows=[_row(evidence_status="failing", residual="blocker")])
    assert json.loads(json.dumps(out.serialized)) == out.serialized
    assert out.serialized["recommendation"] == "blocked"


def test_invalid_coverage_returns_error_envelope(tool):
    out = tool(coverage={"line_percent": 150.0})
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "value_error" in out["error"]["message"]
    assert out["error"]["actionable_hint"]


def test_invalid_ledger_row_returns_error_envelope(tool):
    out = tool(ledger_rows=[_row(evidence_status="probably_fine")])
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "vocab_error" in out["error"]["message"]


def test_sha_bundle_without_local_head_is_unverifiable_not_ready(tool):
    """#401: through the MCP tool, a bundle naming a head_sha with no
    ``local_head_sha`` supplied is unverifiable: insufficient_evidence with its
    own reason, an ``unverified`` dimension (never ok, never stale), and an
    empty ``stale_evidence`` list because the bundle is not known-stale."""
    bundle = {"head_sha": "a" * 40, **_fresh_tests()}
    out = tool(context_bundle=bundle)
    assert isinstance(out, FormatQaScorecardOutput)
    assert out.recommendation == "insufficient_evidence"
    assert out.is_ready is False
    assert "not verified against the local tree" in out.markdown
    assert "stale relative" not in out.markdown
    statuses = {d["name"]: d["status"] for d in out.serialized["dimensions"]}
    assert statuses["Test evidence"] == "unverified"
    assert out.stale_evidence == []
    # Control: the same bundle with the live head supplied is ready.
    ok = tool(context_bundle=bundle, local_head_sha="a" * 40)
    assert ok.recommendation == "ready"
