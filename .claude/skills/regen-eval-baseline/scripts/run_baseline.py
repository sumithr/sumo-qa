#!/usr/bin/env python3
"""Capture a promptfoo eval baseline for one sumo-qa skill config.

Runs `npx promptfoo eval` against the selected config — a base skill YAML
(`--skill <name>`) or an exact suffixed / `.ab.yaml` config (`--config
<selector>`) — writes the JSON output to
docs/qa/runs/eval-baselines/<date>-skill-<slug>__<label>.json, and prints a
pass/fail summary. If a prior baseline exists for the same config, also
prints a brief delta.

The slug and label are separated by a literal ``__`` (double underscore).
Both are validated kebab-case tokens (lowercase alphanumerics + single
hyphens), so neither can contain ``__`` — that makes the slug/label boundary
unambiguous even when the label is itself multi-hyphen (e.g.
``removability-gate``). A single-hyphen separator would be ambiguous: with a
multi-hyphen label, ``<slug>-<label>`` cannot be split back into its parts
without a closed label vocabulary, and the label vocabulary is open-ended
(see ``--label``).

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
        docs/qa/runs/eval-baselines/<date>-skill-<skill>__<label>.json
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


def resolve_config_path(promptfoo_dir: Path, *, skill: str | None, config: str | None) -> Path:
    """Resolve the exact promptfoo config to drive, EXACTLY as named.

    The repo carries three config shapes side by side: a base
    ``skill-<name>.yaml``, suffixed scenario variants such as
    ``skill-reviewing-before-merge-adversarial.yaml``, and ``.ab.yaml`` A/B
    controls. Because the base name is a *prefix* of every suffixed sibling,
    a glob/prefix match would cross-match a base skill against a longer
    variant. This resolver is exact on purpose: it composes one concrete
    filename and requires that exact file to exist — it never scans for a
    near-named neighbour.

    Exactly one of ``skill`` / ``config`` must be given:

    - ``skill="reviewing-before-merge"`` → ``skill-reviewing-before-merge.yaml``
      (the base config only; never a suffixed sibling).
    - ``config`` may be an exact path (``/abs/skill-x.ab.yaml`` or a relative
      one), a filename (``skill-x-adversarial.yaml``), or a bare stem
      (``skill-x-adversarial`` / ``skill-x.ab``) resolved inside the
      promptfoo dir. Double suffixes such as ``.ab.yaml`` are preserved.

    Raises ``FileNotFoundError`` if the composed path does not exist — it does
    NOT fall back to a similarly-named sibling.
    """
    if (skill is None) == (config is None):
        raise ValueError("Provide exactly one of skill / config.")

    if skill is not None:
        candidate = promptfoo_dir / f"skill-{skill}.yaml"
    else:
        assert config is not None
        raw = Path(config)
        if raw.suffix == ".yaml" and (raw.is_absolute() or len(raw.parts) > 1):
            # An explicit path (absolute, or carrying a directory component).
            candidate = raw
        elif config.endswith(".yaml"):
            # A bare filename (possibly double-suffixed, e.g. *.ab.yaml).
            candidate = promptfoo_dir / config
        else:
            # A bare stem — append the single .yaml extension. ``.ab`` etc.
            # stay part of the stem so the double suffix is preserved.
            candidate = promptfoo_dir / f"{config}.yaml"

    if not candidate.is_file():
        raise FileNotFoundError(
            f"No promptfoo config at {candidate}. The selector resolves an exact "
            "file and does not fall back to a near-named sibling — check the "
            "config name (base skill vs suffixed variant vs .ab.yaml control)."
        )
    return candidate


def load_summary(path: Path) -> tuple[int, int]:
    """Return (passed, failed) counts from a promptfoo output JSON."""
    if not path.is_file():
        return (0, 0)
    data = json.loads(path.read_text(encoding="utf-8"))
    results = data.get("results", {})
    stats = results.get("stats", {})
    return (int(stats.get("successes", 0)), int(stats.get("failures", 0)))


def config_to_slug(config_path: Path) -> str:
    """Turn a resolved config filename into a kebab-case snapshot slug.

    The snapshot filename uses ``<date>-skill-<slug>__<label>.json``; the slug
    must be a valid kebab-case token (see ``validate_slug``). A config stem
    carries the ``skill-`` prefix and may carry a ``.ab`` infix
    (``skill-x-adversarial.ab.yaml`` → stem ``skill-x-adversarial.ab``); strip
    the ``skill-`` prefix and turn the ``.ab`` dot into a hyphen so two
    distinct configs for the same base skill (``-adversarial`` vs
    ``-adversarial.ab``) snapshot to distinct, non-colliding names.
    """
    # `.ab.yaml` is a double suffix: Path.stem strips only the last one.
    stem = config_path.name.removesuffix(".yaml")
    return stem.removeprefix("skill-").replace(".", "-")


# Slug and label are separated by ``__`` (a token neither a kebab slug nor a
# kebab label can contain), so the boundary is unambiguous even for a
# multi-hyphen label. The slug is captured non-greedily up to the FIRST ``__``;
# the label (which may itself contain ``-``) is the remainder.
SNAPSHOT_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-skill-(?P<slug>.+?)__(?P<label>.+)\.json$")


def parse_snapshot_slug(name: str) -> str | None:
    """Extract the slug from a snapshot filename, or None if it doesn't parse.

    Snapshots are written as ``<date>-skill-<slug>__<label>.json`` where both
    ``<slug>`` and ``<label>`` are kebab-case tokens. The ``__`` separator is
    unambiguous: neither a kebab slug nor a kebab label can contain a double
    underscore (``validate_slug`` enforces lowercase alphanumerics + single
    hyphens only), so the slug is everything between ``skill-`` and the FIRST
    ``__``, regardless of how many hyphens the label carries.

    The earlier ``<slug>-<label>`` form with a single-hyphen separator was
    ambiguous for multi-hyphen labels (``removability-gate``): an
    ``rpartition('-')`` split would peel only the final segment, parsing
    ``reviewing-before-merge-removability-gate`` as slug
    ``reviewing-before-merge-removability`` (dropping ``-gate``) — missing the
    real prior and cross-matching a different suffixed config. The ``__``
    separator removes that ambiguity without needing a closed label vocabulary
    (the label set is open-ended — see ``--label``).
    """
    m = SNAPSHOT_NAME_RE.match(name)
    if m is None:
        return None
    return m.group("slug")


def find_prior_baseline(baselines_dir: Path, slug: str, current: Path) -> Path | None:
    """Most recent prior snapshot for this EXACT slug, by date-prefix order.

    Selection matches the slug as a bounded token (parsed out of the
    ``<date>-skill-<slug>__<label>.json`` filename and compared for equality),
    not as a glob substring — the same exact-token discipline
    ``resolve_config_path`` uses on the selection side. The ``__`` boundary
    means this holds even when the label is multi-hyphen: target
    ``reviewing-before-merge`` matches only ``…-skill-reviewing-before-merge__*``
    and never a suffixed sibling ``…-skill-reviewing-before-merge-adversarial__*``
    (whose parsed slug is the longer ``reviewing-before-merge-adversarial``).
    This prevents a base config from picking a later-dated *suffixed sibling*'s
    snapshot (``…-adversarial…``, ``…-ab…``) as its prior and printing a delta
    across two different eval suites.
    """
    if not baselines_dir.is_dir():
        return None
    candidates = sorted(
        p
        for p in baselines_dir.glob("*-skill-*.json")
        if p != current and parse_snapshot_slug(p.name) == slug
    )
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
        default=None,
        help=(
            "Base skill name (matches tests/evals/promptfoo/skill-<name>.yaml "
            "exactly — never a suffixed sibling). Mutually exclusive with --config."
        ),
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Exact config selector for a suffixed scenario or .ab.yaml control "
            "(e.g. 'skill-reviewing-before-merge-adversarial', "
            "'skill-x.ab.yaml', or a full path). Resolved exactly — no "
            "cross-matching a base skill against longer siblings. Mutually "
            "exclusive with --skill."
        ),
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

    if (args.skill is None) == (args.config is None):
        print(
            "Provide exactly one of --skill (base skill) or --config (exact "
            "suffixed / .ab.yaml selector or path).",
            file=sys.stderr,
        )
        return 2

    try:
        if args.skill is not None:
            validate_slug(args.skill, "skill")
        validate_slug(args.label, "label")
    except ValueError as e:
        print(f"Invalid input: {e}", file=sys.stderr)
        return 2

    repo_root = args.repo_root or find_repo_root(Path.cwd())
    promptfoo_dir = repo_root / "tests" / "evals" / "promptfoo"

    try:
        yaml_path = resolve_config_path(promptfoo_dir, skill=args.skill, config=args.config)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        available = sorted(p.name for p in promptfoo_dir.glob("skill-*.yaml"))
        if available:
            print("Available configs:", file=sys.stderr)
            for s in available:
                print(f"  - {s}", file=sys.stderr)
        return 2

    snapshot_slug = config_to_slug(yaml_path)

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
    output_path = baselines_dir / f"{today}-skill-{snapshot_slug}__{args.label}.json"
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
        prior = find_prior_baseline(baselines_dir, snapshot_slug, output_path)
        if prior:
            print("\nDelta vs prior baseline:")
            print_delta(prior, output_path)
        else:
            print("\nNo prior baseline for this config — this snapshot becomes the first.")

    if failed:
        print(
            "\nFAILs present. Repo policy: strengthen SKILL.md so the candidate passes, "
            "never loosen the rubric. Invoke the `eval-failure-diagnoser` subagent "
            "to identify which SKILL.md sections to strengthen."
        )

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
