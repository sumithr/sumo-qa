# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""`llm-rubric` grading: build the judge's prompt, then read its verdict.

This reproduces promptfoo's `llm-rubric` semantics, which is what the 66 live
rubric assertions were written against. Two halves:

## Building the prompt

promptfoo renders the rubric prompt against `{...case vars, output, rubric}`
and sends the result to the judge provider. A config supplies its own prompt
via `defaultTest.options.rubricPrompt`; all 61 live configs do, and several of
them interpolate the case's own vars so the loaded catalogues reach the judge's
context alongside the rubric. When a config supplies nothing, promptfoo's
built-in `DEFAULT_GRADING_PROMPT` is used - a JSON-encoded system+user message
pair, reproduced verbatim below from promptfoo 0.121.20 `src/prompts/grading.ts`
(the version pinned in `package.json`), not from memory.

So a rubric prompt arrives in one of two shapes and both are handled: a JSON
message array (render every string scalar, keep the roles) or a plain string
(render it whole, send it as a single user turn). That is exactly what
promptfoo's `renderLlmRubricPrompt` does - it tries `JSON.parse` first and
falls back to rendering the raw string.

`output` and `rubric` are judge-time values and always WIN over a case var of
the same name. promptfoo builds the same context, but the precedence is worth
stating: a config var called `output` that could shadow the candidate's real
answer would silently grade the fixture instead of the response.

## Reading the verdict

promptfoo extracts the first JSON object from the judge's reply and then does:

    let pass = parsed.pass ?? true;

**A reply with no `pass` key PASSES.** That default is how a judge that has
drifted, been truncated, or answered in prose turns into a green gate, and
issue #662 makes refusing it an acceptance criterion. So this module diverges
deliberately: no `pass`, no parse, no verdict - the assertion FAILS, and the
raw reply is carried into the reason so the failure is actionable. The
divergence is documented here and in the runner README because slice 3
compares the two runners config-for-config and needs to know which differences
are intended.

Everything else follows promptfoo: a stringly boolean (`"yes"` / `"no"`) is
coerced, a missing `score` is derived from `pass`, and an assertion-level
`threshold` demotes a pass whose score falls below it.

Belt and braces on the JSON: the judge is called with `--json-schema`, so the
CLI constrains the reply to the verdict shape. The tolerant parser below stays
anyway - the schema is the first line of defence, not a reason to trust the
reply unconditionally.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from claude.templating import render

__all__ = [
    "DEFAULT_RUBRIC_PROMPT",
    "VERDICT_SCHEMA",
    "JudgeVerdict",
    "extract_first_json_object",
    "parse_judge_response",
    "render_judge_prompt",
]

# Verbatim from promptfoo 0.121.20 `src/prompts/grading.ts`
# (`DEFAULT_GRADING_PROMPT`), which builds it with `JSON.stringify` over a
# system+user message pair whose system content is a `dedent` template. Stored
# as the same JSON string promptfoo produces so `render_judge_prompt` takes the
# identical parse-then-render path for it as for a config's own JSON prompt.
DEFAULT_RUBRIC_PROMPT = json.dumps(
    [
        {
            "role": "system",
            "content": (
                "You are grading output according to a user-specified rubric. If the "
                "statement in the rubric is true, then the output passes the test. You "
                "respond with a JSON object with this structure: {reason: string, pass: "
                "boolean, score: number}\n"
                "\n"
                "Examples:\n"
                "\n"
                "<Output>Hello world</Output>\n"
                "<Rubric>Content contains a greeting</Rubric>\n"
                '{"reason": "the content contains the word \'Hello\'", "pass": true, '
                '"score": 1.0}\n'
                "\n"
                "<Output>Avast ye swabs, repel the invaders!</Output>\n"
                "<Rubric>Does not speak like a pirate</Rubric>\n"
                '{"reason": "\'avast ye\' is a common pirate term", "pass": false, '
                '"score": 0.0}'
            ),
        },
        {
            "role": "user",
            "content": "<Output>\n{{ output }}\n</Output>\n<Rubric>\n{{ rubric }}\n</Rubric>",
        },
    ]
)

# Handed to `claude --json-schema`. `additionalProperties: false` plus all
# three keys required is what turns "the judge usually replies in JSON" into
# "the judge replies in the verdict shape". The score bounds are the rubrics'
# own contract: every live `rubricPrompt` asks for 0.0 to 1.0.
VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pass": {"type": "boolean"},
        "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reason": {"type": "string"},
    },
    "required": ["pass", "score", "reason"],
    "additionalProperties": False,
}

_TRUTHY = {"true", "yes", "pass", "y", "1"}

# Closer -> the opener it must match. A mismatch means broken nesting.
_CLOSERS = {"}": "{", "]": "["}
_OPENERS = frozenset(_CLOSERS.values())


@dataclass(frozen=True)
class JudgeVerdict:
    passed: bool
    score: float
    reason: str


def render_judge_prompt(
    rubric_prompt: str | None,
    *,
    rubric: str,
    output: str,
    variables: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Build the judge's messages for one assertion.

    Returns a list of `{role, content}` mappings. A JSON message array keeps
    its roles; a plain string becomes a single user turn. `output` and
    `rubric` override any case var of the same name.
    """
    template = rubric_prompt if rubric_prompt else DEFAULT_RUBRIC_PROMPT
    context = {**dict(variables), "output": output, "rubric": rubric}

    try:
        parsed = json.loads(template)
    except (ValueError, TypeError):
        parsed = None

    if isinstance(parsed, list) and all(
        isinstance(entry, Mapping) and "role" in entry for entry in parsed
    ):
        return [
            {
                "role": str(entry["role"]),
                "content": render(str(entry.get("content", "")), context),
            }
            for entry in parsed
        ]

    return [{"role": "user", "content": render(template, context)}]


def _reject_non_finite(literal: str) -> Any:
    """`json.loads` accepts `NaN`, `Infinity` and `-Infinity`; JSON does not.

    Left alone they are actively dangerous here. A score of `NaN` compares
    False against every threshold, so `score < threshold` is False and a
    malformed reply PASSES - the precise "default to pass" behaviour this
    module exists to refuse. It would also put a bare `NaN` token into the
    JSON report, which is not valid JSON for whatever reads it next.
    """
    raise ValueError(f"{literal} is not valid JSON")


def extract_first_json_object(text: str) -> Any:
    """Return the first TOP-LEVEL JSON object in `text`, or None.

    Judges wrap their verdict in prose or a markdown fence often enough that
    requiring a bare object would fail honest replies, so the object is found
    rather than demanded. What it must never do is find one INSIDE a reply
    that was cut off: `{"wrapper": {"pass": true, "score": 1.0, "reason":
    "ok"}` never closes, yet the inner object reads as a complete verdict, and
    grading it turns a truncated reply into a PASS.

    So the scan walks the text once, string-aware and escape-aware, keeping a
    stack of open `{` and `[`. A `{` is a candidate only when that stack is
    EMPTY - nothing encloses it - and its span is decoded only once the stack
    returns to empty, which is to say only once it actually closed. A reply
    that ends mid-structure never gets there and yields nothing.

    ## The trade this makes, deliberately

    An unmatched `{` in the judge's PROSE - "I thought { about it" before a
    perfectly good verdict - leaves the stack non-empty for the rest of the
    reply, so the real object that follows is never treated as top-level and
    the reply is refused.

    That is a recoverable reply being failed, and an earlier version of this
    function tried to rescue it by decoding from every `{` instead. It worked,
    and it also let the truncated-wrapper fragment above through, because
    nothing then distinguished "a brace enclosing nothing" from "a brace
    enclosing something unfinished". A second attempt skipped braces sitting
    after a `:` or `,`, which refused an ordinary `Here is my verdict: {...}`
    - a far more common reply than one containing a stray brace.

    Both attempts traded a safe failure for an unsafe pass. This one keeps the
    safe failure: a stray prose brace makes the assertion FAIL loudly with the
    raw reply in its reason, which a human reads and understands in seconds.
    A truncated fragment silently graded as a PASS is the failure nobody sees.
    """
    decoder = json.JSONDecoder(parse_constant=_reject_non_finite)
    stack: list[str] = []
    start = -1
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in _OPENERS:
            if not stack and char == "{":
                start = index
            stack.append(char)
        elif char in _CLOSERS:
            if not stack:
                # A closer with nothing open: prose, not structure. Ignore it
                # rather than letting it drive the stack negative.
                continue
            if stack[-1] != _CLOSERS[char]:
                # A closer that does not match its opener - `{"wrapper": ]` -
                # means the reply's structure is broken, not merely
                # unfinished. Popping anyway would empty the stack and hand
                # top-level status to whatever follows, so a malformed wrapper
                # would surrender its insides: `{"wrapper": ] {"pass": true,
                # ...}` graded the verdict that was never top-level at all.
                # Once the nesting is inconsistent nothing later in the reply
                # can be trusted to be top-level, so the whole reply is
                # refused.
                return None
            stack.pop()
            if not stack and start >= 0:
                try:
                    value = decoder.decode(text[start : index + 1])
                except ValueError:
                    # Balanced but not valid JSON (a trailing comma, a
                    # single-quoted key, a non-finite literal). A later
                    # top-level object may still be the verdict.
                    start = -1
                    continue
                if isinstance(value, dict):
                    return value
                start = -1
    return None


def _coerce_pass(value: Any) -> bool | None:
    """Read the judge's verdict, or None when there is nothing usable to read.

    The non-finite guard is not theoretical. `bool(float("nan"))` is True, so
    a `pass` of `NaN` arriving through `structured_output` - which the CLI
    hands over already parsed by an ordinary `json.loads` that accepts it -
    would read as a PASS. That is the same door the score guard closes, and
    the verdict field deserves it at least as much as the score does.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY
    if isinstance(value, (int, float)):
        return bool(value) if math.isfinite(value) else None
    return None


class _NonFiniteScore(ValueError):
    """The reply carried a score that is not a finite number."""


def _coerce_score(value: Any, *, fallback: bool) -> float:
    """Read the judge's score, falling back to the boolean verdict.

    An ABSENT or unreadable score falls back to the boolean, which is the only
    other thing the reply asserted. A score that is PRESENT but not finite
    does not: it raises, and the caller turns it into an ungradeable verdict.

    The distinction is load-bearing, and getting it wrong is how the first
    attempt at this fix reintroduced the bug it was closing. Falling back to
    the boolean for a `NaN` score means `pass: true` becomes score 1.0, which
    then clears any threshold - so a reply the runner is supposed to refuse
    passes a 0.9 gate instead. Refusing outright is the only reading
    consistent with how this module treats every other malformed reply.
    """
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise _NonFiniteScore(repr(value))
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return float(fallback)
        if not math.isfinite(parsed):
            raise _NonFiniteScore(value)
        return parsed
    return float(fallback)


def parse_judge_response(
    text: str,
    *,
    threshold: float | None = None,
    structured_output: Any = None,
) -> JudgeVerdict:
    """Turn the judge's reply into a verdict, failing loudly when it cannot.

    `structured_output` is the CLI's own schema-validated object when
    `--json-schema` produced one; it is preferred over re-parsing the text.
    """
    payload = structured_output if isinstance(structured_output, Mapping) else None
    if payload is None:
        parsed = extract_first_json_object(text or "")
        payload = parsed if isinstance(parsed, Mapping) else None

    if payload is None:
        return _ungradeable(
            text,
            "no JSON object found in the judge's reply, so there is no verdict to "
            "read. Failing rather than defaulting to pass (#662).",
        )

    passed = _coerce_pass(payload.get("pass"))
    if passed is None:
        return _ungradeable(
            text,
            "the judge's reply carries no usable `pass` value. promptfoo would have "
            "defaulted this to PASS; this runner fails it instead (#662).",
        )

    try:
        score = _coerce_score(payload.get("score"), fallback=passed)
    except _NonFiniteScore as exc:
        # Reachable from BOTH doors. The text path is already blocked by
        # `parse_constant`, but `structured_output` is handed over by the CLI,
        # parsed by an ordinary `json.loads` that accepts `NaN` and the
        # infinities - so without this the same malformed value would fail
        # loudly through one door and pass through the other.
        return _ungradeable(
            text,
            f"the judge's score is not a finite number ({exc}), so it cannot be "
            "compared against a threshold. Failing rather than defaulting to "
            "pass (#662).",
        )
    reason = str(payload.get("reason") or "").strip()

    if threshold is not None and passed and score < threshold:
        return JudgeVerdict(
            passed=False,
            score=score,
            reason=reason or f"score {score} below threshold {threshold}",
        )

    return JudgeVerdict(
        passed=passed, score=score, reason=reason or ("graded pass" if passed else "graded fail")
    )


def _ungradeable(text: str, explanation: str) -> JudgeVerdict:
    excerpt = (text or "").strip()
    excerpt = excerpt[:500] if excerpt else "<empty reply>"
    return JudgeVerdict(passed=False, score=0.0, reason=f"{explanation} Raw reply: {excerpt}")
