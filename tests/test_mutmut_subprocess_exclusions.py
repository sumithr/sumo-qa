# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Loud, immediate guard against the mutmut subprocess-trampoline blind spot.

## The hazard

The mutmut mutation gate (`[tool.mutmut]` in `pyproject.toml`) mutates four
production modules. mutmut works by injecting a *trampoline* into each mutated
function: when the function is called, the trampoline reads the
``MUTANT_UNDER_TEST`` environment variable (set by the mutmut runner) to decide
whether to run the original or the mutant.

A test that spawns a *fresh* Python interpreter (``subprocess`` running
``sys.executable -m sumo_qa`` / ``-c "import sumo_qa.knowledge_loaders; ..."``)
launches a process the mutmut runner did NOT start, so ``MUTANT_UNDER_TEST`` is
absent and the trampoline crashes the moment a mutated function is called::

    KeyError: 'MUTANT_UNDER_TEST'

(Older mutmut releases surfaced this as ``AttributeError: 'NoneType' object has
no attribute 'max_stack_depth'`` — same root cause: trampoline state the spawned
interpreter never inherited.)

## Why it was silent

The pre-push mutmut hook (`.pre-commit-config.yaml`) only fires when a diff
touches a mutated module or any test file. So a newly-added subprocess-spawning
test does NOT break the author's own push — it sits latent until some *unrelated*
later change happens to trip the hook, at which point the failure looks like it
belongs to that unrelated change (the PR #189 / #195 burn).

## The mechanism this guard enforces

Excluding such a test from mutation is legitimate (it exercises packaging /
the real server entry point, not the mutated parser internals). The mechanism is
a single declarative marker plus a reciprocal cross-check, so nobody has to carry
the ``--ignore`` list in their head:

1. A test that spawns a subprocess importing the ``sumo_qa`` package or a mutated
   module declares it with the marker comment ``MUTMUT_SUBPROCESS_MARKER`` AND is
   added to ``[tool.mutmut].pytest_add_cli_args`` as ``--ignore=...``.
2. This guard runs in the ORDINARY pytest suite (not the nightly mutmut job), so
   it fails LOUDLY and IMMEDIATELY in the PR that introduces an unmarked /
   unignored subprocess-spawning test — long before the latent mutmut failure
   could surface against an unrelated change.

The guard is a static check: it never invokes mutmut, so it works on every
platform (mutmut's fork-based runner segfaults on macOS) and at PR time.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover -- 3.10 backport path
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"
PYPROJECT = REPO_ROOT / "pyproject.toml"

# The declarative marker a test author adds to opt a subprocess-spawning test
# out of the mutmut gate. Discoverable: this exact string lives in the guard,
# in pyproject's [tool.mutmut] comment, and in docs/DEVELOPMENT.md.
MUTMUT_SUBPROCESS_MARKER = "mutmut-subprocess-spawning"


def _mutated_module_names() -> set[str]:
    """The bare module names mutmut mutates, e.g. {'knowledge_loaders', ...}."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    paths = data["tool"]["mutmut"]["paths_to_mutate"]
    return {Path(p).stem for p in paths}


def _mutmut_ignored_test_files() -> set[str]:
    """Test files excluded via [tool.mutmut].pytest_add_cli_args --ignore=tests/...."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    cli_args = data["tool"]["mutmut"]["pytest_add_cli_args"]
    ignored = set()
    for arg in cli_args:
        if arg.startswith("--ignore=tests/"):
            ignored.add(arg[len("--ignore=") :])
    return ignored


def _spawns_subprocess_importing_mutated_code(path: Path) -> bool:
    """True if this test file spawns a fresh Python interpreter that imports the
    sumo_qa package or a mutated module — the trampoline-crash hazard class.

    Sound over-approximation that avoids the substring/token-confusion failure
    mode (equivalence partitioning): a test that merely *names* ``sumo_qa`` in a
    string arg, asserts on ``["-m", "sumo_qa"]`` without spawning, mocks
    ``subprocess.run``, or spawns a non-mutated entry point (``-m
    sumo_qa.installer`` / ``sumo_qa.doctor``) is NOT flagged. The hazard is a
    REAL spawn whose command imports the full package (``-m sumo_qa``, which
    transitively imports all four mutated modules via the server) or a mutated
    module by name.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    mutated = _mutated_module_names()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_real_subprocess_spawn(node):
            continue
        # The first positional arg is the command arg-list (or a string).
        if not node.args:
            continue
        cmd = _string_literals_in(node.args[0])
        # The spawn must actually launch a Python interpreter.
        if not _is_python_interpreter_spawn(cmd):
            continue
        if _command_imports_mutated_code(cmd, mutated):
            return True
        # `python -c "<inline code>"` / `python -m <pkg>` where the inline code
        # or following args import a mutated module: scan every string literal
        # the call carries (covers `-c` bodies built as separate variables too).
        all_strings = _string_literals_in(node)
        if _command_imports_mutated_code(all_strings, mutated):
            return True
    return False


def _is_real_subprocess_spawn(node: ast.Call) -> bool:
    """True for subprocess.run/Popen/check_output/check_call/call(...)."""
    func = node.func
    name = None
    if isinstance(func, ast.Attribute):
        name = func.attr
        # subprocess.<x> or sp.<x> — accept attribute access on any name; the
        # method name is the discriminator.
    elif isinstance(func, ast.Name):
        name = func.id
    return name in {"run", "Popen", "check_output", "check_call", "call"}


def _is_python_interpreter_spawn(cmd_strings: list[str]) -> bool:
    """True if the command launches a Python interpreter (sys.executable shows up
    as an empty placeholder, or a literal python token)."""
    # sys.executable is not a string literal, so _string_literals_in() yields the
    # following tokens (-m / -c / module). We treat the presence of `-m` or `-c`
    # as the interpreter signal, since those are interpreter flags. A literal
    # "python"/"python3" token also counts.
    for s in cmd_strings:
        if s in {"-m", "-c"}:
            return True
        if s in {"python", "python3"} or s.endswith("/python") or s.endswith("/python3"):
            return True
    return False


def _command_imports_mutated_code(strings: list[str], mutated: set[str]) -> bool:
    """True if the gathered command/source strings import the sumo_qa package or
    a mutated module."""
    for s in strings:
        # `-m sumo_qa` (exact, the full package entry → transitive mutated import)
        # or `-m sumo_qa.ingest` etc. Bare `sumo_qa` token from a `-m` arg.
        if s == "sumo_qa":
            return True
        # An inline `-c` body or a module arg that references a mutated module.
        for m in mutated:
            if f"sumo_qa.{m}" in s or f"import {m}" in s:
                return True
        # `-m sumo_qa.<sub>` where <sub> is a known mutated-importing entry.
        if s.startswith("sumo_qa.ingest"):
            return True
    return False


def _string_literals_in(node: ast.AST) -> list[str]:
    """All str constant literals reachable under an AST node, in source order."""
    out: list[str] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return out


def _has_marker(path: Path) -> bool:
    return MUTMUT_SUBPROCESS_MARKER in path.read_text(encoding="utf-8")


ALL_TEST_FILES = sorted(TESTS_DIR.glob("test_*.py"))


@pytest.mark.parametrize("test_file", ALL_TEST_FILES, ids=lambda p: p.name)
def test_subprocess_spawning_tests_are_excluded_and_marked(test_file: Path) -> None:
    """Every test that spawns a subprocess importing mutated code MUST be in the
    mutmut --ignore list AND carry the marker. Fires loudly at PR time."""
    if not _spawns_subprocess_importing_mutated_code(test_file):
        return  # not a hazard — nothing to enforce

    rel = f"tests/{test_file.name}"
    ignored = _mutmut_ignored_test_files()
    assert rel in ignored, (
        f"{rel} spawns a Python subprocess that imports the sumo_qa package or a "
        f"mutated module, so it will CRASH the mutmut trampoline "
        f"(KeyError: 'MUTANT_UNDER_TEST') and silently disarm the mutation gate. "
        f"Add it to [tool.mutmut].pytest_add_cli_args in pyproject.toml as "
        f'"--ignore={rel}" and annotate it with the marker '
        f"{MUTMUT_SUBPROCESS_MARKER!r}. See docs/DEVELOPMENT.md."
    )
    assert _has_marker(test_file), (
        f"{rel} is in the mutmut --ignore list but is missing the "
        f"{MUTMUT_SUBPROCESS_MARKER!r} marker comment. Add the marker so the "
        f"exclusion is self-documenting (see docs/DEVELOPMENT.md)."
    )


def test_every_ignored_file_is_a_real_subprocess_hazard() -> None:
    """Reciprocal: every file in the mutmut --ignore list must actually be a
    subprocess hazard (or the wheel-build packaging test), so the list cannot
    accumulate stale or unjustified exclusions that quietly shrink mutation
    coverage. Keeps the exclusion mechanism honest in both directions."""
    ignored = _mutmut_ignored_test_files()
    assert ignored, "expected at least the known subprocess exclusions in pyproject"

    # test_wheel_packaging spawns `pip wheel` (a build subprocess against the
    # incomplete mutants/ tree), not `-m sumo_qa`; it is a legitimate exclusion
    # under the same CWD/incomplete-tree rationale but isn't an import-mutated-
    # code spawn, so it's allow-listed here by name with its marker checked.
    build_subprocess_exclusions = {"tests/test_wheel_packaging.py"}

    for rel in sorted(ignored):
        path = REPO_ROOT / rel
        assert path.exists(), f"{rel} is in the mutmut --ignore list but does not exist"
        is_import_hazard = _spawns_subprocess_importing_mutated_code(path)
        assert is_import_hazard or rel in build_subprocess_exclusions, (
            f"{rel} is in the mutmut --ignore list but does not spawn a subprocess "
            f"importing mutated code, and is not a known build-subprocess exclusion. "
            f"Stale exclusions shrink mutation coverage — remove it or justify it "
            f"in {sorted(build_subprocess_exclusions)}."
        )
        assert _has_marker(path), (
            f"{rel} is excluded from mutmut but is missing the "
            f"{MUTMUT_SUBPROCESS_MARKER!r} marker comment (see docs/DEVELOPMENT.md)."
        )
