# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo-qa-doctor — the read-only setup diagnostics CLI.

Each test exercises one check or one rendering path. Production code stays
in src/sumo_qa/doctor.py; installer.py is never modified.
"""

from __future__ import annotations

import json
import queue as _queue
import sys
from collections.abc import Iterable

from sumo_qa import doctor

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
