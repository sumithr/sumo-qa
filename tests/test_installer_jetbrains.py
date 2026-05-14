# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE.
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sumo_qa import installer

# ---------------------------------------------------------------------------
# T1 — No JetBrains config dir: not detected, clear message, no crash
# ---------------------------------------------------------------------------


def test_not_detected_when_no_jb_config_dir(tmp_path: Path) -> None:
    """If the JetBrains config root does not exist the function returns
    detected=False with a human-readable message and does not raise."""
    mcp_path = Path("/abs/path/to/sumo-qa")
    # jb_root at tmp_path / "Library" / "Application Support" / "JetBrains"
    # is intentionally NOT created — home() returns tmp_path, no JB dir exists

    with patch.object(Path, "home", return_value=tmp_path):
        result = installer._setup_intellij(mcp_path, system="Darwin")

    assert result.detected is False
    assert result.configured is False
    assert "not detected" in result.message


# ---------------------------------------------------------------------------
# T2 — JetBrains dir exists but contains no recognised IDE subdirectories
# ---------------------------------------------------------------------------


def test_not_detected_when_no_ide_subdirs(tmp_path: Path) -> None:
    """If the JetBrains root exists but no recognised IDE prefix dirs are
    present, detected=False with an appropriate message."""
    mcp_path = Path("/abs/path/to/sumo-qa")
    jb_root = tmp_path / "Library" / "Application Support" / "JetBrains"
    jb_root.mkdir(parents=True)
    # A directory that doesn't match any _JB_IDE_PREFIXES
    (jb_root / "SomeOtherTool2025.1" / "options").mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        result = installer._setup_intellij(mcp_path, system="Darwin")

    assert result.detected is False
    assert "no JetBrains IDE installation found" in result.message


# ---------------------------------------------------------------------------
# T3 — Darwin: detected; followup contains the Settings-UI fields and binary
# ---------------------------------------------------------------------------


def test_darwin_detected_followup_contains_settings_ui_fields(tmp_path: Path) -> None:
    """On Darwin, when an IntelliJ dir exists, detected=True and followup
    contains 'Name: sumo-qa' and the absolute binary path."""
    mcp_path = Path("/abs/path/to/sumo-qa")
    jb_root = tmp_path / "Library" / "Application Support" / "JetBrains"
    idea_dir = jb_root / "IntelliJIdea2025.1"
    (idea_dir / "options").mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        result = installer._setup_intellij(mcp_path, system="Darwin")

    assert result.detected is True
    assert "sumo-qa" in result.followup
    assert str(mcp_path) in result.followup
    # Must reference the Settings-UI menu path
    assert "AI Assistant" in result.followup
    assert "Model Context Protocol" in result.followup


# ---------------------------------------------------------------------------
# T4 — Followup must use Command field NOT a JSON mcpServers snippet
#       (regression guard: JetBrains uses Settings-UI, not Claude Desktop schema)
# ---------------------------------------------------------------------------


def test_followup_uses_command_field_not_mcp_servers_json(tmp_path: Path) -> None:
    """The JetBrains setup is a Settings-UI guide, not a JSON config write.
    The followup must contain a 'Command:' field and must NOT contain a
    'mcpServers' JSON key — that would be the wrong schema (Claude Desktop)."""
    mcp_path = Path("/abs/path/to/sumo-qa")
    jb_root = tmp_path / "Library" / "Application Support" / "JetBrains"
    (jb_root / "IntelliJIdea2026.1" / "options").mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        result = installer._setup_intellij(mcp_path, system="Darwin")

    assert result.detected is True
    assert "Command:" in result.followup
    # Must NOT silently switch to JSON schema output
    assert "mcpServers" not in result.followup, (
        "followup must not contain 'mcpServers'; JetBrains uses Settings-UI, not JSON config"
    )
    assert "servers" not in result.followup.split("Command:")[0], (
        "followup must not start with a JSON 'servers' block before the Command field"
    )


# ---------------------------------------------------------------------------
# T5 — Linux: JetBrains root at ~/.config/JetBrains is used
# ---------------------------------------------------------------------------


def test_linux_config_dir_detected(tmp_path: Path) -> None:
    """On Linux (system != Darwin/Windows), the root is ~/.config/JetBrains."""
    mcp_path = Path("/usr/local/bin/sumo-qa")
    jb_root = tmp_path / ".config" / "JetBrains"
    (jb_root / "PyCharm2025.3" / "options").mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        result = installer._setup_intellij(mcp_path, system="Linux")

    assert result.detected is True
    assert str(mcp_path) in result.followup


# ---------------------------------------------------------------------------
# T6 — Multiple IDE dirs: the latest (reverse-sorted) is selected
# ---------------------------------------------------------------------------


def test_latest_ide_selected_by_reverse_sort(tmp_path: Path) -> None:
    """When multiple IDE dirs exist, the one that sorts last alphabetically
    (highest version) is selected as 'latest' and mentioned in the message."""
    mcp_path = Path("/abs/path/to/sumo-qa")
    jb_root = tmp_path / "Library" / "Application Support" / "JetBrains"
    for name in ("IntelliJIdea2024.1", "IntelliJIdea2025.3", "IntelliJIdea2023.2"):
        (jb_root / name / "options").mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        result = installer._setup_intellij(mcp_path, system="Darwin")

    assert result.detected is True
    # "IntelliJIdea2025.3" sorts last reverse → is the latest
    assert "IntelliJIdea2025.3" in result.message
    # There are 3 dirs total; message reports 2 others
    assert "(and 2 other IDE(s))" in result.message


# ---------------------------------------------------------------------------
# T7 — Windows: APPDATA env var is used for JetBrains root
# ---------------------------------------------------------------------------


def test_windows_appdata_dir_detected(tmp_path: Path) -> None:
    """On Windows, the root is %APPDATA%/JetBrains, not ~/Library/..."""
    mcp_path = Path("C:/tools/sumo-qa.exe")
    jb_root = tmp_path / "JetBrains"
    (jb_root / "GoLand2025.1" / "options").mkdir(parents=True)

    with patch.dict("os.environ", {"APPDATA": str(tmp_path)}):
        result = installer._setup_intellij(mcp_path, system="Windows")

    assert result.detected is True
    assert str(mcp_path) in result.followup


# ---------------------------------------------------------------------------
# T8 — IDE dir without 'options' subdirectory is NOT counted
# ---------------------------------------------------------------------------


def test_ide_dir_without_options_not_counted(tmp_path: Path) -> None:
    """A dir with a recognised prefix but no 'options' subdir is filtered out."""
    mcp_path = Path("/abs/path/to/sumo-qa")
    jb_root = tmp_path / "Library" / "Application Support" / "JetBrains"
    jb_root.mkdir(parents=True)
    # Recognised prefix, but no 'options' subdir
    (jb_root / "WebStorm2025.1").mkdir()

    with patch.object(Path, "home", return_value=tmp_path):
        result = installer._setup_intellij(mcp_path, system="Darwin")

    assert result.detected is False
    assert "no JetBrains IDE installation found" in result.message
