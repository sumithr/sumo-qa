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


def test_posix_global_root(tmp_path, monkeypatch):
    # _posix_global_root is platform-independent path logic, so it's testable on
    # any host (no os.name flip, which would break pathlib's Path class choice).
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert paths._posix_global_root() == tmp_path / ".local" / "share" / "sumo-qa"


def test_windows_global_root_uses_localappdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    assert paths._windows_global_root() == tmp_path / "appdata" / "sumo-qa"


def test_windows_global_root_falls_back_to_home_appdata(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert paths._windows_global_root() == tmp_path / "AppData" / "Local" / "sumo-qa"


def test_unknown_scope_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown scope"):
        paths.user_pack_root("nope")


def test_subpaths_mirror_bundled_layout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / ".sumo-qa"
    assert paths.knowledge_dir("project") == root / "knowledge"
    assert paths.standards_packs_dir("project") == root / "standards" / "packs"
    assert paths.rules_path("project") == root / "standards" / "rules" / "change_rules.yaml"


def test_export_dir_project_is_under_pack_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert paths.export_dir("project") == paths.user_pack_root("project") / "exports"
    assert paths.export_dir("project") == tmp_path / ".sumo-qa" / "exports"


def test_export_dir_global_is_under_global_root(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.export_dir("global") == paths.user_pack_root("global") / "exports"


def test_export_dir_unknown_scope_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown scope"):
        paths.export_dir("nope")
