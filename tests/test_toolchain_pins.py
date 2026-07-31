# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The two ruff pins have to agree, because nothing else checks that they do.

`pyproject.toml`'s dev extras decide what the required `ruff check + format` CI
job installs and what `uv sync` puts in a contributor's venv.
`.pre-commit-config.yaml`'s `rev:` decides what runs at `git commit`. They used
to disagree by construction: an open `ruff>=0.5,<1` cannot match a fixed `rev:`,
so CI installed whatever was newest while pre-commit stayed on v0.13.0. When
0.16.0 began formatting Python inside Markdown fences, the required job went red
on a `main` nobody had touched while every contributor's `git commit` stayed
green.

**Scope.** These tests cover the version agreement and nothing else. That is a
deliberate line, drawn after several rounds of review kept finding holes in a
broader guard here. The lint job runs `python -m ruff check .` and `python -m
ruff format --check .` over the real tree and never reads
`.pre-commit-config.yaml`, which means:

  * A stale `rev:` is invisible to CI. Nothing but this module catches it, so
    this module checks it.
  * Every other property of the hooks — `types_or`, `args`, `files`, `exclude`,
    `stages` — only affects whether the local convenience hook mirrors CI. Break
    any of them (`--exit-zero`, `exclude_types: [markdown]`, a narrowed
    `files:`) and the required job still fails on the next push. Asserting them
    here guards a layer that cannot be authoritative, over an unbounded space of
    keys, values and pre-commit semantics. The hooks' intended shape and the
    reasoning behind it are documented in `.pre-commit-config.yaml` instead.
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
    ``is_dir()``.
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


def _ruff_repo_rev() -> str | None:
    """The `rev:` of the ruff-pre-commit entry, read as YAML.

    Parsed, not regex-matched: pre-commit itself loads this file as YAML, so
    YAML semantics are the truth here. A regex would tie this to one spelling
    and fail spuriously on a legal reformat (quoted scalars, reordered keys),
    none of which changes what pre-commit does.
    """
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    entries = [repo for repo in config["repos"] if repo.get("repo") == RUFF_PRE_COMMIT_REPO]
    assert len(entries) == 1, (
        f"expected exactly one {RUFF_PRE_COMMIT_REPO} entry in .pre-commit-config.yaml, "
        f"found {len(entries)}"
    )
    return entries[0].get("rev")


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
    """Bumping one and not the other is the drift this test exists to catch.

    CI never reads .pre-commit-config.yaml, so a stale rev here is invisible to
    it: this assertion is the only thing standing between a version bump and a
    contributor formatting with a different ruff than the required job.
    """
    constraint = _pyproject_ruff_constraint()
    rev = _ruff_repo_rev()
    assert rev is not None, "the ruff-pre-commit entry in .pre-commit-config.yaml has no rev:"
    assert rev == f"v{constraint.removeprefix('==')}", (
        f".pre-commit-config.yaml pins ruff-pre-commit at {rev} but pyproject.toml "
        f"says 'ruff{constraint}'. `git commit` and the `ruff check + format` CI job "
        "would run different formatters. Bump both in the same commit and reformat "
        "in that same change."
    )
