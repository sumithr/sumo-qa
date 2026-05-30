# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Regression tests for .claude/hooks/route-qa-runners.py.

The PostToolUse `route-qa-runners` hook watches Bash tool results. When a
`mutmut run` produced survivors, or a promptfoo/`npm run eval` run reported a
FAIL, it injects a non-blocking reminder naming the repo-local triage agent
(`mutation-survivor-triage` / `eval-failure-diagnoser`). On every other path it
must stay silent and never block the underlying Bash result.

The hook is invoked via subprocess so its real contract is exercised:
- stdin is the PostToolUse payload JSON;
- the only observable output is the Claude hook JSON on stdout (or none);
- the exit code must be 0 on every path (a non-zero exit from a PostToolUse
  hook surfaces as an error and could disrupt the loop).

Technique: decision tables over (command-shape x output-marker). The hook's
behaviour is a conjunction of two conditions — the command must match the
runner, AND the output must carry the survivor / FAIL marker — so each row of
the table is a distinct (command, output, expected-route) combination, plus the
exclusion and false-positive rows the issue calls out as regression guards.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"
FIXTURES_DIR = HOOKS_DIR / "fixtures"
HOOK = HOOKS_DIR / "route-qa-runners.py"


def _read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _run_hook(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )


def _payload(command: str, stdout: str = "", stderr: str = "", exit_code: int = 0) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": stdout, "stderr": stderr, "exit_code": exit_code},
    }


def _additional_context(result: subprocess.CompletedProcess) -> str | None:
    """Return the hook's injected reminder text, or None if it stayed silent.

    A routing hook emits Claude hook JSON with hookSpecificOutput; a silent
    no-op emits empty stdout. This helper centralises that contract and asserts
    the PostToolUse event name whenever output IS present.
    """
    if not result.stdout.strip():
        return None
    output = json.loads(result.stdout)
    spec = output["hookSpecificOutput"]
    assert spec["hookEventName"] == "PostToolUse", (
        f"PostToolUse hook must stamp hookEventName=PostToolUse; got {spec!r}"
    )
    return spec.get("additionalContext", "")


class TestMutmutBranch:
    """`mutmut run` x survivor-status markers route to mutation-survivor-triage."""

    @pytest.mark.parametrize("status", ["survived", "timeout", "suspicious"])
    def test_routes_on_survivor_status(self, status: str) -> None:
        """Each survivor status the hook recognises must trip the reminder.

        Decision-table positive rows: command matches `mutmut run` AND the
        output carries a survivor marker. The fixture covers the human-readable
        `Survived` summary; the parametrised lowercase status word is appended
        so each recognised marker is exercised independently of the fixture.
        """
        body = _read_fixture("mutmut-survivors.txt") + f"\nstatus: {status}\n"
        result = _run_hook(_payload("uv run mutmut run", stdout=body))

        assert result.returncode == 0, f"hook crashed: {result.stderr!r}"
        ctx = _additional_context(result)
        assert ctx is not None, (
            f"hook stayed silent on a mutmut survivor ({status!r}); it must inject a reminder."
        )
        assert "mutation-survivor-triage" in ctx, (
            f"reminder must name the mutation-survivor-triage agent verbatim; got: {ctx!r}"
        )

    def test_silent_when_all_mutants_killed(self) -> None:
        """`mutmut run` with zero survivors is the clean negative row: no marker,
        no reminder."""
        result = _run_hook(_payload("uv run mutmut run", stdout=_read_fixture("mutmut-clean.txt")))

        assert result.returncode == 0
        assert _additional_context(result) is None, (
            "hook routed on a clean mutmut run (all mutants killed); it must stay silent."
        )

    def test_does_not_route_on_grep_survived_false_positive(self) -> None:
        """Regression guard from the issue: `cat log.txt | grep survived` carries
        the word 'survived' in BOTH command and output but is NOT a mutmut run.

        The mutmut branch must gate on the `mutmut run` command, not on the
        survivor word appearing somewhere — otherwise any log-grep trips it.
        """
        result = _run_hook(
            _payload(
                "cat log.txt | grep survived",
                stdout="2024-01-01 mutant survived in some old log\n",
            )
        )

        assert result.returncode == 0
        assert _additional_context(result) is None, (
            "hook routed on `grep survived` — a false positive. The mutmut "
            "branch must require the `mutmut run` command."
        )

    def test_does_not_route_on_quoted_mutmut_run_log_grep(self) -> None:
        """Fix 3 regression guard: `cat "mutmut run.log" | grep survived` embeds
        the substring `mutmut run` inside a quoted filename and the output carries
        the survivor word, but it is the prohibited log-grep class, NOT a real
        invocation.

        A bare `\\bmutmut\\s+run\\b` false-positives here (the `\\b` matches before
        `.log` and a quote prefix is a word boundary). is_mutmut_run must require
        `mutmut` at start-or-whitespace and `run` not followed by a
        filename-continuation char.
        """
        result = _run_hook(
            _payload(
                'cat "mutmut run.log" | grep survived',
                stdout="mutant survived\n",
            )
        )

        assert result.returncode == 0
        assert _additional_context(result) is None, (
            'hook routed on `cat "mutmut run.log" | grep survived` — a false '
            "positive. A quoted/embedded `mutmut run.log` is not an invocation."
        )

    @pytest.mark.parametrize(
        "command",
        [
            "uv run mutmut run",
            "python -m mutmut run",
            "mutmut run",
        ],
    )
    def test_real_mutmut_invocations_still_route(self, command: str) -> None:
        """Fix 3 must not weaken real detection: the canonical invocation shapes
        (uv-run, python -m, and a bare leading `mutmut run`) must still route on a
        survivor."""
        result = _run_hook(_payload(command, stdout=_read_fixture("mutmut-survivors.txt")))

        assert result.returncode == 0, f"hook crashed: {result.stderr!r}"
        ctx = _additional_context(result)
        assert ctx is not None, f"hook stayed silent on a real mutmut invocation {command!r}."
        assert "mutation-survivor-triage" in ctx

    @pytest.mark.parametrize(
        "command",
        [
            "mutmut run",
            "uv run mutmut run",
            "python -m mutmut run",
            "mutmut run --paths-to-mutate src/",
            "mutmut run;",
            "mutmut run && echo done",
        ],
    )
    def test_positive_boundary_real_mutmut_invocations_route(self, command: str) -> None:
        """Positive-boundary fix: a real `mutmut run` followed by whitespace,
        end-of-string, or a shell separator (`;`, `&`) must route on a survivor.

        Guards the boundary allowlist `(?=\\s|$|[;&|)<>` backtick `])` against
        regressing the genuine invocation shapes — flags, a trailing `;`, and an
        `&& echo done` chain all keep `mutmut run` as a standalone runner token.
        """
        result = _run_hook(_payload(command, stdout=_read_fixture("mutmut-survivors.txt")))

        assert result.returncode == 0, f"hook crashed: {result.stderr!r}"
        ctx = _additional_context(result)
        assert ctx is not None, (
            f"positive-boundary fix broke a real mutmut invocation: {command!r} stayed "
            "silent on a survivor but must route."
        )
        assert "mutation-survivor-triage" in ctx


class TestPromptfooBranch:
    """promptfoo / npm-run-eval x FAIL markers route to eval-failure-diagnoser."""

    @pytest.mark.parametrize(
        "command",
        [
            "promptfoo eval -c tests/evals/promptfoo/skill-x.yaml",
            "npm run eval",
            "npm run eval:all",
        ],
    )
    def test_routes_on_fail(self, command: str) -> None:
        """Each recognised eval command, when the output carries a `[FAIL]`
        marker, must route to the diagnoser. Decision-table positive rows over
        the three accepted command shapes."""
        result = _run_hook(
            _payload(command, stdout=_read_fixture("promptfoo-fail.txt"), exit_code=100)
        )

        assert result.returncode == 0, f"hook crashed: {result.stderr!r}"
        ctx = _additional_context(result)
        assert ctx is not None, f"hook stayed silent on a promptfoo FAIL for {command!r}."
        assert "eval-failure-diagnoser" in ctx, (
            f"reminder must name the eval-failure-diagnoser agent verbatim; got: {ctx!r}"
        )

    def test_silent_on_all_pass(self) -> None:
        """A passing promptfoo run carries no `[FAIL]` marker — clean negative row."""
        result = _run_hook(
            _payload("npm run eval", stdout=_read_fixture("promptfoo-pass.txt"), exit_code=0)
        )

        assert result.returncode == 0
        assert _additional_context(result) is None, (
            "hook routed on an all-pass promptfoo run; it must stay silent."
        )

    @pytest.mark.parametrize("command", ["npm run eval:generate", "npm run eval:view"])
    def test_excluded_eval_commands_never_route(self, command: str) -> None:
        """Issue AC: `eval:generate` and `eval:view` are explicitly ignored even
        if their output happens to contain a FAIL-shaped token.

        Guards against a substring match on `eval` catching the excluded
        commands (`eval:generate` starts with `npm run eval`)."""
        result = _run_hook(
            _payload(command, stdout=_read_fixture("promptfoo-fail.txt"), exit_code=1)
        )

        assert result.returncode == 0
        assert _additional_context(result) is None, (
            f"hook routed on an excluded command {command!r}; eval:generate and "
            "eval:view must never trigger the diagnoser reminder."
        )

    def test_routes_on_later_nonzero_failures_summary(self) -> None:
        """Fix 1 regression guard: `npm run eval:all` runs multiple eval files and
        emits a `Failures:` summary per file. Output `Failures: 0` then
        `Failures: 2` (no `[FAIL]` token) carries a real failure in a LATER block.

        A `re.search` that inspects only the FIRST summary stays silent here;
        has_eval_failure must scan ALL `Failures:` matches and route if any > 0.
        """
        output = "eval-a\nFailures: 0\nPasses: 5\n\neval-b\nFailures: 2\nPasses: 3\n"
        assert "[FAIL]" not in output, "fixture must isolate the Failures-summary path"
        result = _run_hook(_payload("npm run eval:all", stdout=output, exit_code=100))

        assert result.returncode == 0, f"hook crashed: {result.stderr!r}"
        ctx = _additional_context(result)
        assert ctx is not None, (
            "hook stayed silent on a later `Failures: 2` summary; it must scan all "
            "`Failures:` lines, not just the first."
        )
        assert "eval-failure-diagnoser" in ctx

    def test_compound_eval_with_excluded_subcommand_still_routes(self) -> None:
        """Fix 2 regression guard (a): `npm run eval && npm run eval:view` genuinely
        ran `npm run eval`. A co-present excluded subcommand (`eval:view`) must NOT
        suppress the whole command.

        The old `\\beval:(?!all)\\w+` scanned the WHOLE command string and returned
        early, swallowing the genuine `npm run eval` run."""
        result = _run_hook(
            _payload(
                "npm run eval && npm run eval:view",
                stdout=_read_fixture("promptfoo-fail.txt"),
                exit_code=100,
            )
        )

        assert result.returncode == 0, f"hook crashed: {result.stderr!r}"
        ctx = _additional_context(result)
        assert ctx is not None, (
            "hook stayed silent on `npm run eval && npm run eval:view`; the genuine "
            "`npm run eval` run must still route despite the co-present eval:view."
        )
        assert "eval-failure-diagnoser" in ctx

    @pytest.mark.parametrize("command", ["npm run eval:view", "npm run eval:generate"])
    def test_bare_excluded_subcommand_still_excluded(self, command: str) -> None:
        """Fix 2 regression guard (b/c): a BARE excluded subcommand with no genuine
        accepted runner present must still be excluded — the Fix 2 scoping must not
        accidentally let `eval:view` / `eval:generate` route on their own."""
        result = _run_hook(
            _payload(command, stdout=_read_fixture("promptfoo-fail.txt"), exit_code=1)
        )

        assert result.returncode == 0
        assert _additional_context(result) is None, (
            f"hook routed on bare {command!r}; with no accepted runner present it "
            "must stay excluded."
        )

    def test_does_not_route_on_quoted_promptfoo_eval_log_grep(self) -> None:
        """Re-review regression guard: the accepted-runner lookahead must exclude
        `.` `-` `/` as well as word-chars and `:`. `cat "promptfoo eval.log" | grep
        "[FAIL]"` reads a log file named `promptfoo eval.log` — it is NOT a
        `promptfoo eval` invocation, so the trailing `.log` must block the match."""
        result = _run_hook(
            _payload(
                'cat "promptfoo eval.log" | grep "[FAIL]"',
                stdout="[FAIL] assertion failed\n",
                exit_code=1,
            )
        )

        assert result.returncode == 0
        assert _additional_context(result) is None, (
            'hook routed on `cat "promptfoo eval.log" | grep "[FAIL]"` — a false '
            "positive. The promptfoo matcher lookahead must exclude `.` so "
            "`eval.log` is not read as a `promptfoo eval` invocation."
        )

    @pytest.mark.parametrize(
        "command",
        [
            "npm run eval-watch",
            "npm run eval.view",
            "npm run eval/generate",
        ],
    )
    def test_does_not_route_on_eval_prefixed_npm_scripts(self, command: str) -> None:
        """Re-review regression guard: `eval`-prefixed npm script names that are
        delimited by `-` `.` `/` (not `:`) are distinct runners, not `npm run eval`.
        The widened lookahead `(?![\\w:./-])` must block them even with FAIL output."""
        result = _run_hook(_payload(command, stdout="[FAIL] assertion failed\n", exit_code=1))

        assert result.returncode == 0
        assert _additional_context(result) is None, (
            f"hook routed on {command!r}; an `eval`-prefixed script delimited by "
            "`.` `-` `/` is not `npm run eval` and must stay silent."
        )

    @pytest.mark.parametrize(
        "command",
        [
            "npm run eval",
            "npm run eval:all",
            "promptfoo eval",
        ],
    )
    def test_accepted_eval_runners_still_route(self, command: str) -> None:
        """Re-review regression guard: widening the lookahead to exclude `.` `-` `/`
        must NOT break the genuine accepted runners. `npm run eval:all` in particular
        must still route — the optional `(?::all)?` group matches `:all` BEFORE the
        lookahead, so the lookahead sees the end-of-token and admits the match."""
        result = _run_hook(
            _payload(command, stdout=_read_fixture("promptfoo-fail.txt"), exit_code=100)
        )

        assert result.returncode == 0, f"hook crashed: {result.stderr!r}"
        ctx = _additional_context(result)
        assert ctx is not None, (
            f"widened lookahead broke an accepted runner: {command!r} stayed silent "
            "on a FAIL but must route."
        )
        assert "eval-failure-diagnoser" in ctx

    @pytest.mark.parametrize(
        "command",
        [
            "npm run eval",
            "npm run eval:all",
            "npm run eval -- --filter x",
            "promptfoo eval",
            "promptfoo eval -c config.yaml",
            "npm run eval && deploy",
        ],
    )
    def test_positive_boundary_accepted_eval_runners_route(self, command: str) -> None:
        """Positive-boundary fix: a real eval runner followed by whitespace,
        end-of-string, or a shell separator must route on a FAIL.

        The boundary allowlist must admit `eval` / `eval:all` when followed by a
        space (flags, `--`, `-c`), end-of-string, or `&&`. `npm run eval:all` in
        particular relies on the optional `(?::all)?` consuming `:all` BEFORE the
        boundary so the lookahead then sees a valid boundary.
        """
        result = _run_hook(
            _payload(command, stdout=_read_fixture("promptfoo-fail.txt"), exit_code=100)
        )

        assert result.returncode == 0, f"hook crashed: {result.stderr!r}"
        ctx = _additional_context(result)
        assert ctx is not None, (
            f"positive-boundary fix broke an accepted runner: {command!r} stayed silent "
            "on a FAIL but must route."
        )
        assert "eval-failure-diagnoser" in ctx

    @pytest.mark.parametrize(
        "command",
        [
            "npm run eval:view",
            "npm run eval:generate",
            "npm run eval-watch",
            "npm run eval.view",
            "npm run eval/generate",
            "npm run eval+generate",
            "npm run eval@foo",
            "npm run eval=x",
            "promptfoo eval+foo",
        ],
    )
    def test_positive_boundary_rejects_non_runner_eval_tokens(self, command: str) -> None:
        """Root-cause guard: any char that is NOT a boundary after the runner
        token must block the match.

        This is the case the open-ended negative lookahead `(?![\\w:./-])` could
        never cover — `+`, `@`, `=` (and `?`, `#`, …) are outside the exclusion
        set, so `eval+generate` / `eval@foo` / `eval=x` / `promptfoo eval+foo`
        wrongly slipped through. The positive boundary allowlist rejects every
        non-boundary suffix, including the `:`-, `.`-, `-`-, `/`-delimited
        sibling scripts, with FAIL output present.
        """
        result = _run_hook(_payload(command, stdout="[FAIL] assertion failed\n", exit_code=1))

        assert result.returncode == 0
        assert _additional_context(result) is None, (
            f"hook routed on {command!r}; a non-boundary char after the runner token "
            "means it is a different script / token, not the eval runner — it must "
            "stay silent."
        )


class TestNonTriggeringPaths:
    """Exit-code contract and the regression guards for non-runner Bash results."""

    def test_generic_pytest_failure_does_not_route(self) -> None:
        """Issue regression guard: a plain pytest failure must NOT route. It is
        neither a mutmut run nor a promptfoo/eval command."""
        result = _run_hook(
            _payload(
                "uv run pytest -q",
                stdout="1 failed, 40 passed\nFAILED tests/test_x.py::test_y\n",
                exit_code=1,
            )
        )

        assert result.returncode == 0
        assert _additional_context(result) is None, (
            "hook routed on a generic pytest failure; only mutmut/promptfoo runs route."
        )

    def test_non_bash_tool_is_ignored(self) -> None:
        """A non-Bash tool result has no command to inspect; the hook stays silent."""
        result = _run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "x.py"},
                "tool_response": {"stdout": "survived [FAIL]", "stderr": "", "exit_code": 0},
            }
        )

        assert result.returncode == 0
        assert _additional_context(result) is None

    def test_exits_zero_on_malformed_stdin(self) -> None:
        """Internal exceptions / malformed JSON must still exit 0 — a PostToolUse
        hook must never disrupt the loop with a non-zero exit."""
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not json at all{",
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0, (
            f"hook must exit 0 even on malformed stdin; got {result.returncode}, "
            f"stderr={result.stderr!r}"
        )
        assert result.stdout.strip() == "", "malformed stdin should produce no routing output."

    def test_exits_zero_with_missing_tool_response(self) -> None:
        """Defensive: a payload missing tool_response must not raise; exit 0, silent."""
        result = _run_hook({"tool_name": "Bash", "tool_input": {"command": "uv run mutmut run"}})

        assert result.returncode == 0
        assert _additional_context(result) is None
