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


LEGACY_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-skill-(?P<region>[a-z0-9-]+)\.json$")


def known_config_slugs(promptfoo_dir: Path) -> frozenset[str]:
    """The snapshot slugs the wrapper can actually resolve, from the configs dir.

    A snapshot slug is whatever ``config_to_slug`` derives from a resolvable
    ``skill-*.yaml`` config (base, suffixed scenario, or ``.ab.yaml`` control)
    — the SAME transform the live capture path applies. This is the set the
    legacy fallback disambiguates against (see ``_legacy_snapshot_matches_slug``):
    a legacy filename is only attributed to a slug that the wrapper could have
    produced, never to an arbitrary prefix peeled off a multi-hyphen name.
    """
    if not promptfoo_dir.is_dir():
        return frozenset()
    return frozenset(config_to_slug(p) for p in promptfoo_dir.glob("skill-*.yaml"))


def _legacy_snapshot_matches_slug(
    name: str, slug: str, known_slugs: frozenset[str] | None = None
) -> bool:
    """Does a pre-``__`` (single-hyphen) snapshot name belong to ``slug``?

    Before this PR introduced the ``__`` slug/label separator, snapshots were
    written as ``<date>-skill-<slug>-<label>.json`` with a single hyphen. The
    new ``SNAPSHOT_NAME_RE`` only recognises the ``__`` form, so on the FIRST
    run after upgrading, a pre-existing legacy snapshot for this exact slug
    would parse to None and be filtered out — the run would report "No prior
    baseline" instead of a before/after delta against it.

    The legacy ``<slug>-<label>`` form is genuinely ambiguous when the label is
    itself multi-hyphen (the very ambiguity the ``__`` separator kills going
    forward, and which legacy labels DID allow — see ``--label`` / SKILL.md).
    A legacy name ``…-skill-reviewing-before-merge-removability-gate.json`` could
    be slug ``reviewing-before-merge`` + label ``removability-gate`` OR slug
    ``reviewing-before-merge-removability`` + label ``gate``. We resolve this by
    consulting the set of KNOWN config slugs the wrapper can actually produce.

    With ``known_slugs`` provided, the rule is **exactly-one-explains**: compute
    the SET of known slugs S whose hyphen-bounded prefix ``f"{S}-"`` explains the
    name's region (S followed by a hyphen and a non-empty label). The name is
    attributed to ``slug`` ONLY when EXACTLY ONE known slug explains the region
    AND that slug IS ``slug``. If TWO OR MORE known slugs explain it the name is
    AMBIGUOUS and matches NOTHING — it is skipped for every target. Losing that
    delta is acceptable; a WRONG prior-baseline match is not. This is symmetric:
    neither the base nor a suffixed sibling can claim an ambiguous name.

    - ``…-skill-reviewing-before-merge-adversarial-baseline.json``, known
      {``reviewing-before-merge``, ``reviewing-before-merge-adversarial``}: BOTH
      explain → ambiguous → skip for BOTH targets. The base
      ``reviewing-before-merge`` does NOT wrong-match it (the cross-match this PR
      exists to prevent), and neither does the suffixed sibling.
    - ``…-skill-reviewing-before-merge-removability-gate.json``, known
      {``reviewing-before-merge``, ``reviewing-before-merge-removability``}: both
      explain → ambiguous → skip for both.
    - ``…-skill-reviewing-before-merge-baseline.json``, known
      {``reviewing-before-merge``} only (no suffixed sibling known): exactly one
      explains → MATCH the base (the common-case delta is recovered).

    With ``known_slugs`` omitted (None), this falls back to the round-1
    behaviour: accept ``<slug>-<label>`` only when ``<label>`` is a SINGLE kebab
    segment and the leading part equals the target slug EXACTLY. That preserves
    the unambiguous single-token legacy case for callers that cannot supply the
    config-slug set.
    """
    if known_slugs is None:
        legacy_re = re.compile(
            rf"^\d{{4}}-\d{{2}}-\d{{2}}-skill-{re.escape(slug)}-(?P<label>[a-z0-9]+)\.json$"
        )
        return legacy_re.match(name) is not None

    m = LEGACY_NAME_RE.match(name)
    if m is None:
        return False
    region = m.group("region")

    def explains(s: str) -> bool:
        # ``s`` is a candidate slug; the region must be ``<s>-<label>`` with a
        # non-empty label (so ``s`` alone, with no trailing label, never counts).
        return region.startswith(f"{s}-") and len(region) > len(s) + 1

    # Exactly-one-explains: the name belongs to ``slug`` only when ``slug`` is the
    # SOLE known slug whose hyphen-bounded prefix explains the region. Two or more
    # explaining slugs → ambiguous → matches nothing (skipped for every target).
    explaining = {s for s in known_slugs if explains(s)}
    return explaining == {slug}


def find_prior_baseline(
    baselines_dir: Path,
    slug: str,
    current: Path,
    known_slugs: frozenset[str] | None = None,
) -> Path | None:
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

    Legacy fallback: a pre-``__`` snapshot (single-hyphen
    ``<date>-skill-<slug>-<label>.json``) is also matched, so the first run
    after upgrading still computes a delta against an existing local snapshot
    instead of reporting "No prior baseline". The legacy ``<slug>-<label>`` form
    is ambiguous for multi-hyphen labels; ``known_slugs`` (the set of slugs the
    wrapper can actually resolve — pass ``known_config_slugs(promptfoo_dir)``)
    disambiguates it so the fallback attributes a legacy name only when EXACTLY
    ONE known slug explains it (and that slug is the target) and NEVER
    wrong-matches a base or a suffixed sibling against a name two or more known
    slugs could explain (see ``_legacy_snapshot_matches_slug``).
    When ``known_slugs`` is omitted the fallback uses the bounded single-token
    rule.
    """
    if not baselines_dir.is_dir():
        return None
    candidates = sorted(
        p
        for p in baselines_dir.glob("*-skill-*.json")
        if p != current
        and (
            parse_snapshot_slug(p.name) == slug
            or _legacy_snapshot_matches_slug(p.name, slug, known_slugs)
        )
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
    # The slug derived from a --config stem is NOT covered by the --skill /
    # --label validation above: config_to_slug strips `skill-` and turns `.ab`
    # into `-`, but otherwise passes the stem through verbatim. A stem such as
    # `skill-foo__bar.yaml` would yield a slug `foo__bar` containing the `__`
    # separator the snapshot filename reserves for the slug/label boundary —
    # SNAPSHOT_NAME_RE would then mis-parse it (slug `foo`, label `bar...`) and
    # find_prior_baseline would miss its own prior. Validate the derived slug
    # against the same kebab-case rule so the `__` boundary can never collide
    # with slug content regardless of how the slug was derived.
    try:
        validate_slug(snapshot_slug, "config-derived slug")
    except ValueError as e:
        print(
            f"Invalid --config {args.config!r}: its filename stem derives the slug "
            f"{snapshot_slug!r}, which is not a valid kebab-case token. {e} "
            "Rename the config so its stem (after the `skill-` prefix) is "
            "lowercase letters, digits, and single hyphens only — in particular "
            "it must not contain `__`, which is reserved as the snapshot "
            "slug/label separator.",
            file=sys.stderr,
        )
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
        prior = find_prior_baseline(
            baselines_dir,
            snapshot_slug,
            output_path,
            known_slugs=known_config_slugs(promptfoo_dir),
        )
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
