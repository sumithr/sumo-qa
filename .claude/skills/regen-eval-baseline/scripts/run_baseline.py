#!/usr/bin/env python3
"""Capture a promptfoo eval baseline for one sumo-qa skill.

Runs `npx promptfoo eval` against the named skill's YAML, writes the JSON
output to docs/qa/runs/eval-baselines/<date>-skill-<name>-<label>.json,
and prints a pass/fail summary. If a prior baseline exists for the same
skill, also prints a brief delta.

The baseline directory is gitignored — these snapshots are local evidence
of past runs, not artefact that ships with the repo.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_slug(value: str, field: str) -> None:
    """Reject anything that isn't kebab-case lower-alphanumeric.

    Both `--skill` and `--label` are interpolated into the snapshot
    filename:
        docs/qa/runs/eval-baselines/<date>-skill-<skill>-<label>.json
    A value containing `/` or `..` can land the snapshot outside the
    baselines dir entirely. Reject before composing the path so the
    validation failure is on the input, not on the resulting state.
    """
    if not SLUG_RE.fullmatch(value):
        raise ValueError(
            f"{field}={value!r} is not a valid kebab-case slug. "
            "Expected lowercase letters, digits, and single hyphens only "
            "(e.g. 'baseline' or 'implementing-with-tdd'). Reject reason: "
            "prevents the snapshot path from escaping the baselines dir."
        )


def find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return start


def load_summary(path: Path) -> tuple[int, int]:
    """Return (passed, failed) counts from a promptfoo output JSON."""
    if not path.is_file():
        return (0, 0)
    data = json.loads(path.read_text(encoding="utf-8"))
    results = data.get("results", {})
    stats = results.get("stats", {})
    return (int(stats.get("successes", 0)), int(stats.get("failures", 0)))


def find_prior_baseline(baselines_dir: Path, skill: str, current: Path) -> Path | None:
    """Most recent prior snapshot for this skill, sorted lexicographically (date prefix)."""
    if not baselines_dir.is_dir():
        return None
    candidates = sorted(p for p in baselines_dir.glob(f"*-skill-{skill}-*.json") if p != current)
    return candidates[-1] if candidates else None


def _signed(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)


def print_delta(prior: Path, current: Path) -> None:
    p_pass, p_fail = load_summary(prior)
    c_pass, c_fail = load_summary(current)
    print(f"  Prior baseline: {prior.name} — {p_pass} passed, {p_fail} failed")
    delta_pass = c_pass - p_pass
    delta_fail = c_fail - p_fail
    print(f"  Delta: passed {_signed(delta_pass)}, failed {_signed(delta_fail)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--skill",
        required=True,
        help="Skill name (matches tests/evals/promptfoo/skill-<name>.yaml).",
    )
    parser.add_argument(
        "--label",
        default="baseline",
        help="Snapshot label (default: 'baseline'). Common values: baseline, postcut, greenfix.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repo root override. Default: walk up from cwd looking for pyproject.toml.",
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing snapshot at the target path."
    )
    parser.add_argument(
        "--no-diff", action="store_true", help="Skip the delta-against-prior-baseline section."
    )
    args = parser.parse_args()

    try:
        validate_slug(args.skill, "skill")
        validate_slug(args.label, "label")
    except ValueError as e:
        print(f"Invalid input: {e}", file=sys.stderr)
        return 2

    repo_root = args.repo_root or find_repo_root(Path.cwd())

    yaml_path = repo_root / "tests" / "evals" / "promptfoo" / f"skill-{args.skill}.yaml"
    if not yaml_path.is_file():
        print(f"No eval YAML for skill '{args.skill}' at {yaml_path}.", file=sys.stderr)
        available = sorted(
            p.stem.removeprefix("skill-")
            for p in (repo_root / "tests" / "evals" / "promptfoo").glob("skill-*.yaml")
            if not p.stem.endswith((".gen", ".ab", ".generated-tests"))
        )
        if available:
            print("Available skills:", file=sys.stderr)
            for s in available:
                print(f"  - {s}", file=sys.stderr)
        return 2

    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY is not set. Source ~/.config/promptfoo-keys.env (see tests/evals/promptfoo/README.md) "
            "before running this script — the key must not be passed inline or pasted in chat.",
            file=sys.stderr,
        )
        return 2

    baselines_dir = repo_root / "docs" / "qa" / "runs" / "eval-baselines"
    baselines_dir.mkdir(parents=True, exist_ok=True)

    today = dt.date.today().isoformat()
    output_path = baselines_dir / f"{today}-skill-{args.skill}-{args.label}.json"
    if output_path.exists() and not args.force:
        print(
            f"Snapshot already exists at {output_path}. Re-run with --force to overwrite, "
            "or pick a different --label.",
            file=sys.stderr,
        )
        return 2

    cmd = [
        "npx",
        "promptfoo",
        "eval",
        "-c",
        str(yaml_path),
        "--no-cache",
        "--output",
        str(output_path),
    ]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=repo_root)
    if result.returncode != 0:
        print(
            f"\npromptfoo exited with code {result.returncode}. "
            "Inspect the snapshot at the path above for partial results.",
            file=sys.stderr,
        )

    if not output_path.is_file():
        print(
            f"\nExpected snapshot at {output_path} was not written. "
            "promptfoo may have failed before producing output.",
            file=sys.stderr,
        )
        return result.returncode or 1

    passed, failed = load_summary(output_path)
    print(f"\nSnapshot captured: {output_path.relative_to(repo_root)}")
    print(f"  {passed} passed, {failed} failed")

    if not args.no_diff:
        prior = find_prior_baseline(baselines_dir, args.skill, output_path)
        if prior:
            print("\nDelta vs prior baseline:")
            print_delta(prior, output_path)
        else:
            print("\nNo prior baseline for this skill — this snapshot becomes the first.")

    if failed:
        print(
            "\nFAILs present. Repo policy: strengthen SKILL.md so the candidate passes, "
            "never loosen the rubric. Invoke the `eval-failure-diagnoser` subagent "
            "to identify which SKILL.md sections to strengthen."
        )

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
