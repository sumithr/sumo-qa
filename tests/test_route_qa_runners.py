# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Regression tests for the .claude/hooks/route-qa-runners.py PostToolUse hook.

The hook injects a reminder to route through `mutation-survivor-triage` (mutmut
survivors) or `eval-failure-diagnoser` (promptfoo FAILs) when it sees the
matching runner output on a Bash result. It is advisory only: it must never
block the underlying Bash result and must exit 0 on every path.

Why subprocess (not importlib + monkeypatch): the hook's contract is "given
this real PostToolUse stdin, does it emit the right PostToolUse JSON on stdout
and exit 0?" — directly observable by running it as Claude Code runs it.

THE CENTRAL RISK (issue #127, and the reason an earlier hand-rolled attempt was
discarded): the marker matcher must be built against REAL runner output, not a
fabricated fixture. Real `mutmut run` stdout reports survivors with EMOJI
counters (`🙁 4`), never the literal word "survived" — a hook grepping for
"survived" never fires on real output yet passes against an invented fixture.
Every positive fixture under .claude/hooks/fixtures/ is therefore a byte-for-byte
capture of the real tool:
  - mutmut_survivors.stdout.txt  — real `mutmut run`, 4 survivors (🙁 4)
  - mutmut_clean.stdout.txt      — real `mutmut run`, all 461 killed (🙁 0)
  - mutmut_timeout/suspicious    — the real survivor capture with ONLY the
                                   integer in the verified-real emoji layout
                                   substituted (⏰ N / 🤔 N), every other byte
                                   genuine, to exercise the timeout/suspicious
                                   trigger statuses the AC requires.
  - promptfoo_fail.stdout.txt    — real `promptfoo eval` (echo provider), 1
                                   failed, table cell `[FAIL]`, exit code 100
  - promptfoo_pass.stdout.txt    — real `promptfoo eval`, 1 passed, exit 0

Technique: equivalence partitioning over (command-shape × output-marker) — the
substring/token-confusion failure mode this technique warns about IS the bug
(`grep survived` echoing the word; `eval:generate` containing "eval"); plus
checklist-based testing for the hook contract (exit 0 all paths, PostToolUse
JSON shape, agent named verbatim, never blocks).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".claude" / "hooks" / "route-qa-runners.py"
FIXTURES = REPO_ROOT / ".claude" / "hooks" / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _run_hook(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )


def _post_tool_use(command: str, stdout: str = "", stderr: str = "", exit_code: int = 0) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": stdout, "stderr": stderr, "exit_code": exit_code},
    }


def _additional_context(result: subprocess.CompletedProcess) -> str:
    """Return the hook's injected reminder text, or '' if it stayed silent.

    A non-routing path is allowed to print nothing at all OR valid PostToolUse
    JSON with no additionalContext; both read as 'no reminder'.
    """
    assert result.returncode == 0, f"hook must always exit 0; stderr={result.stderr!r}"
    if not result.stdout.strip():
        return ""
    payload = json.loads(result.stdout)
    spec = payload["hookSpecificOutput"]
    assert spec["hookEventName"] == "PostToolUse", f"wrong hookEventName: {spec}"
    # The hook must never carry a blocking decision on a PostToolUse advisory.
    assert "permissionDecision" not in spec, (
        f"advisory hook must not block the Bash result; got {spec}"
    )
    return spec.get("additionalContext", "") or ""


# --------------------------------------------------------------------------- #
# mutmut branch — positive (real captured output)                              #
# --------------------------------------------------------------------------- #


class TestMutmutSurvivorsRouteToTriage:
    def test_real_survivor_output_routes_to_mutation_survivor_triage(self) -> None:
        """THE regression test. Real `mutmut run` with 4 survivors (🙁 4) and
        the literal word "survived" appearing ZERO times. A hook that grepped
        for "survived" would stay silent here (the discarded attempt); the
        emoji-counter matcher must fire and name `mutation-survivor-triage`.
        """
        out = _fixture("mutmut_survivors.stdout.txt")
        assert "survived" not in out, (
            "fixture invariant: real mutmut output must NOT contain the word "
            "'survived' — if it does, the fixture is no longer a real capture "
            "and the central regression is no longer guarded."
        )
        result = _run_hook(_post_tool_use("uv run mutmut run", stdout=out, exit_code=0))
        context = _additional_context(result)
        assert "mutation-survivor-triage" in context, (
            "hook did not route real mutmut survivor output to "
            f"mutation-survivor-triage. additionalContext={context!r}. The "
            "matcher must parse the 🙁 emoji counter, not the word 'survived'."
        )

    def test_exit_zero_with_survivors_still_routes(self) -> None:
        """`mutmut run` exits 0 EVEN WITH survivors (empirically: both a
        461-killed run and a 4-survivor run exit 0). The mutmut branch must
        key off the emoji counts, never the exit code.
        """
        out = _fixture("mutmut_survivors.stdout.txt")
        result = _run_hook(_post_tool_use("mutmut run", stdout=out, exit_code=0))
        assert "mutation-survivor-triage" in _additional_context(result)

    def test_timeout_status_routes(self) -> None:
        out = _fixture("mutmut_timeout.stdout.txt")
        result = _run_hook(_post_tool_use("mutmut run", stdout=out, exit_code=0))
        assert "mutation-survivor-triage" in _additional_context(result)

    def test_suspicious_status_routes(self) -> None:
        out = _fixture("mutmut_suspicious.stdout.txt")
        result = _run_hook(_post_tool_use("mutmut run", stdout=out, exit_code=0))
        assert "mutation-survivor-triage" in _additional_context(result)


# --------------------------------------------------------------------------- #
# mutmut branch — negative                                                     #
# --------------------------------------------------------------------------- #


class TestMutmutCleanAndFalsePositives:
    def test_clean_run_does_not_route(self) -> None:
        """Real `mutmut run`, all 461 mutants killed (🙁 0, ⏰ 0, 🤔 0). No
        survivor → no reminder.
        """
        out = _fixture("mutmut_clean.stdout.txt")
        result = _run_hook(_post_tool_use("mutmut run", stdout=out, exit_code=0))
        assert _additional_context(result) == "", (
            "hook routed a clean mutmut run (zero survivors). It must only fire "
            "when a survivor/timeout/suspicious count is non-zero."
        )

    def test_grep_survived_command_does_not_route(self) -> None:
        """Regression guard from the issue: `cat log.txt | grep survived`
        echoes the word "survived" in its OUTPUT but is not a mutmut run. The
        command-shape gate must reject it even though the output says
        "survived".
        """
        grep_output = "12:    survived\n48:    survived\n"
        result = _run_hook(
            _post_tool_use("cat log.txt | grep survived", stdout=grep_output, exit_code=0)
        )
        assert _additional_context(result) == "", (
            "hook fired on `grep survived` — a command-shape false positive. "
            "Only an actual `mutmut run` invocation may trigger the mutmut branch."
        )

    def test_cat_mutmut_log_does_not_route(self) -> None:
        """`cat mutmut.log` mentions the string 'mutmut' but is not a run.
        Reading a mutmut log (even one full of real emoji survivor counts)
        must not trigger the hook.
        """
        out = _fixture("mutmut_survivors.stdout.txt")
        result = _run_hook(_post_tool_use("cat mutmut.log", stdout=out, exit_code=0))
        assert _additional_context(result) == "", (
            "hook fired on `cat mutmut.log` — the command is not `mutmut run`."
        )


# --------------------------------------------------------------------------- #
# promptfoo branch                                                             #
# --------------------------------------------------------------------------- #


class TestPromptfooFailsRouteToDiagnoser:
    def test_real_fail_output_routes_to_eval_failure_diagnoser(self) -> None:
        """Real `promptfoo eval`: 1 failed, table cell `[FAIL]`, exit 100."""
        out = _fixture("promptfoo_fail.stdout.txt")
        result = _run_hook(_post_tool_use("promptfoo eval -c x.yaml", stdout=out, exit_code=100))
        context = _additional_context(result)
        assert "eval-failure-diagnoser" in context, (
            f"hook did not route promptfoo FAIL to eval-failure-diagnoser. "
            f"additionalContext={context!r}"
        )

    def test_npm_run_eval_routes(self) -> None:
        out = _fixture("promptfoo_fail.stdout.txt")
        result = _run_hook(_post_tool_use("npm run eval", stdout=out, exit_code=100))
        assert "eval-failure-diagnoser" in _additional_context(result)

    def test_npm_run_eval_all_routes(self) -> None:
        out = _fixture("promptfoo_fail.stdout.txt")
        result = _run_hook(_post_tool_use("npm run eval:all", stdout=out, exit_code=100))
        assert "eval-failure-diagnoser" in _additional_context(result)

    def test_npx_yes_promptfoo_eval_routes(self) -> None:
        """`npx -y promptfoo@<v> eval` (the no-install form, as used to capture
        the fixtures) must route: -y is a boolean flag, promptfoo is the package,
        eval is the subcommand.
        """
        out = _fixture("promptfoo_fail.stdout.txt")
        result = _run_hook(
            _post_tool_use("npx -y promptfoo@0.121.11 eval -c x.yaml", stdout=out, exit_code=100)
        )
        assert "eval-failure-diagnoser" in _additional_context(result)

    def test_pass_run_does_not_route(self) -> None:
        """Real `promptfoo eval`, 1 passed, exit 0, no `[FAIL]` cell."""
        out = _fixture("promptfoo_pass.stdout.txt")
        result = _run_hook(_post_tool_use("promptfoo eval -c x.yaml", stdout=out, exit_code=0))
        assert _additional_context(result) == "", (
            "hook routed a passing promptfoo run. It must only fire on a FAIL "
            "marker or a non-zero failure exit."
        )

    def test_string_exit_code_failure_routes(self) -> None:
        """Defensive: a PostToolUse payload may carry exit_code as a numeric
        STRING rather than an int. A non-zero string code must still count as a
        failure (otherwise an early-crash eval slips past).
        """
        result = _run_hook(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "promptfoo eval -c x.yaml"},
                "tool_response": {"stdout": "", "stderr": "boom", "exit_code": "100"},
            }
        )
        assert "eval-failure-diagnoser" in _additional_context(result)

    def test_early_error_without_fail_marker_routes_on_exit_code(self) -> None:
        """An eval that errors before printing a `[FAIL]` table still routes on
        the non-zero exit alone — the exit code is the fallback signal.
        """
        result = _run_hook(
            _post_tool_use(
                "promptfoo eval -c x.yaml",
                stdout="Error: config not found\n",
                exit_code=1,
            )
        )
        assert "eval-failure-diagnoser" in _additional_context(result)


class TestExcludedEvalCommands:
    """`eval:generate` and `eval:view` must be ignored even if their output or
    exit code looks failure-shaped — they are not eval RUNS. Boundary value
    analysis around the 'is this an eval run' decision.
    """

    def test_eval_generate_is_ignored(self) -> None:
        out = _fixture("promptfoo_fail.stdout.txt")
        result = _run_hook(_post_tool_use("npm run eval:generate", stdout=out, exit_code=100))
        assert _additional_context(result) == "", (
            "hook fired on `npm run eval:generate` — an excluded command."
        )

    def test_eval_view_is_ignored(self) -> None:
        result = _run_hook(_post_tool_use("npm run eval:view", stdout="", exit_code=1))
        assert _additional_context(result) == ""

    def test_promptfoo_generate_is_ignored(self) -> None:
        out = _fixture("promptfoo_fail.stdout.txt")
        result = _run_hook(
            _post_tool_use("promptfoo generate dataset -c x.yaml", stdout=out, exit_code=100)
        )
        assert _additional_context(result) == "", (
            "hook fired on `promptfoo generate` — only `promptfoo eval` runs route."
        )

    def test_promptfoo_view_is_ignored(self) -> None:
        result = _run_hook(_post_tool_use("promptfoo view", stdout="", exit_code=0))
        assert _additional_context(result) == ""


class TestCodexAdversarialFindings:
    """Regressions for the codex adversarial-review pass on this branch — each
    test pins a precision/recall hole codex surfaced in the command-shape gate.
    """

    def test_echo_promptfoo_eval_does_not_route(self) -> None:
        """P1 false positive: `echo promptfoo eval [FAIL]` merely PRINTS the
        words 'promptfoo eval' and '[FAIL]'; promptfoo is not the command word.
        The gate must require promptfoo at the command position, not anywhere
        in argv.
        """
        result = _run_hook(
            _post_tool_use("echo promptfoo eval '[FAIL]'", stdout="promptfoo eval [FAIL]\n")
        )
        assert _additional_context(result) == "", (
            "hook fired on `echo promptfoo eval` — a command-shape false positive. "
            "promptfoo must be the command word, not a printed argument."
        )

    def test_excluded_segment_before_real_eval_still_routes(self) -> None:
        """P1 false negative: a compound command whose FIRST segment is an
        excluded promptfoo subcommand must not suppress routing for a real eval
        in a LATER segment.
        """
        out = _fixture("promptfoo_fail.stdout.txt")
        result = _run_hook(
            _post_tool_use("promptfoo view; promptfoo eval -c x.yaml", stdout=out, exit_code=100)
        )
        assert "eval-failure-diagnoser" in _additional_context(result), (
            "hook missed the real `promptfoo eval` because an earlier "
            "`promptfoo view` segment short-circuited the scan."
        )

    def test_npm_run_eval_with_trailing_flag_routes(self) -> None:
        """`npm run eval --silent` (flags AFTER the script name, the common form)
        is still an eval run — the script is anchored at the token right after
        `run`, so a trailing flag doesn't hide it.
        """
        out = _fixture("promptfoo_fail.stdout.txt")
        result = _run_hook(_post_tool_use("npm run eval --silent", stdout=out, exit_code=100))
        assert "eval-failure-diagnoser" in _additional_context(result)

    def test_npm_run_workspace_value_does_not_false_route(self) -> None:
        """P2 false positive (re-review): `npm run --workspace eval build` runs
        the `build` script with workspace `eval`. Skipping the flag and reading
        its value `eval` as the script would wrongly route. The script must be
        the literal token after `run`.
        """
        out = _fixture("promptfoo_fail.stdout.txt")
        result = _run_hook(
            _post_tool_use("npm run --workspace eval build", stdout=out, exit_code=100)
        )
        assert _additional_context(result) == "", (
            "hook read the `--workspace` value `eval` as the script name. The "
            "script is the literal token immediately after `run`."
        )

    def test_promptfoo_flag_value_eval_does_not_false_route(self) -> None:
        """P2 false positive (re-review): `promptfoo --config eval generate` runs
        the `generate` subcommand with config `eval`. The subcommand must be the
        literal token after `promptfoo`, not a flag value.
        """
        out = _fixture("promptfoo_fail.stdout.txt")
        result = _run_hook(
            _post_tool_use("promptfoo --config eval generate", stdout=out, exit_code=100)
        )
        assert _additional_context(result) == "", (
            "hook read the `--config` value `eval` as the promptfoo subcommand. "
            "The subcommand is the literal token immediately after `promptfoo`."
        )

    def test_quoted_embedded_eval_text_does_not_route(self) -> None:
        """P2 false positive (re-review): a `;`/`|` INSIDE a quoted argument is
        not a command separator. `printf '[FAIL]\\n' "x; promptfoo eval ; y"`
        merely prints text containing `promptfoo eval`; it must not be carved
        into a fake `promptfoo eval` segment.
        """
        result = _run_hook(
            _post_tool_use("printf '[FAIL]\n' \"x; promptfoo eval ; y\"", stdout="[FAIL]\n")
        )
        assert _additional_context(result) == "", (
            "hook split a quoted argument on its embedded `;` and routed printed "
            "text as a real `promptfoo eval`. Segmentation must respect quoting."
        )

    def test_npx_package_flag_value_does_not_false_route(self) -> None:
        """BLOCKER (re-review): `npx -p promptfoo eval` runs the `eval` binary
        with `-p`(ackage) `promptfoo`. The npx value-flag consumes `promptfoo`,
        so the executable is `eval`, not promptfoo — must NOT route.
        """
        out = _fixture("promptfoo_fail.stdout.txt")
        result = _run_hook(_post_tool_use("npx -p promptfoo eval", stdout=out, exit_code=100))
        assert _additional_context(result) == "", (
            "hook read the `-p` value `promptfoo` as the executable. npx "
            "value-flags must consume their following token."
        )

    def test_pipe_stderr_operator_splits_segments(self) -> None:
        """`|&` (pipe-stderr) is a real bash operator and a command separator —
        a real eval after it must still route.
        """
        out = _fixture("promptfoo_fail.stdout.txt")
        result = _run_hook(
            _post_tool_use("promptfoo view |& promptfoo eval -c x.yaml", stdout=out, exit_code=100)
        )
        assert "eval-failure-diagnoser" in _additional_context(result)

    def test_newline_separated_trailing_eval_is_a_documented_non_route(self) -> None:
        """DOCUMENTED LIMITATION (not a bug): a real `promptfoo eval` on a LATER
        line of a multi-line command is not detected. An unquoted newline is
        consumed by the quote-aware lexer as whitespace, so the lines merge into
        one segment. Splitting on newlines naively would re-break quote-awareness
        (a `promptfoo eval` line inside a multi-line quoted string would then
        wrongly route — a false positive). The hook prioritises zero false
        positives; a first-line eval (the common case) still routes. This pins
        the accepted trailing-line miss.
        """
        out = _fixture("promptfoo_fail.stdout.txt")
        result = _run_hook(
            _post_tool_use("promptfoo view\npromptfoo eval -c x.yaml", stdout=out, exit_code=100)
        )
        assert _additional_context(result) == "", (
            "accepted limitation changed: a trailing-line eval now routes. If "
            "intentional (e.g. a real shell parser was adopted), flip this test."
        )

    def test_quoted_multiline_eval_text_does_not_route(self) -> None:
        """The flip side of the limitation above: a `promptfoo eval` line INSIDE
        a multi-line quoted argument must NOT route (this is exactly why naive
        newline-splitting was rejected).
        """
        result = _run_hook(_post_tool_use('echo "foo\npromptfoo eval\nbar"', stdout="[FAIL]\n"))
        assert _additional_context(result) == "", (
            "hook routed a `promptfoo eval` line embedded in a quoted multi-line "
            "echo argument. Quoted newlines must stay inside the token."
        )

    def test_npm_help_run_eval_does_not_route(self) -> None:
        """P3 false positive (re-review): `npm help run eval` has `run` as an
        ARGUMENT to `help`, not as the npm subcommand. The script lookup must
        anchor `run` at the subcommand position, not match it anywhere in argv.
        """
        result = _run_hook(
            _post_tool_use("npm help run eval", stdout="usage: npm run\n", exit_code=1)
        )
        assert _additional_context(result) == "", (
            "hook fired on `npm help run eval` — `run` here is an argument to "
            "`help`, not the npm subcommand."
        )

    def test_global_flag_before_subcommand_is_a_documented_non_route(self) -> None:
        """DOCUMENTED LIMITATION (not a bug): a value-taking global flag before
        the subcommand (`npm --prefix ./pkg run eval`) is not recognised, because
        telling `--prefix ./pkg run` (value flag) from `npm help run` (bare
        subcommand) needs npm's per-flag arity table. The hook anchors strictly
        at argv[1] to keep false POSITIVES at zero; the cost is a missed reminder
        on this exotic form. This test pins that accepted behaviour — if a future
        change makes it route, that's fine, but flip this assertion deliberately.
        """
        out = _fixture("promptfoo_fail.stdout.txt")
        result = _run_hook(_post_tool_use("npm --prefix ./pkg run eval", stdout=out, exit_code=100))
        assert _additional_context(result) == "", (
            "accepted limitation changed: a global flag before the subcommand "
            "now routes. Update the docstring + this test intentionally."
        )

    def test_emoji_glued_to_digit_in_path_does_not_route(self) -> None:
        """P2 false positive: an emoji glued to a digit with NO space (a path
        like `tests/🙁1_case.py`) must not read as a survivor count. Real mutmut
        counts are always `🙁 <space> <digit>`. Here every real stats counter is
        zero, so only the glued path could (wrongly) trigger.
        """
        clean = _fixture("mutmut_clean.stdout.txt")
        poisoned = "wrote tests/🙁1_case.py\n" + clean
        result = _run_hook(_post_tool_use("mutmut run", stdout=poisoned, exit_code=0))
        assert _additional_context(result) == "", (
            "hook read `🙁1` (no space, inside a path) as a survivor count. The "
            "counter pattern must require a space between the emoji and the digit."
        )


# --------------------------------------------------------------------------- #
# hook contract — robustness                                                   #
# --------------------------------------------------------------------------- #


class TestHookContract:
    def test_malformed_stdin_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not json at all {{{",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"hook must swallow malformed stdin and exit 0; got {result.returncode}, "
            f"stderr={result.stderr!r}"
        )

    def test_missing_tool_response_exits_zero(self) -> None:
        """A PostToolUse payload with no tool_response (or partial fields) must
        not crash the hook — it exits 0 and stays silent.
        """
        result = _run_hook({"tool_name": "Bash", "tool_input": {"command": "mutmut run"}})
        assert _additional_context(result) == ""

    def test_non_bash_tool_is_ignored(self) -> None:
        result = _run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "x.py"},
                "tool_response": {"stdout": _fixture("mutmut_survivors.stdout.txt")},
            }
        )
        assert _additional_context(result) == ""

    def test_generic_pytest_failure_does_not_route(self) -> None:
        """Regression guard: a plain pytest failure is neither a mutmut survivor
        nor a promptfoo FAIL. The hook must stay out of the generic test loop.
        """
        pytest_output = "FAILED tests/test_x.py::test_y - AssertionError\n1 failed, 3 passed\n"
        result = _run_hook(_post_tool_use("pytest -q", stdout=pytest_output, exit_code=1))
        assert _additional_context(result) == ""


def test_hook_is_executable() -> None:
    """Deployment contract: settings.json invokes the hook as a bare command,
    so it needs the executable bit and a shebang (same as the sibling hooks).
    """
    import os

    assert HOOK.exists(), f"hook missing at {HOOK}"
    if os.name != "nt":  # executable bit is meaningless on Windows
        assert os.access(HOOK, os.X_OK), (
            f"{HOOK} is not executable; settings.json runs it as a bare command."
        )
    first_line = HOOK.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#!"), f"hook missing shebang: {first_line!r}"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "mutmut_survivors.stdout.txt",
        "mutmut_clean.stdout.txt",
        "promptfoo_fail.stdout.txt",
        "promptfoo_pass.stdout.txt",
    ],
)
def test_fixtures_exist(fixture_name: str) -> None:
    assert (FIXTURES / fixture_name).is_file(), (
        f"missing real-capture fixture {fixture_name}; positive detection cannot "
        "be verified against invented output."
    )


# --------------------------------------------------------------------------- #
# prefilter wrapper — the per-Bash-call latency gate                           #
# --------------------------------------------------------------------------- #

PREFILTER = REPO_ROOT / ".claude" / "hooks" / "route-qa-runners-prefilter.sh"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"


def _run_prefilter(payload: dict | str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(PREFILTER)],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestPrefilterWrapper:
    """The wrapper spares the Python interpreter start-up on Bash calls that
    can never route (no mutmut/promptfoo/eval token anywhere in the payload).
    When a token IS present it must be transparent: same behaviour as invoking
    the Python hook directly. The token set must stay a SUPERSET of the Python
    hook's command shapes; `npm run eval` is the case with no 'promptfoo' in
    the command, which is why 'eval' is in the set.
    """

    def test_irrelevant_command_is_silent_and_exits_zero(self) -> None:
        result = _run_prefilter(_post_tool_use("git status", stdout="clean\n"))
        assert result.returncode == 0, f"prefilter must exit 0; stderr={result.stderr!r}"
        assert result.stdout.strip() == "", (
            "prefilter emitted output for a command with no routing token."
        )

    def test_mutmut_survivors_route_through_wrapper(self) -> None:
        out = _fixture("mutmut_survivors.stdout.txt")
        result = _run_prefilter(_post_tool_use("uv run mutmut run", stdout=out, exit_code=0))
        assert "mutation-survivor-triage" in _additional_context(result), (
            "prefilter swallowed a real mutmut survivor route."
        )

    def test_npm_run_eval_fail_routes_through_wrapper(self) -> None:
        """`npm run eval` contains no 'promptfoo' — if the wrapper's token set
        drops 'eval', this real routing case is silently lost.
        """
        out = _fixture("promptfoo_fail.stdout.txt")
        result = _run_prefilter(_post_tool_use("npm run eval", stdout=out, exit_code=100))
        assert "eval-failure-diagnoser" in _additional_context(result), (
            "prefilter swallowed the `npm run eval` promptfoo route."
        )

    def test_token_passthrough_still_defers_to_python_gate(self) -> None:
        """A payload merely CONTAINING a token passes the prefilter, but the
        Python command-shape gate must still reject it — the wrapper may only
        remove work, never add routes.
        """
        out = _fixture("mutmut_survivors.stdout.txt")
        result = _run_prefilter(_post_tool_use("cat mutmut.log", stdout=out, exit_code=0))
        assert _additional_context(result) == ""

    def test_malformed_stdin_exits_zero(self) -> None:
        result = _run_prefilter("not json at all {{{ mutmut")
        assert result.returncode == 0, (
            f"prefilter must swallow malformed stdin; stderr={result.stderr!r}"
        )

    def test_wrapper_is_executable_with_shebang(self) -> None:
        import os

        assert PREFILTER.exists(), f"prefilter missing at {PREFILTER}"
        if os.name != "nt":
            assert os.access(PREFILTER, os.X_OK), (
                f"{PREFILTER} is not executable; settings.json runs it as a bare command."
            )
        assert PREFILTER.read_text(encoding="utf-8").startswith("#!"), "prefilter missing shebang"

    def test_settings_wires_bash_hook_through_prefilter(self) -> None:
        """Deployment contract: the Bash PostToolUse entry must invoke the
        prefilter (which invokes the Python hook), not the Python hook directly
        — otherwise every Bash call pays the interpreter start-up again.
        """
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        bash_commands = [
            hook["command"]
            for entry in settings["hooks"]["PostToolUse"]
            if entry.get("matcher") == "Bash"
            for hook in entry["hooks"]
        ]
        assert bash_commands, "no Bash PostToolUse hook configured"
        assert all(cmd.endswith("route-qa-runners-prefilter.sh") for cmd in bash_commands), (
            f"Bash PostToolUse must route through the prefilter; got {bash_commands}"
        )
