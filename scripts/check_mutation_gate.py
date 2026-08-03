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
     baseline in mutmut-baseline.json -> DROPPED, EXCEPT where un-judged
     mutants account for the shortfall -> NOISE-DEGRADED (not a failure; see
     below).

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
OBJC_DISABLE_INITIALIZE_FORK_SAFETY on darwin, re-runs a noise-dominated pass
(cache KEPT, bounded by MAX_CONVERGE_PASSES) to let results converge, and
judges any residue honestly: un-judged mutants are neither killed nor
survived, and a shortfall they explain is reported NOISE-DEGRADED with a
pointer to the authoritative Linux dispatch. Off darwin nothing changes: no
env override, and a healthy pass exits the loop after exactly one run.
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

# Fraction of un-judged mutants above which a pass is treated as noise rather
# than signal.
NOISE_THRESHOLD = 0.5

# Upper bound on `mutmut run` passes. The cache is KEPT between passes, so
# results accumulate; the bound exists so a permanently-noisy machine
# terminates the push instead of hanging it.
MAX_CONVERGE_PASSES = 4

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


def is_noise_degraded(current: dict, threshold: float = NOISE_THRESHOLD) -> bool:
    """True when most of the run produced no usable verdict, i.e. the pass tells
    us nothing and judging it would be a false verdict rather than a real one."""
    total = sum(stats.get("total", 0) for stats in current.values())
    if not total:
        return False
    unjudged = sum(stats.get("unjudged", 0) for stats in current.values())
    return unjudged / total > threshold


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


def evaluate(baseline_per_module: dict, current: dict) -> tuple[list[str], list[str]]:
    """Return (summary table lines, failure lines); empty failures == gate passed."""
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
        unjudged = curr.get("unjudged", 0)
        if curr.get("missing"):
            verdict = "MISSING"
            failed.append(f"{module}: .meta file not found - did mutmut run complete?")
        elif survived > 0:
            # Checked BEFORE the kill-count comparison: a survivor is unambiguous
            # evidence of a weak test, and no amount of fork noise may launder it.
            verdict = "SURVIVED"
            failed.append(f"{module}: {survived} mutant(s) survived - 100% kill rate required")
        elif curr_killed < base_killed:
            # Excuse the shortfall only as far as un-judged mutants account for
            # it. A drop that noise cannot explain is still a real regression.
            if curr_killed + unjudged >= base_killed:
                verdict = "NOISE-DEGRADED"
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
            current = read_current()
            if not is_noise_degraded(current):
                break
        else:
            print(
                f"\nStill noise-degraded after {MAX_CONVERGE_PASSES} passes; judging what "
                "verdicts exist."
            )

    if current is None:
        current = read_current()

    lines, failed = evaluate(load_baseline(), current)
    summary = "\n".join(lines)
    print(summary)
    if any("NOISE-DEGRADED" in line for line in lines):
        # Say plainly that this is "could not measure", not "your tree is fine",
        # and name the gate that can actually answer the question.
        print(
            "\nNOISE-DEGRADED: those modules had mutants that produced no verdict "
            "(segfault, or never executed), a known macOS fork-runner failure rather "
            "than a signal about your tree. Un-judged mutants count as neither killed "
            "nor survived, so the shortfall is not treated as a regression. Any real "
            "survivor still fails the gate. The authoritative verdict is the Linux "
            "dispatch: gh workflow run mutation.yml --ref <branch>."
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
    print("\nAll modules: kill counts >= baseline and 0 survivors. Strict gate passed.")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via tests calling main()
    raise SystemExit(main())
