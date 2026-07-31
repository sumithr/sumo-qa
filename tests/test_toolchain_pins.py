# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Every gate that runs ruff must run the same ruff over the same files.

Two things drifted at once on PR #570.

**Version.** `pyproject.toml`'s dev extras decide what the `ruff check + format`
CI job installs and what `uv sync` puts in a contributor's venv;
`.pre-commit-config.yaml`'s `rev:` decides what runs at `git commit`. These used
to disagree by construction, because the open `ruff>=0.5,<1` cannot match a
fixed `rev:`. When 0.16.0 began formatting Python inside Markdown fences, the
required job went red on a `main` nobody had touched while every contributor's
`git commit` stayed green.

**File set.** Measured with `ruff check --show-files .` and
`ruff format --check .`, CI's two steps walk different trees::

    ruff check .           253 .py + pyproject.toml and ruff.toml
    ruff format --check .  253 .py + 83 .md

The upstream ruff-pre-commit hooks declare only python/pyi/jupyter, so
ruff-format needs `markdown` or a drifting fence passes `git commit` and fails
CI. ruff-check does NOT need `toml`: it special-cases the two config files by
name, so that tag would hand it every tracked `.toml` CI ignores.

These assertions are deliberately pure YAML/TOML reads. The pre-push `pytest`
and `mutmut` hooks run in isolated environments whose `additional_dependencies`
list PyYAML but neither `identify` nor `ruff`, so a guard that imported those,
or shelled out to the ruff binary, would raise ModuleNotFoundError there and
take the whole pre-push suite and the mutation gate down with it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on py3.10 only
    import tomli as tomllib

RUFF_PRE_COMMIT_REPO = "https://github.com/astral-sh/ruff-pre-commit"

# Hook id -> the `types_or` it must declare, or None to require the upstream
# default. Mirrors what each CI step discovers; re-measure with
# `ruff check --show-files .` / `ruff format --check .` before editing.
EXPECTED_TYPES_OR: dict[str, set[str] | None] = {
    "ruff-check": None,
    "ruff-format": {"python", "pyi", "jupyter", "markdown"},
}


def _repo_root() -> Path:
    """Anchor on ``.git``, matching tests/test_check_no_em_dashes.py.

    NOT ``parents[1]`` and not a pyproject.toml anchor: mutmut re-runs the suite
    from a ``mutants/`` copy that carries pyproject.toml but none of the repo's
    dotfiles, so either of those resolves inside the copy,
    ``.pre-commit-config.yaml`` comes back missing, and this module raises
    FileNotFoundError. mutmut runs pytest with ``-x``, so that single error
    aborts the whole run and every module reports 0 killed — the gate renders
    one broken test as six catastrophic regressions. (Cost real debugging time
    on PR #570; the same class of trap is documented in
    tests/test_mutmut_subprocess_exclusions.py.)

    ``.git`` is never copied into ``mutants/``, and it is a directory in a
    normal clone but a file in a worktree, hence ``exists()`` rather than
    ``is_dir()``. Anchoring on it also cannot walk out into an enclosing
    project the way a two-marker search can.
    """
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"no .git ancestor of {here!s}")


REPO_ROOT = _repo_root()
PYPROJECT = REPO_ROOT / "pyproject.toml"
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"


def _pyproject_ruff_constraint() -> str:
    """The version constraint on ruff in the dev extras, e.g. '==0.16.0'.

    Returns the WHOLE constraint rather than a parsed operator and version, so
    that a range such as '>=0.5,<1' reaches the exact-pin assertion and fails
    there with its own message instead of dying earlier on a parse error.
    """
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    specs = [
        spec
        for spec in data["project"]["optional-dependencies"]["dev"]
        if re.split(r"[=<>!~\s\[;]", spec, maxsplit=1)[0] == "ruff"
    ]
    assert len(specs) == 1, f"expected exactly one ruff spec in the dev extras, got {specs}"
    return specs[0].strip().removeprefix("ruff").strip()


def _ruff_repo_entry() -> dict:
    """The ruff-pre-commit `- repo:` entry, parsed as YAML.

    Parsed, not regex-matched: pre-commit itself loads this file as YAML, so
    YAML semantics are the truth here. A regex would tie these tests to one
    spelling and fail spuriously on a legal reformat — quoted scalars,
    reordered keys, block-style lists instead of `[a, b]` — none of which
    changes what pre-commit does.
    """
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    entries = [repo for repo in config["repos"] if repo.get("repo") == RUFF_PRE_COMMIT_REPO]
    assert len(entries) == 1, (
        f"expected exactly one {RUFF_PRE_COMMIT_REPO} entry in .pre-commit-config.yaml, "
        f"found {len(entries)}"
    )
    return entries[0]


def _ruff_hooks() -> dict[str, dict]:
    """The ruff hook entries, keyed by id, rejecting duplicate ids.

    pre-commit runs EVERY entry, so a second `- id: ruff-check` is a second
    hook, not a redefinition. Building the dict without this check silently
    keeps whichever one comes last, so a malformed duplicate alongside a
    correct entry would pass every assertion below while pre-commit ran both.
    """
    entries = _ruff_repo_entry()["hooks"]
    ids = [hook["id"] for hook in entries]
    duplicates = sorted({hook_id for hook_id in ids if ids.count(hook_id) > 1})
    assert not duplicates, (
        f"duplicate ruff hook ids in .pre-commit-config.yaml: {duplicates}. "
        "pre-commit runs every entry, so a duplicate is an extra hook whose "
        "settings are not the ones asserted here."
    )
    assert set(ids) == set(EXPECTED_TYPES_OR), (
        f"expected exactly the {sorted(EXPECTED_TYPES_OR)} hooks, got {sorted(ids)}"
    )
    return {hook["id"]: hook for hook in entries}


def test_ruff_is_pinned_exactly_in_pyproject() -> None:
    """A range here is what let CI and pre-commit run different formatters."""
    constraint = _pyproject_ruff_constraint()
    assert re.fullmatch(r"==[\w.]+", constraint), (
        f"ruff must be pinned exactly, got 'ruff{constraint}'. A range resolves to "
        "whatever is newest in CI, which cannot agree with the fixed rev: the "
        "ruff-pre-commit hook needs, so formatter output diverges between "
        "`git commit` and the required `ruff check + format` job."
    )


def test_pre_commit_ruff_rev_matches_the_pyproject_pin() -> None:
    """Bumping one and not the other is the drift this test exists to catch."""
    constraint = _pyproject_ruff_constraint()
    rev = _ruff_repo_entry().get("rev")
    assert rev is not None, "the ruff-pre-commit entry in .pre-commit-config.yaml has no rev:"
    assert rev == f"v{constraint.removeprefix('==')}", (
        f".pre-commit-config.yaml pins ruff-pre-commit at {rev} but pyproject.toml "
        f"says 'ruff{constraint}'. `git commit` and the `ruff check + format` CI job "
        "would run different formatters. Bump both in the same commit and reformat "
        "in that same change."
    )


def test_ruff_format_hook_covers_markdown() -> None:
    """`ruff format --check .` walks 83 Markdown files in this tree.

    The upstream hook declares only python/pyi/jupyter, so without the override
    a drifting fence reports "ruff format...(no files to check)Skipped" at
    `git commit` and turns the required CI job red.
    """
    declared = _ruff_hooks()["ruff-format"].get("types_or")
    assert declared is not None, (
        "ruff-format has no types_or override, so it inherits the upstream "
        "python/pyi/jupyter list and never sees the Markdown CI formats."
    )
    assert set(declared) == EXPECTED_TYPES_OR["ruff-format"], (
        f"ruff-format declares types_or {sorted(declared)}, expected "
        f"{sorted(EXPECTED_TYPES_OR['ruff-format'])}. That mirrors what "
        "`ruff format --check .` discovers; re-measure before changing it."
    )


def test_ruff_check_hook_keeps_the_upstream_file_types() -> None:
    """ruff-check must NOT carry a types_or override.

    `ruff check` ignores Markdown, and its only non-Python inputs are
    pyproject.toml and ruff.toml, which it special-cases by NAME. Adding `toml`
    therefore hands the hook every tracked `.toml` — including
    tests/fixtures/repo_map/rust_context_crate/Cargo.toml, which
    `ruff check --show-files .` does not list — so `git commit` would lint a
    file CI never does. (That over-selection shipped briefly on this branch.)
    """
    declared = _ruff_hooks()["ruff-check"].get("types_or")
    assert declared is None, (
        f"ruff-check declares types_or {sorted(declared)}; it must keep the upstream "
        "python/pyi/jupyter list. `ruff check` special-cases pyproject.toml and "
        "ruff.toml by name, so a `toml` tag over-selects every other tracked .toml "
        "that CI ignores."
    )
