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
list PyYAML but neither `identify` nor `ruff`, so a guard that imported those
would raise ModuleNotFoundError there, and one that shelled out to the ruff
binary would raise FileNotFoundError, either of which takes the whole pre-push
suite and the mutation gate down with it.

Known limit: nothing here re-measures ruff's own discovery, so a config change
that widened it (`extend-include = ["*.html"]`) would leave the hooks behind
without failing these tests. Measuring it needs the ruff binary, which is
exactly what the paragraph above rules out.
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

# pre-commit runs EVERY entry. `alias` adds a second selector rather than
# replacing the id, so `pre-commit run ruff-check` targets both entries that
# carry that id while `pre-commit run ruff-check-config` targets only the
# aliased one. Keying on alias-or-id below is therefore about telling the two
# same-id entries apart, not about mirroring pre-commit's CLI lookup.
# Three entries mirror the one `ruff check + format` CI job: source linting,
# the ruff config files, and formatting.
RUFF_HOOK_NAMES = frozenset({"ruff-check", "ruff-check-config", "ruff-format"})

# What `ruff format --check .` discovers beyond the upstream python/pyi/jupyter
# list. Re-measure before editing.
RUFF_FORMAT_TYPES_OR = {"python", "pyi", "jupyter", "markdown"}

# The files ruff reads as its own configuration. It special-cases these by NAME,
# which is why they need a `files:`-scoped hook rather than a `toml` type tag.
# Ruff also reads `.ruff.toml`, and a nested `**/pyproject.toml` for files under
# it; neither is tracked here, and the first is covered by the hook regex.
RUFF_CONFIG_FILES = ("pyproject.toml", "ruff.toml", ".ruff.toml")

# pre-commit ANDs every file-selecting key it understands, and offers several
# ways to narrow a selection: types, types_or, exclude_types, files, exclude,
# and stages (which can move a hook off `git commit` entirely). Guarding those
# one at a time is a blocklist, and a blocklist is only ever as complete as the
# last review — three separate holes were found that way on this branch. So
# each ruff hook is pinned to an exact set of permitted keys instead: adding
# ANY other key fails until someone re-reasons about what it does to coverage.
PERMITTED_HOOK_KEYS = {
    "ruff-check": {"id", "args"},
    "ruff-check-config": {"id", "alias", "name", "types_or", "files"},
    "ruff-format": {"id", "types_or"},
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
    """The ruff hook entries, keyed the way pre-commit identifies them.

    That key is `alias` when present, else `id`, because two entries share the
    id `ruff-check`: one lints source, one is scoped to the ruff config files.
    pre-commit runs EVERY entry, so a repeated identity is an extra hook rather
    than a redefinition. Keying without rejecting repeats would silently keep
    whichever came last, letting a malformed duplicate sit beside a correct
    entry and pass every assertion below while pre-commit ran both.
    """
    entries = _ruff_repo_entry()["hooks"]
    names = [hook.get("alias", hook["id"]) for hook in entries]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert not duplicates, (
        f"duplicate ruff hook identities in .pre-commit-config.yaml: {duplicates}. "
        "pre-commit runs every entry and identifies a hook by alias-or-id, so a "
        "repeat is an extra hook whose settings are not the ones asserted here. "
        "Give the new entry its own `alias:`."
    )
    assert set(names) == RUFF_HOOK_NAMES, (
        f"expected exactly the {sorted(RUFF_HOOK_NAMES)} hooks, got {sorted(names)}"
    )
    return dict(zip(names, entries, strict=True))


def _assert_no_unreviewed_keys(name: str, hook: dict) -> None:
    """Fail on any hook key outside the reviewed set for that hook.

    An allowlist, not a blocklist. pre-commit ANDs `types`, `types_or`,
    `exclude_types`, `files` and `exclude` together, and `stages` can move a
    hook off `git commit` altogether, so there is no short list of "dangerous"
    keys to deny — each of those silently shrinks what the hook sees while the
    config still reads as correct. Denying them individually missed three
    separate cases on this branch. Requiring the key set to be exactly what was
    reviewed turns every future narrowing, including keys that do not exist
    yet, into a failure that has to be reasoned about.
    """
    unreviewed = sorted(set(hook) - PERMITTED_HOOK_KEYS[name])
    assert not unreviewed, (
        f"{name} declares unreviewed key(s) {unreviewed}. pre-commit ANDs its "
        "file-selecting keys, so types/exclude_types/files/exclude all narrow what "
        "the hook sees, and `stages` can take it off `git commit` entirely — any of "
        "which reopens the CI-vs-commit divergence these tests exist to prevent. "
        f"If the new key is correct, add it to PERMITTED_HOOK_KEYS[{name!r}] "
        "together with a test covering what it does."
    )


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
    hook = _ruff_hooks()["ruff-format"]
    declared = hook.get("types_or")
    assert declared is not None, (
        "ruff-format has no types_or override, so it inherits the upstream "
        "python/pyi/jupyter list and never sees the Markdown CI formats."
    )
    assert set(declared) == RUFF_FORMAT_TYPES_OR, (
        f"ruff-format declares types_or {sorted(declared)}, expected "
        f"{sorted(RUFF_FORMAT_TYPES_OR)}. That mirrors what "
        "`ruff format --check .` discovers; re-measure before changing it."
    )
    _assert_no_unreviewed_keys("ruff-format", hook)


def test_ruff_check_hook_does_not_over_select_toml() -> None:
    """The source-linting hook must not claim every `.toml` in the tree.

    `ruff check` ignores Markdown, and its only non-Python inputs are
    pyproject.toml and ruff.toml, which it special-cases by NAME. A `toml` tag
    therefore hands the hook every tracked `.toml`, including
    tests/fixtures/repo_map/rust_context_crate/Cargo.toml, which
    `ruff check --show-files .` does not list, so `git commit` would lint a file
    CI never does. (That over-selection shipped briefly on this branch.)

    Asserted as "no toml tag" rather than "no types_or at all": re-stating the
    upstream python/pyi/jupyter list explicitly is a legal, behaviour-preserving
    way to write the same hook, and a guard that rejected it would be policing
    spelling rather than behaviour.
    """
    hook = _ruff_hooks()["ruff-check"]
    declared = hook.get("types_or")
    assert "toml" not in set(declared or ()), (
        f"ruff-check declares types_or {sorted(declared)}, which includes 'toml'. "
        "`ruff check` special-cases pyproject.toml and ruff.toml by name, so this "
        "tag over-selects every other tracked .toml that CI ignores. The two config "
        "files are covered by the files-scoped ruff-check-config hook instead."
    )
    _assert_no_unreviewed_keys("ruff-check", hook)


def test_ruff_config_files_are_linted_at_commit_time() -> None:
    """ruff REJECTS an invalid config outright, independent of any lint rule.

    A typo'd selector is syntactically valid TOML, so `check-toml` passes it
    while CI dies with "Unknown rule selector `NOT-A-RULE` in `select`". The
    source-linting hook cannot cover that, because ruff finds these two files by
    name rather than by type, so they get their own files-scoped entry.
    """
    hook = _ruff_hooks()["ruff-check-config"]
    assert hook["id"] == "ruff-check", (
        f"ruff-check-config must alias the ruff-check hook, not {hook['id']!r}"
    )
    # pre-commit ANDs every filter. The upstream ruff-check hook sets types_or
    # to python/pyi/jupyter, so leaving it inherited and adding only `files:`
    # intersects to the empty set: the hook reports "(no files to check)Skipped"
    # and guards nothing while still looking correct in the config. That exact
    # mistake shipped for one commit here, so assert the override, not just the
    # pattern.
    declared = hook.get("types_or")
    assert declared is not None and "toml" in set(declared), (
        f"ruff-check-config declares types_or {declared!r}; it must override the "
        "upstream python/pyi/jupyter list with one containing 'toml'. pre-commit "
        "ANDs types_or with files, so inheriting the upstream list selects nothing "
        "and the hook silently skips every file."
    )
    pattern = hook.get("files")
    assert pattern, "ruff-check-config has no `files:` pattern, so it selects nothing"
    for name in RUFF_CONFIG_FILES:
        assert re.search(pattern, name), (
            f"ruff-check-config's files pattern {pattern!r} does not match {name}, "
            "so an invalid ruff config there would pass `git commit` and fail CI."
        )
    # The same pattern must NOT drag in unrelated TOML, which is the whole
    # reason this is a files-scoped hook rather than a `toml` type tag.
    assert not re.search(pattern, "tests/fixtures/repo_map/rust_context_crate/Cargo.toml"), (
        f"ruff-check-config's files pattern {pattern!r} also matches Cargo.toml, "
        "which `ruff check --show-files .` does not list."
    )
    _assert_no_unreviewed_keys("ruff-check-config", hook)
