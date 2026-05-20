# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from sumo_qa import installer


def _ok(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=b"")


def _full_handshake_stdout() -> str:
    """Stdout the verifier expects: initialize + tools/list with all required tools."""
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
    return json.dumps(init) + "\n" + json.dumps(tools) + "\n"


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

    mcp_proc = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=_full_handshake_stdout(),
        stderr="",
    )

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=mcp_proc),
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

    no_result_proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="unexpected", stderr=""
    )

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=no_result_proc),
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

    mcp_proc = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=_full_handshake_stdout(),
        stderr="",
    )

    with (
        patch(
            "sumo_qa.installer.shutil.which",
            side_effect=lambda name: (
                "/usr/local/bin/sumo-qa" if name in ("sumo-qa", "claude") else None
            ),
        ),
        patch("sumo_qa.installer.subprocess.run", return_value=mcp_proc),
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

    mcp_proc = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=_full_handshake_stdout(),
        stderr="",
    )

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=mcp_proc),
        patch("sys.argv", ["sumo-qa-install", "--claude-code"]),
    ):
        rc = installer.main()

    assert rc == 0
