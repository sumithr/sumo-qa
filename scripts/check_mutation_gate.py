# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Mutation-gate verdict: compare mutmut results against the committed baseline.

Single source of truth for the gate shared by the nightly CI workflow
(.github/workflows/mutation.yml) and the local pre-push hook
(.pre-commit-config.yaml). It exists because `mutmut run` exits 0 even when
mutants survive (root-caused 2026-07-13: the pre-push hook trusted mutmut's
exit code and so never once failed on a survivor-introducing push - that is
how PR #302's 47 survivors reached main). The verdict must therefore be
computed from mutmut's .meta files, never inferred from its exit status.

Reads per-module data directly from mutmut's .meta files - each
mutants/src/sumo_qa/<module>.py.meta contains a JSON object whose
"exit_code_by_key" maps mutant name -> exit code. Exit-code semantics
(from mutmut source, __main__.py status_by_exit_code):
  1, 3, -24        -> killed
  0                -> survived
  5, 33            -> no tests
  34               -> skipped
  35               -> suspicious
  36, 24, 152, 255 -> timeout
  37               -> caught by type check
  -11, -9          -> segfault
  all others       -> suspicious

Two independent failure conditions (both must pass):
  1. Strict-100% gate: any surviving (exit code 0) mutant -> SURVIVED.
     Checked FIRST: a survivor is unambiguous evidence of a weak test and is
     never excused, however noisy the rest of the run was.
  2. Regression catch: any module's killed count below the committed
     baseline in mutmut-baseline.json -> DROPPED, EXCEPT on a LOCAL darwin
     --run-mutmut invocation where that module has ANY un-judged mutant
     -> NOT-MEASURED (not a failure, and not a pass either; see below).

With --run-mutmut the script invokes the `mutmut run` console script (never
`python -m mutmut`; see docs/DEVELOPMENT.md) and propagates a non-zero mutmut
exit immediately - a crashed run leaves stale .meta files behind, and judging
those would be a false verdict.

macOS fork noise (#523). A wiped-out run yields mutants with no verdict at
all: a segfault (-11/-9), or the `null` mutmut pre-populates exit_code_by_key
with at generation time and never fills in when the run aborts before
executing them. Both are outside the killed set and both differ from 0, so
both used to read as killed=0/survived=0 and report every module DROPPED on a
clean tree, blocking the push. So --run-mutmut sets
OBJC_DISABLE_INITIALIZE_FORK_SAFETY on darwin, and any module with an un-judged
mutant is reported NOT-MEASURED on the LOCAL path instead of blocking the push.

SINGLE PASS by design. An earlier revision retried a noisy run and folded the
passes together to recover a real local verdict. That fold produced an unearned
"strict gate passed" in five consecutive review rounds, through five
structurally different holes, because the underlying data cannot support it:
combining a kill count observed in one pass with a completeness observed in
another asserts something no single observation ever made. The invariant now is
simply that EVERY module verdict comes from exactly ONE metadata snapshot. Any
survivor in that snapshot fails; any un-judged mutant in it yields NOT-MEASURED;
only a snapshot with zero un-judged mutants may reach OK or DROPPED. What is
given up is recovering a strict local verdict after a transient noisy pass, and
that is worth it: the local result is advisory anyway, and a run now costs ~6
minutes rather than up to ~12. That is deliberately not a claim that the
tree is clean, and exit 0 here means "not blocking", never "gate passed".

No threshold is used, because none is sound. mutmut-baseline.json stores kill
COUNTS, not mutant identities, so a shortfall can never be attributed to the
mutants that actually went un-judged. Any threshold therefore fails on one side
or the other: above it, a single un-judged mutant excuses an unrelated real
regression in the same module; below it, partial fork noise on a clean tree
still reports DROPPED, which is the original push-blocking bug. So the local
run makes no attribution claim at all.

The tolerance is LOCAL-ONLY: evaluate() takes tolerate_unjudged, default False,
enabled only for a darwin --run-mutmut invocation. .github/workflows/mutation.yml
runs this script WITHOUT --run-mutmut, so the authoritative Linux gate keeps the
original strict semantics and never greens a run it could not measure. A real
survivor fails on either path.

Changed-only scoping (#641, LOCAL hook only). `--changed-only` narrows a
`--run-mutmut` pass to what the push touches, instead of the whole gate on any
test-file edit (a cold full pass is 15+ minutes at --max-children 1):
  - the changed files are `git diff --name-only <from>...HEAD`, <from> being
    PRE_COMMIT_FROM_REF when pre-commit supplies a real sha, else origin/main;
  - a changed `paths_to_mutate` module selects the glob `sumo_qa.<module>.*`;
  - a changed tests/**/*.py selects one glob per mutated function the cached
    mutants/mutmut-stats.json maps that file to (a test that exercises no
    mutated function cannot create a survivor, so it selects nothing);
  - the globs go to `mutmut run` as positional mutant names, which also limits
    mutmut's clean-test pass to the mapped tests;
  - nothing selected -> exit 0 without running mutmut; a test change with no
    stats file -> the full run (the map cannot be inverted safely);
  - only in-scope modules are judged; the rest are listed SKIPPED, never
    MISSING. mutation.yml never passes the flag, so CI stays a full pass.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - 3.10 only
    import tomli as tomllib

# Killed exit codes - copied from mutmut/__main__.py status_by_exit_code.
KILLED_EXIT_CODES = {1, 3, -24}

# Exit codes that carry NO verdict about the mutant (#523). Two shapes:
#   -11 / -9  the fork-based runner segfaulted the child on macOS;
#   None      mutmut pre-populates exit_code_by_key with null at generation
#             time and fills it in as each mutant completes, so a run that
#             aborts before executing them leaves null behind.
# Neither is in KILLED_EXIT_CODES nor equals 0, so both used to collapse to
# killed=0/survived=0 and report every module DROPPED on a clean tree.
SEGFAULT_EXIT_CODES = {-11, -9}

_FORK_SAFETY_ENV = "OBJC_DISABLE_INITIALIZE_FORK_SAFETY"


def module_stats_from_exit_codes(exit_codes: dict) -> dict:
    """Summarise one module's exit codes into killed/survived/unjudged counts."""
    return {
        "killed": sum(1 for ec in exit_codes.values() if ec in KILLED_EXIT_CODES),
        "survived": sum(1 for ec in exit_codes.values() if ec == 0),
        "unjudged": sum(1 for ec in exit_codes.values() if ec is None or ec in SEGFAULT_EXIT_CODES),
        "total": len(exit_codes),
        "missing": False,
        "survivor_names": sorted(k for k, ec in exit_codes.items() if ec == 0),
    }


def module_stats(meta_path: Path) -> dict:
    """Summarise one module's .meta file into killed/survived/unjudged counts."""
    if not meta_path.exists():
        return {"killed": 0, "survived": 0, "unjudged": 0, "total": 0, "missing": True}
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return module_stats_from_exit_codes(meta.get("exit_code_by_key", {}))


def module_not_measured(stats: dict) -> bool:
    """True when ANY of this module's mutants produced no verdict.

    Deliberately NOT a threshold. A threshold is unsound in both directions
    here, because mutmut-baseline.json stores kill COUNTS and not mutant
    identities, so a shortfall can never be attributed to the mutants that
    actually went un-judged:
      - above the threshold, one un-judged mutant excuses an unrelated real
        regression in the same module;
      - below it, partial fork noise on a clean tree still reports DROPPED,
        which is the original push-blocking bug.
    So a run with any un-judged mutant simply is not a measurement, and the
    local gate says so instead of guessing.
    """
    return stats.get("unjudged", 0) > 0


_ZERO_SHA = "0" * 40


def resolve_changed_since_ref(environ: dict) -> str:
    """The ref the push is measured against.

    pre-commit exports PRE_COMMIT_FROM_REF on pre-push: the remote branch's
    current sha, or all zeros for a branch that does not exist remotely yet.
    Anything else (no env, the zero sha) falls back to origin/main."""
    ref = environ.get("PRE_COMMIT_FROM_REF", "")
    if ref and ref != _ZERO_SHA:
        return ref
    return "origin/main"


def changed_files_since(ref: str) -> list[str]:
    """Files changed on HEAD since it diverged from ``ref`` (three-dot diff, so
    a stale remote ref does not drag main's own changes into scope)."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{ref}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def mutated_modules_from_pyproject(path: Path) -> list[str]:
    """Module stems of ``[tool.mutmut] paths_to_mutate``, read live so the
    scope never drifts from the gate's own target list."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    paths = data.get("tool", {}).get("mutmut", {}).get("paths_to_mutate", [])
    return [Path(p).stem for p in paths]


def load_stats_map(path: Path) -> dict | None:
    """mutmut's cached mangled-function -> test-ids map, or None when cold."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("tests_by_mangled_function_name", {})


class Scope:
    """What a changed-only pass must run. A plain class, not a dataclass: the
    test suite loads this script via spec_from_file_location without a
    sys.modules entry, which dataclass decoration needs on 3.14."""

    def __init__(
        self,
        globs: list[str] | None = None,
        modules: set[str] | None = None,
        full_run: bool = False,
        reason: str = "",
    ) -> None:
        self.globs = globs or []
        self.modules = modules or set()
        self.full_run = full_run
        self.reason = reason


def select_scope(
    changed_files: list[str], mutated_modules: list[str], stats_map: dict | None
) -> Scope:
    """Decide what a changed-only pass must run. See the module docstring."""
    changed = set(changed_files)
    module_hits = {m for m in mutated_modules if f"src/sumo_qa/{m}.py" in changed}
    changed_tests = {f for f in changed if f.startswith("tests/") and f.endswith(".py")}

    if changed_tests and stats_map is None:
        return Scope(
            modules=set(mutated_modules),
            full_run=True,
            reason="a test file changed but mutants/mutmut-stats.json is cold; falling back to the full run",
        )

    function_hits: set[str] = set()
    for key, tests in (stats_map or {}).items():
        if any(t.split("::", 1)[0] in changed_tests for t in tests):
            module = key.split(".")[1] if key.startswith("sumo_qa.") else ""
            if module in mutated_modules and module not in module_hits:
                function_hits.add(key)

    globs = [f"sumo_qa.{m}.*" for m in sorted(module_hits)]
    globs += [f"{key}*" for key in sorted(function_hits)]
    modules = set(module_hits) | {key.split(".")[1] for key in function_hits}
    if not globs:
        return Scope(reason="nothing in scope: no mutated module or mapped test changed")
    return Scope(globs=globs, modules=modules, reason=f"scoped to {', '.join(globs)}")


def mutmut_child_env() -> dict | None:
    """Child env for `mutmut run`, or None to inherit unchanged.

    On darwin the fork-based runner segfaults nearly every mutant without
    OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES. Extends os.environ rather than
    replacing it so PATH (which resolves the `mutmut` console script) survives.
    Returns None off darwin so the Linux/CI path is byte-for-byte unchanged.
    """
    if sys.platform != "darwin":
        return None
    return {**os.environ, _FORK_SAFETY_ENV: "YES"}


def evaluate(
    baseline_per_module: dict,
    current: dict,
    tolerate_unjudged: bool = False,
    modules_in_scope: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Return (summary table lines, failure lines); empty failures == gate passed.

    `tolerate_unjudged` is OFF by default and is enabled ONLY for a local darwin
    `--run-mutmut` invocation. The nightly Linux workflow calls this script with
    no `--run-mutmut` (.github/workflows/mutation.yml), so it keeps the original
    strict semantics exactly: the authoritative gate must never green a run it
    could not measure.
    """
    failed: list[str] = []
    lines = [
        "| Module | Baseline killed | Current killed | Survivors | Verdict |",
        "| --- | --- | --- | --- | --- |",
    ]
    for module, base in baseline_per_module.items():
        if modules_in_scope is not None and module not in modules_in_scope:
            # Not touched by this push (#641): its .meta is whatever the last
            # pass left, so it carries no verdict about this change.
            lines.append(f"| {module} | {base['killed']} | - | - | SKIPPED |")
            continue
        curr = current.get(
            module, {"killed": 0, "survived": 0, "unjudged": 0, "total": 0, "missing": True}
        )
        base_killed = base["killed"]
        curr_killed = curr["killed"]
        survived = curr["survived"]
        if curr.get("missing"):
            verdict = "MISSING"
            failed.append(f"{module}: .meta file not found - did mutmut run complete?")
        elif survived > 0:
            # Checked BEFORE the kill-count comparison: a survivor is unambiguous
            # evidence of a weak test, and no amount of fork noise may launder it.
            verdict = "SURVIVED"
            failed.append(f"{module}: {survived} mutant(s) survived - 100% kill rate required")
        elif tolerate_unjudged and module_not_measured(curr):
            # Checked BEFORE the kill-count comparison, and independently of it.
            # "Any un-judged mutant means this module was not measured" has to
            # hold whatever the kill count says: a module sitting at or above
            # baseline with un-judged mutants is still un-measured, and letting
            # it read OK would produce exactly the unearned "strict gate passed"
            # claim this design exists to prevent. Newly-generated mutants that
            # go un-judged are the realistic case.
            verdict = "NOT-MEASURED"
        elif curr_killed < base_killed:
            verdict = "DROPPED"
            failed.append(f"{module}: killed dropped from {base_killed} -> {curr_killed}")
        else:
            verdict = "OK"
        lines.append(f"| {module} | {base_killed} | {curr_killed} | {survived} | {verdict} |")
    return lines, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--run-mutmut",
        action="store_true",
        help="run `mutmut run` first; propagate its exit code if it crashes",
    )
    parser.add_argument(
        "--max-children",
        type=int,
        default=None,
        help="forwarded to `mutmut run` (macOS fork-segfault mitigation)",
    )
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="with --run-mutmut: run only the mutants the push touches (#641)",
    )
    parser.add_argument(
        "--stats",
        type=Path,
        default=Path("mutants/mutmut-stats.json"),
        help="mutmut's cached stats file (inverted to map changed tests to mutants)",
    )
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=Path("pyproject.toml"),
        help="where [tool.mutmut] paths_to_mutate is read from",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("mutmut-baseline.json"),
        help="path to the committed baseline JSON",
    )
    parser.add_argument(
        "--meta-root",
        type=Path,
        default=Path("mutants/src/sumo_qa"),
        help="directory holding mutmut's <module>.py.meta files",
    )
    args = parser.parse_args(argv)

    # The baseline is read LAZILY, never before `mutmut run` has succeeded.
    # A crashed mutmut must propagate its exit code without touching the
    # baseline or the .meta files (judging stale results is a false verdict),
    # and the gate also runs inside mutmut's own `mutants/` working copy during
    # the clean-test phase, where mutmut-baseline.json is not present at all.
    baseline_per_module: dict | None = None

    def load_baseline() -> dict:
        nonlocal baseline_per_module
        if baseline_per_module is None:
            baseline_per_module = json.loads(args.baseline.read_text(encoding="utf-8"))[
                "per_module"
            ]
        return baseline_per_module

    def read_current() -> dict:
        return {
            module: module_stats(args.meta_root / f"{module}.py.meta") for module in load_baseline()
        }

    if args.changed_only and not args.run_mutmut:
        print("--changed-only requires --run-mutmut", file=sys.stderr)
        return 2

    scope: Scope | None = None
    if args.changed_only:
        ref = resolve_changed_since_ref(os.environ)
        scope = select_scope(
            changed_files_since(ref),
            mutated_modules_from_pyproject(args.pyproject),
            load_stats_map(args.stats),
        )
        print(f"changed-only (since {ref}): {scope.reason}")
        if not scope.globs and not scope.full_run:
            return 0
        if scope.full_run:
            scope = None

    current = None
    if args.run_mutmut:
        cmd = ["mutmut", "run"]
        if args.max_children is not None:
            cmd += ["--max-children", str(args.max_children)]
        if scope is not None:
            cmd += scope.globs
        env = mutmut_child_env()
        run_kwargs = {"env": env} if env is not None else {}
        result = subprocess.run(cmd, **run_kwargs)
        if result.returncode != 0:
            print(
                f"mutmut run failed (exit {result.returncode}); not judging stale .meta files.",
                file=sys.stderr,
            )
            return result.returncode
        current = read_current()

    if current is None:
        current = read_current()

    # The noise tolerance is a LOCAL macOS affordance only. CI runs this script
    # without --run-mutmut, so it keeps the original strict semantics.
    tolerate = bool(args.run_mutmut) and sys.platform == "darwin"
    lines, failed = evaluate(
        load_baseline(),
        current,
        tolerate_unjudged=tolerate,
        modules_in_scope=scope.modules if scope is not None else None,
    )
    summary = "\n".join(lines)
    print(summary)
    if any("NOT-MEASURED" in line for line in lines):
        # Say plainly that this run did not gate, rather than implying it did.
        print(
            "\nNOT-MEASURED: those modules had mutants that produced no verdict "
            "(segfault, or never executed), a known macOS fork-runner failure. This "
            "run therefore did NOT enforce the mutation gate on them, and is not "
            "evidence that they are clean. It makes no claim either way. Any real "
            "survivor still fails, here and everywhere. For an actual verdict run "
            "the Linux gate: gh workflow run mutation.yml --ref <branch>."
        )
    # Surface to GitHub Actions step summary when running in CI.
    gh_summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary_path:
        Path(gh_summary_path).write_text(f"## Mutation gate\n\n{summary}\n", encoding="utf-8")

    if failed:
        print("\nFAIL: mutation gate failed:")
        for f in failed:
            print(f"  - {f}")
        # List surviving mutant names so triage can start without re-running mutmut.
        print("\nSurviving mutant names (per module):")
        for module, curr in current.items():
            names = curr.get("survivor_names", [])
            if names:
                print(f"\n  [{module}] {len(names)} survivors:")
                for n in names:
                    print(f"    - {n}")
        return 1
    if any("NOT-MEASURED" in line for line in lines):
        # Do NOT claim the strict gate passed: it was not enforced on those
        # modules. Exit 0 means "not blocking your push", never "gate passed".
        print(
            "\nNo survivors found. NOT a strict-gate pass: the NOT-MEASURED modules "
            "above were not gated locally. Not blocking the push."
        )
        return 0
    print("\nAll modules: kill counts >= baseline and 0 survivors. Strict gate passed.")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via tests calling main()
    raise SystemExit(main())
