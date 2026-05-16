#!/usr/bin/env python3
# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Aggregate promptfoo variance-run outputs into a per-scenario summary.

Promptfoo writes one JSON file per `eval --output` invocation. With --repeat N,
each scenario appears N times in `results.results[*]`. This script walks every
JSON in the input dir, groups by (skill_yaml, scenario_description), counts
PASS / FAIL, and reports the verdict-flip rate per scenario.

Per the eval redesign plan exit criterion #3:
    "Multi-sample variance ≤20% verdict-flip rate per scenario across 5 runs"

A scenario is "stable" if all N runs agreed; "unstable" if the verdict flipped
at least once. Flip-rate = min(pass_count, fail_count) / N — caps at 50%.

Usage:
    python tests/evals/promptfoo/aggregate.py <results_dir>
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def _collect(results_dir: Path) -> dict[tuple[str, str], list[bool]]:
    """Return {(skill_file, scenario_description): [pass_bool, ...]}."""
    buckets: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for json_path in sorted(results_dir.glob("*.json")):
        skill_file = json_path.stem  # e.g. "skill-implementing-with-tdd"
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"  ! skipped (invalid JSON): {json_path.name}", file=sys.stderr)
            continue
        for r in data.get("results", {}).get("results", []):
            desc = (
                r.get("description") or r.get("vars", {}).get("user_prompt", "")[:60] or "<unnamed>"
            )
            verdict = bool(r.get("gradingResult", {}).get("pass"))
            buckets[(skill_file, desc)].append(verdict)
    return buckets


def _report(buckets: dict[tuple[str, str], list[bool]]) -> int:
    total_scenarios = len(buckets)
    if total_scenarios == 0:
        print("No scenarios found. Did you run promptfoo with --output pointing at this dir?")
        return 1

    unstable = []
    for (skill, scenario), verdicts in sorted(buckets.items()):
        n = len(verdicts)
        passes = sum(verdicts)
        fails = n - passes
        flip_rate = min(passes, fails) / n if n else 0.0
        stable = flip_rate == 0
        marker = "✓" if stable else f"⚠ flip={flip_rate:.0%}"
        print(f"  [{marker}] {skill} :: {scenario[:70]}  ({passes}P/{fails}F over {n})")
        if not stable:
            unstable.append((skill, scenario, flip_rate, passes, fails, n))

    print()
    print(f"Scenarios run: {total_scenarios}")
    print(f"Stable (unanimous N runs): {total_scenarios - len(unstable)}")
    print(f"Unstable (verdict flipped): {len(unstable)}")

    if unstable:
        print("\nUnstable scenarios (≥1 flip) — investigate rubric clarity or judge variance:")
        for skill, scenario, rate, p, f, _n in sorted(unstable, key=lambda x: -x[2]):
            print(f"  {skill} :: {scenario[:80]}  flip={rate:.0%} ({p}P/{f}F)")

    # Exit 0 if every scenario flip-rate ≤ 20% (the exit criterion); 1 otherwise.
    over_threshold = [u for u in unstable if u[2] > 0.20]
    return 0 if not over_threshold else 1


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    results_dir = Path(sys.argv[1])
    if not results_dir.is_dir():
        print(f"not a directory: {results_dir}", file=sys.stderr)
        return 2
    buckets = _collect(results_dir)
    return _report(buckets)


if __name__ == "__main__":
    sys.exit(main())
