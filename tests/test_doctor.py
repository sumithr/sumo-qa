# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo-qa-doctor — the read-only setup diagnostics CLI.

Each test exercises one check or one rendering path. Production code stays
in src/sumo_qa/doctor.py; installer.py is never modified.
"""

from __future__ import annotations

import json
import os
import queue as _queue
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest

from sumo_qa import doctor

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Fake subprocess primitives, shared across MCP handshake tests
# ---------------------------------------------------------------------------


class _FakeStream:
    """Minimal stand-in for a Popen pipe. Same shape as the helper used by
    tests/test_installer_verify.py — duplicated here so doctor's tests stay
    independent of installer test internals.
    """

    def __init__(self, lines: Iterable[str] | None = None) -> None:
        self._queue: list[str] = list(lines or [])
        self.writes: list[str] = []
        self.closed = False

    def write(self, data: str) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def readline(self) -> str:
        return "" if not self._queue else self._queue.pop(0)

    def read(self, _size: int = -1) -> str:
        rest = "".join(self._queue)
        self._queue.clear()
        return rest

    def fileno(self) -> int:
        return -1


class _FakeProc:
    def __init__(
        self,
        stdout_lines: Iterable[str] | None = None,
        stderr_text: str = "",
        *,
        exited: bool = False,
        exit_code: int = 0,
    ) -> None:
        self.stdin = _FakeStream()
        self.stdout = _FakeStream(stdout_lines)
        self.stderr = _FakeStream([stderr_text] if stderr_text else [])
        self.returncode: int | None = exit_code if exited else None

    def poll(self) -> int | None:
        if not self.stdout._queue and self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        if self.returncode is None:
            self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def _ok_initialize_line() -> str:
    return json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}}) + "\n"


def _tools_list_line(names: list[str], req_id: int = 2) -> str:
    return (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": [{"name": n} for n in names]},
            }
        )
        + "\n"
    )


def test_module_exposes_main() -> None:
    assert hasattr(doctor, "main")
    assert callable(doctor.main)


def test_module_exposes_check_result_dataclass() -> None:
    cr = doctor.CheckResult(
        check_id="example",
        status="OK",
        summary="example summary",
        fix=None,
    )
    assert cr.check_id == "example"
    assert cr.status == "OK"
    assert cr.summary == "example summary"
    assert cr.fix is None


def test_check_result_dataclass_supports_details() -> None:
    cr = doctor.CheckResult(
        check_id="example",
        status="FAIL",
        summary="broken",
        fix="run X",
        details={"k": "v"},
    )
    assert cr.fix == "run X"
    assert cr.details == {"k": "v"}


def test_python_version_module_marker_used_in_tests() -> None:
    # Sanity guard: the doctor's sumo-qa version probe relies on the
    # interpreter that installed sumo-qa being the one running pytest.
    assert sys.version_info >= (3, 10)


# ---------------------------------------------------------------------------
# Check: python_version
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# MCP probe: handshake + tools_list_complete
# ---------------------------------------------------------------------------


def _mcp_cmd() -> doctor.McpCommand:
    return doctor.McpCommand(command="/fake/sumo-qa", args=[])


def test_run_mcp_probe_ok(monkeypatch) -> None:
    proc = _FakeProc([_ok_initialize_line(), _tools_list_line(list(doctor.REQUIRED_TOOL_NAMES))])
    monkeypatch.setattr(doctor.subprocess, "Popen", lambda *a, **k: proc)

    handshake, tools = doctor.run_mcp_probe(_mcp_cmd())
    assert handshake.check_id == "mcp_handshake"
    assert handshake.status == "OK"
    assert tools.check_id == "tools_list_complete"
    assert tools.status == "OK"
    assert str(len(doctor.REQUIRED_TOOL_NAMES)) in tools.summary


def test_run_mcp_probe_timeout(monkeypatch) -> None:
    # Simulate a stalled server: queue.Queue.get raises queue.Empty
    # immediately, mirroring "server never wrote a byte AND never closed
    # stdout". That's the only way _read_json_rpc_response surfaces a
    # real _VerifyTimeout rather than the EOF arm.
    proc = _FakeProc([])

    def _raise_empty(self, timeout=None):  # noqa: ARG001
        raise _queue.Empty()

    monkeypatch.setattr(doctor.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(_queue.Queue, "get", _raise_empty)

    handshake, tools = doctor.run_mcp_probe(_mcp_cmd())
    assert handshake.status == "FAIL"
    assert "timeout" in handshake.summary.lower()
    assert handshake.fix is not None and "sumo-qa-install" in handshake.fix
    assert tools.status == "FAIL"
    assert "skipped" in tools.summary.lower() or "handshake" in tools.summary.lower()


def test_run_mcp_probe_initialize_error_envelope(monkeypatch) -> None:
    err_line = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": None,
                "error": {"code": -32600, "message": "bad request"},
            }
        )
        + "\n"
    )
    proc = _FakeProc([err_line])
    monkeypatch.setattr(doctor.subprocess, "Popen", lambda *a, **k: proc)

    handshake, _ = doctor.run_mcp_probe(_mcp_cmd())
    assert handshake.status == "FAIL"
    assert "error" in handshake.summary.lower()
    assert "-32600" in handshake.summary or "bad request" in handshake.summary


def test_run_mcp_probe_nonzero_exit_with_stderr(monkeypatch) -> None:
    stderr = "ImportError: cannot import name 'foo'\n" * 20
    proc = _FakeProc([], stderr_text=stderr, exited=True, exit_code=1)
    monkeypatch.setattr(doctor.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(doctor, "_HANDSHAKE_TIMEOUT_SECONDS", 0.1)

    handshake, _ = doctor.run_mcp_probe(_mcp_cmd())
    assert handshake.status == "FAIL"
    assert "stderr" in handshake.details
    assert len(handshake.details["stderr"]) <= 300


def test_run_mcp_probe_malformed_jsonrpc_version(monkeypatch) -> None:
    bad_line = json.dumps({"jsonrpc": "1.0", "id": 1, "result": {}}) + "\n"
    proc = _FakeProc([bad_line])
    monkeypatch.setattr(doctor.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(doctor, "_HANDSHAKE_TIMEOUT_SECONDS", 0.5)

    handshake, _ = doctor.run_mcp_probe(_mcp_cmd())
    assert handshake.status == "FAIL"
    assert "jsonrpc" in handshake.summary.lower()


def test_run_mcp_probe_initialize_result_not_dict(monkeypatch) -> None:
    bad_line = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "nope"}) + "\n"
    proc = _FakeProc([bad_line])
    monkeypatch.setattr(doctor.subprocess, "Popen", lambda *a, **k: proc)

    handshake, _ = doctor.run_mcp_probe(_mcp_cmd())
    assert handshake.status == "FAIL"
    assert "result" in handshake.summary.lower()


def test_run_mcp_probe_tools_list_subset(monkeypatch) -> None:
    only_two = ["sumo_qa_find_test_data", "sumo_qa_load_classifications"]
    proc = _FakeProc([_ok_initialize_line(), _tools_list_line(only_two)])
    monkeypatch.setattr(doctor.subprocess, "Popen", lambda *a, **k: proc)

    handshake, tools = doctor.run_mcp_probe(_mcp_cmd())
    assert handshake.status == "OK"
    assert tools.status == "FAIL"
    # All missing tool names must be enumerable; the summary should at least
    # mention the missing list (the details carry the full set).
    assert "missing" in tools.summary.lower()
    assert "sumo_qa_explain_test_data_requirements" in tools.details["missing"]


def test_run_mcp_probe_tools_list_error_envelope(monkeypatch) -> None:
    tools_err = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "error": {"code": -32601, "message": "method not found"},
            }
        )
        + "\n"
    )
    proc = _FakeProc([_ok_initialize_line(), tools_err])
    monkeypatch.setattr(doctor.subprocess, "Popen", lambda *a, **k: proc)

    _, tools = doctor.run_mcp_probe(_mcp_cmd())
    assert tools.status == "FAIL"
    assert "error" in tools.summary.lower()


def test_run_mcp_probe_tools_list_result_not_dict(monkeypatch) -> None:
    bad = json.dumps({"jsonrpc": "2.0", "id": 2, "result": "nope"}) + "\n"
    proc = _FakeProc([_ok_initialize_line(), bad])
    monkeypatch.setattr(doctor.subprocess, "Popen", lambda *a, **k: proc)

    _, tools = doctor.run_mcp_probe(_mcp_cmd())
    assert tools.status == "FAIL"
    assert "result" in tools.summary.lower()


def test_run_mcp_probe_tools_list_tools_not_list(monkeypatch) -> None:
    bad = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": {"oops": True}}}) + "\n"
    proc = _FakeProc([_ok_initialize_line(), bad])
    monkeypatch.setattr(doctor.subprocess, "Popen", lambda *a, **k: proc)

    _, tools = doctor.run_mcp_probe(_mcp_cmd())
    assert tools.status == "FAIL"
    assert "list" in tools.summary.lower()


def test_run_mcp_probe_eof_before_initialize(monkeypatch) -> None:
    # Server exits immediately; reader returns ``None`` before the deadline.
    proc = _FakeProc([], exited=True, exit_code=1)
    monkeypatch.setattr(doctor.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(doctor, "_HANDSHAKE_TIMEOUT_SECONDS", 0.5)

    handshake, _ = doctor.run_mcp_probe(_mcp_cmd())
    assert handshake.status == "FAIL"


def test_run_mcp_probe_no_tools_list_response(monkeypatch) -> None:
    # initialize answers; tools/list never does (server stalls mid-call).
    proc = _FakeProc([_ok_initialize_line()])
    monkeypatch.setattr(doctor.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(doctor, "_HANDSHAKE_TIMEOUT_SECONDS", 0.2)

    handshake, tools = doctor.run_mcp_probe(_mcp_cmd())
    # initialize succeeded; the absent tools/list trips the second arm.
    assert handshake.status == "OK"
    assert tools.status == "FAIL"


def test_run_mcp_probe_initialize_error_envelope_string(monkeypatch) -> None:
    # ``error`` is not always an object — defensive arm: bare string err.
    bad = json.dumps({"jsonrpc": "2.0", "id": 1, "error": "boom"}) + "\n"
    proc = _FakeProc([bad])
    monkeypatch.setattr(doctor.subprocess, "Popen", lambda *a, **k: proc)

    handshake, _ = doctor.run_mcp_probe(_mcp_cmd())
    assert handshake.status == "FAIL"
    assert "boom" in handshake.summary


def test_run_mcp_probe_clean_exit_without_response(monkeypatch) -> None:
    # Server exits with code 0 having said nothing — distinguishes the
    # "no_response" arm (vs the "nonzero_exit" arm covered above).
    proc = _FakeProc([], exited=True, exit_code=0)
    monkeypatch.setattr(doctor.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(doctor, "_HANDSHAKE_TIMEOUT_SECONDS", 0.2)

    handshake, _ = doctor.run_mcp_probe(_mcp_cmd())
    assert handshake.status == "FAIL"
    assert handshake.details["kind"] == "no_response"


# ---------------------------------------------------------------------------
# Check: claude_code_config
# ---------------------------------------------------------------------------


def test_check_claude_code_config_not_installed(tmp_path) -> None:
    result = doctor.check_claude_code_config(home=tmp_path, system="Linux")
    assert result.check_id == "claude_code_config"
    # Neither ~/.claude/ nor the config dir exists → Claude Code not installed.
    assert result.status == "OK"
    assert "not detected" in result.summary.lower()


def test_check_claude_code_config_missing_when_claude_present(tmp_path) -> None:
    # Claude Code installed (~/.claude/ exists) but the config wasn't written.
    (tmp_path / ".claude").mkdir()
    result = doctor.check_claude_code_config(home=tmp_path, system="Linux")
    assert result.status == "FAIL"
    assert "missing" in result.summary.lower() or "not written" in result.summary.lower()
    assert result.fix is not None and "sumo-qa-install" in result.fix


def test_check_claude_code_config_present_and_resolvable(tmp_path) -> None:
    cfg_dir = tmp_path / ".config" / "claude"
    cfg_dir.mkdir(parents=True)
    (tmp_path / ".claude").mkdir()
    fake_binary = tmp_path / "bin" / "sumo-qa"
    fake_binary.parent.mkdir(parents=True)
    fake_binary.write_text("#!/bin/sh\nexit 0\n")
    fake_binary.chmod(0o755)
    (cfg_dir / "claude_desktop_config.json").write_text(
        json.dumps({"mcpServers": {"sumo-qa": {"command": str(fake_binary)}}})
    )

    result = doctor.check_claude_code_config(home=tmp_path, system="Linux")
    assert result.status == "OK"
    assert "sumo-qa" in result.summary


def test_check_claude_code_config_malformed_json(tmp_path) -> None:
    cfg_dir = tmp_path / ".config" / "claude"
    cfg_dir.mkdir(parents=True)
    (tmp_path / ".claude").mkdir()
    cfg_path = cfg_dir / "claude_desktop_config.json"
    cfg_path.write_text("{not valid json")

    result = doctor.check_claude_code_config(home=tmp_path, system="Linux")
    assert result.status == "FAIL"
    assert str(cfg_path) in result.summary
    assert result.fix is not None and "sumo-qa-install" in result.fix


def test_check_claude_code_config_no_sumo_qa_entry(tmp_path) -> None:
    cfg_dir = tmp_path / ".config" / "claude"
    cfg_dir.mkdir(parents=True)
    (tmp_path / ".claude").mkdir()
    (cfg_dir / "claude_desktop_config.json").write_text(json.dumps({"mcpServers": {}}))

    result = doctor.check_claude_code_config(home=tmp_path, system="Linux")
    assert result.status == "FAIL"
    assert "sumo-qa" in result.summary
    assert result.fix is not None


def test_check_claude_code_config_stale_binary(tmp_path) -> None:
    cfg_dir = tmp_path / ".config" / "claude"
    cfg_dir.mkdir(parents=True)
    (tmp_path / ".claude").mkdir()
    (cfg_dir / "claude_desktop_config.json").write_text(
        json.dumps({"mcpServers": {"sumo-qa": {"command": str(tmp_path / "no_such_binary")}}})
    )

    result = doctor.check_claude_code_config(home=tmp_path, system="Linux")
    assert result.status == "FAIL"
    assert "stale" in result.summary.lower() or "not resolve" in result.summary.lower()
    assert result.fix is not None and "sumo-qa-install" in result.fix


def test_check_claude_code_config_unreadable(tmp_path, monkeypatch) -> None:
    from pathlib import Path as _PathTest

    cfg_dir = tmp_path / ".config" / "claude"
    cfg_dir.mkdir(parents=True)
    (tmp_path / ".claude").mkdir()
    cfg_path = cfg_dir / "claude_desktop_config.json"
    cfg_path.write_text(json.dumps({"mcpServers": {}}))

    real_read = _PathTest.read_text

    def boom(self, *a, **k):
        if self == cfg_path:
            raise PermissionError("no read")
        return real_read(self, *a, **k)

    monkeypatch.setattr(_PathTest, "read_text", boom)
    result = doctor.check_claude_code_config(home=tmp_path, system="Linux")
    assert result.status == "FAIL"
    assert "permission" in result.summary.lower() or "unreadable" in result.summary.lower()


# ---------------------------------------------------------------------------
# Check: claude_desktop_config
# ---------------------------------------------------------------------------


def test_check_claude_desktop_config_not_installed(tmp_path) -> None:
    result = doctor.check_claude_desktop_config(home=tmp_path, system="Linux")
    assert result.check_id == "claude_desktop_config"
    assert result.status == "OK"
    assert "not detected" in result.summary.lower()


def test_check_claude_desktop_config_missing_when_dir_present(tmp_path) -> None:
    (tmp_path / ".config" / "Claude").mkdir(parents=True)
    result = doctor.check_claude_desktop_config(home=tmp_path, system="Linux")
    assert result.status == "FAIL"
    assert "missing" in result.summary.lower() or "not written" in result.summary.lower()


def test_check_claude_desktop_config_present_and_resolvable(tmp_path) -> None:
    cfg_dir = tmp_path / ".config" / "Claude"
    cfg_dir.mkdir(parents=True)
    fake_binary = tmp_path / "bin" / "sumo-qa"
    fake_binary.parent.mkdir(parents=True)
    fake_binary.write_text("#!/bin/sh\nexit 0\n")
    fake_binary.chmod(0o755)
    (cfg_dir / "claude_desktop_config.json").write_text(
        json.dumps({"mcpServers": {"sumo-qa": {"command": str(fake_binary)}}})
    )

    result = doctor.check_claude_desktop_config(home=tmp_path, system="Linux")
    assert result.status == "OK"


def test_check_claude_desktop_config_malformed(tmp_path) -> None:
    cfg_dir = tmp_path / ".config" / "Claude"
    cfg_dir.mkdir(parents=True)
    cfg_path = cfg_dir / "claude_desktop_config.json"
    cfg_path.write_text("{not json")

    result = doctor.check_claude_desktop_config(home=tmp_path, system="Linux")
    assert result.status == "FAIL"
    assert str(cfg_path) in result.summary


def test_check_claude_desktop_config_stale_binary(tmp_path) -> None:
    cfg_dir = tmp_path / ".config" / "Claude"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "claude_desktop_config.json").write_text(
        json.dumps({"mcpServers": {"sumo-qa": {"command": str(tmp_path / "no_such")}}})
    )

    result = doctor.check_claude_desktop_config(home=tmp_path, system="Linux")
    assert result.status == "FAIL"
    assert "stale" in result.summary.lower() or "not resolve" in result.summary.lower()


def test_check_claude_desktop_config_no_sumo_qa_entry(tmp_path) -> None:
    cfg_dir = tmp_path / ".config" / "Claude"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "claude_desktop_config.json").write_text(json.dumps({"mcpServers": {}}))

    result = doctor.check_claude_desktop_config(home=tmp_path, system="Linux")
    assert result.status == "FAIL"
    assert "sumo-qa" in result.summary


def test_check_claude_desktop_config_unreadable(tmp_path, monkeypatch) -> None:
    from pathlib import Path as _PathTest

    cfg_dir = tmp_path / ".config" / "Claude"
    cfg_dir.mkdir(parents=True)
    cfg_path = cfg_dir / "claude_desktop_config.json"
    cfg_path.write_text(json.dumps({"mcpServers": {}}))

    real_read = _PathTest.read_text

    def boom(self, *a, **k):
        if self == cfg_path:
            raise PermissionError("nope")
        return real_read(self, *a, **k)

    monkeypatch.setattr(_PathTest, "read_text", boom)
    result = doctor.check_claude_desktop_config(home=tmp_path, system="Linux")
    assert result.status == "FAIL"
    assert "permission" in result.summary.lower() or "unreadable" in result.summary.lower()


# ---------------------------------------------------------------------------
# CLI surface: main(), argparse, renderers
# ---------------------------------------------------------------------------


def _stub_results(*specs):
    """Build a list of CheckResults from (status, summary, fix?) tuples."""
    out = []
    for spec in specs:
        if len(spec) == 2:
            check_id, status = spec
            out.append(doctor.CheckResult(check_id, status, f"{check_id} ok"))
        elif len(spec) == 3:
            check_id, status, fix = spec
            out.append(doctor.CheckResult(check_id, status, f"{check_id} body", fix=fix))
        else:
            check_id, status, fix, details = spec
            out.append(
                doctor.CheckResult(check_id, status, f"{check_id} body", fix=fix, details=details)
            )
    return out


def test_main_exits_zero_when_all_ok(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(
        doctor,
        "_collect_checks",
        lambda **kw: _stub_results(("c1", "OK"), ("c2", "OK")),
    )
    code = doctor.main(["--workspace", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "[OK]" in out
    assert "c1" in out and "c2" in out


def test_main_exits_one_when_any_fail(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(
        doctor,
        "_collect_checks",
        lambda **kw: _stub_results(("c1", "OK"), ("c2", "FAIL", "run X")),
    )
    code = doctor.main(["--workspace", str(tmp_path)])
    assert code == 1


def test_main_exits_zero_with_warn_only(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        doctor,
        "_collect_checks",
        lambda **kw: _stub_results(("c1", "WARN", "optional")),
    )
    code = doctor.main(["--workspace", str(tmp_path)])
    assert code == 0


def test_main_human_renders_fix_line_for_failures(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(
        doctor,
        "_collect_checks",
        lambda **kw: _stub_results(("c2", "FAIL", "run X")),
    )
    doctor.main(["--workspace", str(tmp_path)])
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "Fix: run X" in out


def test_human_renderer_emits_color_when_stdout_is_tty(monkeypatch) -> None:
    """When stdout is a TTY, status tags get ANSI colors (green/yellow/red).

    Top-tier doctors (flutter doctor, brew doctor) colorise status —
    visual rank order matters when scanning ~10 checks for the one FAIL.
    """
    monkeypatch.setenv("NO_COLOR", "")  # ensure not set
    results = _stub_results(("c1", "OK"), ("c2", "WARN", "x"), ("c3", "FAIL", "y"))
    rendered = doctor._render_human(results, use_color=True)
    assert "\x1b[32m" in rendered  # green for OK
    assert "\x1b[33m" in rendered  # yellow for WARN
    assert "\x1b[31m" in rendered  # red for FAIL
    assert "\x1b[0m" in rendered  # reset after each tag


def test_human_renderer_omits_color_when_not_tty() -> None:
    """Pipe / file destination → no colors (ANSI escapes pollute log files
    and IDE captures). Matches the `isatty` contract honoured by ls, git, etc.
    """
    results = _stub_results(("c1", "OK"), ("c2", "FAIL", "y"))
    rendered = doctor._render_human(results, use_color=False)
    assert "\x1b[" not in rendered
    assert "[OK]" in rendered
    assert "[FAIL]" in rendered


def test_main_respects_no_color_env(monkeypatch, capsys, tmp_path) -> None:
    """``NO_COLOR=1`` suppresses ANSI escapes even when stdout is a TTY.

    Honours the de-facto `NO_COLOR` standard (https://no-color.org/) —
    users with screen readers and CI log captures rely on this knob.
    """
    monkeypatch.setattr(
        doctor,
        "_collect_checks",
        lambda **kw: _stub_results(("c1", "OK"), ("c2", "FAIL", "y")),
    )
    monkeypatch.setenv("NO_COLOR", "1")
    # Force the TTY detection to claim a TTY, so we're specifically
    # testing the NO_COLOR override rather than the non-TTY arm.
    monkeypatch.setattr(doctor, "_stdout_is_tty", lambda: True)
    doctor.main(["--workspace", str(tmp_path)])
    out = capsys.readouterr().out
    assert "\x1b[" not in out


def test_main_summary_line_includes_counts(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(
        doctor,
        "_collect_checks",
        lambda **kw: _stub_results(
            ("c1", "OK"), ("c2", "OK"), ("c3", "WARN", "x"), ("c4", "FAIL", "y")
        ),
    )
    doctor.main(["--workspace", str(tmp_path)])
    out = capsys.readouterr().out
    assert "2 OK" in out
    assert "1 WARN" in out
    assert "1 FAIL" in out


def test_main_json_output_parses(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(
        doctor,
        "_collect_checks",
        lambda **kw: _stub_results(("c1", "OK"), ("c2", "FAIL", "run X", {"k": "v"})),
    )
    code = doctor.main(["--json", "--workspace", str(tmp_path)])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["summary"]["fail"] == 1
    assert payload["summary"]["ok"] == 1
    assert payload["checks"][1]["check_id"] == "c2"
    assert payload["checks"][1]["status"] == "FAIL"
    assert payload["checks"][1]["fix"] == "run X"
    assert payload["checks"][1]["details"]["k"] == "v"
    assert code == 1


def test_main_host_filter_claude_code(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_collect(*, workspace, host_filter):
        captured["host_filter"] = host_filter
        captured["workspace"] = workspace
        return []

    monkeypatch.setattr(doctor, "_collect_checks", fake_collect)
    doctor.main(["--host", "claude-code", "--workspace", str(tmp_path)])
    assert captured["host_filter"] == "claude-code"
    assert captured["workspace"] == tmp_path.resolve()


def test_main_rejects_invalid_host(tmp_path) -> None:
    with pytest.raises(SystemExit):
        doctor.main(["--host", "bogus", "--workspace", str(tmp_path)])


def test_main_no_workspace_defaults_to_cwd(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_collect(*, workspace, host_filter):
        captured["workspace"] = workspace
        return []

    monkeypatch.setattr(doctor, "_collect_checks", fake_collect)
    monkeypatch.chdir(tmp_path)
    doctor.main([])
    assert captured["workspace"] == tmp_path.resolve()


def test_collect_checks_uses_filter(monkeypatch) -> None:
    # Make every per-host check return a sentinel record. Verifies the host
    # filter actually narrows the list rather than just labelling.
    def stub(name, **kw):
        return doctor.CheckResult(name, "OK", f"{name} stub")

    monkeypatch.setattr(doctor, "check_python_version", lambda: stub("python_version"))
    monkeypatch.setattr(doctor, "check_install_mode", lambda: stub("install_mode"))
    monkeypatch.setattr(doctor, "check_binary_discoverable", lambda: stub("binary_discoverable"))
    monkeypatch.setattr(
        doctor,
        "run_mcp_probe",
        lambda cmd: (
            doctor.CheckResult("mcp_handshake", "OK", "stub"),
            doctor.CheckResult("tools_list_complete", "OK", "stub"),
        ),
    )
    monkeypatch.setattr(doctor, "check_claude_code_config", lambda: stub("claude_code_config"))
    monkeypatch.setattr(
        doctor, "check_claude_desktop_config", lambda: stub("claude_desktop_config")
    )
    monkeypatch.setattr(
        doctor, "check_vscode_workspace_config", lambda workspace: stub("vscode_workspace_config")
    )
    monkeypatch.setattr(
        doctor, "check_vscode_user_misleading", lambda workspace: stub("vscode_user_misleading")
    )
    monkeypatch.setattr(doctor, "check_jetbrains_detection", lambda: stub("jetbrains_detection"))

    from pathlib import Path as _PathTest

    ids = [
        r.check_id for r in doctor._collect_checks(workspace=_PathTest("/tmp"), host_filter=None)
    ]
    assert "claude_code_config" in ids
    assert "claude_desktop_config" in ids
    assert "vscode_workspace_config" in ids
    assert "vscode_user_misleading" in ids
    assert "jetbrains_detection" in ids

    ids_cc = [
        r.check_id
        for r in doctor._collect_checks(workspace=_PathTest("/tmp"), host_filter="claude-code")
    ]
    assert "claude_code_config" in ids_cc
    assert "claude_desktop_config" not in ids_cc
    assert "vscode_workspace_config" not in ids_cc
    assert "jetbrains_detection" not in ids_cc

    ids_vs = [
        r.check_id
        for r in doctor._collect_checks(workspace=_PathTest("/tmp"), host_filter="vscode")
    ]
    assert "vscode_workspace_config" in ids_vs
    assert "vscode_user_misleading" in ids_vs
    assert "claude_code_config" not in ids_vs

    ids_jb = [
        r.check_id
        for r in doctor._collect_checks(workspace=_PathTest("/tmp"), host_filter="jetbrains")
    ]
    assert "jetbrains_detection" in ids_jb
    assert "claude_code_config" not in ids_jb


def test_resolve_mcp_command_uses_path(monkeypatch, tmp_path) -> None:
    fake = tmp_path / "sumo-qa"
    fake.write_text("#")
    fake.chmod(0o755)
    monkeypatch.setattr(
        doctor.shutil, "which", lambda name: str(fake) if name == "sumo-qa" else None
    )
    cmd = doctor._resolve_mcp_command()
    assert cmd.command == str(fake.resolve())
    assert cmd.args == []


def test_resolve_mcp_command_fallback(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    cmd = doctor._resolve_mcp_command()
    assert cmd.args == ["-m", "sumo_qa"]


def test_doctor_module_form_help_is_path_independent() -> None:
    """``python -m sumo_qa.doctor --help`` must succeed even when the
    ``sumo-qa-doctor`` console-script wrapper isn't on PATH.

    Same PATH-proof fallback as installer's ``test_installer_module_help_is_path_independent``.
    Critical because doctor is the troubleshooting step for "binary not on PATH"
    — it can't itself require the binary to be on PATH.
    """
    src_path = str(_REPO_ROOT / "src")
    existing = os.environ.get("PYTHONPATH", "")
    pythonpath = f"{src_path}{os.pathsep}{existing}" if existing else src_path

    proc = subprocess.run(
        [sys.executable, "-m", "sumo_qa.doctor", "--help"],
        cwd=str(_REPO_ROOT),
        env={**os.environ, "PYTHONPATH": pythonpath},
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert proc.returncode == 0
    assert "--json" in proc.stdout
    assert "--host" in proc.stdout
    assert "--workspace" in proc.stdout


# ---------------------------------------------------------------------------
# Check: vscode_workspace_config
# ---------------------------------------------------------------------------


def test_check_vscode_workspace_config_missing(tmp_path) -> None:
    result = doctor.check_vscode_workspace_config(workspace=tmp_path)
    assert result.check_id == "vscode_workspace_config"
    assert result.status == "FAIL"
    assert ".vscode/mcp.json" in result.summary or "mcp.json" in result.summary
    assert result.fix is not None and "sumo-qa-install" in result.fix


def test_check_vscode_workspace_config_present_and_resolvable(tmp_path) -> None:
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    fake_binary = tmp_path / "bin" / "sumo-qa"
    fake_binary.parent.mkdir()
    fake_binary.write_text("#!/bin/sh\nexit 0\n")
    fake_binary.chmod(0o755)
    (vscode / "mcp.json").write_text(
        json.dumps(
            {
                "servers": {
                    "sumo-qa": {
                        "type": "stdio",
                        "command": str(fake_binary),
                        "args": [],
                    }
                }
            }
        )
    )

    result = doctor.check_vscode_workspace_config(workspace=tmp_path)
    assert result.status == "OK"


def test_check_vscode_workspace_config_malformed(tmp_path) -> None:
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "mcp.json").write_text("{not json")

    result = doctor.check_vscode_workspace_config(workspace=tmp_path)
    assert result.status == "FAIL"
    assert "mcp.json" in result.summary


def test_check_vscode_workspace_config_unreadable(tmp_path, monkeypatch) -> None:
    from pathlib import Path as _PathTest

    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    cfg = vscode / "mcp.json"
    cfg.write_text(json.dumps({"servers": {}}))

    real_read = _PathTest.read_text

    def boom(self, *a, **k):
        if self == cfg:
            raise PermissionError("nope")
        return real_read(self, *a, **k)

    monkeypatch.setattr(_PathTest, "read_text", boom)
    result = doctor.check_vscode_workspace_config(workspace=tmp_path)
    assert result.status == "FAIL"
    assert "permission" in result.summary.lower() or "unreadable" in result.summary.lower()


def test_check_vscode_workspace_config_non_string_command(tmp_path) -> None:
    # Defensive: command is a non-string value (e.g. accidentally written as
    # an int or list). The stale-binary check must still trip cleanly.
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "mcp.json").write_text(
        json.dumps({"servers": {"sumo-qa": {"type": "stdio", "command": 42}}})
    )

    result = doctor.check_vscode_workspace_config(workspace=tmp_path)
    assert result.status == "FAIL"
    assert "stale" in result.summary.lower() or "not resolve" in result.summary.lower()


def test_check_vscode_workspace_config_no_sumo_qa_entry(tmp_path) -> None:
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "mcp.json").write_text(json.dumps({"servers": {}}))

    result = doctor.check_vscode_workspace_config(workspace=tmp_path)
    assert result.status == "FAIL"
    assert "sumo-qa" in result.summary


def test_check_vscode_workspace_config_stale_binary(tmp_path) -> None:
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    (vscode / "mcp.json").write_text(
        json.dumps(
            {
                "servers": {
                    "sumo-qa": {
                        "type": "stdio",
                        "command": str(tmp_path / "no_such"),
                        "args": [],
                    }
                }
            }
        )
    )

    result = doctor.check_vscode_workspace_config(workspace=tmp_path)
    assert result.status == "FAIL"
    assert "stale" in result.summary.lower() or "not resolve" in result.summary.lower()


def test_check_vscode_workspace_config_path_with_spaces(tmp_path) -> None:
    # Windows-style "Program Files" path-with-spaces coverage.
    workspace = tmp_path / "Workspace With Spaces"
    workspace.mkdir()
    vscode = workspace / ".vscode"
    vscode.mkdir()
    fake_binary = tmp_path / "Program Files" / "sumo-qa.exe"
    fake_binary.parent.mkdir()
    fake_binary.write_text("#!/bin/sh\nexit 0\n")
    fake_binary.chmod(0o755)
    (vscode / "mcp.json").write_text(
        json.dumps(
            {
                "servers": {
                    "sumo-qa": {
                        "type": "stdio",
                        "command": str(fake_binary),
                        "args": [],
                    }
                }
            }
        )
    )

    result = doctor.check_vscode_workspace_config(workspace=workspace)
    assert result.status == "OK"
    # The fix-command in any failure case must quote the workspace path
    # — we just check the OK summary embeds the spaced path correctly.
    assert "Workspace With Spaces" in result.summary


# ---------------------------------------------------------------------------
# Check: vscode_user_misleading
# ---------------------------------------------------------------------------


def test_check_vscode_user_misleading_absent(tmp_path) -> None:
    result = doctor.check_vscode_user_misleading(home=tmp_path, workspace=tmp_path / "ws")
    assert result.check_id == "vscode_user_misleading"
    assert result.status == "OK"


def test_check_vscode_user_misleading_present_warn(tmp_path) -> None:
    user_dir = tmp_path / ".vscode"
    user_dir.mkdir()
    (user_dir / "mcp.json").write_text(json.dumps({"servers": {}}))
    workspace = tmp_path / "ws"
    workspace.mkdir()

    result = doctor.check_vscode_user_misleading(home=tmp_path, workspace=workspace)
    assert result.status == "WARN"
    assert "user" in result.summary.lower() and "workspace" in result.summary.lower()
    assert result.fix is not None


# ---------------------------------------------------------------------------
# Check: jetbrains_detection
# ---------------------------------------------------------------------------


def test_check_jetbrains_detection_no_config_root(tmp_path) -> None:
    result = doctor.check_jetbrains_detection(home=tmp_path, system="Linux")
    assert result.check_id == "jetbrains_detection"
    assert result.status == "OK"
    assert "not detected" in result.summary.lower()


def test_check_jetbrains_detection_present(tmp_path) -> None:
    jb = tmp_path / ".config" / "JetBrains" / "IntelliJIdea2026.1" / "options"
    jb.mkdir(parents=True)

    result = doctor.check_jetbrains_detection(home=tmp_path, system="Linux")
    assert result.status == "OK"
    assert "IntelliJIdea" in result.summary
    # Manual-setup hint — UI add isn't auto-configurable.
    assert result.fix is not None and "Settings" in result.fix


def test_check_jetbrains_detection_config_root_but_no_supported_ide(tmp_path) -> None:
    # Root exists but no supported IDE installation under it.
    (tmp_path / ".config" / "JetBrains").mkdir(parents=True)
    result = doctor.check_jetbrains_detection(home=tmp_path, system="Linux")
    assert result.status == "OK"
    assert "no supported" in result.summary.lower() or "no IDE" in result.summary.lower()


def test_check_jetbrains_detection_darwin(tmp_path) -> None:
    jb = tmp_path / "Library" / "Application Support" / "JetBrains" / "PyCharm2026.1" / "options"
    jb.mkdir(parents=True)

    result = doctor.check_jetbrains_detection(home=tmp_path, system="Darwin")
    assert result.status == "OK"
    assert "PyCharm" in result.summary


# ---------------------------------------------------------------------------
# Check: binary_discoverable
# ---------------------------------------------------------------------------


def test_check_binary_discoverable_on_path(monkeypatch, tmp_path) -> None:
    fake_binary = tmp_path / "sumo-qa"
    fake_binary.write_text("#!/bin/sh\nexit 0\n")
    fake_binary.chmod(0o755)
    monkeypatch.setattr(
        doctor.shutil, "which", lambda name: str(fake_binary) if name == "sumo-qa" else None
    )

    result = doctor.check_binary_discoverable()
    assert result.check_id == "binary_discoverable"
    assert result.status == "OK"
    assert "PATH" in result.summary
    assert result.details["mode"] == "path"
    assert result.details["binary_path"] == str(fake_binary.resolve())
    assert result.fix is None


def test_check_binary_discoverable_fallback_to_module(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)

    result = doctor.check_binary_discoverable()
    # Module-form is a supported invocation — OK, not FAIL.
    assert result.status == "OK"
    assert "python -m sumo_qa" in result.summary or "-m sumo_qa" in result.summary
    assert result.details["mode"] == "module"
    # A fix is offered for hosts that strictly need a binary path.
    assert result.fix is not None


# ---------------------------------------------------------------------------
# Check: install_mode
# ---------------------------------------------------------------------------


def test_check_install_mode_editable(tmp_path) -> None:
    # Editable layout: skills/ at repo root, no bundled _data/skills/.
    module_dir = tmp_path / "src" / "sumo_qa"
    module_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    (tmp_path / "skills").mkdir()

    result = doctor.check_install_mode(module_dir=module_dir)
    assert result.check_id == "install_mode"
    assert result.status == "OK"
    assert "editable" in result.summary.lower()
    assert result.details["mode"] == "editable"
    assert result.details["skills_path"] == str(tmp_path / "skills")


def test_check_install_mode_wheel(tmp_path) -> None:
    # Wheel layout: bundled skills inside the module directory.
    module_dir = tmp_path / "site-packages" / "sumo_qa"
    bundled = module_dir / "_data" / "skills"
    bundled.mkdir(parents=True)

    result = doctor.check_install_mode(module_dir=module_dir)
    assert result.status == "OK"
    assert "wheel" in result.summary.lower()
    assert result.details["mode"] == "wheel"
    assert result.details["skills_path"] == str(bundled)


def test_check_install_mode_defaults_to_actual_module() -> None:
    # Smoke: with no arg, checks the live install and returns one of the
    # known modes. The doctor's own runtime should classify cleanly.
    result = doctor.check_install_mode()
    assert result.status == "OK"
    assert result.details["mode"] in {"wheel", "editable"}


# ---------------------------------------------------------------------------
# Check: python_version
# ---------------------------------------------------------------------------


def test_check_python_version_reports_interpreter_and_package() -> None:
    from importlib.metadata import version as _pkg_version

    result = doctor.check_python_version()
    assert result.check_id == "python_version"
    assert result.status == "OK"
    py = ".".join(str(p) for p in sys.version_info[:3])
    assert py in result.summary
    assert _pkg_version("sumo-qa") in result.summary
    assert result.fix is None
    assert result.details["python_version"] == py
    assert result.details["sumo_qa_version"] == _pkg_version("sumo-qa")
