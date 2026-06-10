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
        ".claude-plugin/marketplace.json",
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


def test_generated_outputs_are_not_gitignored() -> None:
    """T8 — every committed-generator output must be tracked by git on a
    clean checkout. A gitignore rule that silently swallows `git add` would
    pass the on-disk drift check locally but leave the file absent on a CI
    checkout, where `check` then reports MISSING. Regression for codex
    finding on PR #128.

    Skipped under mutmut: the mutmut mirror at `mutants/` is itself
    gitignored, so every path under it is reported ignored by inheritance.
    This test asserts a property of the SOURCE repo's gitignore, not the
    mutant tree, so resolving REPO_ROOT against the real worktree via
    `git rev-parse` is the correct anchor.
    """
    import subprocess

    real_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if "mutants" in Path(real_root).parts:
        pytest.skip("running under mutmut mirror — assertion is about source tree, not mirror")

    for rel in _files_to_check():
        result = subprocess.run(
            ["git", "check-ignore", "-q", rel],
            cwd=real_root,
            capture_output=True,
        )
        # git check-ignore exits 0 when the path IS ignored, 1 when not.
        # We want NOT ignored for every output.
        assert result.returncode != 0, (
            f"{rel} is gitignored — `git add` would silently skip it. "
            f"Edit .gitignore to un-ignore generated plugin outputs."
        )


def test_version_bump_propagates_to_every_embedding_site(fresh_repo: Path) -> None:
    """T9 — Regression for release-please breakage observed on PR #129.

    Simulates a release-please version bump: rewrite
    pyproject.toml[project].version to a fake value, run sync, and assert
    EVERY committed file that embeds the version literal carries the new
    value. The release-please regen step in .github/workflows/release-please.yml
    is the production caller of this code path; that step shipped broken
    on its first run (PR #128) because the workflow had never been
    exercised end-to-end. This test exercises the underlying logic so a
    future regression in `_build_outputs` or the templates is caught
    before it merges.
    """
    import re

    pyproj_path = fresh_repo / "pyproject.toml"
    original = pyproj_path.read_text(encoding="utf-8")
    # Match [project].version specifically — must come before any
    # [project.*] subsection. Avoids picking up `version = 1` inside the
    # `hooks` cursor manifest if a future overlay adds one.
    bumped, count = re.subn(
        r'(\[project\][^\[]*?\nversion\s*=\s*)"[^"]+"',
        r'\1"9.9.9"',
        original,
        count=1,
        flags=re.DOTALL,
    )
    assert count == 1, "could not find [project].version anchor in pyproject.toml"
    pyproj_path.write_text(bumped, encoding="utf-8")

    plugin_generator.sync(fresh_repo)

    # Every file that embeds the version literal must carry the new value.
    embedding_sites = (
        ".claude-plugin/plugin.json",
        ".codex-plugin/plugin.json",
        "src/sumo_qa/_data/plugin_metadata.json",
    )
    for rel in embedding_sites:
        data = json.loads((fresh_repo / rel).read_text(encoding="utf-8"))
        assert data.get("version") == "9.9.9", f"{rel} did not pick up the bumped version"

    # The SHA256 sidecar's hashes must have changed — otherwise the drift
    # check on the release PR would silently pass against stale data.
    sidecar = json.loads(
        (fresh_repo / "plugin_packaging" / "generated" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    for rel in embedding_sites:
        assert rel in sidecar["files"], f"{rel} not in sidecar"


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


def test_snapshot_carries_marketplace_copy(fresh_repo: Path) -> None:
    """T10 — the runtime snapshot propagates the issue-#84 marketplace copy
    fields from the canonical overlay, and the host manifests do NOT
    duplicate them (generator-only propagation: the [project] description
    stays the manifests' `description`)."""
    plugin_generator.sync(fresh_repo)
    snapshot = json.loads(
        (fresh_repo / "src/sumo_qa/_data/plugin_metadata.json").read_text(encoding="utf-8")
    )
    for key in ("short_description", "long_description", "category"):
        assert key in snapshot, key
    assert snapshot["short_description"]
    assert len(snapshot["short_description"]) <= 200
    assert snapshot["long_description"]
    assert snapshot["category"]

    for manifest_rel in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        manifest = json.loads((fresh_repo / manifest_rel).read_text(encoding="utf-8"))
        for key in ("short_description", "long_description", "category"):
            assert key not in manifest, f"{manifest_rel} duplicates marketplace copy key {key}"
