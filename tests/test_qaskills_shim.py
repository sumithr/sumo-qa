# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the qaskills subprocess shim.

The shim is intentionally thin: it runs `npx @qaskills/cli`, strips
ANSI/spinner chrome, and handles filesystem moves for project-scope
installs. We don't parse the CLI's natural-language output — the host
LLM does that. So the tests here verify subprocess plumbing,
ANSI/chrome stripping on real fixture output, and filesystem behaviour
for the scope=project relocation. No parser tests, no dataclasses for
CLI fields.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sumo_qa import qaskills

_FIXTURES = Path(__file__).parent / "fixtures"


def _completed_process(stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

def test_is_available_returns_true_when_npx_present() -> None:
    with patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx") as mock_which:
        assert qaskills.is_available() is True
    mock_which.assert_called_once_with("npx")


def test_is_available_returns_false_when_npx_missing() -> None:
    with patch("sumo_qa.qaskills.shutil.which", return_value=None):
        assert qaskills.is_available() is False


# ---------------------------------------------------------------------------
# search / info — return cleaned text for the host LLM
# ---------------------------------------------------------------------------

def test_search_strips_ansi_and_returns_real_fixture_content() -> None:
    fixture = (_FIXTURES / "qaskills_search_playwright.txt").read_text(encoding="utf-8")
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed_process(fixture)), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        out = qaskills.search("playwright")

    # ANSI codes and spinner glyphs gone, real content preserved.
    assert "\x1b[" not in out
    assert "◒" not in out and "◐" not in out
    # The actual content the LLM needs to interpret is intact.
    assert "Playwright E2E Testing" in out
    assert "thetestingacademy" in out
    assert "npx qaskills add playwright-e2e" in out


def test_search_raises_node_not_found_when_npx_missing() -> None:
    with patch("sumo_qa.qaskills.shutil.which", return_value=None):
        with pytest.raises(qaskills.NodeNotFoundError):
            qaskills.search("anything")


def test_search_raises_cli_error_on_nonzero_exit() -> None:
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed_process("", returncode=2, stderr="boom")), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        with pytest.raises(qaskills.QaskillsCLIError) as exc_info:
            qaskills.search("anything")
    assert "boom" in str(exc_info.value)


def test_info_strips_ansi_and_returns_real_fixture_content() -> None:
    fixture = (_FIXTURES / "qaskills_info_playwright_e2e.txt").read_text(encoding="utf-8")
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed_process(fixture)), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        out = qaskills.info("playwright-e2e")

    assert "Playwright E2E Testing v1.0.0" in out
    assert "Quality Score: 92/100" in out
    assert "License: MIT" in out
    assert "https://qaskills.sh/skills/playwright-e2e" in out
    # No spinner / ANSI leaked through.
    assert "\x1b[" not in out


def test_info_raises_cli_error_with_name_in_message() -> None:
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed_process("", returncode=2, stderr="not found")), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        with pytest.raises(qaskills.QaskillsCLIError) as exc_info:
            qaskills.info("ghost-skill")
    assert "ghost-skill" in str(exc_info.value)
    assert "not found" in str(exc_info.value)


# ---------------------------------------------------------------------------
# add — subprocess + scope-as-move
# ---------------------------------------------------------------------------

def _make_global_skill(home: Path, name: str) -> Path:
    skill_dir = home / ".claude" / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\n---\n# Body\n", encoding="utf-8")
    return skill_dir


def test_add_global_scope_returns_global_path(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    captured: dict = {}

    def _capture(args, **kwargs):
        captured["args"] = args
        _make_global_skill(fake_home, "playwright-e2e")
        return _completed_process(stdout="installed")

    with patch("sumo_qa.qaskills.subprocess.run", side_effect=_capture), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        result = qaskills.add("playwright-e2e", scope="global", project_root=tmp_path / "project")

    # Real CLI shape: no --json, no --project. We pass `-a claude-code` only.
    assert "add" in captured["args"]
    assert "playwright-e2e" in captured["args"]
    assert "-a" in captured["args"]
    assert "claude-code" in captured["args"]
    assert "--project" not in captured["args"]
    assert "--json" not in captured["args"]

    assert result.scope == "global"
    assert result.installed_at == fake_home / ".claude" / "skills" / "playwright-e2e"
    assert result.name == "playwright-e2e"


def test_add_project_scope_relocates_directory(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    def _install_globally(args, **kwargs):
        _make_global_skill(fake_home, "axe-accessibility")
        return _completed_process(stdout="installed")

    with patch("sumo_qa.qaskills.subprocess.run", side_effect=_install_globally), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        result = qaskills.add("axe-accessibility", scope="project", project_root=project_root)

    project_target = project_root / ".claude" / "skills" / "axe-accessibility"
    assert result.scope == "project"
    assert result.installed_at == project_target
    assert (project_target / "SKILL.md").is_file()
    # Global directory was moved, not copied.
    assert not (fake_home / ".claude" / "skills" / "axe-accessibility").exists()


def test_add_project_scope_refuses_to_overwrite_existing(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    project_root = tmp_path / "project"
    (project_root / ".claude" / "skills" / "playwright-e2e").mkdir(parents=True)
    (project_root / ".claude" / "skills" / "playwright-e2e" / "SKILL.md").write_text(
        "local edits", encoding="utf-8"
    )
    monkeypatch.setenv("HOME", str(fake_home))

    def _install(args, **kwargs):
        _make_global_skill(fake_home, "playwright-e2e")
        return _completed_process(stdout="installed")

    with patch("sumo_qa.qaskills.subprocess.run", side_effect=_install), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        with pytest.raises(qaskills.QaskillsCLIError) as exc_info:
            qaskills.add("playwright-e2e", scope="project", project_root=project_root)

    assert "already exists" in str(exc_info.value)


def test_add_rejects_invalid_scope() -> None:
    with pytest.raises(ValueError) as exc_info:
        qaskills.add("playwright-e2e", scope="elsewhere")  # type: ignore[arg-type]
    assert "elsewhere" in str(exc_info.value)


def test_add_raises_cli_error_on_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed_process("", returncode=1, stderr="network down")), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        with pytest.raises(qaskills.QaskillsCLIError) as exc_info:
            qaskills.add("playwright-e2e", scope="global")
    assert "network down" in str(exc_info.value)


def test_add_raises_when_install_succeeded_but_dir_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    with patch("sumo_qa.qaskills.subprocess.run", return_value=_completed_process(stdout="ok")), \
         patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx"):
        with pytest.raises(qaskills.QaskillsCLIError) as exc_info:
            qaskills.add("ghost", scope="global")
    assert "no skill directory" in str(exc_info.value)
