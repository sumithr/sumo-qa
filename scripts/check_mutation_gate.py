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
  1. Regression catch: any module's killed count below the committed
     baseline in mutmut-baseline.json -> DROPPED.
  2. Strict-100% gate: any surviving (exit code 0) mutant -> SURVIVED.

With --run-mutmut the script first invokes the `mutmut run` console script
(never `python -m mutmut`; see docs/DEVELOPMENT.md) and propagates a non-zero
mutmut exit immediately - a crashed run leaves stale .meta files behind, and
judging those would be a false verdict.
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


def module_stats(meta_path: Path) -> dict:
    """Summarise one module's .meta file into killed/survived/total counts."""
    if not meta_path.exists():
        return {"killed": 0, "survived": 0, "total": 0, "missing": True}
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    exit_codes = meta.get("exit_code_by_key", {})
    return {
        "killed": sum(1 for ec in exit_codes.values() if ec in KILLED_EXIT_CODES),
        "survived": sum(1 for ec in exit_codes.values() if ec == 0),
        "total": len(exit_codes),
        "missing": False,
        "survivor_names": sorted(k for k, ec in exit_codes.items() if ec == 0),
    }


def evaluate(baseline_per_module: dict, current: dict) -> tuple[list[str], list[str]]:
    """Return (summary table lines, failure lines); empty failures == gate passed."""
    failed: list[str] = []
    lines = [
        "| Module | Baseline killed | Current killed | Survivors | Verdict |",
        "| --- | --- | --- | --- | --- |",
    ]
    for module, base in baseline_per_module.items():
        curr = current.get(module, {"killed": 0, "survived": 0, "total": 0, "missing": True})
        base_killed = base["killed"]
        curr_killed = curr["killed"]
        survived = curr["survived"]
        if curr.get("missing"):
            verdict = "MISSING"
            failed.append(f"{module}: .meta file not found - did mutmut run complete?")
        elif curr_killed < base_killed:
            verdict = "DROPPED"
            failed.append(f"{module}: killed dropped from {base_killed} -> {curr_killed}")
        elif survived > 0:
            verdict = "SURVIVED"
            failed.append(f"{module}: {survived} mutant(s) survived - 100% kill rate required")
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

    if args.run_mutmut:
        cmd = ["mutmut", "run"]
        if args.max_children is not None:
            cmd += ["--max-children", str(args.max_children)]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(
                f"mutmut run failed (exit {result.returncode}); not judging stale .meta files.",
                file=sys.stderr,
            )
            return result.returncode

    baseline_per_module = json.loads(args.baseline.read_text(encoding="utf-8"))["per_module"]
    current = {
        module: module_stats(args.meta_root / f"{module}.py.meta") for module in baseline_per_module
    }

    lines, failed = evaluate(baseline_per_module, current)
    summary = "\n".join(lines)
    print(summary)
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
