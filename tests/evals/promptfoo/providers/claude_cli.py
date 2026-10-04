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


def _unique_keys(pairs):
    """An object's pairs as a dict; a repeated key, at any depth, does not decode."""
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("repeated key")
    return dict(pairs)


# strict=False: a raw newline or tab inside the judge's "reason" string still decodes.
_DECODER = json.JSONDecoder(strict=False, object_pairs_hook=_unique_keys)
# Judge replies that never gave a verdict are kept here in full (gitignored).
REPLY_DIR = Path(__file__).resolve().parents[2] / "results" / "judge-replies"
# Bare secret values and PEM private-key blocks, drawn from the shapes
# src/sumo_qa/feedback_memory.py refuses, plus `sk-` API keys and fine-grained `github_pat_`
# tokens. A copy, not an import: promptfoo runs this file under PROMPTFOO_PYTHON or the
# `python3` on PATH, where sumo_qa need not be installed.
_SECRET = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"
    r"|\b(?:sk-[A-Za-z0-9_-]{16,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|(?:AKIA|ASIA)[0-9A-Z]{16}\b"
    r"|xox[bpoas]-[0-9A-Za-z-]{10,}"
    r"|eyJ[0-9A-Za-z_-]{6,}\.[0-9A-Za-z_-]{6,}\.[0-9A-Za-z_-]{6,})",
    re.DOTALL,
)
# Credential assignments, value only (the key name stays). The key is one token of letters,
# digits, `_` or `-` holding `password`, `passwd`, `pwd`, `secret`, `token`, `bearer`,
# `authorization`, `api key`, `access key` or `private key` (`_`, `-` or no separator, any
# case), so `DB_PASSWORD`, `client_secret` and `access_token` count; optionally in `**` bold
# or quotes. Then `:` or `=` (a `**` may close the bold after it) with spaces or tabs only,
# never a newline; then an optional `Bearer`, `Basic` or `Token` scheme, kept; then the
# value: a quoted string up to its closing quote, else the run of non-space characters up
# to any `**`. Also a 40-character `[A-Za-z0-9/+=]` AWS secret access key after a key name
# such as "AWS secret key", with or without `:` or `=`. "token count: 12" or "the password
# field" have no separator straight after the key and stay as written.
_ASSIGNED = re.compile(
    r"""((?:\*\*)?["']?[A-Za-z0-9_-]*(?:passw(?:or)?d|pwd|secret|token|bearer|authorization"""
    r"""|(?:api|access|private)[_-]?key)[A-Za-z0-9_-]*["']?(?:\*\*)?[ \t]*[:=](?:\*\*)?[ \t]*(?:\*\*)?"""
    r"""(?:(?:bearer|basic|token)[ \t]+)?)"""
    r"""(?:"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|(?:(?!\*\*)\S)+)"""
    r"""|(\baws[\w -]{0,20}?secret[\w -]{0,20}?key\b["']?[ \t]*[:=]?[ \t]*["']?)"""
    r"""[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])""",
    re.IGNORECASE,
)
# The word "pass" as a key in any spelling: any case, bare or in (escaped) straight, curly
# or backtick quotes or `**` bold, then `:`, `=`, `<` or a bare literal (`"pass" false`).
# "passes", "bypass" or "passed the test" have no key separator and do not match.
_PASS_KEY = re.compile(
    r"""(?<!\w)pass(?:\\?["'`\u2018\u2019\u201c\u201d])?(?:\*\*)?\s*(?:[:=<]|(?:true|false|null)\b)""",
    re.IGNORECASE,
)
# The rubrics' own output-format template, exactly: `{"pass": <true|false>` then only
# `"key": <placeholder>` or `"key": "string"` members (or `...`) up to its `}`. Its own
# "pass" key is not a verdict. `<false>`, `<b>` or a filled-in value is not the template.
_FORMAT_TEMPLATE = re.compile(
    r"""\{\s*"pass"\s*:\s*<true\|false>"""
    r"""(?:\s*,\s*(?:"[^"\\]*"\s*:\s*(?:<[^<>]*>|"[^"\\]*")|\.\.\.|\u2026))*\s*\}"""
)
_TEMPLATE_KEY = re.compile(r"""\{\s*"pass"\s*:""")
# A `{` opening a quoted key starts an object; `{x}` or `{0: 1` is prose.
_OBJECT_START = re.compile(r"""\{\s*["']""")
# Text ending in a quoted key and its colon (`"inner": ` or `"axes": [`): an object after it
# is that key's value, inside an outer object that closed early on an unescaped `"}`.
_KEY_BEFORE = re.compile(r"""["']\s*:\s*(?:\[\s*)?\Z""")
# An object followed by `,` `"` `'` `:` `}` or `]` was cut out of a larger structure (an
# outer object that closed early on an unescaped quote), so its siblings are not top level.
_CUT_AFTER = re.compile(r"""\s*[,"':}\]]""")
# Every rubric asks the reason to end in its verdict ("Verdict PASS.", "VERDICT: FAIL"). The
# word "verdict" in any case, then on the same line only spaces, tabs, `:`, `=`, `-`, `*`
# and the linking words `is`, `was` or `of`, then an uppercase PASS or FAIL, bare or as
# PASSED/PASSES/FAILED/FAILS. "PASS or FAIL" and "PASS/FAIL" offer both and state neither.
_VERDICT_WORD = re.compile(
    r"(?i:\bverdict\b)(?:[ \t:=*-]|(?i:\b(?:is|was|of)\b))*\b(PASS|FAIL)(?:ED|ES|S)?\b"
    r"(?![ \t]+(?i:or)[ \t]+(?:PASS|FAIL)|[ \t]*/[ \t]*(?:PASS|FAIL))"
)
# A string a "verdict", "passed" or "result" key may state the grade in.
_STATED = {"pass": True, "true": True, "fail": False, "false": False}


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
        # Accounting is best effort: a malformed usage field must not throw away an answer.
        # A call that failed after the CLI reported its usage is still counted.
        envelope = answer.get("envelope", {})
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
        if "error" in answer:
            error = _redact(answer["error"])
            if unparsed:
                error += f"; the earlier judge reply is kept at {_keep(unparsed)}"
            return {"error": error, **_spent(prompt_tokens, completion_tokens, cost)}
        result = answer["result"]
        output, problem = _verdict(result) if config.get("jsonReply") else (result, None)
        if not problem:
            return {"output": output, **_spent(prompt_tokens, completion_tokens, cost)}
        unparsed.append({"problem": problem, "reply": result})
    return {
        "error": f"judge reply {problem} (asked twice; both replies kept at "
        f"{_keep(unparsed)}): {_redact(result)[:_EXCERPT]!r}",
        **_spent(prompt_tokens, completion_tokens, cost),
    }


def _spent(prompt_tokens, completion_tokens, cost):
    """The usage of every call made, for an answer or an error alike."""
    return {
        "tokenUsage": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": prompt_tokens + completion_tokens,
        },
        "cost": cost,
    }


def _ask(argv, prompt):
    """{"result", "envelope"} for a successful CLI answer, else {"error"} (with the
    "envelope" when the CLI sent one, so its usage is counted)."""
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
        # Redacted before the cut, so no secret prefix survives it, and before `!r`,
        # which doubles a Windows path's backslashes.
        stdout, stderr = _redact(done.stdout)[:_EXCERPT], _redact(done.stderr)[:_EXCERPT]
        return {
            "error": f"claude exited {done.returncode} without a JSON envelope: "
            f"stdout={stdout!r} stderr={stderr!r}"
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
        error = f"claude call failed (exit {done.returncode}): {_redact(done.stdout)[:_EXCERPT]}"
    elif not isinstance(result, str) or not result.strip():
        error = f"claude reported success but returned no answer: {result!r}"
    elif _USAGE_LIMIT.search(result):
        error = f"claude usage limit: {_redact(result)[:_EXCERPT]}"
    else:
        return {"result": result, "envelope": envelope}
    return {"error": error, "envelope": envelope}


def _keep(unparsed):
    """Write the unparsed judge replies, redacted, to REPLY_DIR; return where they went."""
    # Redacted before json.dumps, which doubles a Windows path's backslashes.
    redacted = [{**entry, "reply": _redact(entry["reply"])} for entry in unparsed]
    text = json.dumps(redacted, indent=2, ensure_ascii=False)
    path = REPLY_DIR / f"judge-reply-{hashlib.sha256(text.encode()).hexdigest()[:12]}.json"
    try:
        REPLY_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        return _redact(f"nowhere (could not write {path}: {exc})")
    return _redact(str(path))


def _redact(text):
    """The text with bare secrets, credential values and the home directory scrubbed."""
    text = _SECRET.sub("[REDACTED]", text)
    text = _ASSIGNED.sub(lambda m: (m[1] or m[2]) + "[REDACTED]", text)
    home = Path.home()
    if home.parent == home:  # a filesystem-root home names no one
        return text
    # Only the whole home path: `/home/al` must not turn `/home/alice` into `~ice`, nor
    # `/data/home/al` into `/data~`. Both separator forms: Windows text may hold
    # `C:/Users/al` as well as `C:\Users\al`.
    forms = "|".join(re.escape(form) for form in {str(home), home.as_posix()})
    return re.sub(r"(?<![\w.-])(?:" + forms + r")(?![\w-]|\.[\w-])", "~", text)


def _verdict(text):
    """(verdict, None) for the reply's one unambiguous verdict object, else (None, the
    problem). Fail-closed: a reply is graded only when nothing in it could be another
    verdict, so a doubtful reply is asked again, never graded from a guess."""
    verdicts, spans = {}, []
    start = text.find("{")
    while start != -1:
        try:
            value, end = _DECODER.raw_decode(text, start)
        except ValueError:
            # A quoted-key object that does not decode (truncated, a trailing comma,
            # unescaped quotes, a repeated key) may be or hold the verdict: the reply is
            # refused whole.
            # Prose braces (`{x}`, `{0: 1`) and the rubric's format template are skipped.
            if _OBJECT_START.match(text, start) and not _FORMAT_TEMPLATE.match(text, start):
                return None, "has a malformed verdict object"
            start = text.find("{", start + 1)
            continue
        if _CUT_AFTER.match(text, end) or _variant_key(value):
            return None, "has a malformed verdict object"
        # Top level only: an object nested inside a decoded one is never scanned on its own.
        # Objects without "pass" (a quoted snippet, trailing notes) are not verdicts.
        if isinstance(value, dict) and "pass" in value:
            if _KEY_BEFORE.search(text, 0, start):
                return None, "has a malformed verdict object"
            if _disagrees(value, value["pass"]):
                return None, 'has a nested "pass" that differs from the verdict'
            spans.append((start, end))
            verdicts.setdefault(json.dumps(_canonical(value), sort_keys=True), value)
        start = text.find("{", end)
    # Every "pass" key, in any spelling, must belong to a decoded verdict: one in prose, in
    # a non-verdict object or in an object that did not decode may be the grade. Only the
    # format template's own leading key is exempt.
    templates = [
        _TEMPLATE_KEY.match(text, m.start()).span() for m in _FORMAT_TEMPLATE.finditer(text)
    ]
    if any(not _within(m.start(), spans + templates) for m in _PASS_KEY.finditer(text)):
        return None, "has a malformed verdict object"
    if not verdicts:
        return None, 'has no verdict object with a "pass" key'
    # Two different verdicts (a quoted example and the grade, or a changed mind) leave the
    # grade ambiguous: no rule here may pick one.
    if len(verdicts) > 1:
        return None, f"has {len(verdicts)} different verdict objects"
    [verdict] = verdicts.values()
    if not isinstance(verdict["pass"], bool):
        return None, '"pass" is not a JSON boolean'
    if not _finite(verdict.get("score", 0)):
        return None, '"score" is not a finite number'
    if not isinstance(verdict.get("reason", ""), str):
        return None, '"reason" is not a string'
    # A verdict word anywhere in the reply, or a stated grade inside the verdict, must agree.
    stated = [m[1] == "PASS" for m in _VERDICT_WORD.finditer(text)]
    if any(said != verdict["pass"] for said in stated + _stated(verdict)):
        return None, 'states a verdict that contradicts "pass"'
    return verdict, None


def _children(value):
    if isinstance(value, dict):
        return list(value.values())
    return value if isinstance(value, list) else []


def _word(text):
    return re.sub(r"[\W_]", "", text).casefold()


def _stated(value):
    """The PASS/FAIL or true/false strings under a "verdict", "passed" or "result" key at
    any depth, as booleans."""
    said = []
    if isinstance(value, dict):
        said = [
            _STATED[_word(item)]
            for key, item in value.items()
            if _word(key) in ("verdict", "passed", "result")
            and isinstance(item, str)
            and _word(item) in _STATED
        ]
    return said + [s for child in _children(value) for s in _stated(child)]


def _variant_key(value):
    """True when a dict at any depth has a key spelled like "pass" that is not exactly
    "pass" (`"Pass"`, `" pass"`), or a "passed" or "verdict" key holding a boolean."""
    if isinstance(value, dict):
        for key, item in value.items():
            word = _word(key)
            if (word == "pass" and key != "pass") or (
                word in ("passed", "verdict") and isinstance(item, bool)
            ):
                return True
    return any(_variant_key(child) for child in _children(value))


def _disagrees(value, top):
    """True when a dict nested at any depth in the verdict has a "pass" unlike `top`."""
    return any(
        (
            isinstance(child, dict)
            and "pass" in child
            and (type(child["pass"]), child["pass"]) != (type(top), top)
        )
        or _disagrees(child, top)
        for child in _children(value)
    )


def _within(at, spans):
    return any(s <= at < e for s, e in spans)


def _canonical(value):
    """The value with integral floats as ints at every depth, so `1` and `1.0` compare
    equal while `1` and `true` stay apart once JSON-encoded."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


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
