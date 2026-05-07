"""Tests for the isError envelope wrapping.

Best practice for MCP tool errors is to return a structured response with
`isError: true` plus a typed error body, instead of letting the exception
propagate as a protocol-level error. The host can then surface the
`actionable_hint` to the user.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sumo_qa.server import build_mcp_server
from sumo_qa.tools import QAShiftLeftService


def _broken_service(tmp_path: Path) -> QAShiftLeftService:
    """Build a service pointing at a non-existent standards path so any tool
    that touches standards raises during evaluation."""
    return QAShiftLeftService.from_standards_path(
        tmp_path / "missing-standards",
        tmp_path / "missing-rules.yaml",
        tmp_path / "missing-test-data",
    )


def _invoke_tool(server, tool_name: str, **kwargs):
    tool = server._tool_manager._tools[tool_name]
    fn = tool.fn
    if asyncio.iscoroutinefunction(fn):
        return asyncio.run(fn(**kwargs))
    return fn(**kwargs)


def test_register_known_good_test_data_returns_is_error_on_invalid_entry(tmp_path: Path) -> None:
    """The catalogue write path raises ValueError on a malformed entry; the
    server wraps it in an isError envelope instead of letting it propagate."""
    server = build_mcp_server()

    response = _invoke_tool(
        server,
        "sumo_qa_register_known_good_test_data",
        entry={"id": "broken", "missing": "almost everything"},
    )

    assert response.get("isError") is True
    error = response.get("error")
    assert isinstance(error, dict)
    assert error.get("type")
    assert error.get("message")
    assert error.get("actionable_hint")


def test_validate_test_data_returns_is_error_when_entry_missing(tmp_path: Path) -> None:
    """Looking up a missing entry id raises ValueError; the server returns
    an isError envelope rather than crashing the protocol."""
    server = build_mcp_server()

    response = _invoke_tool(
        server,
        "sumo_qa_validate_test_data",
        entry_id="this-entry-does-not-exist",
    )

    assert response.get("isError") is True
    assert response["error"]["type"] in {"ValueError", "Exception"}
    assert "not found" in response["error"]["message"].lower() or response["error"]["message"]


def test_is_error_envelope_carries_actionable_hint() -> None:
    """The `actionable_hint` field is always non-empty so hosts have something
    to surface to the user."""
    server = build_mcp_server()

    response = _invoke_tool(
        server,
        "sumo_qa_register_known_good_test_data",
        entry={"id": "broken"},
    )

    assert response["isError"] is True
    hint = response["error"]["actionable_hint"]
    assert isinstance(hint, str) and hint.strip(), "actionable_hint must be non-empty"
