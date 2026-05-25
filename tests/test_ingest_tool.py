# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the sumo_qa_ingest_knowledge_pack MCP tool wrapper."""

import asyncio
import inspect

from sumo_qa.server import build_mcp_server


def _invoke_tool(server, tool_name: str, **kwargs):
    tool = server._tool_manager._tools[tool_name]
    fn = tool.fn
    if inspect.iscoroutinefunction(fn):
        return asyncio.run(fn(**kwargs))
    return fn(**kwargs)


def test_ingest_tool_is_registered():
    server = build_mcp_server()
    assert "sumo_qa_ingest_knowledge_pack" in server._tool_manager._tools


def test_ingest_tool_ingests_into_project_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "principles.md"
    src.write_text("# P\n\nbody\n", encoding="utf-8")
    server = build_mcp_server()
    result = _invoke_tool(server, "sumo_qa_ingest_knowledge_pack", source=str(src), scope="project")
    assert result["status"] == "ingested"
    assert (tmp_path / ".sumo-qa" / "knowledge" / "principles.md").is_file()


def test_ingest_tool_returns_is_error_on_invalid_content(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "principles.md"
    src.write_text("   \n", encoding="utf-8")  # empty -> validation error
    server = build_mcp_server()
    result = _invoke_tool(server, "sumo_qa_ingest_knowledge_pack", source=str(src), scope="project")
    assert result.get("isError") is True
    assert result["error"]["actionable_hint"]
    assert not (tmp_path / ".sumo-qa").exists()


def test_ingest_tool_unsupported_source_routes_to_converter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "deck.pdf"
    src.write_bytes(b"%PDF")
    server = build_mcp_server()
    result = _invoke_tool(server, "sumo_qa_ingest_knowledge_pack", source=str(src), scope="project")
    assert result["status"] == "unsupported_source"
    assert "find-skills" in result["guidance"]
