#!/usr/bin/env python3
"""PostToolUse hook: route mutmut survivors / promptfoo FAILs to the repo agents.

When a Bash result is an actual `mutmut run` that left survivors, or an actual
promptfoo eval that produced a FAIL, inject a non-blocking reminder telling the
assistant to route through the matching repo-local agent
(`mutation-survivor-triage` / `eval-failure-diagnoser`) instead of reacting
ad-hoc. Advisory only: it never blocks the Bash result and exits 0 on every path.

Detection is built against REAL runner output (see tests/test_route_qa_runners.py):

  * `mutmut run` reports survivors with EMOJI counters, never the word
    "survived" — real output is `… ⏰ {timeout}  🤔 {suspicious}  🙁 {survived} …`
    (mutmut 3.5.0 __main__.print_stats). The matcher parses those counters; a
    non-zero survived / timeout / suspicious count means action is needed. The
    exit code is useless here: `mutmut run` exits 0 even with survivors.

  * `promptfoo eval` exits non-zero (default 100) on a failing test case and
    prints `[FAIL]` in the results table. Either signal counts as a FAIL.

Both branches first gate on the COMMAND shape so reading a log
(`cat mutmut.log`, `grep survived`) or a non-run subcommand
(`promptfoo generate`, `npm run eval:view`) never triggers a route.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys

# Wrapper commands that prefix the real invocation; stripped to find the
# effective argv. `uv run mutmut run` / `poetry run promptfoo eval` are common.
_LAUNCHERS = {
    "uv",
    "uvx",
    "poetry",
    "pdm",
    "hatch",
    "rye",
    "pipenv",
    "time",
    "nice",
    "env",
}
_LAUNCHERS_TAKING_RUN = {"uv", "poetry", "pdm", "hatch", "rye", "pipenv"}
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# mutmut survivor-status emoji counters (mutmut 3.5.0 emoji_by_status).
_MUTMUT_STATUS_EMOJI = {
    "survived": "🙁",
    "timeout": "⏰",
    "suspicious": "🤔",
}


def _segments(command: str) -> list[str]:
    """Split a shell command on control operators so a token in one part can't
    bleed into another (`cat mutmut.log | grep survived` is two segments)."""
    return re.split(r"\|\||&&|\||;|&", command)


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _effective_argv(tokens: list[str]) -> list[str]:
    """Strip leading env-assignments and launcher prefixes to reveal the real
    command. `env X=1 uv run mutmut run` -> `['mutmut', 'run']`."""
    i = 0
    progressed = True
    while progressed and i < len(tokens):
        progressed = False
        while i < len(tokens) and _ENV_ASSIGN.match(tokens[i]):
            i += 1
            progressed = True
        if i >= len(tokens):
            break
        base = os.path.basename(tokens[i])
        if base in _LAUNCHERS:
            i += 1
            progressed = True
            if base in _LAUNCHERS_TAKING_RUN and i < len(tokens) and tokens[i] == "run":
                i += 1
        elif base in ("python", "python3") and i + 1 < len(tokens) and tokens[i + 1] == "-m":
            i += 2
            progressed = True
    return tokens[i:]


def _is_mutmut_run(command: str) -> bool:
    for segment in _segments(command):
        eff = _effective_argv(_tokens(segment))
        if len(eff) >= 2 and os.path.basename(eff[0]) == "mutmut" and eff[1] == "run":
            return True
    return False


def _first_non_flag(tokens: list[str]) -> str | None:
    """The first token that is not a `-`/`--` flag."""
    for token in tokens:
        if token.startswith("-"):
            continue
        return token
    return None


def _pm_script(eff: list[str]) -> str | None:
    """The npm/pnpm/yarn/bun script name being run, if any.

    `run`/`run-script` must be the SUBCOMMAND — the token immediately after
    argv[0] — not merely present in argv: `npm help run eval` has `run` as an
    argument to `help`, not the subcommand, and must NOT match. Flags AFTER the
    subcommand are skipped (`npm run --silent eval` -> `eval`).

    Deliberately NOT supported: a value-taking GLOBAL flag before the subcommand
    (`npm --prefix ./pkg run eval`). Distinguishing it from a bare subcommand
    (`npm help run`) needs npm's per-flag arity table — `--silent run` (boolean
    flag, `run` is the subcommand) and `--prefix ./pkg run` (value flag, `run`
    is the subcommand) are otherwise indistinguishable. This hook is advisory,
    so the only cost is a missed reminder on that exotic form (a false negative);
    anchoring strictly at argv[1] keeps the harmful direction — a false positive
    — at zero. The repo's real invocations are plain `npm run eval[:all]`."""
    if len(eff) < 2:
        return None
    sub = eff[1]
    if sub in ("run", "run-script"):
        return _first_non_flag(eff[2:])
    # `yarn eval` / `bun eval` shorthand (no explicit `run`).
    if os.path.basename(eff[0]) in ("yarn", "bun") and not sub.startswith("-"):
        return sub
    return None


def _promptfoo_argv(eff: list[str]) -> list[str] | None:
    """Return the argv beginning at the `promptfoo` token IFF promptfoo is the
    actual command word — eff[0] (`promptfoo eval`, `promptfoo@1.2.3 eval`, an
    absolute path) or the package an npx-style launcher runs (`npx promptfoo
    eval`). A `promptfoo` token buried mid-argv (`echo promptfoo eval`) is NOT
    a promptfoo invocation and returns None."""
    base0 = os.path.basename(eff[0])
    if base0 == "promptfoo" or base0.startswith("promptfoo@"):
        return eff
    if base0 in ("npx", "bunx"):
        rest = eff[1:]
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        if rest:
            base = os.path.basename(rest[0])
            if base == "promptfoo" or base.startswith("promptfoo@"):
                return rest
    return None


def _segment_is_promptfoo_eval(eff: list[str]) -> bool:
    """Is this single command segment an actual promptfoo eval RUN (not
    generate/view, not a script merely named eval-something)?"""
    if not eff:
        return False
    if os.path.basename(eff[0]) in ("npm", "pnpm", "yarn", "bun"):
        return _pm_script(eff) in ("eval", "eval:all")
    pf = _promptfoo_argv(eff)
    return pf is not None and _first_non_flag(pf[1:]) == "eval"


def _is_promptfoo_eval_run(command: str) -> bool:
    """True if ANY segment of the command is a promptfoo eval run. Scanning
    every segment (not stopping at the first promptfoo-ish one) is what lets a
    real eval after an excluded segment still route — `promptfoo view; promptfoo
    eval` must fire on the second segment."""
    return any(
        _segment_is_promptfoo_eval(_effective_argv(_tokens(seg))) for seg in _segments(command)
    )


def _mutmut_has_survivors(output: str) -> bool:
    """True when a survived / timeout / suspicious emoji counter is non-zero.

    The counter is matched as `<emoji> <digits>` with a REQUIRED space — real
    mutmut stats lines are `… 🙁 4 …`. Requiring the space stops a stray
    `🙁1_case.py`-style token from reading as a survivor count, and the
    per-mutant results lines (`🙁 <module.path>`) never match because a module
    name does not start with a digit."""
    for emoji in _MUTMUT_STATUS_EMOJI.values():
        for count in re.findall(re.escape(emoji) + r"\s+([0-9]+)", output):
            if int(count) > 0:
                return True
    return False


def _nonzero_exit(exit_code: object) -> bool:
    """True for a non-zero exit code, tolerating int OR numeric-string forms
    (the PostToolUse payload may carry exit_code either way; promptfoo exits 100
    on failure). A missing / non-numeric code is not treated as a failure."""
    if isinstance(exit_code, bool):  # bool is an int subclass; never an exit code
        return False
    try:
        return int(exit_code) != 0
    except (TypeError, ValueError):
        return False


def _promptfoo_failed(output: str, exit_code: object) -> bool:
    # [FAIL] in the results table is the primary signal; a non-zero exit covers
    # an eval that errored before printing a table.
    return "[FAIL]" in output or _nonzero_exit(exit_code)


_MUTMUT_REMINDER = (
    "`mutmut run` left surviving mutants (survived / timeout / suspicious). "
    "Route them through the `mutation-survivor-triage` agent before touching "
    "tests — it classifies each survivor (equivalent / tautology-killable / "
    "genuine-gap / infrastructure-noise). Do not hand-classify survivors."
)
_PROMPTFOO_REMINDER = (
    "promptfoo reported a FAIL. Route the failure through the "
    "`eval-failure-diagnoser` agent. Repo policy: fix a FAIL by strengthening "
    "the SKILL.md so the candidate passes — never by loosening the rubric."
)


def _emit(context: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": context,
            }
        },
        sys.stdout,
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    try:
        if payload.get("tool_name") != "Bash":
            return 0

        tool_input = payload.get("tool_input") or {}
        command = tool_input.get("command") or ""
        if not command:
            return 0

        response = payload.get("tool_response")
        if not isinstance(response, dict):
            response = {}
        output = f"{response.get('stdout') or ''}\n{response.get('stderr') or ''}"
        exit_code = response.get("exit_code")

        if _is_mutmut_run(command) and _mutmut_has_survivors(output):
            _emit(_MUTMUT_REMINDER)
            return 0

        if _is_promptfoo_eval_run(command) and _promptfoo_failed(output, exit_code):
            _emit(_PROMPTFOO_REMINDER)
            return 0
    except Exception:
        # Advisory hook: never break the Bash flow on an internal error.
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
