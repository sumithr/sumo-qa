# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for ``_verify_mcp_responds`` — JSON-RPC + tools/list verification.

These exercise the hardened verification step that replaces the legacy
``'"result"' in proc.stdout`` substring check. The new behaviour:

  1. Drives an ``initialize`` + ``notifications/initialized`` + ``tools/list``
     handshake against the spawned MCP.
  2. Parses each stdout line as JSON-RPC, defensively skipping non-JSON noise.
  3. Asserts the ``initialize`` response is well-formed (jsonrpc=2.0, id=1,
     dict result, no error envelope).
  4. Asserts every entry in ``REQUIRED_TOOL_NAMES`` appears in the
     ``tools/list`` response.

Production code stays untouched outside ``installer.py``. All ``subprocess.run``
calls are mocked.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

from sumo_qa import installer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _initialize_ok() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "sumo-qa", "version": "test"},
            "capabilities": {},
        },
    }


def _tools_list_response(tool_names: list[str], req_id: int = 2) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"tools": [{"name": n} for n in tool_names]},
    }


def _proc(stdout: str, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _mcp_cmd() -> installer.McpCommand:
    return installer.McpCommand(command="/fake/sumo-qa", args=[])


# ---------------------------------------------------------------------------
# REQUIRED_TOOL_NAMES constant
# ---------------------------------------------------------------------------


def test_required_tool_names_constant_is_defined() -> None:
    """The constant exists and lists the 14 canonical sumo-qa tools."""
    assert hasattr(installer, "REQUIRED_TOOL_NAMES")
    assert isinstance(installer.REQUIRED_TOOL_NAMES, tuple)
    # 4 test-data + 6 knowledge loaders + 4 external skills = 14.
    assert len(installer.REQUIRED_TOOL_NAMES) == 14
    assert "sumo_qa_explain_test_data_requirements" in installer.REQUIRED_TOOL_NAMES
    assert "sumo_qa_load_classifications" in installer.REQUIRED_TOOL_NAMES
    assert "sumo_qa_install_external_skill" in installer.REQUIRED_TOOL_NAMES


# ---------------------------------------------------------------------------
# _verify_mcp_responds — failure paths
# ---------------------------------------------------------------------------


def test_verify_rejects_initialize_with_error_key(capsys) -> None:
    """An ``initialize`` response carrying ``error`` is rejected even when the
    stdout still contains the substring ``"result"`` (catches the legacy
    substring-check behaviour — do not weaken this payload).
    """
    # ``result: null`` forces the bytes ``"result"`` into stdout, so the OLD
    # ``'"result"' in proc.stdout`` check would have falsely passed. The new
    # shape-aware code must still reject on the ``error`` envelope.
    init_err = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": None,
        "error": {"code": -32600, "message": "bad request"},
    }
    stdout = json.dumps(init_err) + "\n"
    assert '"result"' in stdout  # guard: legacy substring check would have passed
    with patch("sumo_qa.installer.subprocess.run", return_value=_proc(stdout)):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "error" in out.lower()


def test_verify_rejects_initialize_with_wrong_id(capsys) -> None:
    """No response carries ``id == 1`` — verification fails."""
    wrong_id = {"jsonrpc": "2.0", "id": 99, "result": {"capabilities": {}}}
    stdout = json.dumps(wrong_id) + "\n"
    with patch("sumo_qa.installer.subprocess.run", return_value=_proc(stdout)):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    # The message must name the missing id.
    assert "id=1" in out or "initialize" in out.lower()


def test_verify_rejects_initialize_with_non_dict_result(capsys) -> None:
    """``result`` must be a dict; a string is rejected."""
    bad_shape = {"jsonrpc": "2.0", "id": 1, "result": "not-a-dict"}
    stdout = json.dumps(bad_shape) + "\n"
    with patch("sumo_qa.installer.subprocess.run", return_value=_proc(stdout)):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "result" in out.lower()


def test_verify_rejects_tools_list_missing_required_tools(capsys) -> None:
    """``tools/list`` missing required tools fails with a list of missing names."""
    stdout = (
        json.dumps(_initialize_ok())
        + "\n"
        + json.dumps(_tools_list_response(["sumo_qa_find_test_data"]))
        + "\n"
    )
    with patch("sumo_qa.installer.subprocess.run", return_value=_proc(stdout)):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    # At least one missing tool must be named in the failure message.
    assert "sumo_qa_explain_test_data_requirements" in out


def test_verify_rejects_tools_list_with_wrong_id(capsys) -> None:
    """A ``tools/list`` response with no id=2 is rejected (no fallback)."""
    stdout = (
        json.dumps(_initialize_ok())
        + "\n"
        + json.dumps(_tools_list_response(list(installer.REQUIRED_TOOL_NAMES), req_id=42))
        + "\n"
    )
    with patch("sumo_qa.installer.subprocess.run", return_value=_proc(stdout)):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "id=2" in out or "tools/list" in out.lower()


def test_verify_rejects_initialize_with_wrong_jsonrpc_version(capsys) -> None:
    """``jsonrpc`` field must be exactly the string ``'2.0'``."""
    bad_ver = {"jsonrpc": "1.0", "id": 1, "result": {"capabilities": {}}}
    stdout = json.dumps(bad_ver) + "\n"
    with patch("sumo_qa.installer.subprocess.run", return_value=_proc(stdout)):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "jsonrpc" in out.lower()


def test_verify_rejects_tools_list_with_error_envelope(capsys) -> None:
    """An ``error`` envelope on the tools/list response is rejected."""
    tools_err = {
        "jsonrpc": "2.0",
        "id": 2,
        "error": {"code": -32601, "message": "method not found"},
    }
    stdout = json.dumps(_initialize_ok()) + "\n" + json.dumps(tools_err) + "\n"
    with patch("sumo_qa.installer.subprocess.run", return_value=_proc(stdout)):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "tools/list" in out.lower()
    assert "error" in out.lower()


def test_verify_rejects_tools_list_when_tools_is_not_a_list(capsys) -> None:
    """``result.tools`` must be a list; a dict is rejected with a clear message."""
    bad_tools = {"jsonrpc": "2.0", "id": 2, "result": {"tools": {"oops": "not-a-list"}}}
    stdout = json.dumps(_initialize_ok()) + "\n" + json.dumps(bad_tools) + "\n"
    with patch("sumo_qa.installer.subprocess.run", return_value=_proc(stdout)):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "tools" in out.lower()


def test_verify_rejects_tools_list_non_dict_result(capsys) -> None:
    """``tools/list.result`` must be a dict containing ``tools``."""
    bad_tools = {"jsonrpc": "2.0", "id": 2, "result": "not-a-dict"}
    stdout = json.dumps(_initialize_ok()) + "\n" + json.dumps(bad_tools) + "\n"
    with patch("sumo_qa.installer.subprocess.run", return_value=_proc(stdout)):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out


def test_verify_handles_timeout(capsys) -> None:
    """``subprocess.TimeoutExpired`` is captured and surfaced."""
    with patch(
        "sumo_qa.installer.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=[], timeout=10),
    ):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "10s" in out or "timeout" in out.lower()


def test_verify_handles_empty_stdout(capsys) -> None:
    """Empty stdout (server crashed silently) is treated as failure."""
    with patch("sumo_qa.installer.subprocess.run", return_value=_proc("", stderr="boom")):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    # _dump_streams should have echoed the stderr hint for the user.
    assert "boom" in out


def test_verify_handles_malformed_json_line(capsys) -> None:
    """A non-JSON log line must not crash parsing; valid responses still apply."""
    stdout = (
        "this is not json at all\n"
        + json.dumps(_initialize_ok())
        + "\n"
        + json.dumps(_tools_list_response(list(installer.REQUIRED_TOOL_NAMES)))
        + "\n"
    )
    with patch("sumo_qa.installer.subprocess.run", return_value=_proc(stdout)):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is True
    out = capsys.readouterr().out
    assert "all required tools present" in out


def test_verify_passes_on_full_handshake(capsys) -> None:
    """All required tools present (plus extras) => True; success line printed."""
    extras = list(installer.REQUIRED_TOOL_NAMES) + ["future_tool_added_later"]
    stdout = json.dumps(_initialize_ok()) + "\n" + json.dumps(_tools_list_response(extras)) + "\n"
    with patch("sumo_qa.installer.subprocess.run", return_value=_proc(stdout)) as run:
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is True
    out = capsys.readouterr().out
    assert "MCP responded with" in out
    assert "all required tools present" in out
    # Verify the stdin payload contained all three JSON-RPC messages, one per line.
    stdin_blob = run.call_args.kwargs["input"]
    lines = [line for line in stdin_blob.split("\n") if line.strip()]
    parsed = [json.loads(line) for line in lines]
    methods = [m.get("method") for m in parsed]
    assert "initialize" in methods
    assert "notifications/initialized" in methods
    assert "tools/list" in methods


# ---------------------------------------------------------------------------
# _parse_json_rpc_lines — direct unit tests (private helper, but worth pinning)
# ---------------------------------------------------------------------------


def test_parse_json_rpc_lines_skips_empty_and_malformed() -> None:
    """Empty strings and non-JSON noise are filtered; valid JSON is parsed."""
    stdout = (
        "\n"
        "log line that isn't JSON\n"
        + json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
        + "\n"
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": []}})
        + "\n"
    )
    parsed = installer._parse_json_rpc_lines(stdout)

    assert len(parsed) == 2
    assert parsed[0]["id"] == 1
    assert parsed[1]["id"] == 2


def test_parse_json_rpc_lines_skips_non_dict_json() -> None:
    """A bare JSON array or string at the line level is skipped — only objects count."""
    stdout = '"a-string"\n[1, 2, 3]\n{"jsonrpc": "2.0", "id": 1, "result": {}}\n'
    parsed = installer._parse_json_rpc_lines(stdout)

    assert len(parsed) == 1
    assert parsed[0]["id"] == 1
