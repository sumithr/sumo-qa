# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Assertion model and deterministic Python evaluators for the eval runner.

The promptfoo matrix uses exactly two assertion types:

* `llm-rubric` (66 in the live matrix) - parsed into a structured object that
  carries the rubric body plus the per-config judge overrides
  (`options.rubricPrompt`, `options.provider`). Slice 1 NEVER grades one;
  asking for an evaluator raises `RubricNotExecutableError`. Slice 2 (#662)
  adds the judge tier.
* `javascript` (10 in the live matrix) - ported to Python here.

Nothing in this module runs the JavaScript. The `value:` of an assertion is
attacker-shaped input in the general case (a config edit, or a `file://`
target outside the repo), so it is only ever PARSED. Each evaluator derives
its parameters from the JS source, so editing the regex in the YAML changes
the Python gate too, instead of the port silently drifting from the original.

The four ported evaluator kinds:

| kind | JS shape | configs |
|---|---|---|
| `regex-test` | `/<pattern>/<flags>.test(output)` announce-line gate | 3 |
| `security-relevance` | `securityTerms` + `context.vars.security_must_appear` | 3 |
| `cites-catalogue-technique` | `file://asserts/cites-catalogue-technique.js` | 3 |
| `retrospective-restore` | scoped-restore / return-reverse git mechanic | 1 |
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "AssertionResult",
    "CitesCatalogueTechniqueEvaluator",
    "JavascriptAssertion",
    "JS_LINE_TERMINATORS",
    "JS_WHITESPACE",
    "RetrospectiveRestoreEvaluator",
    "RegexTestEvaluator",
    "RubricAssertion",
    "RubricNotExecutableError",
    "SecurityRelevanceEvaluator",
    "UnportableJavascriptPatternError",
    "UnportedJavascriptAssertionError",
    "UnsupportedAssertionTypeError",
    "catalogue_technique_names",
    "evaluator_for",
    "js_pattern_to_python",
    "parse_assertion",
]

REPO_ROOT = Path(__file__).resolve().parents[3]
TECHNIQUES_MD = REPO_ROOT / "knowledge" / "techniques.md"


class UnsupportedAssertionTypeError(ValueError):
    """The config used an assertion type the runner has no model for."""


class UnportedJavascriptAssertionError(ValueError):
    """A `javascript` assert whose JS shape has no Python evaluator yet."""


class RubricNotExecutableError(RuntimeError):
    """`llm-rubric` grading is slice 2 (#662); slice 1 only parses rubrics."""


class UnportableJavascriptPatternError(ValueError):
    """A JS regex whose Python translation would silently change its meaning."""


@dataclass(frozen=True)
class AssertionResult:
    passed: bool
    score: int
    reason: str


@dataclass(frozen=True)
class JavascriptAssertion:
    """A deterministic assert. `source` is the JS text, never executed."""

    source: str
    threshold: float | None = None
    origin: Path | None = None
    config_path: Path | None = None


@dataclass(frozen=True)
class RubricAssertion:
    """A parsed, UNEXECUTED `llm-rubric` assert plus its judge overrides."""

    rubric: str
    rubric_prompt: str | None = None
    judge_provider: Any | None = None
    threshold: float | None = None
    config_path: Path | None = None


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

_FILE_URL = "file://"


def parse_assertion(
    raw: Mapping[str, Any],
    base_dir: Path,
    *,
    rubric_prompt: str | None = None,
    judge_provider: Any | None = None,
    config_path: Path | None = None,
) -> JavascriptAssertion | RubricAssertion:
    """Turn one raw `assert:` entry into a structured assertion."""
    kind = raw.get("type")
    value = raw.get("value")
    threshold = raw.get("threshold")

    if kind == "llm-rubric":
        return RubricAssertion(
            rubric=str(value),
            rubric_prompt=rubric_prompt,
            judge_provider=judge_provider,
            threshold=threshold,
            config_path=config_path,
        )
    if kind == "javascript":
        origin = None
        source = str(value)
        if source.startswith(_FILE_URL):
            origin = (base_dir / source[len(_FILE_URL) :]).resolve()
            source = origin.read_text(encoding="utf-8")
        return JavascriptAssertion(
            source=source,
            threshold=threshold,
            origin=origin,
            config_path=config_path,
        )
    raise UnsupportedAssertionTypeError(
        f"unsupported assertion type {kind!r} in {config_path or base_dir}; "
        "the runner models only 'llm-rubric' and 'javascript'"
    )


# --------------------------------------------------------------------------
# Shared JS-source parsing helpers
# --------------------------------------------------------------------------

_REASONS = re.compile(r"reason:\s*'((?:[^'\\]|\\.)*)'")

# Every ported pattern compiles with re.ASCII. Python's Unicode defaults are
# NOT JavaScript's for the constructs these patterns use:
#
# * `re.IGNORECASE` folds `\u017f` (long s) onto `s` and `\u212a` (Kelvin sign)
#   onto `k`; JavaScript's `/i` refuses any mapping of a non-ASCII code unit
#   onto an ASCII one, so `/security/i` does NOT match `\u017fecurity`.
# * `\b` and `\w` are Unicode-aware in Python and ASCII-only in JavaScript,
#   so `/\bxss\b/` matches inside `\u00e9xss\u00e9` in JS but not in Python.
#
# Every pattern in the matrix and every heading in knowledge/techniques.md is
# ASCII, so ASCII-only folding is exactly JavaScript's folding for them - and
# `_js_flags` REFUSES `/i` on a non-ASCII pattern rather than let that
# argument be stretched past where it holds.
#
# `\s`/`\S` go the OTHER way: re.ASCII narrows them below JavaScript's set,
# and the live retrospective gate is full of them
# (`git\s+show\s+\S+:\S+\s*>\s*\S+` and friends), so an answer containing a
# non-breaking space would pass in JavaScript and fail here. Rather than
# choose between the three axes, every lifted pattern has its `\s`/`\S`
# SUBSTITUTED for an explicit JavaScript-whitespace class before it is
# compiled: re.ASCII then stops mattering for whitespace, and still gives
# JavaScript's semantics for `\b`, `\w` and case folding.
#
# `\s` was not the only construct Python spells differently, only the one a
# live pattern used. `.`, `$`, `[]` and `[^]` all compile in Python and match
# a DIFFERENT set - no error, just a quiet disagreement with promptfoo - so
# `js_pattern_to_python` substitutes them too, and `_js_flags` refuses every
# flag whose translation has not been proved. The whole guard holds to one
# rule: a lifted pattern is either translated into genuinely equivalent
# Python, or refused loudly. Nothing compiles into a near-miss.
_JS_ASCII = re.ASCII

# JavaScript's `\s`: WhiteSpace + LineTerminator (ECMA-262 11.2/11.3). Note
# that this is exactly the set `String.prototype.trim` strips, which is why
# `loader.py` imports it for its trim too.
JS_WHITESPACE = (
    "\t\n\v\f\r \u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005"
    "\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)

# JavaScript's LineTerminator set (ECMA-262 11.3). `.` matches any code point
# EXCEPT these; Python's `.` excludes only `\n`, so a lifted `.` is a silent
# divergence on `\r`, U+2028 and U+2029 unless it is substituted too.
JS_LINE_TERMINATORS = "\n\r\u2028\u2029"


def _class_body(members: str) -> str:
    """Spell `members` as numeric escapes for splicing into a character class.

    Numeric escapes keep the body unambiguous no matter what surrounds it: no
    literal `-`, `]` or `^` can fuse with a neighbouring member of the class
    it is spliced into.
    """
    return "".join(f"\\x{ord(c):02x}" if ord(c) < 0x100 else f"\\u{ord(c):04x}" for c in members)


_JS_WS_BODY = _class_body(JS_WHITESPACE)
_JS_LT_BODY = _class_body(JS_LINE_TERMINATORS)

# JavaScript's `[]` matches nothing and its `[^]` matches anything. Python
# spells neither the same way (it reads the `]` as a literal member), but it
# CAN express both: a failing lookahead, and a dot with `s` scoped to it.
_JS_EMPTY_CLASS = "(?:(?!))"
_JS_ANY_CLASS = "(?s:.)"


def js_pattern_to_python(pattern: str, *, dot_all: bool = False) -> str:
    """Rewrite a lifted JS regex into Python that matches the SAME set.

    Walks the source rather than running a regex over it, so it can tell an
    escape from a literal (`\\\\s` is a backslash followed by `s` and must be
    left alone) and a class member from an operator.

    Five constructs are substituted, each because Python spells the same
    JavaScript meaning differently:

    * `\\s`/`\\S` - `re.ASCII` narrows them below JavaScript's whitespace set,
      so they expand to an explicit class. Inside a character class (the
      announce-line prefix `[\\s>*_"']`) `\\s` expands to the class BODY, not
      to a nested `[...]`.
    * `.` - JavaScript's excludes `\\n`, `\\r`, U+2028 and U+2029; Python's
      excludes only `\\n`. Under `dot_all` (JS `/s`) both match everything, so
      it becomes an explicitly dot-all group instead.
    * `[]` and `[^]` - JavaScript's empty and match-anything classes. Python
      reads the `]` as a literal member and silently builds a DIFFERENT set,
      so both are replaced outright.
    * `$` - JavaScript's matches only at end of input; Python's also matches
      before a trailing `\\n`, so it becomes `\\Z`. (`^` needs no such
      treatment: without `re.MULTILINE` Python's `^` is already exactly
      JavaScript's, and JS `/m` is refused rather than mapped.)

    `\\S` inside a character class has no Python translation - it would need
    set subtraction - so it raises rather than compiling to something whose
    verdict silently differs from JavaScript's. No live pattern uses it.
    """
    out: list[str] = []
    index = 0
    length = len(pattern)
    in_class = False
    while index < length:
        char = pattern[index]
        if char == "\\" and index + 1 < length:
            following = pattern[index + 1]
            if following == "s":
                out.append(_JS_WS_BODY if in_class else f"[{_JS_WS_BODY}]")
            elif following == "S":
                if in_class:
                    raise UnportableJavascriptPatternError(
                        r"\S inside a character class has no Python equivalent "
                        f"(in {pattern!r}); rewrite the pattern in the config"
                    )
                out.append(f"[^{_JS_WS_BODY}]")
            else:
                out.append(char + following)
            index += 2
            continue
        if not in_class:
            # `[]` and `[^]` close immediately in JavaScript - unlike POSIX,
            # where that `]` would be a literal member - so they are whole
            # constructs here, not the start of a class.
            if pattern.startswith("[]", index):
                out.append(_JS_EMPTY_CLASS)
                index += 2
                continue
            if pattern.startswith("[^]", index):
                out.append(_JS_ANY_CLASS)
                index += 3
                continue
            if char == ".":
                out.append(_JS_ANY_CLASS if dot_all else f"[^{_JS_LT_BODY}]")
                index += 1
                continue
            if char == "$":
                out.append("\\Z")
                index += 1
                continue
            if char == "[":
                in_class = True
                out.append(char)
                index += 1
                # A leading `^` negates; it does not close.
                if index < length and pattern[index] == "^":
                    out.append("^")
                    index += 1
                continue
        elif char == "]":
            in_class = False
        out.append(char)
        index += 1
    return "".join(out)


# JavaScript regex flags this module can translate into genuinely equivalent
# Python. Everything else is REFUSED rather than dropped or approximated:
#
# * `m` - a real divergence, not a gap. JS anchors `^`/`$` at `\r`, U+2028 and
#   U+2029; `re.MULTILINE` anchors only at `\n`, so `/^b/m.test("a\rb")` is
#   true in Node and false here. Mapping it silently is worse than refusing.
# * `g` - load-bearing state: `.test` advances `lastIndex`, so consecutive
#   calls on one literal answer differently. `re` has no equivalent.
# * `y` - sticky. `/x/y.test("ax")` is false in Node; `re.search` says true.
# * `u`, `v` - change escape and class grammar wholesale (`\u{...}`,
#   `\p{...}`, set notation) and re-define case folding.
# * `d` - only adds match indices, but `.test` never reads them, so honouring
#   it would mean asserting a no-op nobody has proved.
#
# `s` is not in the map because it is handled by the pattern walker (it picks
# which translation `.` gets), not by a Python flag.
_JS_FLAG_MAP = {"i": re.IGNORECASE}
_JS_WALKER_FLAGS = "s"

# A code point can reach a pattern as a literal OR as a `\uXXXX`/`\xXX`
# escape, and `/i` folds it either way. `"\\u00e9".isascii()` is True, so the
# escapes have to be decoded before the ASCII argument below can be trusted:
# Node says `/é/i.test("É")` is true, and `re.ASCII` cannot fold it.
_JS_CODEPOINT_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})")


def _folds_only_ascii(pattern: str) -> bool:
    """Can `/i` on this pattern fold anything outside ASCII?

    Conservative: an escaped backslash followed by `uXXXX` is read as an
    escape it is not, which costs a needless refusal and never a wrong match.
    """
    if not pattern.isascii():
        return False
    return all(
        int(found.group(1) or found.group(2), 16) < 0x80
        for found in _JS_CODEPOINT_ESCAPE.finditer(pattern)
    )


def _site(where: object) -> str:
    """` (<config path>)` for an error message, or nothing if unknown."""
    return "" if where is None else f" ({where})"


def _js_flags(pattern: str, flags: str, where: object = None) -> int:
    """Translate JavaScript regex flags, or refuse them loudly.

    Shared by every lifted pattern - the announce-line `regex-test` literals
    and the `securityTerms` body alike - so the two paths cannot drift into
    disagreeing about which flags are safe.
    """
    site = _site(where)
    if len(set(flags)) != len(flags):
        raise UnportableJavascriptPatternError(
            f"lifted JS regex /{pattern}/{flags} repeats a flag{site}; "
            "JavaScript rejects that at parse time, so the assert would throw "
            "rather than produce a verdict"
        )
    unportable = sorted(set(flags) - set(_JS_FLAG_MAP) - set(_JS_WALKER_FLAGS))
    if unportable:
        raise UnportableJavascriptPatternError(
            f"lifted JS regex /{pattern}/{flags} carries flag(s) "
            f"{''.join(unportable)!r} with no proven Python equivalent{site}; "
            "the port would silently drop them and stop agreeing with "
            "promptfoo. Port the flag before adding it to the matrix"
        )
    compiled = _JS_ASCII
    for flag in flags:
        if flag == "i" and not _folds_only_ascii(pattern):
            # `re.ASCII | re.IGNORECASE` folds only ASCII, which is exactly
            # JavaScript's `/i` for an ASCII pattern (JS refuses any mapping
            # of a non-ASCII code unit onto an ASCII one, so `/security/i`
            # does NOT match `ſecurity`). Once a non-ASCII code point is in
            # the pattern the two part company - `/é/i` matches `É` in Node
            # and nothing here - so that combination is refused instead.
            raise UnportableJavascriptPatternError(
                f"lifted JS regex /{pattern}/{flags} applies /i to a "
                f"non-ASCII pattern{site}; Python folds case for it only with "
                "Unicode rules, which are not JavaScript's. Spell the case "
                "variants out in the pattern instead"
            )
        compiled |= _JS_FLAG_MAP.get(flag, 0)
    return compiled


def _js_compile(pattern: str, flags: str = "", where: object = None) -> re.Pattern[str]:
    """Compile a pattern LIFTED FROM JAVASCRIPT with JavaScript's semantics.

    Either the result matches exactly what `new RegExp(pattern, flags)` does,
    or this raises. Nothing compiles into a near-miss.
    """
    python_flags = _js_flags(pattern, flags, where)
    translated = js_pattern_to_python(pattern, dot_all="s" in flags)
    try:
        return re.compile(translated, python_flags)
    except re.error as exc:
        # Valid JavaScript that Python's grammar rejects: class ranges JS
        # allows and `re` does not, `\Q`-style identity escapes, and so on.
        # It already fails loudly; this only gives it the guard's own name.
        raise UnportableJavascriptPatternError(
            f"lifted JS regex /{pattern}/{flags} has no Python equivalent{_site(where)}: {exc}"
        ) from exc


def _reasons(source: str) -> list[str]:
    """Every `reason: '...'` literal in the JS, in source order.

    Reusing the original strings keeps the Python gate's explanations
    identical to promptfoo's, so a parity diff in slice 3 compares verdicts
    rather than wording.
    """
    return [m.group(1) for m in _REASONS.finditer(source)]


# --------------------------------------------------------------------------
# Evaluators
# --------------------------------------------------------------------------


@dataclass
class RegexTestEvaluator:
    """Port of `/<pattern>/<flags>.test(output)`.

    Used by the three announce-line gates. The pattern is lifted verbatim
    from the YAML, so the anchor (`^[\\s>*_"']{0,8}`) and the phrase stay in
    one place: the config.
    """

    pattern: str
    flags: str = ""
    where: object = None
    kind: str = field(default="regex-test", init=False)
    _matcher: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Compile at CONSTRUCTION so an unportable pattern or flag is refused
        # when the matrix is loaded, not when some later output happens to be
        # graded against it.
        self._matcher = _js_compile(self.pattern, self.flags, self.where)

    def evaluate(self, output: str, context_vars: Mapping[str, Any]) -> AssertionResult:
        del context_vars
        if self._matcher.search(output or ""):
            return AssertionResult(True, 1, f"matches /{self.pattern}/{self.flags}")
        return AssertionResult(False, 0, f"does not match /{self.pattern}/{self.flags}")


@dataclass
class SecurityRelevanceEvaluator:
    """Port of the three security-axis gates.

    Inclusion seeds (`security_must_appear: true`) must raise a grounded
    security concern; the omission direction is deliberately delegated to the
    rubric's fabricated-security anti-pattern, because a candidate correctly
    DECLINING security legitimately uses the word "security".
    """

    terms: str
    reasons: tuple[str, ...]
    flags: str = ""
    where: object = None
    kind: str = field(default="security-relevance", init=False)
    _matcher: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Same construction-time refusal, through the same helper, as
        # `RegexTestEvaluator`. The two paths used to check flags separately;
        # one of them forgot to.
        self._matcher = _js_compile(self.terms, self.flags, self.where)

    def evaluate(self, output: str, context_vars: Mapping[str, Any]) -> AssertionResult:
        lowered = str(output or "").lower()
        mentions = self._matcher.search(lowered) is not None
        if context_vars.get("security_must_appear") is True:
            if mentions:
                return AssertionResult(True, 1, self.reasons[0])
            return AssertionResult(False, 0, self.reasons[1])
        return AssertionResult(True, 1, self.reasons[2])


@dataclass
class RetrospectiveRestoreEvaluator:
    """Port of the retrospective restore/reverse mechanic gate.

    The regexes mirror the inline JS one for one: a scoped reversible restore
    must be present, no destructive command may appear, and the response must
    return to the current tree before the final verification.
    """

    reasons: tuple[str, ...]
    kind: str = field(default="retrospective-restore", init=False)

    _SCOPED_RESTORE = (
        _js_compile(r"git\s+show\s+\S+:\S+\s*>\s*\S+"),
        _js_compile(r"git\s+checkout\s+\S+\s+--\s+\S+"),
    )
    _SCOPED_PATHSPEC = _js_compile(r"git\s+checkout\s+[^\n]*?\s--\s+\S+")
    _DESTRUCTIVE = (
        _js_compile(r"git\s+reset\s+--hard"),
        _js_compile(r"git\s+clean\b"),
    )
    _BARE_CHECKOUT = _js_compile(r"git\s+checkout\s+(?!--\s|HEAD\s+--)[^\n]*")
    _RETURN_REVERSE = (
        _js_compile(r"git\s+checkout\s+--\s+\S+"),
        _js_compile(r"git\s+checkout\s+HEAD\s+--\s+\S+"),
        _js_compile(r"git\s+restore\b"),
    )

    def evaluate(self, output: str, context_vars: Mapping[str, Any]) -> AssertionResult:
        del context_vars
        text = str(output or "")
        has_scoped_restore = any(p.search(text) for p in self._SCOPED_RESTORE)
        stripped = self._SCOPED_PATHSPEC.sub("", text)
        has_destructive = any(p.search(text) for p in self._DESTRUCTIVE) or bool(
            self._BARE_CHECKOUT.search(stripped)
        )
        has_return_reverse = any(p.search(text) for p in self._RETURN_REVERSE)

        if not has_scoped_restore:
            return AssertionResult(False, 0, self.reasons[0])
        if has_destructive:
            return AssertionResult(False, 0, self.reasons[1])
        if not has_return_reverse:
            return AssertionResult(False, 0, self.reasons[2])
        return AssertionResult(True, 1, self.reasons[3])


def catalogue_technique_names(markdown: str) -> list[str]:
    """The catalogue's level-3 (`###`) ATX headings, skipping fenced blocks.

    Level-2 headings are CATEGORIES, not techniques, so they are excluded.
    A closing fence must use the same character, be at least as long as the
    opening run, and carry no info string (CommonMark), so a nested shorter
    fence does not end the block. This mirrors both the JS original and the
    catalogue indexer in `src/sumo_qa/knowledge_loaders.py`.
    """
    names: list[str] = []
    fence: tuple[str, int] | None = None
    open_fence = re.compile(r"^ {0,3}(`{3,}|~{3,})")
    close_fence = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
    heading = re.compile(r"^###\s+(.*\S)\s*$")
    for line in re.split(r"\r?\n", markdown):
        if fence is None:
            opened = open_fence.match(line)
            if opened:
                fence = (opened.group(1)[0], len(opened.group(1)))
                continue
            found = heading.match(line)
            if found:
                names.append(found.group(1).strip())
        else:
            closed = close_fence.match(line)
            if (
                closed
                and closed.group(1)[0] == fence[0]
                and len(closed.group(1)) >= fence[1]
                and closed.group(2).strip() == ""
            ):
                fence = None
    return names


@dataclass
class CitesCatalogueTechniqueEvaluator:
    """Port of `asserts/cites-catalogue-technique.js` (#350).

    The accepted set is DERIVED from `knowledge/techniques.md` headings at
    runtime, never hardcoded: adding a technique to the catalogue widens what
    every eval accepts, with no eval edit. The catalogue is read on first use
    (matching the JS module-level cache) so a test can point the evaluator at
    a fixture catalogue.
    """

    catalogue_path: Path = TECHNIQUES_MD
    kind: str = field(default="cites-catalogue-technique", init=False)
    _compiled: tuple[re.Pattern[str], int] | None = field(default=None, init=False, repr=False)

    def _build(self) -> tuple[re.Pattern[str], int]:
        if self._compiled is None:
            names = catalogue_technique_names(self.catalogue_path.read_text(encoding="utf-8"))
            if not names:
                raise ValueError(
                    f"no technique headings parsed from {self.catalogue_path} "
                    "(catalogue path or format drift)"
                )
            # Longest first so the reported match is the most specific one.
            alternation = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
            self._compiled = (re.compile(alternation, re.IGNORECASE | _JS_ASCII), len(names))
        return self._compiled

    def evaluate(self, output: str, context_vars: Mapping[str, Any]) -> AssertionResult:
        del context_vars
        matcher, count = self._build()
        found = matcher.search("" if output is None else str(output))
        if found:
            return AssertionResult(True, 1, f'cites catalogue technique "{found.group(0)}"')
        return AssertionResult(
            False,
            0,
            "no catalogue technique cited; expected a verbatim heading from "
            f"techniques.md ({count} techniques)",
        )


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------

_REGEX_TEST = re.compile(
    r"^\s*/(?P<pattern>.*)/(?P<flags>[a-z]*)\.test\(\s*output\s*\)\s*;?\s*$",
    re.DOTALL,
)
_SECURITY_TERMS = re.compile(r"securityTerms\s*=\s*/(?P<terms>.+)/(?P<flags>[a-z]*)\s*;")


def evaluator_for(assertion: JavascriptAssertion | RubricAssertion):
    """Return the Python evaluator for a deterministic assertion.

    Raises for `llm-rubric` (slice 2 grades those) and for any JS shape the
    port does not yet cover, so a new inline assert cannot slip into the
    matrix ungated.
    """
    if isinstance(assertion, RubricAssertion):
        raise RubricNotExecutableError(
            "llm-rubric assertions are parsed but never graded in this slice; "
            "the Claude judge tier arrives in #662"
        )

    source = assertion.source
    if assertion.origin is not None and (assertion.origin.name == "cites-catalogue-technique.js"):
        return CitesCatalogueTechniqueEvaluator()

    where = assertion.config_path or assertion.origin

    match = _REGEX_TEST.match(source)
    if match:
        return RegexTestEvaluator(match.group("pattern"), match.group("flags"), where)

    if "security_must_appear" in source:
        terms = _SECURITY_TERMS.search(source)
        reasons = _reasons(source)
        if terms and len(reasons) >= 3:
            # Both lifted-regex evaluators take their flags straight from the
            # JS literal and hand them to the SAME guard, which translates the
            # flags it has proved equivalent and refuses the rest. Neither
            # path may drop a flag on the floor.
            return SecurityRelevanceEvaluator(
                terms.group("terms"), tuple(reasons), terms.group("flags"), where
            )

    if "hasScopedRestore" in source:
        reasons = _reasons(source)
        if len(reasons) >= 4:
            return RetrospectiveRestoreEvaluator(tuple(reasons))

    raise UnportedJavascriptAssertionError(
        "no Python evaluator for this javascript assert "
        f"({assertion.config_path or assertion.origin}); port it before "
        "adding it to the matrix"
    )
