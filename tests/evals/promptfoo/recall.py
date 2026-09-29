#!/usr/bin/env python3
# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Report review recall from promptfoo runs of the review-recall corpus (#754).

`skill-reviewing-before-merge-recall.yaml` holds real past review misses, each
tagged in `metadata` with its ledger `category` and a `split` (`train` or
`held-out`); negative controls carry `category: control`. A case counts as
caught when its promptfoo grade passed (the expected file is named and the judge
matched the defect). This script reads one or more promptfoo JSON reports and
prints recall overall, per category and per split for each run, then the mean
and the spread (max - min) of overall recall across runs, then how many runs
caught each case.

Each report is one run; a report written with `--repeat N` holds N rows per
case, and the k-th row of a case belongs to run k. A result that errored (a
provider error, or a judge that returned no verdict) is not a skill verdict,
so the report is refused rather than scored as a miss.

Usage:
    python tests/evals/promptfoo/recall.py <report.json> [<report.json> ...]

Exit codes: 0 report printed; 2 unusable input (no results, an errored result,
a case missing `category` or `split`).
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

CONTROL = "control"
_ERROR = 2  # promptfoo ResultFailureReason.ERROR


class ReportError(Exception):
    """The report cannot be scored as recall."""


def _bucket() -> dict[str, int]:
    return {"caught": 0, "total": 0}


def _rate(bucket: dict[str, int]) -> float:
    return bucket["caught"] / bucket["total"] if bucket["total"] else 0.0


def _is_error(result: dict) -> bool:
    # promptfoo also copies a failed grade's reason into `error`, so only the
    # failure reason tells a provider error from a miss.
    if result.get("failureReason") == _ERROR:
        return True
    components = (result.get("gradingResult") or {}).get("componentResults") or []
    return any((c.get("metadata") or {}).get("graderError") for c in components)


def _rows(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"{path}: unreadable report ({exc})") from exc
    rows = ((data.get("results") or {}).get("results")) or []
    if not rows:
        raise ReportError(f"{path}: no results")
    return rows


def _case(path: Path, row: dict) -> tuple[str, str, str, bool]:
    test = row.get("testCase") or {}
    name = row.get("description") or test.get("description") or "<unnamed>"
    if _is_error(row):
        raise ReportError(f"{path}: {name} errored; not a skill verdict")
    meta = test.get("metadata") or {}
    for key in ("category", "split"):
        if not meta.get(key):
            raise ReportError(f"{path}: {name} has no metadata.{key}")
    caught = bool((row.get("gradingResult") or {}).get("pass"))
    return name, meta["category"], meta["split"], caught


def _new_run() -> dict:
    return {
        "overall": _bucket(),
        "categories": defaultdict(_bucket),
        "splits": defaultdict(_bucket),
        "controls": {"passed": 0, "total": 0},
    }


def summarise(paths: list[Path]) -> dict:
    """Score every report; return per-run buckets, mean, spread and per-case counts."""
    runs: list[dict] = []
    cases: dict[str, dict] = {}
    for path in paths:
        seen: dict[str, int] = defaultdict(int)
        file_runs: list[dict] = []
        for row in _rows(Path(path)):
            name, category, split, caught = _case(Path(path), row)
            index = seen[name]
            seen[name] += 1
            while len(file_runs) <= index:
                file_runs.append(_new_run())
            run = file_runs[index]
            if category == CONTROL:
                run["controls"]["total"] += 1
                run["controls"]["passed"] += caught
                continue
            for bucket in (run["overall"], run["categories"][category], run["splits"][split]):
                bucket["total"] += 1
                bucket["caught"] += caught
            case = cases.setdefault(
                name, {"caught": 0, "runs": 0, "category": category, "split": split}
            )
            case["runs"] += 1
            case["caught"] += caught
        runs.extend(file_runs)

    for run in runs:
        run["categories"] = dict(run["categories"])
        run["splits"] = dict(run["splits"])
        run["overall"]["recall"] = _rate(run["overall"])
    rates = [run["overall"]["recall"] for run in runs]
    return {
        "runs": runs,
        "mean_recall": sum(rates) / len(rates),
        "spread": max(rates) - min(rates),
        "cases": cases,
    }


def _line(label: str, bucket: dict[str, int]) -> str:
    return f"{label}: {bucket['caught']}/{bucket['total']} ({_rate(bucket):.0%})"


def render(summary: dict) -> str:
    out: list[str] = []
    for number, run in enumerate(summary["runs"], start=1):
        out.append(f"run {number}")
        out.append("  " + _line("overall recall", run["overall"]))
        for name in sorted(run["splits"]):
            out.append("  " + _line(name, run["splits"][name]))
        for name in sorted(run["categories"]):
            out.append("    " + _line(name, run["categories"][name]))
        controls = run["controls"]
        out.append(f"  controls passed: {controls['passed']}/{controls['total']}")
    out.append(
        f"mean overall recall: {summary['mean_recall']:.0%} over {len(summary['runs'])} run(s); "
        f"spread {summary['spread']:.0%}"
    )
    out.append("per case (caught/runs):")
    for name, case in sorted(summary["cases"].items(), key=lambda kv: (kv[1]["category"], kv[0])):
        out.append(f"  {case['caught']}/{case['runs']}  [{case['split']}] {name}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(__doc__)
        return 2
    try:
        summary = summarise([Path(a) for a in args])
    except ReportError as exc:
        print(f"recall: {exc}", file=sys.stderr)
        return 2
    print(render(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
