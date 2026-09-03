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
    (mutmut 3.5.0 __main__.print_stats; layout verified byte-identical on a
    real 3.7.0 run, 2026-09-03). The matcher parses those counters; a
    non-zero survived / timeout / suspicious count means action is needed. The
    exit code is useless here: `mutmut run` exits 0 even with survivors.

  * `promptfoo eval` exits non-zero (default 100) on a failing test case and
    prints `[FAIL]` in the results table. Either signal counts as a FAIL.

Both branches first gate on the COMMAND shape so reading a log
(`cat mutmut.log`, `grep survived`) or a non-run subcommand
(`promptfoo generate`, `npm run eval:view`) never triggers a route.

Deployed behind route-qa-runners-prefilter.cmd, a cmd.exe/sh polyglot. Its POSIX
branch greps stdin for mutmut/promptfoo/eval before paying the Python start-up on
every Bash call; keep that token list a superset of the command shapes recognised
here. Its Windows branch takes no shortcut and pipes every payload straight in.
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

# mutmut survivor-status emoji counters (mutmut 3.5.0 emoji_by_status; the
# same three emojis, in the same layout, in 3.7.0).
_MUTMUT_STATUS_EMOJI = {
    "survived": "🙁",
    "timeout": "⏰",
    "suspicious": "🤔",
}


# Shell control operators that separate sub-commands. `|&` (pipe-stderr) is
# emitted by shlex as a single token. An UNQUOTED newline is consumed by shlex
# as whitespace (so newline-separated commands merge into one segment — an
# accepted false negative; splitting them safely would require a full shell
# parser that also respects multi-line quotes); a QUOTED newline stays inside
# its token, which is what keeps quoted text from forming a fake command.
_CONTROL_OPERATORS = {";", "|", "||", "&&", "&", "|&", "\n"}

# npx/bunx flags that consume the FOLLOWING token as their value, so that value
# is not mistaken for the executable name (`npx -p promptfoo eval` runs `eval`,
# not `promptfoo`). The `--flag=value` form is a single token and needs no entry.
_NPX_VALUE_FLAGS = {"-p", "--package", "-c", "--call"}


def _command_segments(command: str) -> list[list[str]]:
    """Tokenize the command respecting quotes, then split into per-sub-command
    token lists on shell control operators.

    Quoting matters: a `;`/`|` INSIDE a quoted argument
    (`printf "x; promptfoo eval ; y"`) belongs to that argument, not as a command
    separator — a naive `re.split` on operators would carve a fake `promptfoo
    eval` segment out of printed text. `shlex` with `punctuation_chars` keeps the
    quoted run intact and yields unquoted operators as standalone tokens."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        # Unbalanced quotes etc. — degrade to a naive operator split rather than
        # crash; the outer hook still exits 0 regardless.
        return [part.split() for part in re.split(r"\|\||&&|\||;|&", command)]

    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _CONTROL_OPERATORS:
            segments.append(current)
            current = []
        else:
            current.append(token)
    segments.append(current)
    return segments


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
    for segment in _command_segments(command):
        eff = _effective_argv(segment)
        if len(eff) >= 2 and os.path.basename(eff[0]) == "mutmut" and eff[1] == "run":
            return True
    return False


def _pm_script(eff: list[str]) -> str | None:
    """The npm/pnpm/yarn/bun script name being run, if any.

    Two positions are anchored LITERALLY to avoid the flag-arity ambiguity
    (without npm's per-flag arity table, a flag's value can't be told from a
    positional):

    - `run`/`run-script` must be the SUBCOMMAND at argv[1], not merely present
      (`npm help run eval` has `run` as an argument to `help` → no match).
    - the script is the token IMMEDIATELY after the subcommand (argv[2]); a flag
      there means we don't recognise the script (`npm run --workspace eval build`
      runs `build`, not `eval` — reading `eval` would be a false positive).

    Deliberately NOT supported (accepted false NEGATIVES on exotic, repo-unused
    forms): a flag before the script (`npm run --silent eval`) or a value-taking
    global flag before the subcommand (`npm --prefix ./pkg run eval`). The hook
    is advisory; anchoring literally keeps the harmful direction — a false
    positive — at zero. Real repo invocations are plain `npm run eval[:all]`."""
    if len(eff) < 2:
        return None
    sub = eff[1]
    if sub in ("run", "run-script"):
        return eff[2] if len(eff) >= 3 else None
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
            value_flag = rest[0] in _NPX_VALUE_FLAGS
            rest = rest[1:]
            if value_flag and rest:  # also drop the flag's value token
                rest = rest[1:]
        if rest:
            base = os.path.basename(rest[0])
            if base == "promptfoo" or base.startswith("promptfoo@"):
                return rest
    return None


def _segment_is_promptfoo_eval(eff: list[str]) -> bool:
    """Is this single command segment an actual promptfoo eval RUN (not
    generate/view, not a script merely named eval-something)?

    The promptfoo subcommand is the token IMMEDIATELY after `promptfoo` (pf[1]) —
    commander grammar puts the command before its options, so taking it literally
    avoids reading a flag value as the subcommand (`promptfoo --config eval
    generate` actually runs `generate`)."""
    if not eff:
        return False
    if os.path.basename(eff[0]) in ("npm", "pnpm", "yarn", "bun"):
        return _pm_script(eff) in ("eval", "eval:all")
    pf = _promptfoo_argv(eff)
    return pf is not None and len(pf) >= 2 and pf[1] == "eval"


def _is_promptfoo_eval_run(command: str) -> bool:
    """True if ANY segment of the command is a promptfoo eval run. Scanning
    every segment (not stopping at the first promptfoo-ish one) is what lets a
    real eval after an excluded segment still route — `promptfoo view; promptfoo
    eval` must fire on the second segment."""
    return any(
        _segment_is_promptfoo_eval(_effective_argv(seg)) for seg in _command_segments(command)
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
