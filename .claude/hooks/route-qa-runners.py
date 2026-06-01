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


def _pm_script(eff: list[str]) -> str | None:
    """The npm/pnpm/yarn/bun script name being run, if any."""
    if "run" in eff:
        idx = eff.index("run")
        return eff[idx + 1] if idx + 1 < len(eff) else None
    # `yarn eval` / `bun eval` shorthand (no explicit `run`).
    if os.path.basename(eff[0]) in ("yarn", "bun") and len(eff) >= 2 and not eff[1].startswith("-"):
        return eff[1]
    return None


def _promptfoo_subcommand(eff: list[str]) -> str | None:
    """The first non-flag token after a `promptfoo` token (handles `npx`,
    `promptfoo@1.2.3`, and absolute paths)."""
    idx = None
    for j, token in enumerate(eff):
        base = os.path.basename(token)
        if base == "promptfoo" or base.startswith("promptfoo@"):
            idx = j
            break
    if idx is None:
        return None
    for token in eff[idx + 1 :]:
        if token.startswith("-"):
            continue
        return token
    return None


def _promptfoo_eval_kind(command: str) -> str | None:
    """Classify the command's promptfoo intent: 'run' (an eval run we watch),
    'excluded' (generate/view — explicitly ignored), or None (not promptfoo)."""
    for segment in _segments(command):
        eff = _effective_argv(_tokens(segment))
        if not eff:
            continue
        base0 = os.path.basename(eff[0])
        if base0 in ("npm", "pnpm", "yarn", "bun"):
            script = _pm_script(eff)
            if script is None:
                continue
            if script in ("eval", "eval:all"):
                return "run"
            if script.startswith("eval"):  # eval:generate, eval:view, …
                return "excluded"
            continue
        sub = _promptfoo_subcommand(eff)
        if sub == "eval":
            return "run"
        if sub in ("generate", "view"):
            return "excluded"
    return None


def _mutmut_has_survivors(output: str) -> bool:
    """True when a survived / timeout / suspicious emoji counter is non-zero."""
    for emoji in _MUTMUT_STATUS_EMOJI.values():
        for count in re.findall(re.escape(emoji) + r"\s*([0-9]+)", output):
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

        if _promptfoo_eval_kind(command) == "run" and _promptfoo_failed(output, exit_code):
            _emit(_PROMPTFOO_REMINDER)
            return 0
    except Exception:
        # Advisory hook: never break the Bash flow on an internal error.
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
