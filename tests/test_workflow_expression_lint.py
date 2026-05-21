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
    """Every `fromJSON(steps.<id>.outputs.<name>)` call must be guarded by an
    `&&` short-circuit on the SAME `steps.<id>.outputs.<name>` value — not just
    by any `&&` on the line. A guard on a different expression (e.g.
    `github.ref == 'refs/heads/main' && fromJSON(steps.x.outputs.y)`) still
    lets `fromJSON('')` execute when the left predicate is true and the step
    output is empty (PR #131 regression, codex P2 follow-up)."""
    fromjson_pattern = re.compile(r"fromJSON\((steps\.[\w-]+\.outputs\.[\w-]+)[^)]*\)")
    offenders: list[tuple[int, str]] = []
    for lineno, raw in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
        for match in fromjson_pattern.finditer(raw):
            step_path = match.group(1)
            # Required guard: literal `<step_path> && fromJSON(<step_path>`.
            # The repeated path is what makes the short-circuit actually skip
            # the fromJSON call when the step output is empty.
            guard = re.compile(rf"{re.escape(step_path)}\s*&&\s*fromJSON\({re.escape(step_path)}")
            if not guard.search(raw):
                offenders.append((lineno, raw.strip()))
                break  # one offender per line is enough
    assert not offenders, (
        f"{workflow.name}: `fromJSON(steps.X.outputs.Y)` not guarded by "
        f"`steps.X.outputs.Y && fromJSON(steps.X.outputs.Y...)` on the same line. "
        f"An `&&` on a different expression doesn't short-circuit the empty-output "
        f"case. Wrap with `(steps.X.outputs.Y && fromJSON(steps.X.outputs.Y).field) || ''`:\n"
        + "\n".join(f"  L{n}: {line}" for n, line in offenders)
    )


def _run_fromjson_lint(workflow_text: str) -> list[tuple[int, str]]:
    """Re-implement the check against arbitrary YAML text for self-testing.
    Kept in sync with test_no_unguarded_fromjson_on_step_outputs above."""
    fromjson_pattern = re.compile(r"fromJSON\((steps\.[\w-]+\.outputs\.[\w-]+)[^)]*\)")
    offenders: list[tuple[int, str]] = []
    for lineno, raw in enumerate(workflow_text.splitlines(), 1):
        for match in fromjson_pattern.finditer(raw):
            step_path = match.group(1)
            guard = re.compile(rf"{re.escape(step_path)}\s*&&\s*fromJSON\({re.escape(step_path)}")
            if not guard.search(raw):
                offenders.append((lineno, raw.strip()))
                break
    return offenders


def test_fromjson_lint_rejects_unrelated_guard() -> None:
    """Self-test of the lint logic: an `&&` on an unrelated expression (e.g.
    `github.ref`) must NOT count as a guard for `fromJSON(steps.x.outputs.y)`.
    Codex P2 finding on PR #133 — the original lint accepted this shape as a
    false negative."""
    yaml = (
        "ref: ${{ github.ref == 'refs/heads/main' && "
        "fromJSON(steps.release.outputs.pr).headBranchName }}\n"
    )
    assert _run_fromjson_lint(yaml), "unrelated-guard form should be flagged"


def test_fromjson_lint_accepts_matching_guard() -> None:
    """Self-test: the canonical guarded form
    `(steps.X.outputs.Y && fromJSON(steps.X.outputs.Y).field) || ''`
    must be accepted."""
    yaml = (
        "ref: ${{ (steps.release.outputs.pr && "
        "fromJSON(steps.release.outputs.pr).headBranchName) || '' }}\n"
    )
    assert not _run_fromjson_lint(yaml), "canonical guarded form should be accepted"


def test_fromjson_lint_rejects_no_guard() -> None:
    """Self-test: a raw `fromJSON(steps.X.outputs.Y)` with no `&&` at all is
    flagged (the PR #131 bug we shipped)."""
    yaml = "ref: ${{ fromJSON(steps.release.outputs.pr).headBranchName }}\n"
    assert _run_fromjson_lint(yaml), "unguarded form should be flagged"


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
