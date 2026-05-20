# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sumo_qa import installer

# ---------------------------------------------------------------------------
# T1 — Not detected when no workspace marker exists
# ---------------------------------------------------------------------------


def test_not_detected_when_no_workspace_marker(tmp_path: Path) -> None:
    """A plain empty directory has no marker → detected=False, configured=False."""
    mcp_cmd = installer.McpCommand(command="/abs/path/to/sumo-qa", args=[])
    result = installer._setup_vscode_copilot(mcp_cmd, workspace=tmp_path)

    assert result.detected is False
    assert result.configured is False
    assert "skipped" in result.message
    # The .vscode directory must NOT have been created.
    assert not (tmp_path / ".vscode").exists()


# ---------------------------------------------------------------------------
# T2 — Workspace flag is honoured; writes .vscode/mcp.json there, not CWD
# ---------------------------------------------------------------------------


def test_workspace_flag_honoured_over_cwd(tmp_path: Path) -> None:
    """An explicit workspace path is used verbatim; CWD is irrelevant."""
    workspace = tmp_path / "my_project"
    workspace.mkdir()
    (workspace / "pyproject.toml").touch()  # marker so detection passes

    mcp_cmd = installer.McpCommand(command="/usr/local/bin/sumo-qa", args=[])
    result = installer._setup_vscode_copilot(mcp_cmd, workspace=workspace)

    assert result.configured is True
    expected_config = workspace / ".vscode" / "mcp.json"
    assert result.config_path == expected_config
    assert expected_config.exists()


# ---------------------------------------------------------------------------
# T3 — Writes "servers" schema (not "mcpServers"); correct command + type
# ---------------------------------------------------------------------------


def test_writes_servers_schema_not_mcp_servers(tmp_path: Path) -> None:
    """The VS Code schema uses 'servers', NOT 'mcpServers'.  Regression guard."""
    (tmp_path / ".git").mkdir()  # workspace marker
    mcp_cmd = installer.McpCommand(command="/usr/local/bin/sumo-qa", args=[])

    result = installer._setup_vscode_copilot(mcp_cmd, workspace=tmp_path)

    assert result.configured is True
    written = json.loads((tmp_path / ".vscode" / "mcp.json").read_text())

    # Must use the VS Code-native "servers" key.
    assert "servers" in written, "Expected 'servers' top-level key (VS Code schema)"
    assert "mcpServers" not in written, (
        "'mcpServers' must NOT appear (that's Claude Desktop schema)"
    )

    entry = written["servers"]["sumo-qa"]
    assert entry["type"] == "stdio"
    assert entry["command"] == mcp_cmd.command
    assert entry["args"] == []


# ---------------------------------------------------------------------------
# T4 — Preserves existing entries alongside the new sumo-qa entry
# ---------------------------------------------------------------------------


def test_preserves_existing_server_entries(tmp_path: Path) -> None:
    """Existing entries in mcp.json are kept; sumo-qa is added alongside."""
    (tmp_path / ".git").mkdir()
    vscode_dir = tmp_path / ".vscode"
    vscode_dir.mkdir()
    config_path = vscode_dir / "mcp.json"
    existing = {"servers": {"other-tool": {"type": "stdio", "command": "other-bin", "args": []}}}
    config_path.write_text(json.dumps(existing) + "\n", encoding="utf-8")

    mcp_cmd = installer.McpCommand(command="/usr/local/bin/sumo-qa", args=[])
    result = installer._setup_vscode_copilot(mcp_cmd, workspace=tmp_path)

    assert result.configured is True
    written = json.loads(config_path.read_text())
    assert "other-tool" in written["servers"], "Existing entry must be preserved"
    assert "sumo-qa" in written["servers"], "sumo-qa entry must be added"


# ---------------------------------------------------------------------------
# T5 — Graceful error on existing-but-invalid JSON; file not clobbered
# ---------------------------------------------------------------------------


def test_invalid_json_not_clobbered(tmp_path: Path) -> None:
    """If mcp.json is unparseable, the function returns an error and leaves the file intact."""
    (tmp_path / ".git").mkdir()
    vscode_dir = tmp_path / ".vscode"
    vscode_dir.mkdir()
    config_path = vscode_dir / "mcp.json"
    bad_content = "{ this is not json !!!"
    config_path.write_text(bad_content, encoding="utf-8")

    mcp_cmd = installer.McpCommand(command="/usr/local/bin/sumo-qa", args=[])
    result = installer._setup_vscode_copilot(mcp_cmd, workspace=tmp_path)

    # Should not be configured.
    assert result.configured is False
    # File must be unchanged.
    assert config_path.read_text() == bad_content
    # Message must mention the path.
    assert str(config_path) in result.message


# ---------------------------------------------------------------------------
# T6 — HOME directory is refused even if it has workspace markers
# ---------------------------------------------------------------------------


def test_refuses_home_directory(tmp_path: Path) -> None:
    """Writing to $HOME/.vscode/mcp.json is actively refused (VS Code ignores it)."""
    mcp_cmd = installer.McpCommand(command="/usr/local/bin/sumo-qa", args=[])

    # Patch Path.home() to return tmp_path so the guard fires without touching
    # the real home directory.
    with patch.object(Path, "home", return_value=tmp_path):
        result = installer._setup_vscode_copilot(mcp_cmd, workspace=tmp_path)

    assert result.detected is False
    assert result.configured is False
    assert "$HOME" in result.message or "--workspace" in result.message


# ---------------------------------------------------------------------------
# T7 — Strips legacy mcpServers key from previously written config
# ---------------------------------------------------------------------------


def test_strips_legacy_mcp_servers_key(tmp_path: Path) -> None:
    """A pre-existing 'mcpServers' key (wrong schema) is removed on re-install."""
    (tmp_path / ".git").mkdir()
    vscode_dir = tmp_path / ".vscode"
    vscode_dir.mkdir()
    config_path = vscode_dir / "mcp.json"
    # Simulate a file that was written with the wrong (Claude Desktop) schema.
    legacy = {"mcpServers": {"sumo-qa": {"command": "/old/path"}}}
    config_path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    mcp_cmd = installer.McpCommand(command="/usr/local/bin/sumo-qa", args=[])
    result = installer._setup_vscode_copilot(mcp_cmd, workspace=tmp_path)

    assert result.configured is True
    written = json.loads(config_path.read_text())
    assert "mcpServers" not in written, "Legacy mcpServers key must be stripped"
    assert "servers" in written
    assert written["servers"]["sumo-qa"]["command"] == mcp_cmd.command
