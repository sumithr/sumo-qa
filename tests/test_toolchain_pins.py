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

REPO_ROOT = Path(__file__).resolve().parents[1]
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


def _pre_commit_ruff_rev() -> str:
    """Read the `rev:` of the ruff-pre-commit repo entry.

    Parsed with a regex rather than yaml.safe_load so the assertion still runs
    if the file grows an anchor or a merge key the loader would resolve away.
    """
    text = PRE_COMMIT.read_text(encoding="utf-8")
    match = re.search(
        r"- repo:\s*https://github\.com/astral-sh/ruff-pre-commit\b.*?^\s*rev:\s*(?P<rev>\S+)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "no ruff-pre-commit repo entry with a rev: in .pre-commit-config.yaml"
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
