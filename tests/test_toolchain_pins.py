# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Every gate that runs ruff must run the same ruff over the same files.

Two things have to agree, and both drifted at once on PR #570:

**Version.** `pyproject.toml`'s dev extras decide what the `ruff check + format`
CI job installs and what `uv sync` puts in a contributor's venv;
`.pre-commit-config.yaml`'s `rev:` decides what runs at `git commit`. These used
to disagree by construction, because the open `ruff>=0.5,<1` cannot match a
fixed `rev:`. When 0.16.0 began formatting Python inside Markdown fences, the
required job went red on a `main` nobody had touched while every contributor's
`git commit` stayed green.

**File set.** The upstream ruff-pre-commit hooks declare only python/pyi/jupyter,
and the two ruff subcommands do not cover the same files anyway. Measured on
this tree with `ruff check --show-files .` and `ruff format --check .`:

    ruff check .           253 .py + 2 .toml (pyproject.toml, ruff.toml)
    ruff format --check .  253 .py + 83 .md

so each hook needs its own `types_or`, or a file CI checks goes unchecked at
commit time and the divergence simply moves from "different versions" to
"different file sets".

These tests turn either drift into a test failure rather than a surprise on
somebody's unrelated PR.
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

# What each hook has to see, so that `git commit` and the required CI job cover
# the same files. Derived from `ruff check --show-files .` / `ruff format
# --check .`, not from taste — re-measure before editing.
EXPECTED_TYPES_OR = {
    "ruff-check": {"python", "pyi", "jupyter", "toml"},
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


def test_pre_commit_ruff_hooks_see_the_files_ci_checks() -> None:
    """Matching versions are not enough: the hooks must see the same FILES.

    The upstream hooks declare only python/pyi/jupyter. `ruff format` also walks
    Markdown (Python inside fences), and `ruff check` also walks TOML
    (pyproject.toml, ruff.toml) while ignoring Markdown entirely. Without a
    per-hook `types_or` override, `git commit` reports "(no files to
    check)Skipped" for a file the CLI would reformat and the required CI job
    goes red on a commit that passed every local gate.
    """
    hooks = {hook["id"]: hook for hook in _ruff_repo_entry()["hooks"]}
    assert set(hooks) == set(EXPECTED_TYPES_OR), (
        f"expected exactly the {sorted(EXPECTED_TYPES_OR)} hooks, got {sorted(hooks)}"
    )
    for hook_id, expected in EXPECTED_TYPES_OR.items():
        declared = hooks[hook_id].get("types_or")
        assert declared is not None, (
            f"{hook_id} has no types_or override, so it inherits the upstream "
            "python/pyi/jupyter list and misses files CI checks. A drift in one "
            "of them would pass `git commit` and fail the required job."
        )
        assert set(declared) == expected, (
            f"{hook_id} declares types_or {sorted(declared)}, expected {sorted(expected)}. "
            "That list mirrors what its CI counterpart discovers (`ruff check "
            "--show-files .` / `ruff format --check .`); re-measure before changing it."
        )
