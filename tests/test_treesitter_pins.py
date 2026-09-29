# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Guard the ``[treesitter]`` extra's version pins across their two homes.

The extra is declared in ``pyproject.toml`` and repeated in the pre-push
``pytest`` hook's ``additional_dependencies`` (pre-commit hook venvs cannot
install extras). Dependabot only edits ``pyproject.toml``, so the hook copy
drifts silently unless something compares them (#489 bumped ``tree-sitter``
to ``<0.27`` in pyproject and left the hook at ``<0.26``).

``tree-sitter-language-pack`` 1.14.1 and 1.14.2 shipped without the
``windows-x86_64`` prebuilt parsers, so every repo-map test failed on Windows
with ``DownloadError`` at runtime (#595). Upstream restored them in 1.14.3
(xberg-io/tree-sitter-language-pack#174); the pin excludes the two broken
releases so no resolver can land on them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover -- 3.10 backport path
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]

WINDOWS_PARSERLESS_RELEASES = ("1.14.1", "1.14.2")


def _dist_name(requirement: str) -> str:
    return canonicalize_name(Requirement(requirement).name)


def _pyproject_treesitter_extra() -> list[str]:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["project"]["optional-dependencies"]["treesitter"]


def _pytest_hook_treesitter_deps() -> list[str]:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = [hook for repo in config["repos"] for hook in repo["hooks"] if hook["id"] == "pytest"]
    assert len(hooks) == 1, "expected exactly one pre-push pytest hook"
    return [
        dep
        for dep in hooks[0]["additional_dependencies"]
        if _dist_name(dep).startswith("tree-sitter")
    ]


def test_pytest_hook_pins_match_treesitter_extra() -> None:
    assert sorted(_pytest_hook_treesitter_deps()) == sorted(_pyproject_treesitter_extra())


def test_language_pack_excludes_windows_parserless_releases() -> None:
    (language_pack,) = [
        Requirement(req)
        for req in _pyproject_treesitter_extra()
        if _dist_name(req) == "tree-sitter-language-pack"
    ]
    for release in WINDOWS_PARSERLESS_RELEASES:
        assert release not in language_pack.specifier, f"{language_pack} must exclude {release}"
