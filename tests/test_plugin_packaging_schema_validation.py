# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for plugin_packaging.validate_plugins.

Covers:
  T1 — Generated .claude-plugin/plugin.json validates against vendored schema
  T2 — Generated hooks/hooks-codex.json validates against vendored schema
  T3 — validate_plugins.main() exits 0 on a clean tree
  T4 — Injecting a wrong-typed field surfaces SchemaValidationError
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from plugin_packaging import plugin_generator, validate_plugins

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fresh_repo(tmp_path: Path) -> Path:
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
    plugin_generator.sync(dest)
    return dest


def test_claude_code_manifest_validates(fresh_repo: Path) -> None:
    """T1 — manifest validates against the published JSON Schema."""
    validate_plugins.validate_claude_code(fresh_repo)


def test_codex_hooks_validates(fresh_repo: Path) -> None:
    """T2 — Codex hooks file validates against the Codex hooks schema."""
    validate_plugins.validate_codex_hooks(fresh_repo)


def test_main_returns_zero_on_clean_tree(fresh_repo: Path) -> None:
    """T3 — main() returns 0 when both validations pass."""
    assert validate_plugins.main(["--repo-root", str(fresh_repo)]) == 0


def test_wrong_typed_field_fails(fresh_repo: Path) -> None:
    """T4 — Setting keywords to a string instead of array fails validation."""
    manifest_path = fresh_repo / ".claude-plugin" / "plugin.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["keywords"] = "not-an-array"
    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(validate_plugins.SchemaValidationError):
        validate_plugins.validate_claude_code(fresh_repo)


def test_main_returns_nonzero_when_invalid(fresh_repo: Path) -> None:
    """T4b — main() exits non-zero when a validator raises."""
    manifest_path = fresh_repo / ".claude-plugin" / "plugin.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["keywords"] = "not-an-array"
    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    assert validate_plugins.main(["--repo-root", str(fresh_repo)]) != 0
