# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the ownership-aware uninstall path in installer.py.

Uninstall is the inverse of install: it removes exactly the fixed-key entry
the installer wrote (``mcpServers["sumo-qa"]`` / ``servers["sumo-qa"]``, key =
``PLUGIN_METADATA.mcp_server_name``) and the skill symlinks it created, while
proving ownership so it never nukes a co-existing unrelated server or a
user-customised skill.

Covered per host:
  (a) removes OUR entry
  (b) PRESERVES a co-existing unrelated server entry
  (c) idempotent / no-op when our entry is absent or the file is missing
  (d) not-detected when no config dir exists

Plus the skills-removal safety guard and a main()-level dispatch test.

All filesystem operations use tmp_path / patched Path.home. No real host
config is touched.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sumo_qa import installer

SERVER = installer.PLUGIN_METADATA.mcp_server_name


def _ok(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=b"")


# ===========================================================================
# _remove_server_entry — the JSON-surgery primitive shared by every host
# ===========================================================================


def test_remove_server_entry_removes_our_key(tmp_path: Path) -> None:
    """Our key is popped from the container; True is returned."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"mcpServers": {SERVER: {"command": "/abs/sumo-qa"}}}) + "\n",
        encoding="utf-8",
    )

    removed = installer._remove_server_entry(config_path, "mcpServers")

    assert removed is True
    written = json.loads(config_path.read_text(encoding="utf-8"))
    assert SERVER not in written["mcpServers"]


def test_remove_server_entry_preserves_other_servers(tmp_path: Path) -> None:
    """A co-existing unrelated entry survives the removal untouched."""
    config_path = tmp_path / "config.json"
    other = {"command": "/usr/local/bin/uvx", "args": ["mcp-obsidian"]}
    config_path.write_text(
        json.dumps({"mcpServers": {"obsidian": other, SERVER: {"command": "/abs/sumo-qa"}}}) + "\n",
        encoding="utf-8",
    )

    removed = installer._remove_server_entry(config_path, "mcpServers")

    assert removed is True
    written = json.loads(config_path.read_text(encoding="utf-8"))
    assert written["mcpServers"]["obsidian"] == other
    assert SERVER not in written["mcpServers"]


def test_remove_server_entry_noop_when_key_absent(tmp_path: Path) -> None:
    """No-op (returns False) and leaves the file untouched when our key is absent."""
    config_path = tmp_path / "config.json"
    original = json.dumps({"mcpServers": {"obsidian": {"command": "/x"}}}) + "\n"
    config_path.write_text(original, encoding="utf-8")

    removed = installer._remove_server_entry(config_path, "mcpServers")

    assert removed is False
    assert config_path.read_text(encoding="utf-8") == original


def test_remove_server_entry_noop_when_file_missing(tmp_path: Path) -> None:
    """A missing config file is a no-op, returns False, never raises."""
    config_path = tmp_path / "does_not_exist.json"

    removed = installer._remove_server_entry(config_path, "mcpServers")

    assert removed is False
    assert not config_path.exists()


def test_remove_server_entry_noop_on_invalid_json(tmp_path: Path) -> None:
    """Invalid JSON is a no-op (returns False); the file is left intact."""
    config_path = tmp_path / "config.json"
    bad = "{ this is not json !!!"
    config_path.write_text(bad, encoding="utf-8")

    removed = installer._remove_server_entry(config_path, "mcpServers")

    assert removed is False
    assert config_path.read_text(encoding="utf-8") == bad


def test_remove_server_entry_leaves_empty_container(tmp_path: Path) -> None:
    """The now-empty container key is left in place (not deleted)."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"mcpServers": {SERVER: {"command": "/abs/sumo-qa"}}}) + "\n",
        encoding="utf-8",
    )

    installer._remove_server_entry(config_path, "mcpServers")

    written = json.loads(config_path.read_text(encoding="utf-8"))
    assert written["mcpServers"] == {}


# ===========================================================================
# _remove_claude_code_skills — removal half of the per-dir install
# ===========================================================================


def _repo_skill_names() -> set[str]:
    return {p.name for p in installer.SKILLS_SRC.iterdir() if p.is_dir()}


def test_remove_skills_removes_our_symlinks(tmp_path: Path) -> None:
    """Symlinks pointing at our repo skills are removed."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    names = sorted(_repo_skill_names())[:2]
    for name in names:
        (skills_dir / name).symlink_to(installer.SKILLS_SRC / name, target_is_directory=True)

    installer._remove_claude_code_skills(skills_dir)

    for name in names:
        assert not (skills_dir / name).exists()
        assert not (skills_dir / name).is_symlink()


def test_remove_skills_preserves_unrelated_skill_dir(tmp_path: Path) -> None:
    """An unrelated skill directory the user installed is left untouched."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    unrelated = skills_dir / "codex-review"
    unrelated.mkdir()
    (unrelated / "SKILL.md").write_text("# codex-review\n", encoding="utf-8")

    installer._remove_claude_code_skills(skills_dir)

    assert unrelated.is_dir()
    assert (unrelated / "SKILL.md").exists()


def test_remove_skills_does_not_delete_user_customised_skill(tmp_path: Path) -> None:
    """A real dir bearing one of OUR names but with a DIFFERENT SKILL.md is
    preserved — the same safety guard the install cleanup uses."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    name = next(iter(_repo_skill_names()))
    customised = skills_dir / name
    customised.mkdir()
    (customised / "SKILL.md").write_text("# heavily customised by the user\n", encoding="utf-8")

    installer._remove_claude_code_skills(skills_dir)

    assert customised.is_dir(), "user-customised skill dir must not be deleted"
    assert "customised by the user" in (customised / "SKILL.md").read_text(encoding="utf-8")


def test_remove_skills_removes_matching_real_dir(tmp_path: Path) -> None:
    """A real dir bearing our name whose SKILL.md matches the repo IS removed."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    name = next(iter(_repo_skill_names()))
    repo_skill_md = (installer.SKILLS_SRC / name / "SKILL.md").read_text(encoding="utf-8")
    matching = skills_dir / name
    matching.mkdir()
    (matching / "SKILL.md").write_text(repo_skill_md, encoding="utf-8")

    installer._remove_claude_code_skills(skills_dir)

    assert not matching.exists()


def test_remove_skills_removes_legacy_wrapper(tmp_path: Path) -> None:
    """The legacy ``sumo-qa`` wrapper symlink/dir is removed."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    wrapper = skills_dir / "sumo-qa"
    wrapper.mkdir()
    (wrapper / "marker").write_text("legacy", encoding="utf-8")

    installer._remove_claude_code_skills(skills_dir)

    assert not wrapper.exists()


# ===========================================================================
# _uninstall_vscode
# ===========================================================================


def test_uninstall_vscode_removes_our_entry(tmp_path: Path) -> None:
    workspace = tmp_path
    vscode = workspace / ".vscode"
    vscode.mkdir()
    config_path = vscode / "mcp.json"
    config_path.write_text(
        json.dumps({"servers": {SERVER: {"type": "stdio", "command": "/abs/sumo-qa"}}}) + "\n",
        encoding="utf-8",
    )

    result = installer._uninstall_vscode(workspace)

    assert result.configured is True
    written = json.loads(config_path.read_text(encoding="utf-8"))
    assert SERVER not in written["servers"]


def test_uninstall_vscode_preserves_other_entry(tmp_path: Path) -> None:
    workspace = tmp_path
    vscode = workspace / ".vscode"
    vscode.mkdir()
    config_path = vscode / "mcp.json"
    other = {"type": "stdio", "command": "other-bin", "args": []}
    config_path.write_text(
        json.dumps({"servers": {"other-tool": other, SERVER: {"command": "/x"}}}) + "\n",
        encoding="utf-8",
    )

    result = installer._uninstall_vscode(workspace)

    assert result.configured is True
    written = json.loads(config_path.read_text(encoding="utf-8"))
    assert written["servers"]["other-tool"] == other
    assert SERVER not in written["servers"]


def test_uninstall_vscode_noop_when_entry_absent(tmp_path: Path) -> None:
    workspace = tmp_path
    vscode = workspace / ".vscode"
    vscode.mkdir()
    config_path = vscode / "mcp.json"
    original = json.dumps({"servers": {"other-tool": {"command": "/x"}}}) + "\n"
    config_path.write_text(original, encoding="utf-8")

    result = installer._uninstall_vscode(workspace)

    assert result.configured is False
    assert config_path.read_text(encoding="utf-8") == original


def test_uninstall_vscode_not_detected_when_no_config(tmp_path: Path) -> None:
    """No .vscode/mcp.json → not detected, no crash."""
    result = installer._uninstall_vscode(tmp_path)

    assert result.detected is False
    assert result.configured is False


# ===========================================================================
# _uninstall_claude_desktop
# ===========================================================================


def test_uninstall_claude_desktop_removes_our_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "claude_desktop_config.json"
    config_path.write_text(
        json.dumps({"mcpServers": {SERVER: {"command": "/abs/sumo-qa"}}}) + "\n",
        encoding="utf-8",
    )

    result = installer._uninstall_claude_desktop("Darwin")

    assert result.configured is True
    written = json.loads(config_path.read_text(encoding="utf-8"))
    assert SERVER not in written["mcpServers"]


def test_uninstall_claude_desktop_preserves_other_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "claude_desktop_config.json"
    other = {"command": "/usr/local/bin/uvx", "args": ["mcp-obsidian"]}
    config_path.write_text(
        json.dumps({"mcpServers": {"obsidian": other, SERVER: {"command": "/x"}}}) + "\n",
        encoding="utf-8",
    )

    result = installer._uninstall_claude_desktop("Darwin")

    assert result.configured is True
    written = json.loads(config_path.read_text(encoding="utf-8"))
    assert written["mcpServers"]["obsidian"] == other
    assert SERVER not in written["mcpServers"]


def test_uninstall_claude_desktop_noop_when_entry_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "claude_desktop_config.json"
    original = json.dumps({"mcpServers": {"obsidian": {"command": "/x"}}}) + "\n"
    config_path.write_text(original, encoding="utf-8")

    result = installer._uninstall_claude_desktop("Darwin")

    assert result.configured is False
    assert config_path.read_text(encoding="utf-8") == original


def test_uninstall_claude_desktop_not_detected_when_no_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    # Do NOT create the Claude Desktop config dir.

    result = installer._uninstall_claude_desktop("Darwin")

    assert result.detected is False
    assert result.configured is False
    assert "not detected" in result.message.lower()


# ===========================================================================
# _uninstall_claude_code
# ===========================================================================


def test_uninstall_claude_code_removes_skills_and_entry_and_runs_mcp_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    # Detected via ~/.claude
    claude_home = home / ".claude"
    skills_dir = claude_home / "skills"
    skills_dir.mkdir(parents=True)
    name = next(iter(_repo_skill_names()))
    (skills_dir / name).symlink_to(installer.SKILLS_SRC / name, target_is_directory=True)
    # claude_desktop_config.json under the claude-code config dir
    cc_config_dir = home / ".config" / "claude"
    cc_config_dir.mkdir(parents=True)
    cc_config = cc_config_dir / "claude_desktop_config.json"
    cc_config.write_text(
        json.dumps({"mcpServers": {SERVER: {"command": "/abs/sumo-qa"}}}) + "\n",
        encoding="utf-8",
    )

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()) as run,
    ):
        result = installer._uninstall_claude_code("Linux")

    assert result.detected is True
    assert result.configured is True
    # Skill symlink removed.
    assert not (skills_dir / name).exists()
    # MCP registry entry removed.
    written = json.loads(cc_config.read_text(encoding="utf-8"))
    assert SERVER not in written["mcpServers"]
    # `claude mcp remove sumo-qa -s user` was run.
    remove_args = run.call_args_list[0].args[0]
    assert remove_args == ["/usr/local/bin/claude", "mcp", "remove", SERVER, "-s", "user"]


def test_uninstall_claude_code_skips_mcp_remove_when_claude_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    (home / ".claude" / "skills").mkdir(parents=True)

    with (
        patch("sumo_qa.installer.shutil.which", return_value=None),
        patch("sumo_qa.installer.subprocess.run") as run,
    ):
        result = installer._uninstall_claude_code("Linux")

    assert result.detected is True
    assert run.call_count == 0


def test_uninstall_claude_code_not_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    # Neither ~/.claude nor ~/.config/claude exists.

    with patch("sumo_qa.installer.shutil.which", return_value=None):
        result = installer._uninstall_claude_code("Linux")

    assert result.detected is False
    assert result.configured is False
    assert "not detected" in result.message.lower()


# ===========================================================================
# _uninstall_intellij
# ===========================================================================


def test_uninstall_intellij_detected_gives_manual_followup(tmp_path: Path) -> None:
    """JetBrains was never written by the installer → manual followup, configured stays False."""
    jb_root = tmp_path / "Library" / "Application Support" / "JetBrains"
    (jb_root / "IntelliJIdea2026.1" / "options").mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        result = installer._uninstall_intellij("Darwin")

    assert result.detected is True
    assert result.configured is False
    assert "Model Context Protocol" in result.followup
    assert SERVER in result.followup


def test_uninstall_intellij_not_detected(tmp_path: Path) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        result = installer._uninstall_intellij("Darwin")

    assert result.detected is False
    assert result.configured is False


# ===========================================================================
# main() — uninstall dispatch
# ===========================================================================


def test_main_uninstall_dispatches_and_skips_binary_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--uninstall`` runs the uninstall path and NEVER installs the binary."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    (home / ".claude" / "skills").mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    with (
        patch("sumo_qa.installer._install_mcp_binary") as install_binary,
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()),
        patch("sumo_qa.installer.subprocess.Popen") as popen,
        patch("sys.argv", ["sumo-qa-install", "--uninstall"]),
    ):
        rc = installer.main()

    assert rc == 0
    install_binary.assert_not_called()
    # Uninstall must never run the verify handshake either.
    popen.assert_not_called()


def test_main_uninstall_single_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--uninstall --claude-desktop`` targets only Claude Desktop."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)
    (config_dir / "claude_desktop_config.json").write_text(
        json.dumps({"mcpServers": {SERVER: {"command": "/abs/sumo-qa"}}}) + "\n",
        encoding="utf-8",
    )

    with (
        patch("sumo_qa.installer._install_mcp_binary") as install_binary,
        patch("sumo_qa.installer.platform.system", return_value="Darwin"),
        patch("sys.argv", ["sumo-qa-install", "--uninstall", "--claude-desktop"]),
    ):
        rc = installer.main()

    assert rc == 0
    install_binary.assert_not_called()
    written = json.loads((config_dir / "claude_desktop_config.json").read_text(encoding="utf-8"))
    assert SERVER not in written["mcpServers"]


def test_remove_server_entry_noop_on_non_dict_root(tmp_path: Path) -> None:
    """A JSON file whose root is not an object (e.g. a list) is a no-op."""
    config_path = tmp_path / "config.json"
    payload = json.dumps([1, 2, 3])
    config_path.write_text(payload, encoding="utf-8")

    removed = installer._remove_server_entry(config_path, "mcpServers")

    assert removed is False
    assert config_path.read_text(encoding="utf-8") == payload


def test_remove_skills_removes_legacy_wrapper_real_dir(tmp_path: Path) -> None:
    """A legacy ``sumo-qa`` wrapper left as a REAL directory is removed (the
    pre-per-skill-symlink layout some older installs left behind)."""
    skills_dir = tmp_path / "skills"
    wrapper = skills_dir / "sumo-qa"
    (wrapper / "nested").mkdir(parents=True)
    (wrapper / "nested" / "old.md").write_text("legacy", encoding="utf-8")

    installer._remove_claude_code_skills(skills_dir)

    assert not wrapper.exists()


def test_uninstall_intellij_linux_config_path(tmp_path: Path) -> None:
    """On Linux the JetBrains root resolves under ~/.config/JetBrains."""
    jb_root = tmp_path / ".config" / "JetBrains"
    (jb_root / "PyCharm2026.1" / "options").mkdir(parents=True)

    with patch.object(Path, "home", return_value=tmp_path):
        result = installer._uninstall_intellij("Linux")

    assert result.detected is True
    assert result.configured is False
    assert "Model Context Protocol" in result.followup


def test_uninstall_intellij_dir_present_but_no_ide(tmp_path: Path) -> None:
    """JetBrains config dir exists but holds no recognised IDE → not detected."""
    jb_root = tmp_path / "Library" / "Application Support" / "JetBrains"
    jb_root.mkdir(parents=True)  # exists, but empty (no IDE subdir with options/)

    with patch.object(Path, "home", return_value=tmp_path):
        result = installer._uninstall_intellij("Darwin")

    assert result.detected is False
    assert "no JetBrains IDE installation found" in result.message


def test_remove_skills_removes_legacy_wrapper_file(tmp_path: Path) -> None:
    """A legacy ``sumo-qa`` wrapper left as a plain file/symlink is unlinked
    (the install-time layout removed it the same way)."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    wrapper = skills_dir / "sumo-qa"
    wrapper.write_text("legacy", encoding="utf-8")

    installer._remove_claude_code_skills(skills_dir)

    assert not wrapper.exists()
