#!/usr/bin/env python3
"""PostToolUse hook: route mutmut survivors and promptfoo FAILs to the right agent.

Non-blocking. When a Bash result is a `mutmut run` that left survivors, or a
promptfoo / `npm run eval` run that reported a FAIL, this hook injects a reminder
naming the repo-local triage agent — `mutation-survivor-triage` for survivors,
`eval-failure-diagnoser` for eval failures (see .claude/agents/). It never blocks
the underlying Bash result and exits 0 on every path, including internal errors.

Detection is a conjunction of two conditions: the command must match the runner
AND the output must carry the survivor / FAIL marker. This avoids false positives
like `cat log.txt | grep survived`, which carries the word but is not a mutmut run.

Output channel: Claude hook JSON on stdout with
`hookSpecificOutput.hookEventName == "PostToolUse"` and an `additionalContext`
reminder. Silent (empty stdout) on every non-matching path.
"""

from __future__ import annotations

import json
import re
import sys

# Survivor statuses mutmut reports for mutants the suite failed to kill.
MUTMUT_SURVIVOR_MARKERS = ("survived", "timeout", "suspicious")

MUTATION_REMINDER = (
    "mutmut left survivors. Route this through the `mutation-survivor-triage` "
    "agent to classify each survivor (equivalent / tautology-killable / "
    "genuine-gap / infrastructure-noise) before strengthening tests — do not "
    "edit production code to chase mutants."
)

EVAL_REMINDER = (
    "A promptfoo eval reported a FAIL. Route this through the "
    "`eval-failure-diagnoser` agent to identify the failed assertion and the "
    "SKILL.md section to strengthen — never loosen the rubric."
)


def is_mutmut_run(command: str) -> bool:
    """True only for an actual `mutmut run` invocation.

    Matches `mutmut run` as a whole-word command token so `uv run mutmut run`
    and `python -m mutmut run` count, but `cat log | grep mutmut` or a path
    containing the substring does not.
    """
    return re.search(r"\bmutmut\s+run\b", command) is not None


def is_eval_run(command: str) -> bool:
    """True for the eval commands the diagnoser covers, excluding the
    non-failure subcommands.

    Accepted: `promptfoo eval`, `npm run eval`, `npm run eval:all`.
    Excluded: `eval:generate`, `eval:view` (and any other `eval:` subcommand
    that is not `eval:all`). The exclusion is checked first so the broad
    `npm run eval` match cannot swallow `npm run eval:generate`.
    """
    # Explicitly ignored eval subcommands.
    if re.search(r"\beval:(?!all\b)\w+", command):
        return False
    if re.search(r"\bpromptfoo\s+eval\b", command):
        return True
    if re.search(r"\bnpm\s+run\s+eval(:all)?\b", command):
        return True
    return False


def has_mutmut_survivor(output: str) -> bool:
    lowered = output.lower()
    return any(marker in lowered for marker in MUTMUT_SURVIVOR_MARKERS)


def has_eval_failure(output: str) -> bool:
    """True when the output carries a promptfoo failure marker.

    Detects the per-assert `[FAIL]` token or a non-zero `Failures:` summary
    line (`Failures: 1` and above; `Failures: 0` is a pass).
    """
    if "[FAIL]" in output:
        return True
    match = re.search(r"Failures:\s*(\d+)", output)
    if match and int(match.group(1)) > 0:
        return True
    return False


def emit(reminder: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": reminder,
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

        tool_response = payload.get("tool_response") or {}
        combined_output = "\n".join(
            str(tool_response.get(key) or "") for key in ("stdout", "stderr")
        )

        if is_mutmut_run(command) and has_mutmut_survivor(combined_output):
            emit(MUTATION_REMINDER)
            return 0

        if is_eval_run(command) and has_eval_failure(combined_output):
            emit(EVAL_REMINDER)
            return 0
    except Exception:
        # A PostToolUse hook must never disrupt the loop with a non-zero exit
        # or an unhandled traceback; degrade to a silent no-op.
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
