# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Guard that toolchain pins declared in two files stay in lockstep.

Some tools are pinned twice: once in ``pyproject.toml`` (what a synced venv
and CI install) and once in ``.pre-commit-config.yaml`` (what the git hooks
install). Dependabot only ever edits ``pyproject.toml``, so every bump it
raises for one of these tools is half a change until the second site moves
too. Each site is individually valid, so running either config cannot reveal
the disagreement; this guard compares the two declared version strings.

The check is version-agnostic: it never hard-codes a version, it asserts the
two sites agree. ``LOCKSTEP_PAIRS`` is the table of pairs. A new lockstep pair
is one row: a label plus one site reader per file, built from the readers
below (``pyproject_dev_pin``, ``precommit_repo_rev``, ``precommit_hook_dep``).
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover -- 3.10 backport path
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = "pyproject.toml"
PRECOMMIT = ".pre-commit-config.yaml"


@dataclass(frozen=True)
class Pin:
    """One declared pin: where it lives, what it says, and what it means."""

    site: str
    raw: str
    specifier: SpecifierSet


# A site reader takes the parsed ``pyproject.toml`` and ``.pre-commit-config.yaml``
# documents and returns the pin declared at that site.
SiteReader = Callable[[dict[str, Any], dict[str, Any]], Pin]


def _requirement_pin(site: str, raw: str, package: str) -> Pin:
    req = Requirement(raw)
    assert req.name.lower() == package.lower(), (
        f"{site}: expected a {package} requirement, got {raw!r}"
    )
    return Pin(site=site, raw=raw, specifier=req.specifier)


def pyproject_dev_pin(package: str) -> SiteReader:
    """Read ``package``'s requirement from pyproject's ``dev`` optional extra."""

    def read(pyproject: dict[str, Any], _precommit: dict[str, Any]) -> Pin:
        site = f"{PYPROJECT} [project.optional-dependencies].dev"
        matches = [
            raw
            for raw in pyproject["project"]["optional-dependencies"]["dev"]
            if Requirement(raw).name.lower() == package.lower()
        ]
        assert len(matches) == 1, f"{site}: expected exactly one {package} entry, found {matches!r}"
        return _requirement_pin(site, matches[0], package)

    return read


def precommit_repo_rev(repo_url: str) -> SiteReader:
    """Read the ``rev:`` of a pre-commit repo whose tag is ``v<version>``."""

    def read(_pyproject: dict[str, Any], precommit: dict[str, Any]) -> Pin:
        site = f"{PRECOMMIT} rev: of {repo_url}"
        revs = [str(repo["rev"]) for repo in precommit["repos"] if repo["repo"] == repo_url]
        assert len(revs) == 1, f"{site}: expected exactly one repo entry, found {len(revs)}"
        raw = revs[0]
        return Pin(site=site, raw=raw, specifier=SpecifierSet(f"=={raw.removeprefix('v')}"))

    return read


def precommit_hook_dep(hook_id: str, package: str) -> SiteReader:
    """Read ``package``'s entry from a pre-commit hook's ``additional_dependencies``."""

    def read(_pyproject: dict[str, Any], precommit: dict[str, Any]) -> Pin:
        site = f"{PRECOMMIT} hook {hook_id!r} additional_dependencies"
        hooks = [
            hook for repo in precommit["repos"] for hook in repo["hooks"] if hook["id"] == hook_id
        ]
        assert len(hooks) == 1, f"{site}: expected exactly one hook, found {len(hooks)}"
        matches = [
            raw
            for raw in hooks[0].get("additional_dependencies", [])
            if Requirement(raw).name.lower() == package.lower()
        ]
        assert len(matches) == 1, f"{site}: expected exactly one {package} entry, found {matches!r}"
        return _requirement_pin(site, matches[0], package)

    return read


@dataclass(frozen=True)
class LockstepPair:
    label: str
    first: SiteReader
    second: SiteReader


LOCKSTEP_PAIRS = (
    LockstepPair(
        "ruff",
        pyproject_dev_pin("ruff"),
        precommit_repo_rev("https://github.com/astral-sh/ruff-pre-commit"),
    ),
    LockstepPair("mutmut", pyproject_dev_pin("mutmut"), precommit_hook_dep("mutmut", "mutmut")),
)


def lockstep_mismatch(
    pair: LockstepPair, pyproject: dict[str, Any], precommit: dict[str, Any]
) -> str | None:
    """Return a fix-it message when the pair's two sites disagree, else ``None``."""
    first = pair.first(pyproject, precommit)
    second = pair.second(pyproject, precommit)
    if first.specifier == second.specifier:
        return None
    return (
        f"{pair.label} pins disagree:\n"
        f"  {first.site}: {first.raw!r}\n"
        f"  {second.site}: {second.raw!r}\n"
        f"Move both sites to the same version in one commit."
    )


def _load_repo_configs() -> tuple[dict[str, Any], dict[str, Any]]:
    pyproject = tomllib.loads((REPO_ROOT / PYPROJECT).read_text(encoding="utf-8"))
    precommit = yaml.safe_load((REPO_ROOT / PRECOMMIT).read_text(encoding="utf-8"))
    return pyproject, precommit


@pytest.mark.parametrize("pair", LOCKSTEP_PAIRS, ids=lambda pair: pair.label)
def test_repo_toolchain_pins_are_in_lockstep(pair: LockstepPair) -> None:
    pyproject, precommit = _load_repo_configs()
    message = lockstep_mismatch(pair, pyproject, precommit)
    if message is not None:
        pytest.fail(message, pytrace=False)


# Synthetic documents shaped like the two real files, so the guard's own
# discrimination is proven independently of whatever versions the repo pins.
RUFF_URL = "https://github.com/astral-sh/ruff-pre-commit"


def _pyproject(*dev: str) -> dict[str, Any]:
    return {"project": {"optional-dependencies": {"dev": list(dev)}}}


def _precommit(ruff_rev: str, mutmut_dep: str) -> dict[str, Any]:
    return {
        "repos": [
            {"repo": RUFF_URL, "rev": ruff_rev, "hooks": [{"id": "ruff-check"}]},
            {
                "repo": "local",
                "hooks": [
                    {"id": "mutmut", "additional_dependencies": ["hypothesis>=6,<7", mutmut_dep]},
                    {"id": "pytest", "additional_dependencies": ["hypothesis>=6,<7"]},
                ],
            },
        ]
    }


PAIRS_BY_LABEL = {pair.label: pair for pair in LOCKSTEP_PAIRS}


@pytest.mark.parametrize(
    ("label", "pyproject_raw", "precommit_ruff_rev", "precommit_mutmut_dep"),
    [
        # The rev tag's leading `v` is not part of the version.
        ("ruff", "ruff==1.2.3", "v1.2.3", "mutmut>=3,<4"),
        # Specifier clause order and spacing do not change meaning.
        ("mutmut", "mutmut>=3.8,<3.9", "v1.2.3", "mutmut <3.9, >=3.8"),
    ],
)
def test_agreeing_sites_pass(
    label: str, pyproject_raw: str, precommit_ruff_rev: str, precommit_mutmut_dep: str
) -> None:
    pyproject = _pyproject(pyproject_raw, "pytest>=8")
    precommit = _precommit(precommit_ruff_rev, precommit_mutmut_dep)
    assert lockstep_mismatch(PAIRS_BY_LABEL[label], pyproject, precommit) is None


@pytest.mark.parametrize(
    (
        "label",
        "pyproject_raw",
        "precommit_ruff_rev",
        "precommit_mutmut_dep",
        "first_raw",
        "second_raw",
    ),
    [
        # One patch apart: the half-applied dependabot ruff bump.
        ("ruff", "ruff==1.2.4", "v1.2.3", "mutmut>=3,<4", "'ruff==1.2.4'", "'v1.2.3'"),
        # Ceiling moved on one side only: the half-applied dependabot mutmut bump.
        (
            "mutmut",
            "mutmut>=3.8,<3.9",
            "v1.2.3",
            "mutmut>=3.8,<3.8.1",
            "'mutmut>=3.8,<3.9'",
            "'mutmut>=3.8,<3.8.1'",
        ),
    ],
)
def test_disagreeing_sites_name_both_files_and_values(
    label: str,
    pyproject_raw: str,
    precommit_ruff_rev: str,
    precommit_mutmut_dep: str,
    first_raw: str,
    second_raw: str,
) -> None:
    pyproject = _pyproject(pyproject_raw, "pytest>=8")
    precommit = _precommit(precommit_ruff_rev, precommit_mutmut_dep)
    message = lockstep_mismatch(PAIRS_BY_LABEL[label], pyproject, precommit)
    assert message is not None
    assert PYPROJECT in message
    assert PRECOMMIT in message
    assert first_raw in message
    assert second_raw in message


def test_a_missing_site_fails_loudly_instead_of_passing() -> None:
    """A renamed hook or dropped pin must not turn the guard into a silent no-op."""
    pyproject = _pyproject("ruff==1.2.3")
    precommit = _precommit("v1.2.3", "mutmut>=3,<4")
    with pytest.raises(AssertionError, match="expected exactly one mutmut entry"):
        lockstep_mismatch(PAIRS_BY_LABEL["mutmut"], pyproject, precommit)
