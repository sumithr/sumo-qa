# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.plugin_metadata.

Covers:
  T1 — Loads the bundled snapshot via importlib.resources
  T2 — Frozen dataclass — no mutation possible
  T3 — Logical fields surface (name, version, mcp_server_name, etc.)
  T4 — Snapshot version matches pyproject [project].version
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover -- 3.10 backport path
    import tomli as tomllib

from sumo_qa import plugin_metadata


def test_from_bundle_returns_frozen_dataclass() -> None:
    """T1+T2 — Loads via importlib.resources, frozen."""
    meta = plugin_metadata.PluginMetadata.from_bundle()
    assert isinstance(meta, plugin_metadata.PluginMetadata)
    with pytest.raises(dataclasses.FrozenInstanceError):
        meta.name = "changed"  # type: ignore[misc]


def test_required_fields_present() -> None:
    """T3 — Logical fields populated."""
    meta = plugin_metadata.PluginMetadata.from_bundle()
    assert meta.name == "sumo-qa"
    assert meta.mcp_server_name == "sumo-qa"
    assert meta.version
    assert meta.description


def test_version_matches_project_version() -> None:
    """T4 — Snapshot must match pyproject [project].version so a version
    bump that doesn't re-run the generator is caught."""
    repo_root = Path(__file__).resolve().parents[1]
    pyproj = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    meta = plugin_metadata.PluginMetadata.from_bundle()
    assert meta.version == pyproj["project"]["version"]
