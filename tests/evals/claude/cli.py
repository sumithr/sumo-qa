# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The eval runner's command line: a dry run that costs nothing, and a live run.

    uv run python tests/evals/run_claude_eval.py --dry-run
    uv run python tests/evals/run_claude_eval.py --skill reviewing-before-merge
    uv run python tests/evals/run_claude_eval.py --config skill-using-sumo-qa.yaml
    uv run python tests/evals/run_claude_eval.py --repeat 3 --report out.json

## Spending is opt-in

**The default is the dry run.** An invocation with neither `--live` nor
`--dry-run` assembles every prompt, estimates input tokens, prints the
summary and exits, having called nothing. Only `--live` grades.

That default is not politeness. The full matrix is over 200 cases - 218 in a
fresh clone, 229 where the test generator has run - each of which costs a
candidate call and a judge call, and the runner spends the account's
Claude subscription allowance - so a mistyped or forgotten flag has a real
price. Making the free mode the one you get by accident is the only ordering
where the accident is cheap. It has already paid for itself once: an existing
test invoked `main()` with no mode flag, and under an earlier draft where the
live run was the default, that test launched the whole matrix.

`--live` drives the candidate and judge through the local Claude Code CLI on
the account's existing subscription; see `claude/provider.py` for why that
rather than a metered API key.

## Scoping, because the judge tier is the expensive one

`--skill` and `--config` exist so a PR grades only the configs it affects.
`--skill` takes a skill name and picks up every variant config for it;
`--config` takes filenames or globs. Reaching for the full matrix when three
configs would do is the difference between a few minutes and an hour.

## The exit codes, and what is on disk after each

    0  every case passed, or the dry run completed. The report was written.
    1  at least one case failed. The report was written - a completed run
       that found real failures is exactly what the report is for.
    2  the invocation was wrong (no configs matched, --repeat below 1, the
       CLI is missing). Nothing was written.
    3  the run ABORTED on a quota, credit, rate-limit or otherwise
       non-retryable failure. NOTHING WAS WRITTEN - not a partial report,
       not a baseline.

Exit 3 is the #651 regression. The old baseline script turned that situation
into a zero-passed snapshot on disk, which read as a catastrophic skill
regression and became the number the next run compared against. A distinct
code, and an empty disk, is what stops that repeating.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from claude import loader, tokens
from claude.assertions import (
    UnportableJavascriptPatternError,
    UnportedJavascriptAssertionError,
    UnsupportedAssertionTypeError,
)
from claude.errors import FatalRunError
from claude.judge import VERDICT_SCHEMA
from claude.models import CANDIDATE_MODEL, JUDGE_MODEL
from claude.provider import ClaudeCliMissingError, Provider
from claude.report import RunReport, write_report
from claude.runner import (
    CANDIDATE_SYSTEM_PROMPT,
    JUDGE_SYSTEM_PROMPT,
    Runner,
    preflight,
)

__all__ = [
    "EXIT_ABORTED",
    "EXIT_FAILED",
    "EXIT_OK",
    "EXIT_USAGE",
    "build_parser",
    "build_providers",
    "main",
]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_ABORTED = 3

_NAME_WIDTH = 56

# A broken config is a LOCAL mistake, not a failed run, so it exits as usage
# rather than as the abort code that means a matrix died part-way through.
# They were previously uncaught and surfaced as a traceback.
#
# Caught ONLY around `preflight`, which runs before a provider is even built.
# Wrapping the whole run instead would let a mid-run `FileNotFoundError` -
# `CitesCatalogueTechniqueEvaluator` reads `knowledge/techniques.md` lazily,
# on first evaluation - be reported as "no model call was made" on a run that
# had already made plenty.
_CONFIG_ERRORS = (
    loader.MalformedConfigError,
    UnsupportedAssertionTypeError,
    UnportedJavascriptAssertionError,
    UnportableJavascriptPatternError,
    FileNotFoundError,
)

# There is no output-token ceiling to set. The Claude Code CLI exposes no
# `--max-tokens`, so the model's own default applies. That is the right
# default here anyway: the rubrics grade shape and grounding, and a ceiling
# low enough to truncate an answer would fail cases for the wrong reason.


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_claude_eval.py",
        description="Claude skill-eval runner (subscription-backed, via the Claude Code CLI).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="actually grade: call the candidate and judge. Without it, nothing is called.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="the default: assemble every prompt and report estimated input tokens",
    )
    parser.add_argument(
        "--skill",
        default=None,
        help="scope to one skill, e.g. reviewing-before-merge",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="scope to config filenames matching this glob, e.g. 'skill-using-*.yaml'",
    )
    parser.add_argument(
        "--config-glob",
        default=None,
        help=argparse.SUPPRESS,  # slice 1's spelling; --config is the documented one
    )
    parser.add_argument(
        "--config-dir",
        default=str(loader.PROMPTFOO_DIR),
        help="directory holding the eval configs",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="run every case N times and record each result separately (default 1)",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="write the JSON report here; omitted means no file, summary only",
    )
    parser.add_argument(
        "--candidate-model",
        default=CANDIDATE_MODEL,
        help=argparse.SUPPRESS,  # escape hatch; the pair lives in claude/models.py
    )
    parser.add_argument(
        "--judge-model",
        default=JUDGE_MODEL,
        help=argparse.SUPPRESS,
    )
    return parser


def build_providers(args: argparse.Namespace) -> tuple[Provider, Provider]:
    """The candidate and judge tiers, both on the same CLI transport."""
    candidate = Provider(
        model=args.candidate_model,
        system_prompt=CANDIDATE_SYSTEM_PROMPT,
    )
    judge = Provider(
        model=args.judge_model,
        system_prompt=JUDGE_SYSTEM_PROMPT,
        # The schema is the first line of defence on the verdict shape; the
        # tolerant parser in claude/judge.py is the second.
        json_schema=VERDICT_SCHEMA,
    )
    return candidate, judge


def _select(args: argparse.Namespace) -> list[Path]:
    pattern = args.config or args.config_glob
    return loader.discover_configs(args.config_dir, skill=args.skill, pattern=pattern)


def _dry_run(paths: Sequence[Path], config_dir: str) -> int:
    print("Claude eval runner: DRY RUN, no model calls, no network. Pass --live to grade.")
    print(f"configs: {config_dir}")
    print(f"tokens:  {tokens.ESTIMATE_METHOD}")
    print("")

    total_cases = 0
    total_tokens = 0
    for path in paths:
        config = loader.load_config(path)
        cases = loader.build_cases(config)
        config_tokens = sum(tokens.estimate_tokens(c.rendered_prompt) for c in cases)
        total_cases += len(cases)
        total_tokens += config_tokens
        print(f"  {path.name:<{_NAME_WIDTH}} {len(cases):>4} cases  {config_tokens:>10,} tokens")
        for warning in config.warnings:
            print(f"    warning: {warning}", file=sys.stderr)

    print("")
    print(
        f"  {'TOTAL':<{_NAME_WIDTH}} {len(paths)} configs  "
        f"{total_cases} cases  {total_tokens:,} tokens (estimated)"
    )
    return EXIT_OK


def _print_summary(report: RunReport) -> None:
    payload = report.to_dict()
    totals = payload["totals"]
    print("")
    for config in payload["configs"]:
        status = "PASS" if config["passed"] else "FAIL"
        cost = config["cost"]
        print(
            f"  {config['config']:<{_NAME_WIDTH}} {status}  "
            f"{len(config['cases']):>3} cases  "
            f"{cost['input_tokens']:>9,} in  {cost['output_tokens']:>7,} out  "
            f"${cost['usd']:.4f}"
        )
    print("")
    print(
        f"  {'TOTAL':<{_NAME_WIDTH}} "
        f"{totals['passed']}/{totals['cases']} cases passed  "
        f"{totals['input_tokens']:,} in  {totals['output_tokens']:,} out  "
        f"${totals['usd']:.4f} ({payload['cost_basis']} price)"
    )
    print(
        "  cost is the notional list-price equivalent; the run itself was covered "
        "by the Claude subscription."
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    paths = _select(args)
    if not paths:
        print(
            f"no configs matched in {args.config_dir} "
            f"(skill={args.skill!r}, config={(args.config or args.config_glob)!r})",
            file=sys.stderr,
        )
        return EXIT_USAGE

    # Validated before the mode branch: a repeat below 1 is a malformed
    # invocation whether or not it would have spent anything, and reporting it
    # only on the live path would let `--repeat 0` look accepted in a dry run
    # and then fail on the run that mattered.
    if args.repeat < 1:
        print(f"--repeat must be at least 1, got {args.repeat}", file=sys.stderr)
        return EXIT_USAGE

    if not args.live:
        return _dry_run(paths, args.config_dir)

    # Before the providers exist, let alone before a call is made, so the
    # message below cannot be wrong about what it cost.
    try:
        loaded = preflight(paths)
    except _CONFIG_ERRORS as exc:
        print(f"config error: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(
            "No model call was made and nothing was written. Fix the config "
            "and re-run; --dry-run reaches the same loader for free.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        candidate, judge = build_providers(args)
        candidate.ensure_available()
    except ClaudeCliMissingError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    print(
        f"Claude eval runner: candidate={args.candidate_model} judge={args.judge_model} "
        f"configs={len(paths)} repeat={args.repeat}"
    )

    try:
        report = Runner(candidate, judge).run(paths, repeat=args.repeat, loaded=loaded)
    except FatalRunError as exc:
        # The one place this is caught. Nothing is written: not a report, not
        # a baseline, not a partial. See the module docstring and #651.
        print("", file=sys.stderr)
        print(f"RUN ABORTED: {exc}", file=sys.stderr)
        print(
            "No report and no baseline were written. Re-run once the cause is "
            "cleared; a partially-graded matrix would be worse than none.",
            file=sys.stderr,
        )
        return EXIT_ABORTED

    _print_summary(report)
    if args.report:
        write_report(Path(args.report), report)
        print(f"  report: {args.report}")

    return EXIT_OK if report.passed else EXIT_FAILED
