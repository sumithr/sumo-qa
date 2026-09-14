"""promptfoo provider that answers through the Claude Code CLI.

`claude -p` authenticates on the account's Claude subscription, so an eval run
spends subscription usage instead of metered API credit. Everything else stays
promptfoo's: rubrics, templating, `javascript` asserts, thresholds, reports.

Wired in by `providers/claude-candidate.yaml` and `providers/claude-judge.yaml`
(see `run-eval.sh`, `SUMO_EVAL_BACKEND=claude`).

Any call that does not come back as a successful answer is returned as a
promptfoo `error`, never as output. A usage-limit or quota message must not be
graded as the candidate's answer: that is the #651 failure, where a quota
failure turned into a zero-passed baseline that read as a skill regression.
"""

from __future__ import annotations

import json
import math
import re
import subprocess

# Isolation: no tools, no MCP servers (without --strict-mcp-config the
# developer's own sumo-qa server attaches and the skills grade themselves), no
# user settings, no slash commands. Together these cut ~19k tokens of Claude
# Code scaffolding from every call.
BASE_FLAGS = [
    "-p",
    "--output-format",
    "json",
    "--max-turns",
    "1",
    "--tools",
    "",
    "--strict-mcp-config",
    "--setting-sources",
    "",
    "--disable-slash-commands",
]

TIMEOUT_SECONDS = 600
_EXCERPT = 400
# The CLI's usage-limit stop: "Claude AI usage limit reached|<reset epoch>". Matched
# anywhere in the answer and in any case, even inside a success envelope, so it is never
# graded as the candidate's answer. The "|<digits>" suffix keeps an answer that merely
# quotes the phrase from matching.
_USAGE_LIMIT = re.compile(r"usage limit reached\|\d+", re.IGNORECASE)


def call_api(prompt, options=None, context=None):
    config = (options or {}).get("config") or {}
    if not config.get("model"):
        return {"error": "provider config has no model"}
    argv = ["claude", *BASE_FLAGS, "--model", config["model"]]
    # Without a system prompt Claude Code's default agent prompt applies: the
    # candidate narrates tool use it cannot perform and the rubrics fail it.
    if config.get("systemPrompt"):
        argv += ["--system-prompt", config["systemPrompt"]]

    try:
        # The prompt goes in on stdin: a rendered eval prompt reaches ~22k tokens.
        done = subprocess.run(
            argv, input=prompt, capture_output=True, text=True, timeout=TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": f"claude CLI did not run: {exc}"}

    try:
        envelope = json.loads(done.stdout)
    except ValueError:
        envelope = None
    if not isinstance(envelope, dict):
        return {
            "error": f"claude exited {done.returncode} without a JSON envelope: "
            f"stdout={done.stdout[:_EXCERPT]!r} stderr={done.stderr[:_EXCERPT]!r}"
        }

    # Success is established positively; every other shape is an error.
    result = envelope.get("result")
    if (
        done.returncode != 0
        or envelope.get("type") != "result"
        or envelope.get("subtype") != "success"
        or envelope.get("is_error")
        or envelope.get("api_error_status")
    ):
        return {"error": f"claude call failed (exit {done.returncode}): {done.stdout[:_EXCERPT]}"}
    if not isinstance(result, str) or not result.strip():
        return {"error": f"claude reported success but returned no answer: {result!r}"}
    if _USAGE_LIMIT.search(result):
        return {"error": f"claude usage limit: {result[:_EXCERPT]}"}

    # Accounting is best effort: a malformed usage field must not throw away an answer.
    usage = envelope.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    prompt_tokens = sum(
        _number(usage.get(key))
        for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    )
    completion_tokens = _number(usage.get("output_tokens"))
    return {
        "output": result,
        "tokenUsage": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": prompt_tokens + completion_tokens,
        },
        # List-price notional cost from the CLI; nothing is invoiced.
        "cost": float(_number(envelope.get("total_cost_usd"), float)),
    }


def _number(value, kind=int):
    """A usage figure, or 0 when the CLI sent something that is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return kind(0)
    return kind(value)
