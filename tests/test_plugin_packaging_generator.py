# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for plugin_packaging.plugin_generator.

Covers:
  T1 — sync writes all expected files
  T2 — sync is idempotent (running twice = no diff)
  T3 — check exits 0 when in sync
  T4 — check exits non-zero after mutating an overlay field
  T5 — check exits non-zero when SHA256 sidecar is tampered
  T6 — emitted JSON files contain no skill-body markdown headers
  T7 — generated JSON is deterministic (sorted keys, trailing newline)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from plugin_packaging import plugin_generator

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fresh_repo(tmp_path: Path) -> Path:
    """Mirror the repo into tmp_path so sync writes without disturbing the real tree."""
    dest = tmp_path / "repo"
    shutil.copytree(
        REPO_ROOT,
        dest,
        ignore=shutil.ignore_patterns(
            ".git",
            ".claude",
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            ".mutmut-cache",
            "mutants",
            "htmlcov",
            ".coverage*",
            "*.egg-info",
        ),
    )
    return dest


def _files_to_check() -> tuple[str, ...]:
    return (
        ".claude-plugin/plugin.json",
        ".codex-plugin/plugin.json",
        ".mcp.json",
        "hooks/hooks.json",
        "hooks/hooks-codex.json",
        "docs/host-adapters.md",
        "src/sumo_qa/_data/plugin_metadata.json",
        "plugin_packaging/generated/manifest.json",
    )


def test_sync_writes_all_files(fresh_repo: Path) -> None:
    """T1 — sync produces every file in the generator's output list."""
    plugin_generator.sync(fresh_repo)
    for rel in _files_to_check():
        assert (fresh_repo / rel).is_file(), rel


def test_sync_is_idempotent(fresh_repo: Path) -> None:
    """T2 — running sync twice does not change any file on the second pass."""
    plugin_generator.sync(fresh_repo)
    first = {rel: (fresh_repo / rel).read_bytes() for rel in _files_to_check()}
    plugin_generator.sync(fresh_repo)
    second = {rel: (fresh_repo / rel).read_bytes() for rel in _files_to_check()}
    assert first == second


def test_check_passes_when_in_sync(fresh_repo: Path) -> None:
    """T3 — check exits 0 immediately after a sync."""
    plugin_generator.sync(fresh_repo)
    assert plugin_generator.check(fresh_repo) == 0


def test_check_fails_after_mutation(fresh_repo: Path) -> None:
    """T4 — bumping the canonical overlay then check fails."""
    plugin_generator.sync(fresh_repo)
    pyproj = (fresh_repo / "pyproject.toml").read_text(encoding="utf-8")
    pyproj = pyproj.replace('display_name = "Sumo QA"', 'display_name = "Sumo QA mutated"')
    (fresh_repo / "pyproject.toml").write_text(pyproj, encoding="utf-8")
    assert plugin_generator.check(fresh_repo) != 0


def test_check_fails_when_sidecar_tampered(fresh_repo: Path) -> None:
    """T5 — manual edit of the SHA256 sidecar fails check."""
    plugin_generator.sync(fresh_repo)
    sidecar_path = fresh_repo / "plugin_packaging" / "generated" / "manifest.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    rel = next(iter(sidecar["files"]))
    sidecar["files"][rel] = "0" * 64
    sidecar_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert plugin_generator.check(fresh_repo) != 0


def test_no_skill_body_content_in_json(fresh_repo: Path) -> None:
    """T6 — generated JSON files contain no SKILL.md section headers."""
    plugin_generator.sync(fresh_repo)
    for rel in _files_to_check():
        if not rel.endswith(".json"):
            continue
        text = (fresh_repo / rel).read_text(encoding="utf-8")
        assert "## " not in text, rel


def test_emitted_json_is_deterministic(fresh_repo: Path) -> None:
    """T7 — JSON outputs have sorted keys and end with a single newline."""
    plugin_generator.sync(fresh_repo)
    for rel in _files_to_check():
        if not rel.endswith(".json"):
            continue
        raw = (fresh_repo / rel).read_bytes()
        assert raw.endswith(b"\n"), rel
        text = raw.decode("utf-8")
        loaded = json.loads(text)
        canonical_str = json.dumps(loaded, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        assert canonical_str == text, rel
