# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Guard that every dependency pinned in a git hook mirrors ``pyproject.toml``.

pre-commit hook venvs install from PyPI, so a hook that needs project
dependencies repeats them in its ``additional_dependencies``. Those copies
drift: Dependabot only ever edits ``pyproject.toml``, so every bump it raises
for a package a hook also lists is half a change until the hook moves too.
Each file is individually valid, so running either config cannot reveal the
disagreement; this guard compares the declarations.

The rule: for every hook in ``.pre-commit-config.yaml`` with
``additional_dependencies``, each entry whose package (canonical name) is also
declared in ``pyproject.toml`` (``[project].dependencies`` or any
``[project.optional-dependencies]`` group) must carry an equal specifier set.
A hook entry for a package pyproject does not declare is out of scope. A
package pyproject declares in several places with different specifiers is a
failure: there is no single source of truth to mirror.

Environment markers and extras are deliberately ignored. A marker says WHERE a
dependency installs, not WHICH versions are allowed, and the two files have
legitimately different reasons to condition an install (``tomli`` is
``; python_version < '3.11'`` in the hooks but unconditional in the ``dev``
extra, because mypy type-checks the 3.10 branch on every interpreter).

ruff is the one explicit special case: its hook pin is the ruff-pre-commit
repo's ``rev: v<version>``, not an ``additional_dependencies`` entry, and it
must equal the ``ruff==<version>`` pin in pyproject.

The check is version-agnostic: it hard-codes no version, only asserts that the
sites agree, and it reports every mismatch in one failure.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover -- 3.10 backport path
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = "pyproject.toml"
PRECOMMIT = ".pre-commit-config.yaml"
RUFF_REPO = "https://github.com/astral-sh/ruff-pre-commit"


@dataclass(frozen=True)
class Declaration:
    """One declared requirement: where it lives, what it says, and what it allows."""

    site: str
    raw: str
    specifier: SpecifierSet


def pyproject_declarations(pyproject: dict[str, Any]) -> dict[str, list[Declaration]]:
    """Map each canonical package name to every pyproject declaration of it."""
    project = pyproject.get("project", {})
    sources = [(f"{PYPROJECT} [project].dependencies", project.get("dependencies", []))]
    for group, requirements in project.get("optional-dependencies", {}).items():
        sources.append((f"{PYPROJECT} [project.optional-dependencies].{group}", requirements))
    declarations: dict[str, list[Declaration]] = {}
    for site, requirements in sources:
        for raw in requirements:
            req = Requirement(raw)
            declarations.setdefault(canonicalize_name(req.name), []).append(
                Declaration(site=site, raw=raw, specifier=req.specifier)
            )
    return declarations


def _ambiguity(package: str, declarations: list[Declaration]) -> str | None:
    if len({decl.specifier for decl in declarations}) <= 1:
        return None
    listed = "\n".join(f"  {decl.site}: {decl.raw!r}" for decl in declarations)
    return (
        f"{package} is declared in {PYPROJECT} with different specifiers, so there is "
        f"no single source of truth for {PRECOMMIT} to mirror:\n{listed}\n"
        f"Make the {PYPROJECT} declarations agree first."
    )


def hook_dependency_mismatches(pyproject: dict[str, Any], precommit: dict[str, Any]) -> list[str]:
    """Every hook ``additional_dependencies`` entry that disagrees with pyproject."""
    declarations = pyproject_declarations(pyproject)
    messages: list[str] = []
    reported_ambiguous: set[str] = set()
    for repo in precommit.get("repos", []):
        for hook in repo.get("hooks", []):
            for raw in hook.get("additional_dependencies", []):
                req = Requirement(raw)
                package = canonicalize_name(req.name)
                if package not in declarations:
                    continue
                ambiguity = _ambiguity(package, declarations[package])
                if ambiguity is not None:
                    if package not in reported_ambiguous:
                        reported_ambiguous.add(package)
                        messages.append(ambiguity)
                    continue
                source = declarations[package][0]
                if source.specifier == req.specifier:
                    continue
                messages.append(
                    f"{package} pins disagree:\n"
                    f"  {source.site}: {source.raw!r}\n"
                    f"  {PRECOMMIT} hook {hook['id']!r} additional_dependencies: {raw!r}"
                )
    return messages


def ruff_rev_mismatch(pyproject: dict[str, Any], precommit: dict[str, Any]) -> str | None:
    """Compare the ruff-pre-commit ``rev: v<version>`` with pyproject's ``ruff==``."""
    site = f"{PRECOMMIT} rev: of {RUFF_REPO}"
    repos = [repo for repo in precommit.get("repos", []) if repo.get("repo") == RUFF_REPO]
    if len(repos) != 1:
        return f"{site}: expected exactly one repo entry, found {len(repos)}"
    raw_rev = repos[0].get("rev")
    version: Version | None = None
    if isinstance(raw_rev, str) and raw_rev.startswith("v"):
        try:
            version = Version(raw_rev.removeprefix("v"))
        except InvalidVersion:
            version = None
    if version is None:
        return (
            f"{site}: expected a string tag 'v<version>', got {raw_rev!r} "
            f"({type(raw_rev).__name__}); a frozen commit SHA or an unquoted YAML number "
            f"cannot be compared with the ruff pin in {PYPROJECT}."
        )
    declarations = pyproject_declarations(pyproject).get("ruff", [])
    if not declarations:
        return f"{site}: {PYPROJECT} declares no ruff requirement to compare {raw_rev!r} with"
    ambiguity = _ambiguity("ruff", declarations)
    if ambiguity is not None:
        return ambiguity
    source = declarations[0]
    if source.specifier == SpecifierSet(f"=={version}"):
        return None
    return f"ruff pins disagree:\n  {source.site}: {source.raw!r}\n  {site}: {raw_rev!r}"


def lockstep_mismatches(pyproject: dict[str, Any], precommit: dict[str, Any]) -> list[str]:
    """All disagreements between the two files, ruff rev first."""
    ruff = ruff_rev_mismatch(pyproject, precommit)
    return ([ruff] if ruff else []) + hook_dependency_mismatches(pyproject, precommit)


def test_repo_hook_pins_mirror_pyproject() -> None:
    pyproject = tomllib.loads((REPO_ROOT / PYPROJECT).read_text(encoding="utf-8"))
    precommit = yaml.safe_load((REPO_ROOT / PRECOMMIT).read_text(encoding="utf-8"))
    messages = lockstep_mismatches(pyproject, precommit)
    if messages:
        pytest.fail(
            f"{len(messages)} pin mismatch(es) between {PYPROJECT} and {PRECOMMIT}; "
            f"move each pair together in one commit:\n\n" + "\n\n".join(messages),
            pytrace=False,
        )


# Synthetic documents shaped like the two real files, so the guard's own
# discrimination is proven independently of whatever versions the repo pins.
# Each case builds only the declarations it needs.


def _pyproject(dependencies: list[str] | None = None, **groups: list[str]) -> dict[str, Any]:
    return {"project": {"dependencies": dependencies or [], "optional-dependencies": groups}}


def _precommit(*repos: dict[str, Any]) -> dict[str, Any]:
    return {"repos": list(repos)}


def _ruff_repo(rev: Any) -> dict[str, Any]:
    return {"repo": RUFF_REPO, "rev": rev, "hooks": [{"id": "ruff-check"}]}


def _local(**hook_deps: list[str]) -> dict[str, Any]:
    return {
        "repo": "local",
        "hooks": [
            {"id": hook_id, "additional_dependencies": deps} for hook_id, deps in hook_deps.items()
        ],
    }


def test_agreeing_hook_dependency_passes() -> None:
    # Clause order, spacing and name spelling do not change meaning.
    pyproject = _pyproject(dev=["mutmut>=3.8,<3.9", "PyYAML>=6,<7"])
    precommit = _precommit(_local(mutmut=["mutmut <3.9, >=3.8", "pyyaml>=6,<7"]))
    assert hook_dependency_mismatches(pyproject, precommit) == []


def test_disagreeing_hook_dependency_names_both_sites_and_values() -> None:
    pyproject = _pyproject(dev=["mutmut>=3.8,<3.9"])
    precommit = _precommit(_local(mutmut=["mutmut>=3.7,<3.8"]))
    [message] = hook_dependency_mismatches(pyproject, precommit)
    assert f"{PYPROJECT} [project.optional-dependencies].dev: 'mutmut>=3.8,<3.9'" in message
    assert f"{PRECOMMIT} hook 'mutmut' additional_dependencies: 'mutmut>=3.7,<3.8'" in message


def test_every_mismatch_is_reported_together() -> None:
    pyproject = _pyproject(["pydantic>=2.8,<3"], dev=["pytest-cov>=6,<8"], ts=["tree-sitter>=1,<2"])
    precommit = _precommit(
        _local(
            mutmut=["pytest-cov>=6,<7", "pydantic>=2.8,<3"],
            pytest=["pytest-cov>=6,<7", "tree-sitter>=1,<1.5"],
        )
    )
    messages = hook_dependency_mismatches(pyproject, precommit)
    assert len(messages) == 3
    joined = "\n".join(messages)
    assert "hook 'mutmut' additional_dependencies: 'pytest-cov>=6,<7'" in joined
    assert "hook 'pytest' additional_dependencies: 'pytest-cov>=6,<7'" in joined
    assert "hook 'pytest' additional_dependencies: 'tree-sitter>=1,<1.5'" in joined


def test_hook_dependency_absent_from_pyproject_is_ignored() -> None:
    pyproject = _pyproject(dev=["pytest>=8"])
    precommit = _precommit(_local(pytest=["hatchling>=1.25", "tzdata"]))
    assert hook_dependency_mismatches(pyproject, precommit) == []


def test_marker_only_difference_passes() -> None:
    pyproject = _pyproject(dev=["tomli>=2,<3"])
    precommit = _precommit(_local(pytest=["tomli>=2,<3; python_version < '3.11'"]))
    assert hook_dependency_mismatches(pyproject, precommit) == []


def test_ambiguous_pyproject_declarations_fail_naming_each() -> None:
    pyproject = _pyproject(["tomli>=2,<3"], dev=["tomli>=2,<4"])
    precommit = _precommit(_local(mutmut=["tomli>=2,<3"], pytest=["tomli>=2,<3"]))
    [message] = hook_dependency_mismatches(pyproject, precommit)
    assert "no single source of truth" in message
    assert f"{PYPROJECT} [project].dependencies: 'tomli>=2,<3'" in message
    assert f"{PYPROJECT} [project.optional-dependencies].dev: 'tomli>=2,<4'" in message


def test_agreeing_ruff_rev_passes() -> None:
    # The rev tag's leading `v` is not part of the version.
    pyproject = _pyproject(dev=["ruff==1.2.3"])
    assert ruff_rev_mismatch(pyproject, _precommit(_ruff_repo("v1.2.3"))) is None


def test_disagreeing_ruff_rev_names_both_sites_and_values() -> None:
    pyproject = _pyproject(dev=["ruff==1.2.4"])
    message = ruff_rev_mismatch(pyproject, _precommit(_ruff_repo("v1.2.3")))
    assert message is not None
    assert f"{PYPROJECT} [project.optional-dependencies].dev: 'ruff==1.2.4'" in message
    assert f"{PRECOMMIT} rev: of {RUFF_REPO}: 'v1.2.3'" in message


def test_missing_ruff_repo_fails_loudly() -> None:
    """A renamed or dropped ruff repo must not turn the guard into a silent no-op."""
    pyproject = _pyproject(dev=["ruff==1.2.3"])
    messages = lockstep_mismatches(pyproject, _precommit(_local(pytest=["ruff==1.2.3"])))
    assert messages == [
        f"{PRECOMMIT} rev: of {RUFF_REPO}: expected exactly one repo entry, found 0"
    ]


@pytest.mark.parametrize(
    "rev",
    [
        # `pre-commit autoupdate --freeze` writes a commit SHA.
        "0123456789abcdef0123456789abcdef01234567",
        # An unquoted `rev: 1.10` parses as the float 1.1.
        1.1,
        "vnot-a-version",
    ],
)
def test_ruff_rev_that_is_not_a_version_tag_fails_clearly(rev: Any) -> None:
    pyproject = _pyproject(dev=["ruff==1.2.3"])
    message = ruff_rev_mismatch(pyproject, _precommit(_ruff_repo(rev)))
    assert message is not None
    assert f"{PRECOMMIT} rev: of {RUFF_REPO}" in message
    assert repr(rev) in message


def test_ruff_rev_without_a_pyproject_ruff_pin_fails() -> None:
    message = ruff_rev_mismatch(_pyproject(dev=["pytest>=8"]), _precommit(_ruff_repo("v1.2.3")))
    assert message == (
        f"{PRECOMMIT} rev: of {RUFF_REPO}: {PYPROJECT} declares no ruff requirement "
        f"to compare 'v1.2.3' with"
    )


def test_ambiguous_ruff_declarations_fail() -> None:
    pyproject = _pyproject(dev=["ruff==1.2.3"], lint=["ruff==1.2.4"])
    message = ruff_rev_mismatch(pyproject, _precommit(_ruff_repo("v1.2.3")))
    assert message is not None
    assert "no single source of truth" in message


def test_ruff_and_hook_mismatches_are_reported_together() -> None:
    pyproject = _pyproject(dev=["ruff==1.2.4", "pytest-cov>=6,<8"])
    precommit = _precommit(_ruff_repo("v1.2.3"), _local(pytest=["pytest-cov>=6,<7"]))
    messages = lockstep_mismatches(pyproject, precommit)
    assert [message.splitlines()[0] for message in messages] == [
        "ruff pins disagree:",
        "pytest-cov pins disagree:",
    ]
