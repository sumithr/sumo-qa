# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Offline core of the Claude skill-eval runner (slice 1 of epic #660).

This package replaces promptfoo's OFFLINE half: it loads the existing
promptfoo YAML configs, resolves their `file://` vars, renders their
templates, evaluates the deterministic `javascript` assertions in Python and
parses (never grades) the `llm-rubric` ones, then reports an estimated token
cost for the whole matrix.

It makes NO network call and imports NO model SDK. The Claude candidate and
judge tier is slice 2 (#662); promptfoo keeps running untouched until slice 4
retires it, gated on a parity run.

Entry point: `uv run python tests/evals/run_claude_eval.py --dry-run`.
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
