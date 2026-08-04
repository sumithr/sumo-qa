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
clean tree, blocking the push. So --run-mutmut now sets
OBJC_DISABLE_INITIALIZE_FORK_SAFETY on darwin, and re-runs any pass in which
some module was not measured (cache KEPT, bounded by MAX_CONVERGE_PASSES),
FOLDING each pass into the last rather than replacing it - mutmut
re-initialises verdicts on a later run, so evaluating only the final pass could
erase a survivor an earlier one saw.

If un-judged mutants remain, the LOCAL run reports NOT-MEASURED for those
modules and does not block the push. That is deliberately not a claim that the
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
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

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

# Upper bound on `mutmut run` passes. A pass costs ~6 minutes, and this runs
# synchronously in a pre-push hook, so the bound is deliberately tight: turning
# a blocked push into a 24-minute one is not a fix. #523's own evidence is that
# a single extra pass resolved the wipeout both times it was observed.
MAX_CONVERGE_PASSES = 2

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


def any_not_measured(current: dict) -> bool:
    """True when any module was not fully measured. One un-judged mutant is
    reason enough to spend the single retry; the bound keeps that affordable."""
    return any(module_not_measured(stats) for stats in current.values())


def merge_passes(acc: dict | None, new: dict) -> dict:
    """Fold a fresh pass into the accumulated best-known state.

    A later pass must never ERASE evidence an earlier one produced. mutmut
    re-initialises verdicts on a subsequent run, so a survivor observed in pass 1
    can come back as un-judged in pass 2; taking only the final pass would let a
    genuine survivor vanish behind the retry that was supposed to reduce noise.
    Survivor names therefore accumulate as a union and killed counts take the
    best observed value, while un-judged counts take the latest (converging)
    value.
    """
    if acc is None:
        return new
    merged: dict = {}
    for module, fresh in new.items():
        prior = acc.get(module, {})
        names = sorted(set(prior.get("survivor_names", [])) | set(fresh.get("survivor_names", [])))
        merged[module] = {
            "killed": max(prior.get("killed", 0), fresh.get("killed", 0)),
            "survived": len(names),
            "unjudged": fresh.get("unjudged", 0),
            "total": fresh.get("total", 0) or prior.get("total", 0),
            "missing": bool(fresh.get("missing")) and bool(prior.get("missing")),
            "survivor_names": names,
        }
    return merged


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
    baseline_per_module: dict, current: dict, tolerate_unjudged: bool = False
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
        elif curr_killed < base_killed:
            # On the LOCAL path a module with any un-judged mutant was not
            # measured, so no regression claim can honestly be made about it.
            # This is NOT "noise explains the shortfall" - that claim is
            # unprovable from counts alone. It is "this run did not measure
            # this module", and the caller is told to go run the Linux gate.
            if tolerate_unjudged and module_not_measured(curr):
                verdict = "NOT-MEASURED"
            else:
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

    current = None
    if args.run_mutmut:
        cmd = ["mutmut", "run"]
        if args.max_children is not None:
            cmd += ["--max-children", str(args.max_children)]
        env = mutmut_child_env()
        run_kwargs = {"env": env} if env is not None else {}
        for attempt in range(1, MAX_CONVERGE_PASSES + 1):
            if attempt > 1:
                # The cache is deliberately kept: results accumulate across
                # passes, which is what lets a noisy machine converge.
                print(f"local fork noise, converging (pass {attempt}); max {MAX_CONVERGE_PASSES}")
            result = subprocess.run(cmd, **run_kwargs)
            if result.returncode != 0:
                print(
                    f"mutmut run failed (exit {result.returncode}); not judging stale .meta files.",
                    file=sys.stderr,
                )
                return result.returncode
            # Fold, never replace: a retry must not erase a survivor an earlier
            # pass already observed.
            current = merge_passes(current, read_current())
            if not any_not_measured(current):
                break
        else:
            print(
                f"\nStill un-measured after {MAX_CONVERGE_PASSES} passes; reporting what "
                "verdicts exist."
            )

    if current is None:
        current = read_current()

    # The noise tolerance is a LOCAL macOS affordance only. CI runs this script
    # without --run-mutmut, so it keeps the original strict semantics.
    tolerate = bool(args.run_mutmut) and sys.platform == "darwin"
    lines, failed = evaluate(load_baseline(), current, tolerate_unjudged=tolerate)
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
