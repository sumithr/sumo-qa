# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for _setup_claude_desktop in installer.py.

Covers:
  T1 — macOS path resolution
  T2 — Linux path resolution
  T3 — Not detected when parent dir is absent
  T4 — Merge with existing mcpServers (don't clobber)
  T5 — Create new config file when parent exists but config doesn't
  T6 — Graceful error on invalid existing JSON
  T7 — Re-run is idempotent (sumo-qa key updated, no duplicates)
  T8 — Windows path resolution (via APPDATA env var)

All filesystem operations use tmp_path / monkeypatch.
No real Claude Desktop config is touched.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sumo_qa import installer

# ---------------------------------------------------------------------------
# T1 — macOS path: ~/Library/Application Support/Claude/claude_desktop_config.json
# ---------------------------------------------------------------------------


def test_macos_path_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """On Darwin, config is written to ~/Library/Application Support/Claude/."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    # Create the Claude Desktop config dir so it is "detected".
    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)

    mcp_cmd = installer.McpCommand(command="/usr/local/bin/sumo-qa", args=[])
    result = installer._setup_claude_desktop(mcp_cmd, "Darwin")

    assert result.detected is True
    assert result.configured is True
    expected = config_dir / "claude_desktop_config.json"
    assert result.config_path == expected
    assert expected.exists()

    written = json.loads(expected.read_text(encoding="utf-8"))
    assert written["mcpServers"]["sumo-qa"]["command"] == mcp_cmd.command


# ---------------------------------------------------------------------------
# T2 — Linux path: ~/.config/Claude/claude_desktop_config.json (uppercase Claude)
# ---------------------------------------------------------------------------


def test_linux_path_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """On Linux, config is written to ~/.config/Claude/ (uppercase C)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    config_dir = home / ".config" / "Claude"
    config_dir.mkdir(parents=True)

    mcp_cmd = installer.McpCommand(command="/home/user/.local/bin/sumo-qa", args=[])
    result = installer._setup_claude_desktop(mcp_cmd, "Linux")

    assert result.detected is True
    assert result.configured is True
    expected = config_dir / "claude_desktop_config.json"
    assert result.config_path == expected
    assert expected.exists()

    written = json.loads(expected.read_text(encoding="utf-8"))
    assert written["mcpServers"]["sumo-qa"]["command"] == mcp_cmd.command


# ---------------------------------------------------------------------------
# T3 — Not detected when parent dir is absent
# ---------------------------------------------------------------------------


def test_not_detected_when_parent_dir_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the Claude Desktop config dir doesn't exist, return detected=False."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    # Do NOT create ~/Library/Application Support/Claude/ — simulates no app installed.

    mcp_cmd = installer.McpCommand(command="/usr/local/bin/sumo-qa", args=[])
    result = installer._setup_claude_desktop(mcp_cmd, "Darwin")

    assert result.detected is False
    assert result.configured is False
    assert "not detected" in result.message.lower()


# ---------------------------------------------------------------------------
# T4 — Merge with existing mcpServers (don't clobber other entries)
# ---------------------------------------------------------------------------


def test_merges_with_existing_mcp_servers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing mcpServers entries (e.g. obsidian) are preserved after install."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "claude_desktop_config.json"

    existing = {
        "mcpServers": {
            "obsidian": {
                "command": "/usr/local/bin/uvx",
                "args": ["mcp-obsidian"],
                "env": {"OBSIDIAN_API_KEY": "abc123"},
            }
        }
    }
    config_path.write_text(json.dumps(existing) + "\n", encoding="utf-8")

    mcp_cmd = installer.McpCommand(command="/usr/local/bin/sumo-qa", args=[])
    result = installer._setup_claude_desktop(mcp_cmd, "Darwin")

    assert result.configured is True
    written = json.loads(config_path.read_text(encoding="utf-8"))

    # Existing entry must still be present and unchanged.
    assert "obsidian" in written["mcpServers"], "obsidian entry must be preserved"
    assert written["mcpServers"]["obsidian"] == existing["mcpServers"]["obsidian"]

    # sumo-qa entry must have been added.
    assert "sumo-qa" in written["mcpServers"]
    assert written["mcpServers"]["sumo-qa"]["command"] == mcp_cmd.command


# ---------------------------------------------------------------------------
# T5 — Create new config file when parent exists but config doesn't
# ---------------------------------------------------------------------------


def test_creates_config_when_parent_exists_but_file_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the parent dir exists but claude_desktop_config.json is absent,
    the file is created with the sumo-qa entry."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)
    # Do NOT pre-create claude_desktop_config.json.

    mcp_cmd = installer.McpCommand(command="/usr/local/bin/sumo-qa", args=[])
    result = installer._setup_claude_desktop(mcp_cmd, "Darwin")

    assert result.detected is True
    assert result.configured is True

    config_path = config_dir / "claude_desktop_config.json"
    assert config_path.exists(), "Config file should have been created"

    written = json.loads(config_path.read_text(encoding="utf-8"))
    assert written == {"mcpServers": {"sumo-qa": {"command": mcp_cmd.command}}}


# ---------------------------------------------------------------------------
# T6 — Graceful error on invalid existing JSON
# ---------------------------------------------------------------------------


def test_graceful_error_on_invalid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If claude_desktop_config.json exists but is invalid JSON, return an
    error message without clobbering the file."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "claude_desktop_config.json"
    bad_content = "{ this is not json !!!"
    config_path.write_text(bad_content, encoding="utf-8")

    mcp_cmd = installer.McpCommand(command="/usr/local/bin/sumo-qa", args=[])
    result = installer._setup_claude_desktop(mcp_cmd, "Darwin")

    assert result.detected is True
    assert result.configured is False
    # File must be unchanged.
    assert config_path.read_text(encoding="utf-8") == bad_content
    # Message must mention the path.
    assert str(config_path) in result.message


# ---------------------------------------------------------------------------
# T7 — Re-run is idempotent (single sumo-qa key; no clobber)
# ---------------------------------------------------------------------------


def test_rerun_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Running _setup_claude_desktop twice leaves exactly one sumo-qa key."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)

    mcp_cmd = installer.McpCommand(command="/usr/local/bin/sumo-qa", args=[])
    installer._setup_claude_desktop(mcp_cmd, "Darwin")
    installer._setup_claude_desktop(mcp_cmd, "Darwin")

    config_path = config_dir / "claude_desktop_config.json"
    written = json.loads(config_path.read_text(encoding="utf-8"))
    mcp_servers = written.get("mcpServers", {})

    assert list(mcp_servers.keys()) == ["sumo-qa"], (
        f"Expected exactly one 'sumo-qa' key after two runs; got: {list(mcp_servers.keys())}"
    )
    assert mcp_servers["sumo-qa"] == {"command": mcp_cmd.command}


# ---------------------------------------------------------------------------
# T8 — Windows path resolution via APPDATA env var
# ---------------------------------------------------------------------------


def test_windows_path_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """On Windows, config is written to %APPDATA%\\Claude\\claude_desktop_config.json."""
    app_data = tmp_path / "AppData" / "Roaming"
    app_data.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))

    config_dir = app_data / "Claude"
    config_dir.mkdir(parents=True)

    mcp_cmd = installer.McpCommand(command="C:/tools/sumo-qa.exe", args=[])

    with patch.dict(os.environ, {"APPDATA": str(app_data)}):
        result = installer._setup_claude_desktop(mcp_cmd, "Windows")

    assert result.detected is True
    assert result.configured is True
    expected = config_dir / "claude_desktop_config.json"
    assert result.config_path == expected
    assert expected.exists()

    written = json.loads(expected.read_text(encoding="utf-8"))
    assert written["mcpServers"]["sumo-qa"]["command"] == mcp_cmd.command
