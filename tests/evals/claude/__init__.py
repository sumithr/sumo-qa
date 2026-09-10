# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The Claude skill-eval runner, replacing the OpenAI + promptfoo gate (#660).

This module deliberately re-exports only the OFFLINE core (slice 1, #661): the
config loader, the nunjucks-subset renderer, the assertion model with its
Python ports of the deterministic `javascript` asserts, and the dry run's
token estimate. Importing `claude` therefore still pulls in nothing that can
leave the process.

The grading tier (slice 2, #662) lives in `claude.provider`, `claude.judge`,
`claude.runner`, `claude.errors`, `claude.models` and `claude.report`, and is
imported from those modules directly rather than re-exported here - so the
transport, which is the one place a child process is created, stays off the
import path of anything that only needs the offline half.

It grades through the local Claude Code CLI on the account's Claude
subscription; there is no model SDK anywhere in the package and nothing here
speaks HTTP. promptfoo keeps running untouched until slice 4 retires it,
gated on a parity run.

Entry point: `uv run python tests/evals/run_claude_eval.py` (free), plus
`--live` to grade.
"""

from claude.assertions import (
    AssertionResult,
    JavascriptAssertion,
    RubricAssertion,
    evaluator_for,
)
from claude.loader import (
    EvalCase,
    EvalConfig,
    build_cases,
    discover_configs,
    load_all_configs,
    load_config,
)
from claude.templating import render
from claude.tokens import estimate_tokens

__all__ = [
    "AssertionResult",
    "EvalCase",
    "EvalConfig",
    "JavascriptAssertion",
    "RubricAssertion",
    "build_cases",
    "discover_configs",
    "estimate_tokens",
    "evaluator_for",
    "load_all_configs",
    "load_config",
    "render",
]
