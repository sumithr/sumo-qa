# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable
from pathlib import Path
from unittest.mock import patch

import pytest

from sumo_qa import installer


@pytest.fixture(autouse=True)
def _select_always_ready(monkeypatch):
    """See tests/test_installer_verify.py — patches the production select
    branch so FakeStream's dummy fileno is never touched by the OS."""

    def _ready(rlist, wlist, xlist, timeout=None):  # noqa: ARG001
        return list(rlist), [], []

    monkeypatch.setattr(installer.select, "select", _ready)


def _ok(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=b"")


# ---------------------------------------------------------------------------
# Fake Popen used by tests that exercise _verify_mcp_responds end-to-end via
# main(). Mirrors tests/test_installer_verify.py's _FakeProc but kept local
# here so this file is self-contained.
# ---------------------------------------------------------------------------


class _FakeStream:
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
        if not self._queue:
            return ""
        return self._queue.pop(0)

    def read(self, _size: int = -1) -> str:
        rest = "".join(self._queue)
        self._queue.clear()
        return rest

    def fileno(self) -> int:
        # Returning a dummy fd lets the production code take the
        # select-on-POSIX branch (the real install-smoke path) while tests
        # patch ``select.select`` to control timing.
        return -1


class _FakeProc:
    def __init__(
        self,
        stdout_lines: Iterable[str] | None = None,
        stderr_text: str = "",
    ) -> None:
        self.stdin = _FakeStream()
        self.stdout = _FakeStream(stdout_lines)
        self.stderr = _FakeStream([stderr_text] if stderr_text else [])
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        if not self.stdout._queue:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode


def _handshake_lines() -> list[str]:
    """Lines the verifier expects: initialize + tools/list with all required tools."""
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "sumo-qa", "version": "test"},
            "capabilities": {},
        },
    }
    tools = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {"tools": [{"name": n} for n in installer.REQUIRED_TOOL_NAMES]},
    }
    return [json.dumps(init) + "\n", json.dumps(tools) + "\n"]


def _handshake_proc() -> _FakeProc:
    return _FakeProc(_handshake_lines())


def test_register_runs_remove_then_add_with_user_scope() -> None:
    mcp_cmd = installer.McpCommand(command="/abs/path/to/sumo-qa", args=[])
    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()) as run,
    ):
        msg = installer._register_claude_code_mcp(mcp_cmd)

    assert run.call_count == 2
    remove_args = run.call_args_list[0].args[0]
    add_args = run.call_args_list[1].args[0]
    assert remove_args == ["/usr/local/bin/claude", "mcp", "remove", "sumo-qa", "-s", "user"]
    assert add_args == [
        "/usr/local/bin/claude",
        "mcp",
        "add",
        "-s",
        "user",
        "sumo-qa",
        "--",
        mcp_cmd.command,
    ]
    assert "registered" in msg
    assert mcp_cmd.command in msg


def test_register_includes_module_args_after_double_dash() -> None:
    """Module-fallback invocation must pass `-m sumo_qa` to claude mcp add via `--`."""
    import sys

    mcp_cmd = installer.McpCommand(command=sys.executable, args=["-m", "sumo_qa"])
    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()) as run,
    ):
        installer._register_claude_code_mcp(mcp_cmd)

    add_args = run.call_args_list[1].args[0]
    assert add_args == [
        "/usr/local/bin/claude",
        "mcp",
        "add",
        "-s",
        "user",
        "sumo-qa",
        "--",
        sys.executable,
        "-m",
        "sumo_qa",
    ]


def test_register_skips_when_claude_cli_not_on_path() -> None:
    mcp_cmd = installer.McpCommand(command="/abs/sumo-qa", args=[])
    with (
        patch("sumo_qa.installer.shutil.which", return_value=None),
        patch("sumo_qa.installer.subprocess.run") as run,
    ):
        msg = installer._register_claude_code_mcp(mcp_cmd)

    assert run.call_count == 0
    assert "claude CLI not on PATH" in msg


def test_register_tolerates_remove_failure_and_still_adds() -> None:
    """The first `remove` may fail if no entry exists. That MUST NOT block the add."""

    def run_side_effect(cmd, **kwargs):
        if "remove" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=1, stderr=b"not found")
        return _ok()

    mcp_cmd = installer.McpCommand(command="/abs/sumo-qa", args=[])
    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", side_effect=run_side_effect) as run,
    ):
        msg = installer._register_claude_code_mcp(mcp_cmd)

    assert run.call_count == 2
    assert "registered" in msg


def test_register_surfaces_add_failure_in_message() -> None:
    def run_side_effect(cmd, **kwargs):
        if "add" in cmd:
            raise subprocess.CalledProcessError(
                returncode=2, cmd=cmd, stderr=b"some error from claude"
            )
        return _ok()

    mcp_cmd = installer.McpCommand(command="/abs/sumo-qa", args=[])
    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", side_effect=run_side_effect),
    ):
        msg = installer._register_claude_code_mcp(mcp_cmd)

    assert "claude mcp add failed" in msg
    assert "some error from claude" in msg


# ---------------------------------------------------------------------------
# HostResult.render() — lines 96-105
# ---------------------------------------------------------------------------


def test_host_result_render_configured() -> None:
    """HostResult.render() returns [OK] when configured=True."""
    r = installer.HostResult("Test Host")
    r.configured = True
    r.message = "all good"
    assert "[OK]" in r.render()
    assert "all good" in r.render()


def test_host_result_render_detected_not_configured() -> None:
    """HostResult.render() returns [...] when detected=True but configured=False."""
    r = installer.HostResult("Test Host")
    r.detected = True
    r.message = "found but not set up"
    assert "[...]" in r.render()


def test_host_result_render_not_detected() -> None:
    """HostResult.render() returns [skip] when not detected."""
    r = installer.HostResult("Test Host")
    r.message = "not found"
    assert "[skip]" in r.render()


def test_host_result_render_with_followup() -> None:
    """HostResult.render() appends followup text when set."""
    r = installer.HostResult("Test Host")
    r.configured = True
    r.message = "done"
    r.followup = "  Follow-up instructions."
    rendered = r.render()
    assert "Follow-up instructions." in rendered


# ---------------------------------------------------------------------------
# _setup_claude_code — Linux branch (line 280), not-detected early return
# (lines 285-286), invalid JSON config (lines 313-319)
# ---------------------------------------------------------------------------


def test_setup_claude_code_not_detected_when_neither_dir_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """_setup_claude_code() returns early with 'not detected' when neither
    ~/.claude nor config_dir exists (lines 285-286)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    # Do NOT create ~/.claude or ~/.config/claude — both missing.

    result = installer._setup_claude_code(
        installer.McpCommand(command="/usr/local/bin/sumo-qa", args=[]), "Darwin"
    )

    assert result.detected is False
    assert "not detected" in result.message


def test_setup_claude_code_on_linux_uses_config_home(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """_setup_claude_code() reaches the else: branch for Linux (line 280)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    # Create the config dir to bypass early-return.
    config_dir = home / ".config" / "claude"
    config_dir.mkdir(parents=True)

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()),
    ):
        result = installer._setup_claude_code(
            installer.McpCommand(command="/usr/local/bin/sumo-qa", args=[]), "Linux"
        )

    assert result.configured is True


def test_setup_claude_code_surfaces_json_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """_setup_claude_code() returns early with an error message when
    claude_desktop_config.json exists but is invalid JSON (lines 313-319)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    config_dir = home / ".config" / "claude"
    config_dir.mkdir(parents=True)
    # Write broken JSON.
    (config_dir / "claude_desktop_config.json").write_text("{invalid json", encoding="utf-8")

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()),
    ):
        result = installer._setup_claude_code(
            installer.McpCommand(command="/usr/local/bin/sumo-qa", args=[]), "Darwin"
        )

    assert result.configured is False
    assert "invalid JSON" in result.message


# ---------------------------------------------------------------------------
# _verify_mcp_responds tests live in tests/test_installer_verify.py — the
# new JSON-RPC + tools/list verification surface is exercised there.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# main() — lines 109-210
# ---------------------------------------------------------------------------


def test_main_all_hosts_success(tmp_path: Path, monkeypatch) -> None:
    """main() with all defaults configures claude, vscode, and jetbrains and
    returns 0 when MCP responds (covers lines 109-210)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    # Set up a fake workspace with a .git dir.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    monkeypatch.chdir(workspace)
    # Claude detected.
    (home / ".claude").mkdir(parents=True)
    # No JetBrains config dir — that host will be skipped.

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()),
        patch("sumo_qa.installer.subprocess.Popen", return_value=_handshake_proc()),
        patch("sys.argv", ["sumo-qa-install"]),
    ):
        rc = installer.main()

    assert rc == 0


def test_main_skip_mcp_install_missing_binary_returns_1(monkeypatch) -> None:
    """main() with --skip-mcp-install and no binary on PATH returns 1 (line 178-179)."""
    with (
        patch("sumo_qa.installer.shutil.which", return_value=None),
        patch("sys.argv", ["sumo-qa-install", "--skip-mcp-install"]),
    ):
        rc = installer.main()

    assert rc == 1


def test_main_returns_2_when_mcp_does_not_respond(tmp_path: Path, monkeypatch) -> None:
    """main() returns 2 when _verify_mcp_responds returns False (lines 207-210)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    monkeypatch.chdir(workspace)
    (home / ".claude").mkdir(parents=True)

    # Stdout contains unparseable noise — no id=1 line — so the verifier
    # fails and main() returns 2.
    bad_proc = _FakeProc(["unexpected\n"])

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()),
        patch("sumo_qa.installer.subprocess.Popen", return_value=bad_proc),
        patch("sys.argv", ["sumo-qa-install"]),
    ):
        rc = installer.main()

    assert rc == 2


def test_main_skip_mcp_install_with_binary_found(tmp_path: Path, monkeypatch) -> None:
    """main() with --skip-mcp-install and binary on PATH prints the binary path
    and continues (line 180)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    (home / ".claude").mkdir(parents=True)

    with (
        patch(
            "sumo_qa.installer.shutil.which",
            side_effect=lambda name: (
                "/usr/local/bin/sumo-qa" if name in ("sumo-qa", "claude") else None
            ),
        ),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()),
        patch("sumo_qa.installer.subprocess.Popen", return_value=_handshake_proc()),
        patch("sys.argv", ["sumo-qa-install", "--skip-mcp-install"]),
    ):
        rc = installer.main()

    assert rc == 0


def test_main_claude_only_flag(tmp_path: Path, monkeypatch) -> None:
    """main() with --claude-code configures only Claude Code (line 157-159)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    (home / ".claude").mkdir(parents=True)

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()),
        patch("sumo_qa.installer.subprocess.Popen", return_value=_handshake_proc()),
        patch("sys.argv", ["sumo-qa-install", "--claude-code"]),
    ):
        rc = installer.main()

    assert rc == 0
