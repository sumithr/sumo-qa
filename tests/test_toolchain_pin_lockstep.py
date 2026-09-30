# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Guard that every Python dependency pinned in a git hook mirrors ``pyproject.toml``.

The end of the module also guards the pre-push pytest hook the delivery skills
rely on as the full local suite: installed by default, run on every pre-push
stage, verbose, and with a bare ``pytest`` argv so addopts alone sets its
options (#773).

pre-commit hook venvs install from PyPI, so a hook that needs project
dependencies repeats them in its ``additional_dependencies``. Those copies
drift: Dependabot only ever edits ``pyproject.toml``, so every bump it raises
for a package a hook also lists is half a change until the hook moves too.
Each file is individually valid, so running either config cannot reveal the
disagreement; this guard compares the declarations.

Which entries are compared. A hook with an inline ``language`` other than
``python`` (``system``, ``node``, ...) is skipped. Every other hook, including
a remote-repo hook whose language lives in that repo's manifest, has each
``additional_dependencies`` entry checked on its own: an entry that does not
parse as a PEP 508 requirement is skipped, and a parsed entry is compared only
when ``pyproject.toml`` declares its package. In this repo the compared hooks
are the ``repo: local`` ``mutmut`` and ``pytest`` hooks (``language:
python``); the other local hooks are ``language: system`` and the remote hooks
carry no ``additional_dependencies``.

Where the source of truth lives. Hooks mirror the dev tooling, so a hook entry
is compared first with the optional-extra-equivalent declarations: every
``[project.optional-dependencies]`` group, every PEP 735 ``[dependency-groups]``
group (string entries only; ``{include-group = ...}`` tables are ignored) and
``[tool.uv].dev-dependencies``. Only when the package appears in none of those
is it compared with ``[project].dependencies``. A package the optional sources
declare with different specifiers or URLs fails as ambiguous, and so does a
package ``[project].dependencies`` declares twice under the same environment
marker with different pins. Runtime entries under different markers (a marker
split such as ``demo==1; python_version < '3.12'`` and ``demo==2;
python_version >= '3.12'``) are all candidates: the hook entry passes when it
matches any one of them. A hook entry for a package ``pyproject.toml`` does
not declare is out of scope.

What is compared. The specifier set and the direct-reference URL
(``pkg @ git+https://...@ref``). Environment markers and extras are ignored in
the comparison: a marker says WHERE a dependency installs, not WHICH versions
are allowed, and the two files have legitimately different reasons to
condition an install (``tomli`` is ``; python_version < '3.11'`` in the hooks
but unconditional in the ``dev`` extra, because mypy type-checks the 3.10
branch on every interpreter).

Anchored mirrors. Comparing only what both files happen to list would turn a
deleted pin into a silent pass, so ``REQUIRED_MIRRORS`` names the pairs that
must exist: each package must be declared exactly once in ``pyproject.toml``
and exactly once in the named Python hook's ``additional_dependencies``. A new
must-exist mirror is one row in that table.

ruff is the one explicit special case: its hook pin is the ruff-pre-commit
repo's ``rev: v<version>`` (exactly one such repo entry must exist), not an
``additional_dependencies`` entry, and it must equal the ``ruff==<version>``
pin in pyproject.

The pin check is version-agnostic: it hard-codes no version, only asserts that
the sites agree, and it reports every mismatch in one failure.
"""

from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml
from packaging.requirements import InvalidRequirement, Requirement
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
RUNTIME_SITE = f"{PYPROJECT} [project].dependencies"

# (package, hook id): each package must be declared exactly once in pyproject
# and exactly once in that Python hook's additional_dependencies.
REQUIRED_MIRRORS: tuple[tuple[str, str], ...] = (("mutmut", "mutmut"),)


@dataclass(frozen=True)
class Declaration:
    """One declared requirement: where it lives, what it says, and what it allows."""

    site: str
    raw: str
    specifier: SpecifierSet
    url: str | None
    marker: str | None

    @classmethod
    def parse(cls, site: str, raw: str) -> tuple[str, Declaration]:
        req = Requirement(raw)
        marker = str(req.marker) if req.marker is not None else None
        declaration = cls(site=site, raw=raw, specifier=req.specifier, url=req.url, marker=marker)
        return canonicalize_name(req.name), declaration

    @property
    def pin(self) -> tuple[SpecifierSet, str | None]:
        """What the declaration allows: the specifier set and any direct URL."""
        return self.specifier, self.url


@dataclass
class PyprojectPins:
    """pyproject parsed once: every declaration, each package's candidates, each ambiguity."""

    declarations: dict[str, list[Declaration]] = field(default_factory=dict)
    sources: dict[str, list[Declaration]] = field(default_factory=dict)
    ambiguities: dict[str, str] = field(default_factory=dict)


def _optional_sources(pyproject: dict[str, Any]) -> list[tuple[str, list[str]]]:
    project = pyproject.get("project", {})
    sources = [
        (f"{PYPROJECT} [project.optional-dependencies].{group}", list(requirements))
        for group, requirements in project.get("optional-dependencies", {}).items()
    ]
    for group, entries in pyproject.get("dependency-groups", {}).items():
        # PEP 735 `{include-group = ...}` tables add no requirement of their own.
        strings = [entry for entry in entries if isinstance(entry, str)]
        sources.append((f"{PYPROJECT} [dependency-groups].{group}", strings))
    uv_dev = pyproject.get("tool", {}).get("uv", {}).get("dev-dependencies", [])
    sources.append((f"{PYPROJECT} [tool.uv].dev-dependencies", list(uv_dev)))
    return sources


def _ambiguity_message(package: str, declarations: list[Declaration]) -> str:
    listed = "\n".join(f"  {decl.site}: {decl.raw!r}" for decl in declarations)
    return (
        f"{package} is declared in {PYPROJECT} with different specifiers, so there is "
        f"no single source of truth for {PRECOMMIT} to mirror:\n{listed}\n"
        f"Make the {PYPROJECT} declarations agree first."
    )


def _distinct(declarations: list[Declaration]) -> list[Declaration]:
    """The first declaration of each distinct pin, in declaration order."""
    by_pin: dict[tuple[SpecifierSet, str | None], Declaration] = {}
    for decl in declarations:
        by_pin.setdefault(decl.pin, decl)
    return list(by_pin.values())


def _resolve_runtime(package: str, runtime: list[Declaration], pins: PyprojectPins) -> None:
    """Every distinct runtime pin is a candidate, unless one marker carries two pins."""
    markers = [decl.marker for decl in _distinct(runtime)]
    if len(markers) != len(set(markers)):
        pins.ambiguities[package] = _ambiguity_message(package, runtime)
    else:
        pins.sources[package] = _distinct(runtime)


def parse_pyproject(pyproject: dict[str, Any]) -> PyprojectPins:
    """Map each package to its declarations, its candidate pins, or its ambiguity."""
    pins = PyprojectPins()
    optional: dict[str, list[Declaration]] = {}
    runtime: dict[str, list[Declaration]] = {}
    sites = [(RUNTIME_SITE, pyproject.get("project", {}).get("dependencies", []), runtime)]
    sites += [(site, reqs, optional) for site, reqs in _optional_sources(pyproject)]
    for site, requirements, bucket in sites:
        for raw in requirements:
            package, decl = Declaration.parse(site, raw)
            bucket.setdefault(package, []).append(decl)
            pins.declarations.setdefault(package, []).append(decl)
    for package, decls in optional.items():
        if len(_distinct(decls)) > 1:
            pins.ambiguities[package] = _ambiguity_message(package, decls)
        else:
            pins.sources[package] = _distinct(decls)
    for package, decls in runtime.items():
        if package not in optional:
            _resolve_runtime(package, decls, pins)
    return pins


def _python_requirements(hook: dict[str, Any]) -> list[tuple[str, Requirement]] | None:
    """Each entry that parses as PEP 508, or None when the hook's inline language is not Python."""
    if hook.get("language", "python") != "python":
        return None
    parsed: list[tuple[str, Requirement]] = []
    for raw in map(str, hook.get("additional_dependencies", [])):
        try:
            parsed.append((raw, Requirement(raw)))
        except InvalidRequirement:
            continue
    return parsed


def _hooks(precommit: dict[str, Any]) -> list[tuple[str | None, str, dict[str, Any]]]:
    """Every hook as (id or None, a label naming it, the hook mapping)."""
    hooks = []
    for repo in precommit.get("repos", []):
        for index, hook in enumerate(repo.get("hooks", [])):
            hook_id = hook.get("id")
            label = repr(hook_id) if hook_id else f"#{index} of repo {repo.get('repo')!r}"
            hooks.append((hook_id, label, hook))
    return hooks


def _disagreement(package: str, candidates: list[Declaration], site: str, value: str) -> str:
    listed = "".join(f"  {decl.site}: {decl.raw!r}\n" for decl in candidates)
    return f"{package} pins disagree:\n{listed}  {site}: {value!r}"


def hook_dependency_mismatches(pins: PyprojectPins, precommit: dict[str, Any]) -> list[str]:
    """Every Python hook ``additional_dependencies`` entry that disagrees with pyproject."""
    messages: list[str] = []
    reported_ambiguous: set[str] = set()
    for hook_id, label, hook in _hooks(precommit):
        if hook_id is None:
            messages.append(
                f"{PRECOMMIT} hook {label} has no 'id', so its pins cannot be named or compared"
            )
            continue
        requirements = _python_requirements(hook)
        if requirements is None:
            continue
        for raw, req in requirements:
            package = canonicalize_name(req.name)
            if package in pins.ambiguities:
                if package not in reported_ambiguous:
                    reported_ambiguous.add(package)
                    messages.append(pins.ambiguities[package])
                continue
            candidates = pins.sources.get(package, [])
            if not candidates or (req.specifier, req.url) in {decl.pin for decl in candidates}:
                continue
            messages.append(
                _disagreement(
                    package, candidates, f"{PRECOMMIT} hook {label} additional_dependencies", raw
                )
            )
    return messages


def required_mirror_mismatches(
    pins: PyprojectPins,
    precommit: dict[str, Any],
    required: tuple[tuple[str, str], ...] = REQUIRED_MIRRORS,
) -> list[str]:
    """Each anchored mirror that is missing (or duplicated) on either side."""
    messages: list[str] = []
    hooks = _hooks(precommit)
    for package, hook_id in required:
        declared = pins.declarations.get(package, [])
        if len(declared) != 1:
            found = "".join(f"\n  {decl.site}: {decl.raw!r}" for decl in declared)
            messages.append(
                f"{package} must be declared exactly once in {PYPROJECT} to anchor its "
                f"mirror in {PRECOMMIT} hook {hook_id!r}; found {len(declared)}{found}"
            )
        matching = [hook for found_id, _, hook in hooks if found_id == hook_id]
        site = f"{PRECOMMIT} hook {hook_id!r} additional_dependencies"
        if len(matching) != 1:
            messages.append(
                f"{site}: expected exactly one hook with id {hook_id!r} to mirror "
                f"{package} from {PYPROJECT}, found {len(matching)}"
            )
            continue
        requirements = _python_requirements(matching[0])
        if requirements is None:
            messages.append(f"{site}: hook {hook_id!r} must be a Python hook to mirror {package}")
            continue
        count = sum(canonicalize_name(req.name) == package for _, req in requirements)
        if count != 1:
            messages.append(
                f"{site}: must list {package} exactly once to mirror {PYPROJECT}, found {count}"
            )
    return messages


def ruff_rev_mismatch(pins: PyprojectPins, precommit: dict[str, Any]) -> str | None:
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
    if "ruff" in pins.ambiguities:
        return pins.ambiguities["ruff"]
    candidates = pins.sources.get("ruff", [])
    if not candidates:
        return f"{site}: {PYPROJECT} declares no ruff requirement to compare {raw_rev!r} with"
    if (SpecifierSet(f"=={version}"), None) in {decl.pin for decl in candidates}:
        return None
    return _disagreement("ruff", candidates, site, raw_rev)


def lockstep_mismatches(
    pyproject: dict[str, Any],
    precommit: dict[str, Any],
    required: tuple[tuple[str, str], ...] = REQUIRED_MIRRORS,
) -> list[str]:
    """All disagreements between the two files: ruff rev, missing mirrors, then hook pins."""
    pins = parse_pyproject(pyproject)
    ruff = ruff_rev_mismatch(pins, precommit)
    return (
        ([ruff] if ruff else [])
        + required_mirror_mismatches(pins, precommit, required)
        + hook_dependency_mismatches(pins, precommit)
    )


def _repo_precommit() -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / PRECOMMIT).read_text(encoding="utf-8"))


def test_repo_hook_pins_mirror_pyproject() -> None:
    pyproject = tomllib.loads((REPO_ROOT / PYPROJECT).read_text(encoding="utf-8"))
    messages = lockstep_mismatches(pyproject, _repo_precommit())
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
            {"id": hook_id, "language": "python", "additional_dependencies": deps}
            for hook_id, deps in hook_deps.items()
        ],
    }


def _hook_mismatches(pyproject: dict[str, Any], precommit: dict[str, Any]) -> list[str]:
    return hook_dependency_mismatches(parse_pyproject(pyproject), precommit)


def _ruff_mismatch(pyproject: dict[str, Any], precommit: dict[str, Any]) -> str | None:
    return ruff_rev_mismatch(parse_pyproject(pyproject), precommit)


def test_agreeing_hook_dependency_passes() -> None:
    # Clause order, spacing and name spelling do not change meaning.
    pyproject = _pyproject(dev=["mutmut>=3.8,<3.9", "PyYAML>=6,<7"])
    precommit = _precommit(_local(mutmut=["mutmut <3.9, >=3.8", "pyyaml>=6,<7"]))
    assert _hook_mismatches(pyproject, precommit) == []


def test_disagreeing_hook_dependency_names_both_sites_and_values() -> None:
    pyproject = _pyproject(dev=["mutmut>=3.8,<3.9"])
    precommit = _precommit(_local(mutmut=["mutmut>=3.7,<3.8"]))
    [message] = _hook_mismatches(pyproject, precommit)
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
    messages = _hook_mismatches(pyproject, precommit)
    assert len(messages) == 3
    joined = "\n".join(messages)
    assert "hook 'mutmut' additional_dependencies: 'pytest-cov>=6,<7'" in joined
    assert "hook 'pytest' additional_dependencies: 'pytest-cov>=6,<7'" in joined
    assert "hook 'pytest' additional_dependencies: 'tree-sitter>=1,<1.5'" in joined


def test_hook_dependency_absent_from_pyproject_is_ignored() -> None:
    pyproject = _pyproject(dev=["pytest>=8"])
    precommit = _precommit(_local(pytest=["hatchling>=1.25", "tzdata"]))
    assert _hook_mismatches(pyproject, precommit) == []


def test_marker_only_difference_passes() -> None:
    pyproject = _pyproject(dev=["tomli>=2,<3"])
    precommit = _precommit(_local(pytest=["tomli>=2,<3; python_version < '3.11'"]))
    assert _hook_mismatches(pyproject, precommit) == []


def test_differing_direct_reference_urls_mismatch() -> None:
    pyproject = _pyproject(dev=["mutmut @ git+https://example.com/mutmut@fix-a"])
    agreeing = _precommit(_local(mutmut=["mutmut @ git+https://example.com/mutmut@fix-a"]))
    assert _hook_mismatches(pyproject, agreeing) == []
    precommit = _precommit(_local(mutmut=["mutmut @ git+https://example.com/mutmut@fix-b"]))
    [message] = _hook_mismatches(pyproject, precommit)
    assert "'mutmut @ git+https://example.com/mutmut@fix-a'" in message
    assert (
        "hook 'mutmut' additional_dependencies: 'mutmut @ git+https://example.com/mutmut@fix-b'"
        in message
    )


def test_ambiguous_optional_declarations_fail_naming_each() -> None:
    pyproject = _pyproject(dev=["tomli>=2,<3"], lint=["tomli>=2,<4"])
    precommit = _precommit(_local(mutmut=["tomli>=2,<3"], pytest=["tomli>=2,<3"]))
    [message] = _hook_mismatches(pyproject, precommit)
    assert "no single source of truth" in message
    assert f"{PYPROJECT} [project.optional-dependencies].dev: 'tomli>=2,<3'" in message
    assert f"{PYPROJECT} [project.optional-dependencies].lint: 'tomli>=2,<4'" in message


def test_hook_mirrors_dev_extra_over_looser_runtime_dependency() -> None:
    pyproject = _pyproject(["pytest-cov>=6"], dev=["pytest-cov>=6,<8"])
    precommit = _precommit(_local(pytest=["pytest-cov>=6,<8"]))
    assert _hook_mismatches(pyproject, precommit) == []
    [message] = _hook_mismatches(pyproject, _precommit(_local(pytest=["pytest-cov>=6"])))
    assert f"{PYPROJECT} [project.optional-dependencies].dev: 'pytest-cov>=6,<8'" in message


def test_runtime_fallback_when_no_optional_group_declares_the_package() -> None:
    pyproject = _pyproject(["pydantic>=2.8,<3"], dev=["pytest>=8"])
    [message] = _hook_mismatches(pyproject, _precommit(_local(pytest=["pydantic>=2,<3"])))
    assert f"{RUNTIME_SITE}: 'pydantic>=2.8,<3'" in message


def test_marker_split_runtime_hook_pin_must_match_one_candidate() -> None:
    split = _pyproject(["demo==1; python_version < '3.12'", "demo==2; python_version >= '3.12'"])
    assert _hook_mismatches(split, _precommit(_local(pytest=["demo==2"]))) == []
    [message] = _hook_mismatches(split, _precommit(_local(pytest=["demo==99"])))
    assert message == (
        "demo pins disagree:\n"
        f"  {RUNTIME_SITE}: \"demo==1; python_version < '3.12'\"\n"
        f"  {RUNTIME_SITE}: \"demo==2; python_version >= '3.12'\"\n"
        f"  {PRECOMMIT} hook 'pytest' additional_dependencies: 'demo==99'"
    )


def test_same_marker_runtime_entries_with_different_specifiers_are_ambiguous() -> None:
    pyproject = _pyproject(["numpy>=1.26", "numpy>=2"])
    [message] = _hook_mismatches(pyproject, _precommit(_local(pytest=["numpy>=2"])))
    assert "no single source of truth" in message


def test_dependency_groups_and_uv_dev_dependencies_are_sources() -> None:
    pyproject = {
        "project": {"dependencies": []},
        "dependency-groups": {
            "dev": ["mutmut>=3.8,<3.9", {"include-group": "test"}],
            "test": ["pytest>=8.4,<10"],
        },
        "tool": {"uv": {"dev-dependencies": ["pytest-cov>=6,<8"]}},
    }
    precommit = _precommit(
        _local(mutmut=["mutmut>=3.7,<3.8", "pytest>=8.4,<10", "pytest-cov>=6,<7"])
    )
    messages = _hook_mismatches(pyproject, precommit)
    assert [message.splitlines()[1] for message in messages] == [
        f"  {PYPROJECT} [dependency-groups].dev: 'mutmut>=3.8,<3.9'",
        f"  {PYPROJECT} [tool.uv].dev-dependencies: 'pytest-cov>=6,<8'",
    ]
    assert required_mirror_mismatches(parse_pyproject(pyproject), precommit) == []


def test_hooks_with_an_inline_non_python_language_are_ignored() -> None:
    pyproject = _pyproject(dev=["prettier>=4"])
    node_local = {
        "repo": "local",
        "hooks": [
            {
                "id": "eslint",
                "language": "node",
                "additional_dependencies": ["@types/node@20", "prettier@3.0.0"],
            }
        ],
    }
    system_local = {
        "repo": "local",
        "hooks": [{"id": "fmt", "language": "system", "additional_dependencies": ["prettier"]}],
    }
    assert _hook_mismatches(pyproject, _precommit(node_local, system_local)) == []


def test_remote_hook_with_plain_pep508_entries_is_compared() -> None:
    pyproject = _pyproject(dev=["types-PyYAML>=6,<7"])
    remote = {
        "repo": "https://github.com/pre-commit/mirrors-mypy",
        "rev": "v1.0.0",
        "hooks": [{"id": "mypy", "additional_dependencies": ["types-PyYAML>=5"]}],
    }
    [message] = _hook_mismatches(pyproject, _precommit(remote))
    assert "hook 'mypy' additional_dependencies: 'types-PyYAML>=5'" in message


def test_each_remote_hook_entry_is_compared_on_its_own() -> None:
    # A direct-URL entry, an undeclared package and an unparseable entry do not
    # stop the declared pytest-cov entry beside them from being compared.
    pyproject = _pyproject(dev=["pytest-cov>=6,<8"])
    entries = ["pytest-cov>=6,<7", "demo @ https://example.com/demo.whl", "@types/node@20"]
    remote = {
        "repo": RUFF_REPO,
        "rev": "v1.2.3",
        "hooks": [{"id": "ruff-check", "additional_dependencies": entries}],
    }
    assert _hook_mismatches(pyproject, _precommit(remote)) == [
        "pytest-cov pins disagree:\n"
        f"  {PYPROJECT} [project.optional-dependencies].dev: 'pytest-cov>=6,<8'\n"
        f"  {PRECOMMIT} hook 'ruff-check' additional_dependencies: 'pytest-cov>=6,<7'"
    ]


def test_hook_without_id_fails_clearly() -> None:
    precommit = _precommit({"repo": "local", "hooks": [{"language": "python"}]})
    assert _hook_mismatches(_pyproject(), precommit) == [
        f"{PRECOMMIT} hook #0 of repo 'local' has no 'id', so its pins cannot be named or compared"
    ]


def test_required_mirror_present_on_both_sides_passes() -> None:
    pyproject = _pyproject(dev=["mutmut>=3.8,<3.9"])
    precommit = _precommit(_local(mutmut=["mutmut>=3.8,<3.9"]))
    assert required_mirror_mismatches(parse_pyproject(pyproject), precommit) == []


def test_required_mirror_missing_from_pyproject_fails() -> None:
    precommit = _precommit(_local(mutmut=["mutmut>=3.8,<3.9"]))
    assert lockstep_mismatches(_pyproject(dev=["pytest>=8"]), precommit)[1:] == [
        f"mutmut must be declared exactly once in {PYPROJECT} to anchor its mirror in "
        f"{PRECOMMIT} hook 'mutmut'; found 0"
    ]


def test_required_mirror_missing_from_hook_fails() -> None:
    pyproject = parse_pyproject(_pyproject(dev=["mutmut>=3.8,<3.9"]))
    site = f"{PRECOMMIT} hook 'mutmut' additional_dependencies"
    assert required_mirror_mismatches(pyproject, _precommit(_local(mutmut=["pytest>=8"]))) == [
        f"{site}: must list mutmut exactly once to mirror {PYPROJECT}, found 0"
    ]
    assert required_mirror_mismatches(pyproject, _precommit(_local(pytest=["pytest>=8"]))) == [
        f"{site}: expected exactly one hook with id 'mutmut' to mirror mutmut from "
        f"{PYPROJECT}, found 0"
    ]
    system = _precommit(
        {
            "repo": "local",
            "hooks": [{"id": "mutmut", "language": "system", "additional_dependencies": []}],
        }
    )
    assert required_mirror_mismatches(pyproject, system) == [
        f"{site}: hook 'mutmut' must be a Python hook to mirror mutmut"
    ]


def test_agreeing_ruff_rev_passes() -> None:
    # The rev tag's leading `v` is not part of the version.
    pyproject = _pyproject(dev=["ruff==1.2.3"])
    assert _ruff_mismatch(pyproject, _precommit(_ruff_repo("v1.2.3"))) is None


def test_disagreeing_ruff_rev_names_both_sites_and_values() -> None:
    pyproject = _pyproject(dev=["ruff==1.2.4"])
    message = _ruff_mismatch(pyproject, _precommit(_ruff_repo("v1.2.3")))
    assert message is not None
    assert f"{PYPROJECT} [project.optional-dependencies].dev: 'ruff==1.2.4'" in message
    assert f"{PRECOMMIT} rev: of {RUFF_REPO}: 'v1.2.3'" in message


def test_missing_ruff_repo_fails_loudly() -> None:
    """A renamed or dropped ruff repo must not turn the guard into a silent no-op."""
    pyproject = _pyproject(dev=["ruff==1.2.3"])
    messages = lockstep_mismatches(pyproject, _precommit(_local(pytest=["ruff==1.2.3"])), ())
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
    message = _ruff_mismatch(pyproject, _precommit(_ruff_repo(rev)))
    assert message is not None
    assert f"{PRECOMMIT} rev: of {RUFF_REPO}" in message
    assert repr(rev) in message


def test_ruff_rev_without_a_pyproject_ruff_pin_fails() -> None:
    message = _ruff_mismatch(_pyproject(dev=["pytest>=8"]), _precommit(_ruff_repo("v1.2.3")))
    assert message == (
        f"{PRECOMMIT} rev: of {RUFF_REPO}: {PYPROJECT} declares no ruff requirement "
        f"to compare 'v1.2.3' with"
    )


def test_ambiguous_ruff_declarations_fail() -> None:
    pyproject = _pyproject(dev=["ruff==1.2.3"], lint=["ruff==1.2.4"])
    message = _ruff_mismatch(pyproject, _precommit(_ruff_repo("v1.2.3")))
    assert message is not None
    assert "no single source of truth" in message


def test_ruff_and_hook_mismatches_are_reported_together() -> None:
    pyproject = _pyproject(dev=["ruff==1.2.4", "pytest-cov>=6,<8"])
    precommit = _precommit(_ruff_repo("v1.2.3"), _local(pytest=["pytest-cov>=6,<7"]))
    messages = lockstep_mismatches(pyproject, precommit, required=())
    assert [message.splitlines()[0] for message in messages] == [
        "ruff pins disagree:",
        "pytest-cov pins disagree:",
    ]


# The delivery skills treat the pre-push pytest hook's output as the full local
# suite's evidence, so a clone must install that hook by default, and whenever
# pre-commit runs the pre-push stage the hook must run too, even when the pushed
# range has no net file changes (an `--allow-empty` commit, or a commit plus its
# revert) (#773).


def _pytest_hook() -> dict[str, Any]:
    hooks = [hook for hook_id, _, hook in _hooks(_repo_precommit()) if hook_id == "pytest"]
    assert len(hooks) == 1, f"{PRECOMMIT}: expected one hook with id 'pytest', found {len(hooks)}"
    return hooks[0]


def test_plain_install_adds_the_pre_push_hook() -> None:
    precommit = _repo_precommit()
    assert {"pre-commit", "pre-push"} <= set(precommit.get("default_install_hook_types", []))
    # The config needs 3.2+ (the stage names and the pinned pre-commit-hooks);
    # the minimum makes an older binary fail with a clear version error.
    minimum = precommit.get("minimum_pre_commit_version")
    site = f"{PRECOMMIT} minimum_pre_commit_version"
    assert isinstance(minimum, str), f"{site}: expected a version string, got {minimum!r}"
    try:
        version = Version(minimum)
    except InvalidVersion:
        pytest.fail(f"{site}: {minimum!r} is not a version")
    assert version >= Version("3.2"), f"{site}: {minimum} is below 3.2"


def test_pre_push_pytest_hook_always_runs() -> None:
    pytest_hook = _pytest_hook()
    assert pytest_hook.get("stages") == ["pre-push"]
    assert pytest_hook.get("always_run") is True
    # With filenames passed, `always_run` would run `pytest <changed files>`,
    # not the full suite.
    assert pytest_hook.get("pass_filenames") is False


def test_pre_push_pytest_hook_prints_its_counts() -> None:
    # pre-commit hides a passing hook's output unless `verbose` is set, and a
    # hook option that takes pytest below addopts' `-q` drops the "N passed"
    # line, so either would leave the push log without the counts the skills
    # quote. The hook takes its options from addopts alone: an option added
    # here is a deliberate change that updates this guard too.
    pytest_hook = _pytest_hook()
    assert pytest_hook.get("verbose") is True
    argv = shlex.split(pytest_hook["entry"]) + [str(arg) for arg in pytest_hook.get("args", [])]
    assert argv == ["pytest"], (
        f"{PRECOMMIT} pytest hook argv {argv}: options belong in {PYPROJECT} addopts; "
        "change this guard deliberately if the hook needs its own"
    )
