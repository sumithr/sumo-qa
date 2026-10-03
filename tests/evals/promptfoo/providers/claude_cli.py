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

With `jsonReply: true` (the judge) the verdict object is parsed here and handed to
promptfoo as an object. promptfoo's own extractor counts braces without reading
strings, so a `{` or `}` inside the reason drops the grade or passes it silently.
A judge reply with no valid verdict is a promptfoo `error`, never text for promptfoo
to parse: promptfoo grades a missing or non-boolean "pass" as a pass. Such a reply is
asked again once; when the second reply has no verdict either, both replies are kept
in full (redacted) under `tests/evals/results/judge-replies/` and the error names the
file (#796).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

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
# strict=False: a raw newline or tab inside the judge's "reason" string still decodes.
_DECODER = json.JSONDecoder(strict=False)
# Judge replies that never gave a verdict are kept here in full (gitignored).
REPLY_DIR = Path(__file__).resolve().parents[2] / "results" / "judge-replies"
_SECRET = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,})")


def call_api(prompt, options=None, context=None):
    config = (options or {}).get("config") or {}
    if not config.get("model"):
        return {"error": "provider config has no model"}
    argv = ["claude", *BASE_FLAGS, "--model", config["model"]]
    # Without a system prompt Claude Code's default agent prompt applies: the
    # candidate narrates tool use it cannot perform and the rubrics fail it.
    if config.get("systemPrompt"):
        argv += ["--system-prompt", config["systemPrompt"]]

    # A judge reply with no verdict is asked once more before it becomes an error.
    unparsed = []
    prompt_tokens = completion_tokens = 0
    cost = 0.0
    for _ in range(2 if config.get("jsonReply") else 1):
        answer = _ask(argv, prompt)
        if "error" in answer:
            if unparsed:
                answer["error"] += f"; the earlier judge reply is kept at {_keep(unparsed)}"
            return answer
        result, envelope = answer["result"], answer["envelope"]
        # Accounting is best effort: a malformed usage field must not throw away an answer.
        usage = envelope.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        prompt_tokens += sum(
            _number(usage.get(key))
            for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        )
        completion_tokens += _number(usage.get("output_tokens"))
        # List-price notional cost from the CLI; nothing is invoiced.
        cost += float(_number(envelope.get("total_cost_usd"), float))
        output, problem = _verdict(result) if config.get("jsonReply") else (result, None)
        if not problem:
            return {
                "output": output,
                "tokenUsage": {
                    "prompt": prompt_tokens,
                    "completion": completion_tokens,
                    "total": prompt_tokens + completion_tokens,
                },
                "cost": cost,
            }
        unparsed.append({"problem": problem, "reply": result})
    return {
        "error": f"judge reply {problem} (asked twice; both replies kept at "
        f"{_keep(unparsed)}): {result[:_EXCERPT]!r}"
    }


def _ask(argv, prompt):
    """{"result", "envelope"} for a successful CLI answer, else {"error"}."""
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
    return {"result": result, "envelope": envelope}


def _keep(unparsed):
    """Write the unparsed judge replies, redacted, to REPLY_DIR; return where they went."""
    text = _SECRET.sub("[REDACTED]", json.dumps(unparsed, indent=2, ensure_ascii=False))
    text = text.replace(str(Path.home()), "~")
    path = REPLY_DIR / f"judge-reply-{hashlib.sha256(text.encode()).hexdigest()[:12]}.json"
    try:
        REPLY_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        return f"nowhere (could not write {path}: {exc})"
    return str(path)


def _verdict(text):
    """(verdict, None) for the reply's one verdict object, else (None, the problem)."""
    verdicts = []
    start = text.find("{")
    while start != -1:
        try:
            value, end = _DECODER.raw_decode(text, start)
        except ValueError:
            # A `{` that does not decode (stray prose) starts no object.
            start = text.find("{", start + 1)
            continue
        # Top level only: an object nested inside another one is never scanned on its own.
        # Objects without "pass" (a quoted snippet, trailing notes) are not verdicts.
        if isinstance(value, dict) and "pass" in value and value not in verdicts:
            verdicts.append(value)
        start = text.find("{", end)
    if not verdicts:
        return None, 'has no verdict object with a "pass" key'
    # Two different verdicts (a quoted example and the grade, or a changed mind) leave the
    # grade ambiguous: no rule here may pick one.
    if len(verdicts) > 1:
        return None, f"has {len(verdicts)} different verdict objects"
    verdict = verdicts[0]
    if not isinstance(verdict["pass"], bool):
        return None, '"pass" is not a JSON boolean'
    if not _finite(verdict.get("score", 0)):
        return None, '"score" is not a finite number'
    if not isinstance(verdict.get("reason", ""), str):
        return None, '"reason" is not a string'
    return verdict, None


def _finite(value):
    """True for a JSON number a float can hold; an int too large for one is not finite."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _number(value, kind=int):
    """A usage figure, or 0 when the CLI sent something that is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return kind(0)
    return kind(value)
