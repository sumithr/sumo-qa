# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.paths — scope-keyed user-pack directory resolution."""

from pathlib import Path

import pytest

from sumo_qa import paths


def test_project_root_is_cwd_dot_sumo_qa(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert paths.user_pack_root("project") == tmp_path / ".sumo-qa"


def test_global_root_honours_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.user_pack_root("global") == tmp_path / "xdg" / "sumo-qa"


def test_global_root_falls_back_to_local_share(tmp_path, monkeypatch):
    # On posix hosts (CI) XDG-absent falls back to ~/.local/share. The Windows
    # LOCALAPPDATA branch is platform-conditional (pragma: no cover) — it can't
    # be exercised here because flipping os.name to "nt" breaks pathlib on posix.
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert paths.user_pack_root("global") == tmp_path / ".local" / "share" / "sumo-qa"


def test_unknown_scope_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown scope"):
        paths.user_pack_root("nope")


def test_subpaths_mirror_bundled_layout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / ".sumo-qa"
    assert paths.knowledge_dir("project") == root / "knowledge"
    assert paths.standards_packs_dir("project") == root / "standards" / "packs"
    assert paths.rules_path("project") == root / "standards" / "rules" / "change_rules.yaml"
