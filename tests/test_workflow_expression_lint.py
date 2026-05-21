# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Static lint for GitHub Actions workflow files.

These checks codify two specific bugs we have already shipped:

  - PR #130: `git clone https://github.com/${REPO}.git` inside a `run:` block
    falls back to interactive credential prompting on the runner. Switch to
    `actions/checkout@v4`, which configures git auth correctly for any
    follow-up `git push`.

  - PR #131: `fromJSON(steps.X.outputs.Y).field` evaluated unconditionally
    in a `with:` or `env:` block crashes the template parser when the
    step is skipped (the upstream step has `if:`, but expression
    evaluation runs regardless). Wrap with `(steps.X.outputs.Y && fromJSON(...)) || ''`.

Neither pattern is caught by `actionlint` today, so we keep the lint
local. Surfacing them as pytest cases means the standard suite blocks
their reintroduction.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_no_unguarded_fromjson_on_step_outputs(workflow: Path) -> None:
    """Every `fromJSON(steps.*)` call must be preceded by an `&&` short-circuit
    guard on the same expression — otherwise an empty step output crashes
    template validation (PR #131 regression)."""
    pattern = re.compile(r"fromJSON\(steps\.")
    offenders: list[tuple[int, str]] = []
    for lineno, raw in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
        match = pattern.search(raw)
        if not match:
            continue
        before = raw[: match.start()]
        if "&&" not in before:
            offenders.append((lineno, raw.strip()))
    assert not offenders, (
        f"{workflow.name}: unguarded `fromJSON(steps.*)` — wrap with "
        f"`(steps.X.outputs.Y && fromJSON(steps.X.outputs.Y).field) || ''`:\n"
        + "\n".join(f"  L{n}: {line}" for n, line in offenders)
    )


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_no_manual_github_git_clone(workflow: Path) -> None:
    """Forbid `git clone https://github.com/` in workflow `run:` blocks —
    auth via `-c http.extraheader` is unreliable on runners and falls back
    to interactive credential prompting (PR #130 regression). Use
    `actions/checkout@v4` instead."""
    offenders: list[tuple[int, str]] = []
    for lineno, raw in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
        if "git clone https://github.com/" in raw:
            offenders.append((lineno, raw.strip()))
    assert not offenders, (
        f"{workflow.name}: manual `git clone https://github.com/` — replace with "
        f"actions/checkout@v4:\n" + "\n".join(f"  L{n}: {line}" for n, line in offenders)
    )
