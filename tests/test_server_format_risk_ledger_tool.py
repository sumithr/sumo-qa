# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the sumo_qa_format_risk_ledger MCP tool (#144).

The tool is file/format plumbing: it validates host-supplied risk rows and
renders the structured markdown appendix + compact summary. It never infers
risk. These tests pin the tool registration, the read-only annotation, the
success shape, the uncovered-blocker count, truncation, and the error envelope.
"""

from __future__ import annotations

import pytest

from sumo_qa.server import build_mcp_server
from sumo_qa.server_schemas import FormatRiskLedgerOutput


@pytest.fixture
def server():
    return build_mcp_server()


@pytest.fixture
def tool(server):
    return server._tool_manager._tools["sumo_qa_format_risk_ledger"].fn


def _row(**overrides) -> dict:
    base = {
        "risk_id": "R1",
        "risk": "Refund issued twice on retry.",
        "source_anchor": "refund.py:47",
        "test": "tests/test_refund.py::test_idempotent",
        "evidence_status": "passing",
        "residual": "accepted",
    }
    base.update(overrides)
    return base


def test_tool_is_registered(server):
    assert "sumo_qa_format_risk_ledger" in server._tool_manager._tools


def test_tool_advertises_read_only_annotation(server):
    ann = server._tool_manager._tools["sumo_qa_format_risk_ledger"].annotations
    assert ann.readOnlyHint is True
    assert ann.destructiveHint is False
    assert ann.openWorldHint is False


def test_tool_description_is_declarative(server):
    desc = (server._tool_manager._tools["sumo_qa_format_risk_ledger"].description or "").lower()
    for forbidden in ("use this when", "use this before"):
        assert forbidden not in desc


def test_success_returns_structured_output(tool):
    out = tool(rows=[_row()])
    assert isinstance(out, FormatRiskLedgerOutput)
    assert out.tool == "sumo_qa_format_risk_ledger"
    assert out.row_count == 1
    assert out.uncovered_blocker_count == 0
    assert "**Risk ledger**" in out.markdown
    assert "R1" in out.markdown
    assert out.compact_summary.startswith("Risk ledger: 1 risks")
    assert out.truncated is False


def test_uncovered_blocker_is_counted(tool):
    out = tool(
        rows=[
            _row(risk_id="R1", evidence_status="failing", residual="blocker"),
            _row(risk_id="R2"),
        ]
    )
    assert out.uncovered_blocker_count == 1


def test_truncation_flag_and_notice(tool):
    rows = [_row(risk_id=f"R{i}") for i in range(1, 6)]
    out = tool(rows=rows, max_rows=2)
    assert out.truncated is True
    assert "3 more" in out.markdown
    assert out.row_count == 5


def test_empty_rows_returns_placeholder(tool):
    out = tool(rows=[])
    assert out.row_count == 0
    assert out.uncovered_blocker_count == 0
    assert "no risks recorded" in out.markdown.lower()
    assert out.compact_summary == "Risk ledger: 0 risks."


def test_invalid_evidence_status_returns_error_envelope(tool):
    out = tool(rows=[_row(evidence_status="probably_fine")])
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "vocab_error" in out["error"]["message"]
    assert out["error"]["actionable_hint"]


def test_duplicate_risk_id_returns_error_envelope(tool):
    out = tool(rows=[_row(risk_id="R1"), _row(risk_id="R1")])
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "duplicate" in out["error"]["message"]


def test_missing_required_field_returns_error_envelope(tool):
    bad = _row()
    del bad["residual"]
    out = tool(rows=[bad])
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "missing_field" in out["error"]["message"]
