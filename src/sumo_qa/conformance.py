# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Deterministic cross-model conformance validator (issue #214).

Turns the human-readable QA scenarios in ``tests/scenarios/SCENARIOS.md`` and
``TOOL-SELECTION.md`` into machine-readable contracts and scores a captured
host/tool-call transcript against them WITHOUT a live LLM call. It answers one
question per scenario: did the host route to the right skill, call the required
tools, avoid the forbidden ones, and keep the forbidden claims out of its
output?

This is the deterministic half of the conformance layer. Response *quality*
(residual risks, verbosity, grounding) stays with the provider-backed
promptfoo evals under ``tests/evals/promptfoo/`` and their variance aggregator;
this module never calls a model.

The transcript is provider-agnostic: a ``tool`` name plus its ``args`` per
call, and the final assistant ``output_text``. Tool names may be sumo-qa MCP
tools or host tools; the fixtures pin sumo-qa tool names and a guard test ties
them to the registered tool surface. ``transcript_from_debug_dir`` reconstructs
a transcript from a ``SUMO_QA_DEBUG_DIR`` capture (see ``debug_capture``).

First-slice matching semantics (documented limits): ``required_tool_calls``
are checked as a SET (presence, not order or multiplicity), and output markers
match as case-insensitive substrings — pin distinctive phrases in fixtures
(an id like ``INV-12345`` also matches inside ``INV-123456``).
"""

from __future__ import annotations

import json
import re
from bisect import bisect_left
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from sumo_qa.knowledge_loaders import sumo_qa_load_approaches, sumo_qa_load_classifications
from sumo_qa.skill_prompts import _skills_dir

# The canonical router chain fires BEFORE the destination skill, in this
# order: the entry router first, then the approach decider. A router tool ahead
# of the expected entry skill is exempt from mis-route detection ONLY when it
# precedes the expected skill in this chain — `sumo_qa_deciding_approach`
# before an expected `using_sumo_qa` is still a wrong route (the entry router
# must fire first), while either router before an ordinary destination skill
# is a legitimate prelude.
ROUTER_CHAIN = ("using_sumo_qa", "sumo_qa_deciding_approach")

ROUTING_LEAK_FAMILIES = (
    "payload_json",
    "taxonomy_label",
    "route_announcement",
    "checklist_status",
    "router_checklist",
)

_VALID_MODES = frozenset({"deterministic", "provider-backed"})

# Trailing collision suffix a debug run dir grows when two captures share a
# timestamp (see debug_capture: ``{ts}-{tool}``, then ``{ts}-{tool}-1`` ...).
_COLLISION_SUFFIX_RE = re.compile(r"-\d+$")


class ViolationKind(str, Enum):
    """The contract axis a scenario violated."""

    WRONG_SKILL_ROUTING = "wrong_skill_routing"
    MISSING_REQUIRED_TOOL = "missing_required_tool"
    FORBIDDEN_TOOL_CALLED = "forbidden_tool_called"
    MISSING_OUTPUT_MARKER = "missing_output_marker"
    FORBIDDEN_OUTPUT_MARKER = "forbidden_output_marker"
    ROUTING_STATE_LEAK = "routing_state_leak"


@dataclass(frozen=True)
class Violation:
    kind: ViolationKind
    detail: str


@dataclass(frozen=True)
class ConformanceScenario:
    """One machine-readable scenario contract (a row in ``scenarios.yaml``)."""

    id: str
    source_doc: str
    source_heading: str
    user_prompt: str
    mode: str
    expected_entry_skill: str | None = None
    required_tool_calls: tuple[str, ...] = ()
    forbidden_tool_calls: tuple[str, ...] = ()
    required_output_markers: tuple[str, ...] = ()
    forbidden_output_markers: tuple[str, ...] = ()

    @property
    def deterministic(self) -> bool:
        return self.mode == "deterministic"


@dataclass(frozen=True)
class ToolCall:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Transcript:
    """A captured interaction: the tools the host called, in order, plus the
    final assistant output text."""

    scenario_id: str
    tool_calls: tuple[ToolCall, ...]
    output_text: str = ""


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    violations: tuple[Violation, ...]
    skipped: bool = False

    @property
    def passed(self) -> bool:
        return not self.skipped and not self.violations


# --------------------------------------------------------------------------- #
# Loading                                                                     #
# --------------------------------------------------------------------------- #
def load_scenarios(path: str | Path) -> list[ConformanceScenario]:
    """Parse the conformance fixture YAML into scenario objects.

    Raises ``ValueError`` on an unknown ``mode``, a duplicate ``id``, or a
    deterministic scenario declaring no enforceable clause, so a malformed
    fixture fails loudly rather than scoring vacuously."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    scenarios = [_parse_scenario(entry) for entry in data["scenarios"]]
    ids = [s.id for s in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate scenario ids in {path}: {sorted(_duplicates(ids))}")
    return scenarios


def _duplicates(items: list[str]) -> set[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for item in items:
        if item in seen:
            dupes.add(item)
        seen.add(item)
    return dupes


def _parse_scenario(entry: dict[str, Any]) -> ConformanceScenario:
    mode = entry["mode"]
    if mode not in _VALID_MODES:
        raise ValueError(
            f"scenario {entry.get('id')!r}: mode {mode!r} is not one of {sorted(_VALID_MODES)}"
        )
    scenario = ConformanceScenario(
        id=entry["id"],
        source_doc=entry["source_doc"],
        source_heading=entry["source_heading"],
        user_prompt=entry["user_prompt"],
        mode=mode,
        expected_entry_skill=entry.get("expected_entry_skill"),
        required_tool_calls=tuple(entry.get("required_tool_calls") or ()),
        forbidden_tool_calls=tuple(entry.get("forbidden_tool_calls") or ()),
        required_output_markers=tuple(entry.get("required_output_markers") or ()),
        forbidden_output_markers=tuple(entry.get("forbidden_output_markers") or ()),
    )
    if scenario.deterministic and not (
        scenario.expected_entry_skill
        or scenario.required_tool_calls
        or scenario.forbidden_tool_calls
        or scenario.required_output_markers
        or scenario.forbidden_output_markers
    ):
        raise ValueError(
            f"scenario {scenario.id!r}: deterministic but declares no enforceable "
            f"clause (expected_entry_skill, tool calls, or output markers) — it "
            f"would pass every transcript vacuously"
        )
    return scenario


# --------------------------------------------------------------------------- #
# Scoring                                                                     #
# --------------------------------------------------------------------------- #
def validate_transcript(
    scenario: ConformanceScenario,
    transcript: Transcript,
    known_entry_skills: frozenset[str] | None = None,
) -> ScenarioResult:
    """Score one transcript against one scenario.

    Provider-backed scenarios are deferred (skipped) - they need an LLM judge.
    ``known_entry_skills`` is the set of destination skills used to tell a
    mis-route apart from a legitimate loader call. It defaults to the REGISTERED
    skill-tool surface (``registered_entry_skills()``) so a single-scenario
    check is as strict as ``validate_all``: a route to any registered skill the
    fixture never names is still flagged, not silently accepted. Pass an
    explicit set (including ``frozenset()``) to override the default."""
    if not scenario.deterministic:
        return ScenarioResult(scenario.id, (), skipped=True)
    if known_entry_skills is None:
        known_entry_skills = registered_entry_skills()
    violations = (
        _routing_violations(scenario, transcript, known_entry_skills)
        + _tool_violations(scenario, transcript)
        + _output_violations(scenario, transcript)
        + _leak_violations(transcript)
    )
    return ScenarioResult(scenario.id, tuple(violations))


def _routing_violations(
    scenario: ConformanceScenario,
    transcript: Transcript,
    known_entry_skills: frozenset[str],
) -> list[Violation]:
    expected = scenario.expected_entry_skill
    if expected is None:
        return []
    names = [tc.tool for tc in transcript.tool_calls]
    if expected not in names:
        return [
            Violation(
                ViolationKind.WRONG_SKILL_ROUTING,
                f"expected entry skill {expected!r} was never invoked",
            )
        ]
    expected_idx = names.index(expected)
    for name in names[:expected_idx]:
        if _router_exempt(name, expected):
            continue
        if name in known_entry_skills or name in ROUTER_CHAIN:
            return [
                Violation(
                    ViolationKind.WRONG_SKILL_ROUTING,
                    f"routed to {name!r} before the expected entry skill {expected!r}",
                )
            ]
    return []


def _router_exempt(name: str, expected: str) -> bool:
    """Whether a router-chain tool ahead of the expected skill is a legitimate
    prelude: it must precede the expected skill in the canonical chain, or the
    expected skill must be an ordinary (non-chain) destination."""
    if name not in ROUTER_CHAIN:
        return False
    if expected not in ROUTER_CHAIN:
        return True
    return ROUTER_CHAIN.index(name) < ROUTER_CHAIN.index(expected)


def _tool_violations(scenario: ConformanceScenario, transcript: Transcript) -> list[Violation]:
    called = {tc.tool for tc in transcript.tool_calls}
    violations: list[Violation] = []
    for required in scenario.required_tool_calls:
        if required not in called:
            violations.append(
                Violation(
                    ViolationKind.MISSING_REQUIRED_TOOL,
                    f"required tool {required!r} was not called",
                )
            )
    for forbidden in scenario.forbidden_tool_calls:
        if forbidden in called:
            violations.append(
                Violation(
                    ViolationKind.FORBIDDEN_TOOL_CALLED,
                    f"forbidden tool {forbidden!r} was called",
                )
            )
    return violations


def _output_violations(scenario: ConformanceScenario, transcript: Transcript) -> list[Violation]:
    """Markers match as CASE-INSENSITIVE substrings: a host that leaks
    ``classification: docs_change`` must not slip past a fixture that pins
    ``Classification: docs_change``. Substring semantics are a documented
    first-slice limit — fixtures pin distinctive phrases."""
    text = transcript.output_text.casefold()
    violations: list[Violation] = []
    for marker in scenario.required_output_markers:
        if marker.casefold() not in text:
            violations.append(
                Violation(
                    ViolationKind.MISSING_OUTPUT_MARKER,
                    f"required output marker {marker!r} is absent",
                )
            )
    for marker in scenario.forbidden_output_markers:
        if marker.casefold() in text:
            violations.append(
                Violation(
                    ViolationKind.FORBIDDEN_OUTPUT_MARKER,
                    f"forbidden output marker {marker!r} is present",
                )
            )
    return violations


# --------------------------------------------------------------------------- #
# Routing-state leaks (issue #248)                                            #
# --------------------------------------------------------------------------- #
# The approach router's payload keys; a brace-balanced span naming all three is
# the routing object, whether compact, pretty-printed, or written with the
# skill's own unquoted-key notation. A config snippet that merely has an
# ``approach`` key is not.
_PAYLOAD_KEYS = ("classification", "approach", "next_action")
_NEXT_ACTION_RE = re.compile(r"\bnext_action[\"']?\s*:\s*(?=\{)", re.ASCII)
_SKILL_KEY_RE = re.compile(r"\bskill[\"']?\s*:", re.ASCII)
# Quoted strings, taken left to right. One followed by ``:`` is a key; any
# other is a value, blanked before key matching so ``"skill: beginner"`` is
# not a skill key. A single quote between two word characters is an
# apostrophe (``user's``), never a delimiter. Every character has one way to
# match, so an unterminated string cannot backtrack exponentially.
_WORD = "A-Za-z0-9_"
# Emphasis, code and quote marks a host wraps around a label or its value.
_DECO_CHARS = "*_`\"'"
_DECO_SET = re.escape(_DECO_CHARS)
_DECO = f"[{_DECO_SET}]"
_QUOTED_RE = re.compile(
    r'"(?:\\.|[^"\\])*"'
    rf"|(?<![{_WORD}])'(?:\\.|[^'\\]|(?<=[{_WORD}])'(?=[{_WORD}]))*"
    rf"(?:(?<![{_WORD}])'|'(?![{_WORD}]))",
    re.DOTALL,
)
_KEY_FOLLOWS_RE = re.compile(r"\s*:")
# One explicit character set for both engines (their ``\s`` differ).
_LINE_BREAK_RE = re.compile("[\r\u2028\u2029]")
_SPACE_RE = re.compile("[\t\v\f \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u202f\u205f\u3000\ufeff]")
# High-confidence router voice only. Downstream skills may offer a handoff
# ("I'd recommend handing off to sumo-qa-reviewing-before-merge") or tell the
# user to send output to a tool, so paraphrased handoffs are left to the eval's
# judge rather than matched here.
_TO_SKILL = r"[:\s*_`\"'\[(]{0,8}(?:the\s+[*_`\"'\[(]{0,8})?(?:sumo-qa-|using[-_]sumo[-_]qa)"
_ROUTE_ANNOUNCEMENT_RE = re.compile(
    r"picking the qa approach"
    r"|\brouting this qa intent\b"
    # A skill is named ``sumo-qa-*`` (hyphens); ``sumo_qa_*`` tool names are
    # where downstream skills legitimately send data.
    r"|\b(?:routing|routed)(?:\s+(?:this|you|it))?\s+to"
    + _TO_SKILL
    + r"|\b(?:i'm|i am|i'll|i will)\s+(?:now\s+)?(?:rout(?:e|ing)|handing)\s+"
    r"(?:you\s+to\b|this\s+to" + _TO_SKILL + ")",
    re.IGNORECASE | re.ASCII,
)
# A router step named on a line: what makes a status marker or a numbered
# line router bookkeeping rather than a downstream plan.
_ROUTER_STEP = (
    r"(?:load(?:_|\s+)(?:the\s+)?(?:classifications|approaches|catalogues)"
    r"|removability (?:gate|check)|reason about (?:classification|shape)"
    r"|routing[- ]payload|read the user's intent|pick the approach"
    r"|route to the (?:named )?sub-skill)"
)
_ROUTER_STEP_RE = re.compile(_ROUTER_STEP, re.IGNORECASE | re.ASCII)
_CHECKLIST_STATUS_RE = re.compile(r"\[(?:done|in[ _]progress|pending|completed)\]", re.IGNORECASE)
_NUMBERED_LINE_RE = re.compile(r"[ \t]*\d+[.)][ \t]", re.ASCII)
_CATALOGUE_HEADING_RE = re.compile(r"^##\s+([a-z][a-z0-9_-]*)\s*$", re.MULTILINE)


def find_routing_leaks(text: str) -> tuple[str, ...]:
    """The routing-state leak families present in user-visible ``text``.

    The approach router is an internal hop: its payload object, taxonomy
    labels, route announcement and checklist bookkeeping must never reach the
    user. Each family is matched structurally rather than by bare word, so
    prose that says "approach" or "classification", a downstream plan's
    progress markers, or a config snippet is not a leak. A taxonomy label only
    counts when its value is exactly a catalogue entry name (or ``n/a``), read
    from the live catalogues."""
    text = _normalise(text)
    checks = {
        "payload_json": _has_routing_payload,
        "taxonomy_label": _has_taxonomy_label,
        "route_announcement": lambda s: bool(_ROUTE_ANNOUNCEMENT_RE.search(s)),
        "checklist_status": _has_router_status,
        "router_checklist": lambda s: len(_router_step_lines(s, _NUMBERED_LINE_RE.match)) >= 2,
    }
    return tuple(family for family in ROUTING_LEAK_FAMILIES if checks[family](text))


def _normalise(text: str) -> str:
    """Typographic single and double quotes to ASCII, line breaks (CRLF, CR, U+2028/9) to
    newlines, and every other whitespace character to a plain space, so the
    Python and JS matchers see the same text."""
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\r\n", "\n")
    text = _LINE_BREAK_RE.sub("\n", text)
    return _SPACE_RE.sub(" ", text)


def _router_step_lines(text: str, qualifies: Any) -> list[str]:
    """Lines that qualify (a status marker, a numbered-step prefix) AND name a
    router step. Checked line by line so matching stays linear."""
    return [line for line in text.split("\n") if qualifies(line) and _ROUTER_STEP_RE.search(line)]


def _has_router_status(text: str) -> bool:
    return bool(_router_step_lines(text, _CHECKLIST_STATUS_RE.search))


def _has_routing_payload(text: str) -> bool:
    """A brace-balanced span naming the payload keys whose ``next_action``
    object itself carries a ``skill`` handoff; coincidental config keys, or a
    ``skill:`` elsewhere or inside a string value, are not a payload."""
    return any(
        all(re.search(rf"\b{key}[\"']?\s*:", keys, re.ASCII) for key in _PAYLOAD_KEYS)
        and _next_action_has_skill(keys)
        for keys in (_blank_string_values(span) for span in _brace_spans(text))
    )


def _blank_string_values(span: str) -> str:
    def keep_keys(m: re.Match[str]) -> str:
        return m.group(0) if _KEY_FOLLOWS_RE.match(span, m.end()) else '""'

    return _QUOTED_RE.sub(keep_keys, span)


def _next_action_has_skill(span: str) -> bool:
    """Whether an object that is a ``next_action`` value holds a ``skill`` key.
    One brace pass maps each ``{`` to its ``}``, so every ``next_action`` is a
    lookup, not a rescan; a ``next_action`` inside a quoted key opens no
    object."""
    closes = {open_: close for open_, close, _ in _brace_pairs(span)}
    skills = [m.start() for m in _SKILL_KEY_RE.finditer(span)]
    for match in _NEXT_ACTION_RE.finditer(span):
        close = closes.get(match.end())
        if close is None:
            continue
        k = bisect_left(skills, match.end())
        if k < len(skills) and skills[k] < close:
            return True
    return False


_WORD_RE = re.compile(f"[{_WORD}]")


def _is_word(text: str, i: int) -> bool:
    return 0 <= i < len(text) and _WORD_RE.match(text, i) is not None


def _brace_pairs(text: str) -> list[tuple[int, int, int]]:
    """Every balanced ``{...}`` as ``(open, close, depth)``, ignoring braces
    inside quoted strings (a single quote between word characters is an
    apostrophe, not a delimiter)."""
    pairs: list[tuple[int, int, int]] = []
    stack: list[int] = []
    quote = ""
    escaped = False
    for i, ch in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote and not (
                ch == "'" and _is_word(text, i - 1) and _is_word(text, i + 1)
            ):
                quote = ""
        elif stack and (ch == '"' or (ch == "'" and not _is_word(text, i - 1))):
            quote = ch
        elif ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            open_ = stack.pop()
            pairs.append((open_, i, len(stack)))
    return pairs


def _brace_spans(text: str) -> list[str]:
    """Top-level ``{...}`` spans; an unbalanced brace yields no span."""
    # Top-level pairs close in document order, so no sort is needed.
    return [text[o : c + 1] for o, c, depth in _brace_pairs(text) if depth == 0]


def _has_taxonomy_label(text: str) -> bool:
    names = _catalogue_names()
    return bool(names) and bool(_label_re(names).search(text))


@lru_cache(maxsize=4)
def _label_re(names: frozenset[str]) -> re.Pattern[str]:
    """A bare label line: the label and a catalogue value (or ``n/a``) are the
    whole line, give or take a list or heading prefix, emphasis, quotes, a
    clause end and the other label with its own catalogue value.
    Labels inside prose are left to the eval's judge."""
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    bare_pair = (
        rf"(?:classification|approach){_DECO}*[ \t]*:[ \t{_DECO_SET}]*"
        rf"(?:{alternatives}|n/a){_DECO}*"
    )
    pair = rf"{_DECO}*{bare_pair}"
    return re.compile(
        # List or heading prefixes, each followed by whitespace, so a prefix
        # run has a single parse.
        rf"^[ \t]*(?:(?:[-+*]|>+|#{{1,6}}|\d{{1,3}}[.)])[ \t]+)*{pair}"
        # Then a clause end, or the other label with its own value after a
        # clause end or whitespace, then line end.
        # (a second label straight after the first value's decoration starts
        # with a letter, so that branch has one parse).
        rf"(?:(?:(?:[ \t]*[.,;][ \t]*|[ \t]+){pair}|{bare_pair})(?:[ \t]*[.,;])?"
        r"|[ \t]*[.,;])?[ \t]*$",
        re.IGNORECASE | re.MULTILINE | re.ASCII,
    )


def _catalogue_names() -> frozenset[str]:
    """Entry names from the live classification + approach catalogues; empty
    when a catalogue is unreadable or undecodable so scoring degrades instead
    of erroring."""
    try:
        text = sumo_qa_load_classifications() + "\n" + sumo_qa_load_approaches()
    except (OSError, ValueError):
        return frozenset()
    return frozenset(_CATALOGUE_HEADING_RE.findall(text))


def _leak_violations(transcript: Transcript) -> list[Violation]:
    return [
        Violation(
            ViolationKind.ROUTING_STATE_LEAK,
            f"internal routing state leaked into the output ({family})",
        )
        for family in find_routing_leaks(transcript.output_text)
    ]


def registered_entry_skills() -> frozenset[str]:
    """Every skill-tool name registered from the skills/ directory (directory
    name with ``-`` -> ``_``, mirroring ``register_skills_as_prompts``), i.e.
    every tool a host could actually route to as an entry skill. Deriving the
    mis-route set from the REGISTERED surface (not just the fixture's own
    scenarios) means a route to a registered skill the fixture never names
    still fails. Returns an empty set when the skills directory is unavailable
    so scoring degrades to the fixture-derived set rather than erroring."""
    try:
        skills_dir = _skills_dir()
        if not skills_dir.is_dir():
            return frozenset()
        return frozenset(
            p.name.replace("-", "_")
            for p in skills_dir.iterdir()
            if p.is_dir() and (p / "SKILL.md").is_file()
        )
    except OSError:
        return frozenset()


def validate_all(
    scenarios: list[ConformanceScenario],
    transcripts: list[Transcript],
    known_entry_skills: frozenset[str] | None = None,
) -> list[ScenarioResult]:
    """Score every scenario against its matching transcript (by ``scenario_id``).

    A deterministic scenario with no supplied transcript is reported skipped -
    the suite scores whatever was captured, it does not fabricate a verdict.
    ``known_entry_skills`` (default: the registered skill-tool surface) is
    unioned with the fixture's own declared entry skills for mis-route
    detection."""
    by_id = {t.scenario_id: t for t in transcripts}
    known = frozenset(s.expected_entry_skill for s in scenarios if s.expected_entry_skill)
    known |= known_entry_skills if known_entry_skills is not None else registered_entry_skills()
    results: list[ScenarioResult] = []
    for scenario in scenarios:
        transcript = by_id.get(scenario.id)
        if transcript is None:
            results.append(ScenarioResult(scenario.id, (), skipped=True))
            continue
        results.append(validate_transcript(scenario, transcript, known))
    return results


# --------------------------------------------------------------------------- #
# Reporting                                                                   #
# --------------------------------------------------------------------------- #
def format_report(results: list[ScenarioResult]) -> str:
    """A compact, provider-log-free report: PASS/FAIL/SKIP per scenario, the
    violated contract inline on a failure, and a one-line summary."""
    lines: list[str] = []
    passed = failed = skipped = 0
    for result in results:
        if result.skipped:
            skipped += 1
            lines.append(f"SKIP {result.scenario_id} (provider-backed or no transcript)")
        elif result.passed:
            passed += 1
            lines.append(f"PASS {result.scenario_id}")
        else:
            failed += 1
            lines.append(f"FAIL {result.scenario_id}")
            for violation in result.violations:
                lines.append(f"       - {violation.kind.value}: {violation.detail}")
    lines.append("")
    lines.append(f"{passed} passed, {failed} failed, {skipped} skipped")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Bridge from the SUMO_QA_DEBUG_DIR capture format                            #
# --------------------------------------------------------------------------- #
def transcript_from_debug_dir(
    debug_dir: str | Path, scenario_id: str, output_text: str = ""
) -> Transcript:
    """Reconstruct a transcript from a ``SUMO_QA_DEBUG_DIR`` capture directory.

    Each per-tool subdirectory ``debug_capture`` wrote (``{ts}-{tool}`` with its
    ``input.json``) becomes one ordered ``ToolCall``. The debug capture records
    only tool exchanges, not the final assistant text, so ``output_text`` is
    supplied by the caller (the human running the manual conformance check).

    Ordering: directory names carry only SECOND-resolution timestamps, so
    same-second calls to different tools would sort by tool name, not call
    order — and the wrong-route check depends on true call order. Run dirs are
    therefore ordered by their capture's ``input.json`` mtime (nanoseconds,
    falling back to the dir's own mtime), with the name as the deterministic
    tiebreak for captures whose mtimes a copy or archive flattened."""
    base = Path(debug_dir)
    calls: list[ToolCall] = []
    for run_dir in sorted((p for p in base.iterdir() if p.is_dir()), key=_run_dir_sort_key):
        input_path = run_dir / "input.json"
        args = json.loads(input_path.read_text(encoding="utf-8")) if input_path.is_file() else {}
        calls.append(ToolCall(tool=_tool_name_from_run_dir(run_dir.name), args=args))
    return Transcript(scenario_id=scenario_id, tool_calls=tuple(calls), output_text=output_text)


def _run_dir_sort_key(run_dir: Path) -> tuple[int, str]:
    """Call-order sort key for a capture run dir: the ``input.json`` mtime in
    nanoseconds (the file is written at call time; the dir itself is the
    fallback when a capture has no input.json), then the dir name."""
    input_path = run_dir / "input.json"
    marker = input_path if input_path.is_file() else run_dir
    return (marker.stat().st_mtime_ns, run_dir.name)


def _tool_name_from_run_dir(name: str) -> str:
    """Recover the tool name from a ``{YYYYmmdd}-{HHMMSS}-{tool}[-{n}]`` dir name."""
    parts = name.split("-", 2)
    rest = parts[2] if len(parts) == 3 else name
    return _COLLISION_SUFFIX_RE.sub("", rest)
