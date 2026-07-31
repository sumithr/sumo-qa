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
and the two ruff subcommands do not cover the same files anyway. On this tree
`ruff check .` walks 253 .py plus 2 .toml while `ruff format --check .` walks
253 .py plus 83 .md, so each hook needs its own `types_or` or the divergence
simply moves from "different versions" to "different file sets".

Those numbers are context, not the contract: the coverage test MEASURES ruff
rather than asserting a list, because a hard-coded list would only relocate the
drift into a test that can itself be wrong while staying green. A new extension,
or a ruff release that starts or stops handling a type, therefore fails here
instead of on somebody's unrelated PR.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml
from identify import identify

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on py3.10 only
    import tomli as tomllib

RUFF_PRE_COMMIT_REPO = "https://github.com/astral-sh/ruff-pre-commit"

# Which CI step each hook id mirrors. The FILE SETS are deliberately not listed
# here: they are measured from ruff itself, so this module cannot drift from
# reality the way a hard-coded list would. As of ruff 0.16.0 the answer is
# python+toml for check and python+markdown for format, but nothing below
# depends on that staying true.
RUFF_HOOK_SUBCOMMANDS = {"ruff-check": "check", "ruff-format": "format"}


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
    assert set(ids) == set(RUFF_HOOK_SUBCOMMANDS), (
        f"expected exactly the {sorted(RUFF_HOOK_SUBCOMMANDS)} hooks, got {sorted(ids)}"
    )
    return {hook["id"]: hook for hook in entries}


def _ruff_covers(subcommand: str, path: Path) -> bool:
    """Whether `ruff <subcommand> .` would DISCOVER a file of this type.

    Probes a directory holding one copy of the file, never the file itself. An
    explicitly named path bypasses ruff's discovery rules and is processed
    regardless of extension — `ruff format --check marketplace.json` reports
    "1 file would be reformatted", parsing JSON as Python — whereas the same
    file inside a directory yields "No Python files found under the given
    path(s)". CI runs `ruff check .` / `ruff format --check .`, both
    directories, so discovery is the behaviour the hooks must mirror.

    The scratch directory lives inside the repo so ruff resolves the same
    ruff.toml it would in CI.
    """
    with tempfile.TemporaryDirectory(dir=REPO_ROOT, prefix=".ruff-probe-") as scratch:
        probe = Path(scratch) / path.name
        shutil.copyfile(path, probe)
        argv = (
            ["ruff", "check", "--show-files", scratch]
            if subcommand == "check"
            else ["ruff", "format", "--check", scratch]
        )
        result = subprocess.run(argv, cwd=REPO_ROOT, capture_output=True, text=True)
    if subcommand == "check":
        return bool(result.stdout.strip())
    return bool(re.search(r"\b1 file\b", result.stdout + result.stderr))


def _one_tracked_file_per_suffix() -> dict[str, Path]:
    """One representative tracked file per extension, for probing ruff."""
    listing = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    representatives: dict[str, Path] = {}
    for line in listing.stdout.splitlines():
        path = REPO_ROOT / line
        if path.suffix and path.is_file():
            representatives.setdefault(path.suffix, path)
    return representatives


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


def test_both_ruff_hooks_declare_a_types_or_override() -> None:
    """The upstream definitions list only python/pyi/jupyter, which is wrong for
    both subcommands here: `ruff format` also walks Markdown (Python inside
    fences) and `ruff check` also walks TOML. Without an override, `git commit`
    reports "(no files to check)Skipped" for a file the CLI processes and the
    required CI job goes red on a commit that passed every local gate.
    """
    for hook_id, hook in _ruff_hooks().items():
        assert hook.get("types_or") is not None, (
            f"{hook_id} has no types_or override, so it inherits the upstream "
            "python/pyi/jupyter list and misses files its CI step checks."
        )


@pytest.mark.parametrize("hook_id", sorted(RUFF_HOOK_SUBCOMMANDS))
def test_each_ruff_hook_selects_exactly_what_its_subcommand_processes(hook_id: str) -> None:
    """The hook's file selection must equal ruff's own, measured not assumed.

    Asserting a hard-coded list would only relocate the drift: the list and
    reality could then disagree, with the list wrong and the test still green.
    So this probes `ruff` itself with one real file per tracked extension and
    requires the hook's `types_or` to agree on every one. A new extension, or a
    ruff release that starts or stops handling a type, fails here rather than
    in CI on somebody's unrelated PR.
    """
    subcommand = RUFF_HOOK_SUBCOMMANDS[hook_id]
    declared = set(_ruff_hooks()[hook_id]["types_or"])
    mismatches = []
    for suffix, path in sorted(_one_tracked_file_per_suffix().items()):
        ruff_covers = _ruff_covers(subcommand, path)
        hook_selects = bool(identify.tags_from_path(str(path)) & declared)
        if ruff_covers != hook_selects:
            rel = path.relative_to(REPO_ROOT)
            mismatches.append(
                f"  {suffix}: `ruff {subcommand}` "
                f"{'processes' if ruff_covers else 'ignores'} {rel}, but the hook "
                f"{'selects' if hook_selects else 'skips'} it"
            )
    assert not mismatches, (
        f"{hook_id} types_or {sorted(declared)} does not match what `ruff {subcommand}` "
        "actually processes:\n" + "\n".join(mismatches)
    )
