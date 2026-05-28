# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for release-please configuration."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_release_please_updates_generated_version_snapshots() -> None:
    """The initial release PR commit must not expose stale generated versions."""
    config = json.loads((REPO_ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    extra_files = config["packages"]["."]["extra-files"]

    version_updaters = {
        entry["path"]: entry["jsonpath"]
        for entry in extra_files
        if isinstance(entry, dict) and entry.get("type") == "json"
    }

    expected = {
        ".claude-plugin/plugin.json": "$.version",
        ".codex-plugin/plugin.json": "$.version",
        "src/sumo_qa/_data/plugin_metadata.json": "$.version",
    }

    assert expected.items() <= version_updaters.items()
