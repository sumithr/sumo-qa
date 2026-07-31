# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The ruff version has to be identical in every gate that runs it.

ruff is a formatter as well as a linter, and pre-1.0 minors change formatter
output. Three places choose a ruff for this repo:

  * `pyproject.toml` dev extras — what `ruff check + format` installs in CI, and
    what `uv sync` puts in a contributor's venv.
  * `.pre-commit-config.yaml` `rev:` — what runs at `git commit`.

They used to disagree by construction: an open `ruff>=0.5,<1` cannot match a
fixed `rev:`, so CI installed whatever was newest while pre-commit stayed on an
old rev. When 0.16.0 started formatting Python inside Markdown fences, the
required `ruff check + format` job went red on a `main` nobody had touched,
while every contributor's `git commit` stayed green. These tests make that
divergence a test failure instead of a surprise on an unrelated PR.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on py3.10 only
    import tomli as tomllib


def _repo_root() -> Path:
    """The real repo root, which is NOT always `parents[1]` of this file.

    mutmut runs the suite from a `mutants/` copy of the tree. That copy gets
    `pyproject.toml` (mutmut needs its own config) but not the repo's dotfiles,
    so a naive `parents[1]` resolves to `mutants/`, `.pre-commit-config.yaml`
    is missing, and this module raises FileNotFoundError. mutmut runs pytest
    with `-x`, so that one error aborts the whole run and every module reports
    0 killed — the gate reads as six catastrophic regressions rather than a
    broken test. (Cost real debugging time on PR #570; the same class of trap
    is documented in tests/test_mutmut_subprocess_exclusions.py.)

    Walking up for a directory containing BOTH files skips the `mutants/` copy,
    which only ever has one of them.
    """
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (
            candidate / ".pre-commit-config.yaml"
        ).is_file():
            return candidate
    raise AssertionError(
        "no ancestor of this test file holds both pyproject.toml and "
        ".pre-commit-config.yaml; cannot locate the repo root"
    )


REPO_ROOT = _repo_root()
PYPROJECT = REPO_ROOT / "pyproject.toml"
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"

_RUFF_SPEC = re.compile(r"^ruff\s*(?P<constraint>.*)$")


def _pyproject_ruff_constraint() -> str:
    """The version constraint on ruff in the dev extras, e.g. '==0.16.0'.

    Deliberately returns the WHOLE constraint rather than a parsed operator and
    version: a range such as '>=0.5,<1' has to reach the exact-pin assertion and
    fail there with its own message, not die earlier on a parse error.
    """
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    specs = [
        spec
        for spec in data["project"]["optional-dependencies"]["dev"]
        if re.split(r"[=<>!~\s\[;]", spec, maxsplit=1)[0] == "ruff"
    ]
    assert len(specs) == 1, f"expected exactly one ruff spec in the dev extras, got {specs}"
    match = _RUFF_SPEC.match(specs[0].strip())
    assert match is not None, f"could not parse the ruff dev-extra spec {specs[0]!r}"
    return match.group("constraint")


def _ruff_repo_block() -> str:
    """The `- repo: .../ruff-pre-commit` entry, up to the next `- repo:`.

    Bounded on purpose. A `.*?` reaching across the whole file would, if ruff's
    own `rev:` were ever deleted, happily match the NEXT repo's rev and report
    a mismatch instead of a missing pin — a misleading failure for a real
    defect. Everything downstream reads from this slice only.
    """
    text = PRE_COMMIT.read_text(encoding="utf-8")
    match = re.search(
        r"^\s*- repo:\s*https://github\.com/astral-sh/ruff-pre-commit\b"
        r"(?P<block>.*?)(?=^\s*- repo:|\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "no ruff-pre-commit repo entry in .pre-commit-config.yaml"
    return match.group("block")


def _pre_commit_ruff_rev() -> str:
    """Read the `rev:` of the ruff-pre-commit repo entry.

    Parsed with a regex rather than yaml.safe_load so the assertion still runs
    if the file grows an anchor or a merge key the loader would resolve away.
    """
    match = re.search(r"^\s*rev:\s*(?P<rev>\S+)", _ruff_repo_block(), re.MULTILINE)
    assert match is not None, "the ruff-pre-commit entry in .pre-commit-config.yaml has no rev:"
    return match.group("rev")


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
    rev = _pre_commit_ruff_rev()
    assert rev == f"v{constraint.removeprefix('==')}", (
        f".pre-commit-config.yaml pins ruff-pre-commit at {rev} but pyproject.toml "
        f"says 'ruff{constraint}'. `git commit` and the `ruff check + format` CI job "
        "would run different formatters. Bump both in the same commit and reformat "
        "in that same change."
    )


def test_pre_commit_ruff_hooks_cover_markdown() -> None:
    """Matching versions are not enough: the hooks must see the same FILES.

    ruff 0.16 formats and lints Python inside Markdown fences, and CI runs a
    bare `ruff check .` / `ruff format --check .` that picks those files up.
    The upstream ruff-pre-commit hooks declare only python/pyi/jupyter, so
    without a `types_or` override `git commit` reports "ruff format...(no files
    to check)Skipped" for a Markdown file the CLI would reformat, and the
    required CI job goes red on a commit that passed every local gate. Both
    hook ids need it: `ruff check` and `ruff format` are separate CI steps.
    """
    block = _ruff_repo_block()
    hooks = re.findall(
        r"^\s*- id:\s*(?P<id>ruff-\S+)(?P<body>.*?)(?=^\s*- id:|\Z)",
        block,
        re.DOTALL | re.MULTILINE,
    )
    assert {hook_id for hook_id, _ in hooks} == {"ruff-check", "ruff-format"}, (
        f"expected exactly the ruff-check and ruff-format hooks, got {[h for h, _ in hooks]}"
    )
    for hook_id, body in hooks:
        types_or = re.search(r"^\s*types_or:\s*\[(?P<types>[^\]]*)\]", body, re.MULTILINE)
        assert types_or is not None, (
            f"{hook_id} has no types_or override, so it inherits the upstream "
            "python/pyi/jupyter list and never sees Markdown. A drifting fence "
            "would pass `git commit` and fail the required `ruff check + format` job."
        )
        declared = {entry.strip() for entry in types_or.group("types").split(",")}
        assert "markdown" in declared, (
            f"{hook_id} declares types_or {sorted(declared)} with no 'markdown'. "
            "ruff 0.16 handles Python inside Markdown fences and CI checks them, "
            "so this hook must too."
        )
