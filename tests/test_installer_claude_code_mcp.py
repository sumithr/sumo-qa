# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from unittest.mock import patch

import pytest

from sumo_qa import installer
from sumo_qa.paths import mcp_profile_path

# No ``select`` fixture needed — the production reader uses a daemon thread +
# ``queue.Queue.get(timeout=...)``, which works identically on POSIX and
# Windows. Tests drive the verifier purely through ``_FakeProc.stdout`` lines.


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
        # Vestigial — the production reader no longer branches on
        # ``fileno``. Kept on the fake to mirror real Popen-pipe shape.
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


def _add_json_entry(add_args: list[str]) -> dict:
    assert add_args[:6] == ["/usr/local/bin/claude", "mcp", "add-json", "-s", "user", "sumo-qa"]
    assert len(add_args) == 7
    return json.loads(add_args[6])


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
    assert _add_json_entry(add_args) == {"type": "stdio", "command": mcp_cmd.command}
    assert "registered" in msg
    assert mcp_cmd.command in msg


def test_register_includes_module_args() -> None:
    """Module-fallback invocation must register `-m sumo_qa` as the entry's args."""
    import sys

    mcp_cmd = installer.McpCommand(command=sys.executable, args=["-m", "sumo_qa"])
    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()) as run,
    ):
        installer._register_claude_code_mcp(mcp_cmd)

    assert _add_json_entry(run.call_args_list[1].args[0]) == {
        "type": "stdio",
        "command": sys.executable,
        "args": ["-m", "sumo_qa"],
    }


def test_register_keeps_the_registry_entry_env(_empty_claude_home: Path) -> None:
    """A re-run removes and re-adds the Claude Code registry entry; the env
    the user set on it (e.g. a ``core`` profile) must be re-registered."""
    env = {"SUMO_QA_MCP_PROFILE": "core", "OTHER": "1"}
    (_empty_claude_home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"sumo-qa": {"command": "/old/sumo-qa", "env": env}}}),
        encoding="utf-8",
    )
    mcp_cmd = installer.McpCommand(command="/new/sumo-qa", args=[])
    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()) as run,
    ):
        installer._register_claude_code_mcp(mcp_cmd)

    entry = _add_json_entry(run.call_args_list[1].args[0])
    assert entry == {"type": "stdio", "command": "/new/sumo-qa", "env": env}


@pytest.mark.skipif(shutil.which("claude") is None, reason="the claude CLI is not installed")
def test_register_keeps_env_through_the_real_claude_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round trip through the installed ``claude`` CLI in a temp HOME: an entry
    added with an env keeps it after the installer re-registers it."""
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    env = {"SUMO_QA_MCP_PROFILE": "core"}
    claude = shutil.which("claude")
    seed = json.dumps({"type": "stdio", "command": "/old/sumo-qa", "env": env})
    subprocess.run(
        [claude, "mcp", "add-json", "-s", "user", "sumo-qa", seed],
        capture_output=True,
        check=True,
        cwd=tmp_path,
    )

    msg = installer._register_claude_code_mcp(installer.McpCommand(command="/new/sumo-qa"))

    assert "registered" in msg, msg
    registry = json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))
    entry = registry["mcpServers"]["sumo-qa"]
    assert entry["command"] == "/new/sumo-qa"
    assert entry["env"] == env


def _seed_registry(home: Path, entry: dict) -> None:
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"sumo-qa": entry}}), encoding="utf-8"
    )


def _cli_error(cmd: list[str], stderr: bytes) -> subprocess.CalledProcessError:
    return subprocess.CalledProcessError(returncode=1, cmd=cmd, stderr=stderr)


def test_register_drops_non_string_env_values_before_removing(_empty_claude_home: Path) -> None:
    """``add-json`` rejects a non-string env value (e.g. a hand-edited
    ``"PORT": 8080``); it must never reach the add that follows the remove."""
    _seed_registry(_empty_claude_home, {"command": "/old", "env": {"P": "core", "PORT": 8080}})
    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()) as run,
    ):
        msg = installer._register_claude_code_mcp(installer.McpCommand(command="/new"))

    assert "registered" in msg
    assert _add_json_entry(run.call_args_list[1].args[0])["env"] == {"P": "core"}


def test_register_falls_back_to_add_when_the_cli_has_no_add_json(
    _empty_claude_home: Path,
) -> None:
    """An older ``claude`` without ``add-json`` gets ``add`` with ``-e`` per env value."""
    _seed_registry(_empty_claude_home, {"command": "/old", "env": {"A": "1", "B": "x=y"}})

    def run_side_effect(cmd, **kwargs):
        if "add-json" in cmd:
            raise _cli_error(cmd, b"error: unknown command 'add-json'")
        return _ok()

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", side_effect=run_side_effect) as run,
    ):
        msg = installer._register_claude_code_mcp(
            installer.McpCommand(command="/new", args=["-m", "sumo_qa"])
        )

    assert "registered" in msg, msg
    assert run.call_args_list[-1].args[0] == [
        "/usr/local/bin/claude", "mcp", "add", "-s", "user", "sumo-qa",
        "-e", "A=1", "-e", "B=x=y", "--", "/new", "-m", "sumo_qa",
    ]  # fmt: skip


@pytest.mark.parametrize("restore_ok", [True, False])
def test_register_restores_the_previous_entry_when_the_add_fails(
    _empty_claude_home: Path, restore_ok: bool
) -> None:
    """A failed add after the remove must re-add the entry it removed."""
    previous = {"type": "stdio", "command": "/old", "env": {"P": "core"}}
    _seed_registry(_empty_claude_home, previous)
    added: list[dict] = []

    def run_side_effect(cmd, **kwargs):
        if "add-json" in cmd:
            added.append(json.loads(cmd[-1]))
            if len(added) == 1 or not restore_ok:
                raise _cli_error(cmd, b"boom")
        return _ok()

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", side_effect=run_side_effect),
    ):
        msg = installer._register_claude_code_mcp(installer.McpCommand(command="/new"))

    assert added[0]["command"] == "/new"
    assert added[1] == previous
    assert "claude mcp add-json failed (1): boom" in msg
    if restore_ok:
        assert msg.endswith("; restored the previous sumo-qa entry")
    else:
        assert msg.endswith(
            "; the previous sumo-qa entry could not be restored "
            "(claude mcp add-json failed (1): boom)"
        )


def test_register_does_not_restore_when_the_remove_failed(_empty_claude_home: Path) -> None:
    """A failed remove leaves the previous entry registered, so the add fails
    on it; the message must say it is still there, not that it was lost."""
    _seed_registry(_empty_claude_home, {"type": "stdio", "command": "/old"})
    calls: list[list[str]] = []

    def run_side_effect(cmd, **kwargs):
        calls.append(cmd)
        if "remove" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=1, stderr=b"locked")
        raise _cli_error(cmd, b"MCP server sumo-qa already exists in user config")

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", side_effect=run_side_effect),
    ):
        msg = installer._register_claude_code_mcp(installer.McpCommand(command="/new"))

    assert len(calls) == 2, "no restore is attempted when nothing was removed"
    assert msg.endswith(
        "; `claude mcp remove` also failed, so the previous sumo-qa entry is still registered"
    ), msg


def _no_add_json(cmd, **kwargs):
    if "add-json" in cmd:
        raise _cli_error(cmd, b"error: unknown command 'add-json'")
    return _ok()


def test_add_fallback_warns_naming_the_keys_it_cannot_pass(
    _empty_claude_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``claude mcp add`` takes only a command, args and env: a kept ``envFile``
    is dropped, and the installer says so."""
    _seed_registry(_empty_claude_home, {"command": "/old", "envFile": "/w/.env"})
    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", side_effect=_no_add_json),
    ):
        msg = installer._register_claude_code_mcp(installer.McpCommand(command="/new"))

    assert "registered" in msg, msg
    out = capsys.readouterr().out
    assert "WARNING" in out and "envFile" in out and "type" not in out


def test_add_fallback_never_restores_an_entry_without_a_command(_empty_claude_home: Path) -> None:
    """A URL entry cannot be re-added with ``claude mcp add -- COMMAND``; the
    installer reports that instead of registering an empty command."""
    _seed_registry(_empty_claude_home, {"type": "http", "url": "https://example.test/mcp"})
    adds: list[list[str]] = []

    def run_side_effect(cmd, **kwargs):
        if cmd[2] == "add":
            adds.append(cmd)
            raise _cli_error(cmd, b"boom")
        return _no_add_json(cmd)

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", side_effect=run_side_effect),
    ):
        msg = installer._register_claude_code_mcp(installer.McpCommand(command="/new"))

    assert len(adds) == 1 and adds[0][-1] == "/new"
    assert msg.endswith("; the entry has no command for `claude mcp add`)"), msg


@pytest.mark.skipif(shutil.which("claude") is None, reason="the claude CLI is not installed")
def test_register_through_the_real_cli_survives_a_non_string_env_value(
    _empty_claude_home: Path,
) -> None:
    """Real ``claude`` in a temp HOME: a hand-edited non-string env value must
    not cost the registration."""
    _seed_registry(
        _empty_claude_home,
        {"type": "stdio", "command": "/old", "env": {"SUMO_QA_MCP_PROFILE": "core", "PORT": 8080}},
    )

    msg = installer._register_claude_code_mcp(installer.McpCommand(command="/new/sumo-qa"))

    assert "registered" in msg, msg
    registry = json.loads((_empty_claude_home / ".claude.json").read_text(encoding="utf-8"))
    entry = registry["mcpServers"]["sumo-qa"]
    assert entry["command"] == "/new/sumo-qa"
    assert entry["env"] == {"SUMO_QA_MCP_PROFILE": "core"}


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
        if "add-json" in cmd:
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

    assert "claude mcp add-json failed" in msg
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


# --profile saves the profile every launch path reads (#809). Technique:
# equivalence partitioning over the saved file's prior state (absent, the other
# profile, an invalid value the flag must be able to repair).
@pytest.mark.parametrize("prior", [None, "full\n", "bogus\n"])
def test_main_profile_flag_saves_the_profile_for_every_host(
    tmp_path: Path, monkeypatch, prior
) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    handshake = _handshake_proc()  # derives the tool list, so before any saved file
    if prior is not None:
        mcp_profile_path().parent.mkdir(parents=True)
        mcp_profile_path().write_text(prior, encoding="utf-8")

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()),
        patch("sumo_qa.installer.subprocess.Popen", return_value=handshake),
        patch("sys.argv", ["sumo-qa-install", "--claude-code", "--profile", "core"]),
    ):
        rc = installer.main()

    assert rc == 0
    assert mcp_profile_path().read_text(encoding="utf-8") == "core\n"


def test_main_profile_flag_rejects_an_unknown_profile_and_saves_nothing(capsys) -> None:
    with (
        patch("sys.argv", ["sumo-qa-install", "--profile", "minimal"]),
        pytest.raises(SystemExit) as exc,
    ):
        installer.main()
    assert exc.value.code == 2
    assert "invalid choice: 'minimal'" in capsys.readouterr().err
    assert not mcp_profile_path().exists()
