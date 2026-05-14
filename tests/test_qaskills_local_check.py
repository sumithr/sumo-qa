# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

from pathlib import Path

from sumo_qa import qaskills


def _make_skill_dir(root: Path, name: str) -> Path:
    skill_dir = root / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\n---\n# Body\n", encoding="utf-8")
    return skill_dir


def test_is_installed_locally_finds_global(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    skill_dir = _make_skill_dir(fake_home / ".claude", "playwright-e2e")

    location = qaskills.is_installed_locally("playwright-e2e", project_root=tmp_path / "project")

    assert location is not None
    assert location.scope == "global"
    assert location.path == skill_dir / "SKILL.md"


def test_is_installed_locally_finds_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "elsewhere"))
    project_root = tmp_path / "project"
    skill_dir = _make_skill_dir(project_root / ".claude", "axe-accessibility")

    location = qaskills.is_installed_locally("axe-accessibility", project_root=project_root)

    assert location is not None
    assert location.scope == "project"
    assert location.path == skill_dir / "SKILL.md"


def test_is_installed_locally_prefers_project_over_global(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    project_root = tmp_path / "project"
    _make_skill_dir(fake_home / ".claude", "playwright-e2e")
    project_skill = _make_skill_dir(project_root / ".claude", "playwright-e2e")

    location = qaskills.is_installed_locally("playwright-e2e", project_root=project_root)

    assert location is not None
    assert location.scope == "project"
    assert location.path == project_skill / "SKILL.md"


def test_is_installed_locally_returns_none_when_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert qaskills.is_installed_locally("not-installed", project_root=tmp_path / "project") is None
