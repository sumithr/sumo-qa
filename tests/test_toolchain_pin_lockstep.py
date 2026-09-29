# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Guard that every Python dependency pinned in a git hook mirrors ``pyproject.toml``.

pre-commit hook venvs install from PyPI, so a hook that needs project
dependencies repeats them in its ``additional_dependencies``. Those copies
drift: Dependabot only ever edits ``pyproject.toml``, so every bump it raises
for a package a hook also lists is half a change until the hook moves too.
Each file is individually valid, so running either config cannot reveal the
disagreement; this guard compares the declarations.

Which hooks are compared. Only Python hooks: a hook whose inline ``language``
is ``python``. A hook with any other inline ``language`` (``system``, ``node``,
...) is skipped. A hook from a remote repo usually declares its language in
that repo's manifest rather than in ``.pre-commit-config.yaml``; when no inline
``language`` is present, its ``additional_dependencies`` are treated as Python
only if every entry parses as a PEP 508 requirement without a URL, otherwise
the hook is skipped. In this repo the compared hooks are the ``repo: local``
``mutmut`` and ``pytest`` hooks (``language: python``); the other local hooks
are ``language: system`` and the remote hooks carry no
``additional_dependencies``.

Where the source of truth lives. Hooks mirror the dev tooling, so a hook entry
is compared first with the optional-extra-equivalent declarations: every
``[project.optional-dependencies]`` group, every PEP 735 ``[dependency-groups]``
group (string entries only; ``{include-group = ...}`` tables are ignored) and
``[tool.uv].dev-dependencies``. Only when the package appears in none of those
is it compared with ``[project].dependencies``. A package the optional sources
declare with different specifiers or URLs fails as ambiguous. In the
``[project].dependencies`` fallback, entries that differ only because they
carry different environment markers are a marker split, not an ambiguity: the
single unmarked entry is the source if exactly one exists, otherwise the
package is skipped. A hook entry for a package ``pyproject.toml`` does not
declare is out of scope.

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

The check is version-agnostic: it hard-codes no version, only asserts that the
sites agree, and it reports every mismatch in one failure.
"""

from __future__ import annotations

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
    """pyproject parsed once: every declaration, each package's source, each ambiguity."""

    declarations: dict[str, list[Declaration]] = field(default_factory=dict)
    sources: dict[str, Declaration] = field(default_factory=dict)
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


def _resolve_runtime(package: str, runtime: list[Declaration], pins: PyprojectPins) -> None:
    if len({decl.pin for decl in runtime}) <= 1:
        pins.sources[package] = runtime[0]
        return
    by_marker: dict[str | None, set[tuple[SpecifierSet, str | None]]] = {}
    for decl in runtime:
        by_marker.setdefault(decl.marker, set()).add(decl.pin)
    if any(len(pins_under_marker) > 1 for pins_under_marker in by_marker.values()):
        pins.ambiguities[package] = _ambiguity_message(package, runtime)
        return
    # A marker split: compare against the one unmarked entry, else nothing.
    unmarked = [decl for decl in runtime if decl.marker is None]
    if len(unmarked) == 1:
        pins.sources[package] = unmarked[0]


def parse_pyproject(pyproject: dict[str, Any]) -> PyprojectPins:
    """Map each package to its declarations, its single source, or its ambiguity."""
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
        if len({decl.pin for decl in decls}) > 1:
            pins.ambiguities[package] = _ambiguity_message(package, decls)
        else:
            pins.sources[package] = decls[0]
    for package, decls in runtime.items():
        if package not in optional:
            _resolve_runtime(package, decls, pins)
    return pins


def _python_requirements(hook: dict[str, Any]) -> list[tuple[str, Requirement]] | None:
    """The hook's dependencies as Python requirements, or None when it is not a Python hook."""
    raws = [str(raw) for raw in hook.get("additional_dependencies", [])]
    language = hook.get("language")
    parsed: list[tuple[str, Requirement]] = []
    for raw in raws:
        try:
            parsed.append((raw, Requirement(raw)))
        except InvalidRequirement:
            if language == "python":
                raise
            return None
    if language is not None:
        return parsed if language == "python" else None
    # No inline language (a remote repo's manifest declares it): Python only
    # when every entry is a URL-free PEP 508 requirement.
    return None if any(req.url for _, req in parsed) else parsed


def _hooks(precommit: dict[str, Any]) -> list[tuple[str | None, str, dict[str, Any]]]:
    """Every hook as (id or None, a label naming it, the hook mapping)."""
    hooks = []
    for repo in precommit.get("repos", []):
        for index, hook in enumerate(repo.get("hooks", [])):
            hook_id = hook.get("id")
            label = repr(hook_id) if hook_id else f"#{index} of repo {repo.get('repo')!r}"
            hooks.append((hook_id, label, hook))
    return hooks


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
            source = pins.sources.get(package)
            if source is None or source.pin == (req.specifier, req.url):
                continue
            messages.append(
                f"{package} pins disagree:\n"
                f"  {source.site}: {source.raw!r}\n"
                f"  {PRECOMMIT} hook {label} additional_dependencies: {raw!r}"
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
    source = pins.sources.get("ruff")
    if source is None:
        return f"{site}: {PYPROJECT} declares no ruff requirement to compare {raw_rev!r} with"
    if source.pin == (SpecifierSet(f"=={version}"), None):
        return None
    return f"ruff pins disagree:\n  {source.site}: {source.raw!r}\n  {site}: {raw_rev!r}"


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


def test_marker_split_runtime_pair_does_not_falsely_fail() -> None:
    split = [
        "numpy>=1.26,<2; python_version < '3.12'",
        "numpy>=2,<3; python_version >= '3.12'",
    ]
    precommit = _precommit(_local(pytest=["numpy>=2,<3"]))
    # No unmarked entry: nothing to compare against, and not ambiguous.
    assert _hook_mismatches(_pyproject(split), precommit) == []
    # Exactly one unmarked entry: it is the source.
    with_unmarked = _pyproject([*split, "numpy>=1.26"])
    [message] = _hook_mismatches(with_unmarked, precommit)
    assert f"{RUNTIME_SITE}: 'numpy>=1.26'" in message


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


def test_non_python_hooks_are_ignored() -> None:
    pyproject = _pyproject(dev=["prettier>=4"])
    node_deps = ["@types/node@20", "prettier@3.0.0"]
    node_local = {
        "repo": "local",
        "hooks": [{"id": "eslint", "language": "node", "additional_dependencies": node_deps}],
    }
    system_local = {
        "repo": "local",
        "hooks": [{"id": "fmt", "language": "system", "additional_dependencies": ["prettier"]}],
    }
    # A remote hook with no inline language: not all entries are URL-free PEP 508.
    remote = {
        "repo": "https://github.com/example/mirrors-prettier",
        "rev": "v3.0.0",
        "hooks": [{"id": "prettier", "additional_dependencies": node_deps}],
    }
    remote_url = {
        "repo": "https://github.com/example/mirrors-prettier",
        "rev": "v3.0.0",
        "hooks": [{"id": "prettier-url", "additional_dependencies": ["prettier@3.0.0"]}],
    }
    precommit = _precommit(node_local, system_local, remote, remote_url)
    assert _hook_mismatches(pyproject, precommit) == []


def test_remote_hook_with_plain_pep508_entries_is_compared() -> None:
    pyproject = _pyproject(dev=["types-PyYAML>=6,<7"])
    remote = {
        "repo": "https://github.com/pre-commit/mirrors-mypy",
        "rev": "v1.0.0",
        "hooks": [{"id": "mypy", "additional_dependencies": ["types-PyYAML>=5"]}],
    }
    [message] = _hook_mismatches(pyproject, _precommit(remote))
    assert "hook 'mypy' additional_dependencies: 'types-PyYAML>=5'" in message


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
