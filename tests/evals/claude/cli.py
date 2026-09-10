# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Thin CLI over the offline eval-runner core.

Slice 1 supports exactly one mode: `--dry-run`. It loads the matrix,
assembles every prompt for every config, estimates input tokens, prints a
per-config and total summary, and exits zero WITHOUT touching the network.

That is deliberate. Epic #660 exists because the OpenAI credit backing the
old promptfoo gate ran out mid-run; a dry run that can be trusted to cost
nothing is how the matrix gets sized before slice 2 (#662) is allowed to
spend anything. Nothing in this package imports an HTTP client or an SDK,
and `tests/test_claude_eval_runner.py` fails the build if a socket or an
HTTP connection is constructed during a dry run.

Run it as:

    uv run python tests/evals/run_claude_eval.py --dry-run
    uv run python tests/evals/run_claude_eval.py --dry-run --skill reviewing-before-merge
    uv run python tests/evals/run_claude_eval.py --dry-run --config-glob '*.ab.yaml'
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from claude import loader, tokens

__all__ = ["build_parser", "main"]

_NAME_WIDTH = 56


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_claude_eval.py",
        description="Offline core of the Claude skill-eval runner (no API calls).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="assemble every prompt and report estimated input tokens",
    )
    parser.add_argument(
        "--skill",
        default=None,
        help="scope to one skill, e.g. reviewing-before-merge",
    )
    parser.add_argument(
        "--config-glob",
        default=None,
        help="scope to config filenames matching this glob, e.g. '*.ab.yaml'",
    )
    parser.add_argument(
        "--config-dir",
        default=str(loader.PROMPTFOO_DIR),
        help="directory holding the eval configs",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    if not args.dry_run:
        print(
            "only --dry-run is supported in this slice; the Claude "
            "candidate/judge tier arrives in #662",
            file=sys.stderr,
        )
        return 2

    paths = loader.discover_configs(args.config_dir, skill=args.skill, pattern=args.config_glob)
    if not paths:
        print(
            f"no configs matched in {args.config_dir} "
            f"(skill={args.skill!r}, glob={args.config_glob!r})",
            file=sys.stderr,
        )
        return 1

    print("Claude eval runner: DRY RUN, no API calls, no network.")
    print(f"configs: {args.config_dir}")
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
    return 0
