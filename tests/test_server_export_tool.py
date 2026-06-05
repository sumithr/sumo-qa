# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the sumo_qa_export_test_cases MCP tool (#148).

The tool is deterministic file/format plumbing: it validates host-supplied test
cases and renders them into json / markdown / csv. It never infers a case and is
side-effect free (returns text, never writes a file). These tests pin the tool
registration, the read-only annotation, the success shapes per format, the
markdown default, the schema-version stamp, and the error envelopes for an
unsupported format, a non-flat CSV request, and an invalid case.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from sumo_qa.server import build_mcp_server
from sumo_qa.server_schemas import ExportTestCasesOutput


@pytest.fixture
def server():
    return build_mcp_server()


@pytest.fixture
def tool(server):
    return server._tool_manager._tools["sumo_qa_export_test_cases"].fn


def _case(**overrides) -> dict:
    base = {
        "id": "TC1",
        "title": "Refund is idempotent across a retried request.",
        "preconditions": ["A charge exists with a known idempotency key."],
        "steps": ["POST the refund twice with the same idempotency key."],
        "expected_result": "The charge is refunded exactly once.",
        "priority": "high",
        "evidence_status": "planned",
    }
    base.update(overrides)
    return base


def test_tool_is_registered(server):
    assert "sumo_qa_export_test_cases" in server._tool_manager._tools


def test_export_title_param_survives_schema_title_slimming(server):
    # Regression for #148: the export-level title arg must be named
    # `export_title`, NOT `title`. The served-schema slimming pass drops every
    # dict key named `title` (Pydantic field-name echoes), so a param literally
    # named `title` would be stripped from the published inputSchema and a host
    # model could never see or fill it. Assert the real served schema exposes
    # `export_title` and carries no top-level `title` property (the bug shape).
    tools = asyncio.run(server.list_tools())
    export = next(t for t in tools if t.name == "sumo_qa_export_test_cases")
    props = (export.inputSchema or {}).get("properties", {})
    assert "export_title" in props, f"export_title missing from served schema: {sorted(props)}"
    assert "title" not in props


def test_tool_advertises_read_only_annotation(server):
    ann = server._tool_manager._tools["sumo_qa_export_test_cases"].annotations
    assert ann.readOnlyHint is True
    assert ann.destructiveHint is False
    assert ann.openWorldHint is False


def test_tool_description_is_declarative(server):
    desc = (server._tool_manager._tools["sumo_qa_export_test_cases"].description or "").lower()
    for forbidden in ("use this when", "use this before"):
        assert forbidden not in desc


def test_default_format_is_markdown(tool):
    out = tool(test_cases=[_case()])
    assert isinstance(out, ExportTestCasesOutput)
    assert out.tool == "sumo_qa_export_test_cases"
    assert out.format == "markdown"
    assert out.schema_version == "1.0"
    assert out.test_case_count == 1
    assert "**QA test cases**" in out.content


def test_json_export_returns_parseable_versioned_document(tool):
    out = tool(test_cases=[_case()], format="json", export_title="Billing")
    assert out.format == "json"
    parsed = json.loads(out.content)
    assert parsed["schema_version"] == "1.0"
    assert parsed["title"] == "Billing"
    assert parsed["test_cases"][0]["id"] == "TC1"


def test_csv_export_for_flat_outline(tool):
    out = tool(test_cases=[_case(preconditions=[], steps=[])], format="csv")
    assert out.format == "csv"
    assert out.content.startswith('"id","title",')


def test_unsupported_format_returns_error_envelope(tool):
    out = tool(test_cases=[_case()], format="xml")
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "unsupported export format" in out["error"]["message"]
    assert out["error"]["actionable_hint"]


def test_csv_for_nested_export_returns_error_envelope(tool):
    out = tool(
        test_cases=[_case(steps=["a", "b"])],
        format="csv",
    )
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "flat test-case outlines" in out["error"]["message"]


def test_invalid_priority_returns_error_envelope(tool):
    out = tool(test_cases=[_case(priority="urgent")])
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "vocab_error" in out["error"]["message"]


def test_duplicate_id_returns_error_envelope(tool):
    out = tool(test_cases=[_case(id="TC1"), _case(id="TC1")])
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "duplicate" in out["error"]["message"]


def test_missing_required_field_returns_error_envelope(tool):
    bad = _case()
    del bad["expected_result"]
    out = tool(test_cases=[bad])
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "missing_field" in out["error"]["message"]


def test_empty_export_renders_placeholder(tool):
    out = tool(test_cases=[])
    assert out.test_case_count == 0
    assert "none recorded" in out.content.lower()
