# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for doctor's Claude-Desktop-aware probe and config checks.

Closes the doctor half of issue #181:

* ``sumo-qa-doctor --host claude-desktop`` must probe the command stored in
  ``claude_desktop_config.json``, not whatever ``shutil.which("sumo-qa")``
  returns from the current shell — the configured command is what the app
  will actually launch, and the bug the user is debugging is precisely that
  the two diverged.
* ``check_claude_desktop_config`` must downgrade an OK to WARN when the
  configured command lives in a source-checkout venv on Darwin — so the
  shell-based check doesn't mask a config Claude Desktop can't use.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sumo_qa import doctor

# ---------------------------------------------------------------------------
# AC #4 — handshake probes the configured command, not shutil.which
# ---------------------------------------------------------------------------


def test_resolve_mcp_command_for_claude_desktop_reads_configured_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``host == "claude-desktop"``, the resolver reads
    ``claude_desktop_config.json`` and returns the command stored there —
    not whatever ``shutil.which`` finds on the current PATH.
    """
    home = tmp_path / "home"
    home.mkdir()
    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "claude_desktop_config.json"

    configured_cmd = "/Users/u/proj/.venv/bin/sumo-qa"
    config_path.write_text(
        json.dumps({"mcpServers": {"sumo-qa": {"command": configured_cmd}}}),
        encoding="utf-8",
    )

    # shutil.which returns a different command; the probe must NOT use it.
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/local/bin/sumo-qa")

    cmd = doctor._resolve_mcp_command(host="claude-desktop", system="Darwin", home=home)

    assert cmd.command == configured_cmd, (
        "doctor must probe the command in claude_desktop_config.json, not shutil.which"
    )


def test_resolve_mcp_command_default_still_uses_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no --host filter, the resolver keeps the legacy PATH-first
    behaviour — this is the existing contract every other host depends on.

    The mocked ``which`` result is sourced from ``tmp_path`` so that the
    resolver's ``Path(...).resolve()`` is a no-op on every platform; a
    hardcoded POSIX path gets a drive prefix prepended on Windows and the
    assertion would compare ``D:\\usr\\...`` to ``/usr/...``.
    """
    path_command = str(tmp_path / "sumo-qa")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: path_command)

    cmd = doctor._resolve_mcp_command()

    assert cmd.command == path_command
    assert cmd.args == []


def test_resolve_mcp_command_for_claude_desktop_falls_back_to_path_when_config_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the config file is missing entirely, the resolver falls back to
    the PATH command so the rest of the check sequence still runs. The
    missing-config case is reported by ``check_claude_desktop_config``.
    """
    home = tmp_path / "home"
    home.mkdir()
    # Source the mocked ``which`` result from ``tmp_path`` so the resolver's
    # ``Path(...).resolve()`` is a no-op on every platform (see comment on
    # ``test_resolve_mcp_command_default_still_uses_path``).
    path_command = str(tmp_path / "sumo-qa")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: path_command)

    cmd = doctor._resolve_mcp_command(host="claude-desktop", system="Darwin", home=home)

    assert cmd.command == path_command


@pytest.mark.parametrize(
    "config_text",
    [
        pytest.param("{ not valid json", id="corrupt_json"),
        pytest.param('{"mcpServers": {"sumo-qa": null}}', id="entry_is_null"),
        pytest.param('{"mcpServers": {"sumo-qa": {"command": ""}}}', id="empty_command"),
        pytest.param('{"mcpServers": [1, 2, 3]}', id="mcp_servers_is_non_empty_list"),
        pytest.param('{"mcpServers": "oops"}', id="mcp_servers_is_string"),
        pytest.param('["mcpServers"]', id="top_level_is_array"),
    ],
)
def test_resolve_mcp_command_falls_back_when_config_is_malformed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_text: str,
) -> None:
    """Corrupt JSON, non-dict server entry, or empty-string command all
    fall back to the PATH command. The resolver is robust to a user-edited
    config — the diagnostic for malformed content lives in
    ``check_claude_desktop_config``, not here.
    """
    home = tmp_path / "home"
    home.mkdir()
    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)
    (config_dir / "claude_desktop_config.json").write_text(config_text, encoding="utf-8")

    # Source the mocked ``which`` result from ``tmp_path`` so the resolver's
    # ``Path(...).resolve()`` is a no-op on every platform (see comment on
    # ``test_resolve_mcp_command_default_still_uses_path``).
    path_command = str(tmp_path / "sumo-qa")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: path_command)

    cmd = doctor._resolve_mcp_command(host="claude-desktop", system="Darwin", home=home)

    assert cmd.command == path_command


# ---------------------------------------------------------------------------
# AC #5 — config check WARNs when the configured command is unsafe
# ---------------------------------------------------------------------------


def test_check_claude_desktop_config_warns_on_unsafe_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A config pointing at ``<repo>/.venv/bin/sumo-qa`` parses fine and the
    binary exists, but the macOS Claude Desktop sandbox can't read it.
    Doctor must surface WARN with the fix command pointing at re-running
    the installer from a stable-sumo-qa shell.
    """
    home = tmp_path / "home"
    home.mkdir()
    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)

    # Create a real binary at an unsafe path so _server_entry_resolves passes.
    unsafe_dir = tmp_path / "proj" / ".venv" / "bin"
    unsafe_dir.mkdir(parents=True)
    unsafe_binary = unsafe_dir / "sumo-qa"
    unsafe_binary.write_text("#!/bin/sh\n", encoding="utf-8")
    unsafe_binary.chmod(0o755)

    config_path = config_dir / "claude_desktop_config.json"
    config_path.write_text(
        json.dumps({"mcpServers": {"sumo-qa": {"command": str(unsafe_binary)}}}),
        encoding="utf-8",
    )

    result = doctor.check_claude_desktop_config(home=home, system="Darwin")

    assert result.status == "WARN", (
        f"Expected WARN for unsafe configured command, got {result.status}: {result.summary}"
    )
    assert str(unsafe_binary) in result.summary
    assert result.fix is not None and "sumo-qa-install" in result.fix


def test_check_claude_desktop_config_stays_ok_when_command_is_safe(
    tmp_path: Path,
) -> None:
    """A pipx/pyenv/brew install location is the happy path — the check
    stays OK so the existing contract isn't disturbed."""
    home = tmp_path / "home"
    home.mkdir()
    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)

    safe_dir = tmp_path / "pyenv" / "versions" / "3.13.13" / "bin"
    safe_dir.mkdir(parents=True)
    safe_binary = safe_dir / "sumo-qa"
    safe_binary.write_text("#!/bin/sh\n", encoding="utf-8")
    safe_binary.chmod(0o755)

    config_path = config_dir / "claude_desktop_config.json"
    config_path.write_text(
        json.dumps({"mcpServers": {"sumo-qa": {"command": str(safe_binary)}}}),
        encoding="utf-8",
    )

    result = doctor.check_claude_desktop_config(home=home, system="Darwin")

    assert result.status == "OK"
    assert str(safe_binary) in result.summary


def test_check_claude_desktop_config_does_not_warn_off_darwin(tmp_path: Path) -> None:
    """The macOS sandbox restriction is Darwin-only — on Linux/Windows the
    same configured path is fine, so the check stays OK."""
    home = tmp_path / "home"
    home.mkdir()
    config_dir = home / ".config" / "Claude"
    config_dir.mkdir(parents=True)

    unsafe_dir = tmp_path / "proj" / ".venv" / "bin"
    unsafe_dir.mkdir(parents=True)
    unsafe_binary = unsafe_dir / "sumo-qa"
    unsafe_binary.write_text("#!/bin/sh\n", encoding="utf-8")
    unsafe_binary.chmod(0o755)

    config_path = config_dir / "claude_desktop_config.json"
    config_path.write_text(
        json.dumps({"mcpServers": {"sumo-qa": {"command": str(unsafe_binary)}}}),
        encoding="utf-8",
    )

    result = doctor.check_claude_desktop_config(home=home, system="Linux")

    assert result.status == "OK", f"Expected OK off Darwin, got {result.status}: {result.summary}"
