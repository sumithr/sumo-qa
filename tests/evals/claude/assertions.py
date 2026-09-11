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
target outside the repo), so it is only ever PARSED.

The four ported evaluator kinds:

| kind | JS shape | configs | parameters |
|---|---|---|---|
| `regex-test` | `/<pattern>/<flags>.test(output)` announce-line gate | 3 | lifted |
| `security-relevance` | `securityTerms` + `context.vars.security_must_appear` | 3 | lifted |
| `cites-catalogue-technique` | `file://asserts/cites-catalogue-technique.js` | 3 | from catalogue |
| `retrospective-restore` | scoped-restore / return-reverse git mechanic | 1 | HAND-TRANSCRIBED |

Three of the four DERIVE their parameters: the two lifted-regex kinds read the
regex literal straight out of the config text, so editing the regex in the
YAML changes the Python gate too; `cites-catalogue-technique` reads the
catalogue at runtime. `retrospective-restore` does NOT - see the note on
`RetrospectiveRestoreEvaluator`.

## What the regex port does and does not claim

This module ports THE SPECIFIC PATTERNS THE SUMO-QA EVAL MATRIX USES. It is
not a general JavaScript-to-Python regex translator, and it does not claim
that an arbitrary lifted pattern will match the same set in both engines.

It cannot make that claim: honouring it would mean implementing a large part
of the ECMAScript regex grammar, which the runner has never needed. So the
port is CLOSED BY DEFAULT. The allowlist below is derived from the constructs
the 15 live regex instances actually use; every construct outside it is
refused with a loud, actionable error rather than approximated. A future
assert that needs one gets a refusal telling its author to extend the port -
which is the correct outcome, because extending the port is the only way to
know the two engines agree.

The refusal is the guarantee. Within the allowlist, each construct is
translated into Python that matches the same set - pinned offline by the
suite from both sides (every admitted construct on an output it must accept
and one it must reject; every refused construct on its error), and checked
against real Node by a differential harness that is deliberately NOT
committed, because this package must stay offline and Node-free. That harness
is a development tool whose result is not reproducible from this repo; what
survives it is the unit tests its findings became.
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
    """`llm-rubric` is graded by the judge tier, never by an evaluator here.

    This module only ever PARSES a rubric. Grading one means a model call,
    which lives in `claude/judge.py` and `claude/runner.py`; asking for an
    evaluator is a category error and says so rather than returning something
    that would quietly always pass.
    """


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
# ASCII-only folding is therefore exactly JavaScript's folding - but only for
# an ASCII pattern, which is one of the reasons the walker below admits no
# non-ASCII character at all.
#
# `\s`/`\S` go the OTHER way: re.ASCII narrows them below JavaScript's set,
# and the live retrospective gate is full of them
# (`git\s+show\s+\S+:\S+\s*>\s*\S+` and friends), so an answer containing a
# non-breaking space would pass in JavaScript and fail here. Rather than
# choose between the three axes, every lifted pattern has its `\s`/`\S`
# SUBSTITUTED for an explicit JavaScript-whitespace class before it is
# compiled: re.ASCII then stops mattering for whitespace, and still gives
# JavaScript's semantics for `\b`, `\w` and case folding.
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


def _class_body(members: str) -> str:
    """Spell `members` as numeric escapes for splicing into a character class.

    Numeric escapes keep the body unambiguous no matter what surrounds it: no
    literal `-`, `]` or `^` can fuse with a neighbouring member of the class
    it is spliced into.
    """
    return "".join(f"\\x{ord(c):02x}" if ord(c) < 0x100 else f"\\u{ord(c):04x}" for c in members)


_JS_WS_BODY = _class_body(JS_WHITESPACE)


def _site(where: object) -> str:
    """` (<config path>)` for an error message, or nothing if unknown."""
    return "" if where is None else f" ({where})"


def _refusal(
    pattern: str, construct: str, why: str, where: object
) -> UnportableJavascriptPatternError:
    """The one refusal every unsupported construct comes back through."""
    return UnportableJavascriptPatternError(
        f"lifted JS regex /{pattern}/ uses {construct}{_site(where)}, which "
        f"this port does not support: {why}. This module ports only the regex "
        "constructs the live sumo-qa eval matrix uses - extend the port (and "
        "its Node differential) before putting this construct in a config"
    )


# --------------------------------------------------------------------------
# The allowlist
# --------------------------------------------------------------------------
#
# The guard is CLOSED BY DEFAULT. It admits exactly the constructs the live
# matrix uses and refuses everything else, because the alternative - trusting
# any construct nobody has thought to check - is a claim about the whole
# ECMAScript regex grammar that this runner has never needed and cannot
# honour. Every entry below is DERIVED from the 15 regex instances the 10 live
# `javascript` asserts compile (3 announce-line literals, 3 `securityTerms`
# bodies, 9 retrospective-gate literals), not chosen:
#
# | construct | a live instance |
# |---|---|
# | printable-ASCII literal | `git`, `HEAD`, `--`, `:`, `>`, `idor` |
# | `^` (start anchor) | `^[\s>*_"']{0,8}closing one qa gap at a time` |
# | `|` (alternation) | `(security|securit|vulnerab|...)` |
# | `(`...`)` (capturing group) | the `securityTerms` body |
# | `(?!`...`)` (negative lookahead) | `git\s+checkout\s+(?!--\s|HEAD\s+--)...` |
# | quantifier, greedy or lazy | `\s+`, `[^\n]*?`, `{0,8}` |
# | `\s`, `\S` | `git\s+show\s+\S+:\S+\s*>\s*\S+` |
# | `\b` | `\bxss\b`, `git\s+clean\b` |
# | `\n` (inside a class) | `[^\n]` |
# | `[`...`]`, `[^`...`]` of literals / `\s` / `\n` | `[\s>*_"']`, `[^\n]` |
# | flag `i`, or no flags | the announce literals; everything else |
#
# Quantifiers are admitted as ONE construct (the ECMA-262 `Quantifier`
# production: `*`, `+`, `?`, `{m}`, `{m,}`, `{m,n}`, each optionally lazy)
# because the two grammars define the whole production identically - it is
# parameterised by a repeat bound, not by a meaning. ONE is load-bearing: the
# production allows exactly one quantifier per atom, so a SECOND stacked on
# the first is refused (`a++` is a SyntaxError in Node and a possessive
# quantifier in Python), while a lazy `?` after a quantifier stays admitted.
#
# Escapes and flags are admitted INDIVIDUALLY, because each one carries its
# own semantics and its own chance of disagreeing.
#
# Everything absent from that table is refused, including several constructs
# that do compile in Python: `.`, `$`, `[]`, `[^]`, `\d`, `\w`, `\uXXXX`,
# `\xXX`, legacy octal escapes, `(?:`, lookbehind, backreferences, class
# ranges, and any non-ASCII character. Some of those would match a different
# set than Node; the rest are simply unproven. The guard does not distinguish,
# which is the point: it cannot be wrong about a construct it never accepts.

# The metacharacters the walker handles by name. Whatever is left over when
# the walk reaches its final branch (`$`, `.`, a bare `]` or `}`) is refused.
_JS_METACHARACTERS = frozenset("\\^$.|?*+()[]{}")

# `{m}` / `{m,}` / `{m,n}`. Spelled out rather than trusted to `re`, so a `{`
# that is not a bounded quantifier (a literal brace in JavaScript, but not
# always in Python) is refused instead of guessed at.
_BOUNDED_QUANTIFIER = re.compile(r"\{\d+(?:,\d*)?\}")

_ESCAPE_REASON = (
    r"only \s, \S, \b and \n are ported. The rest either disagree "
    r"(\d and \w are Unicode-aware in Python and ASCII-only in JavaScript), "
    r"mean different things (\1 is a backreference in both but \351 is a "
    r"legacy octal escape in JavaScript and a backreference-or-octal in "
    r"Python), or exist only in Python (\N{...}, \U........), or reintroduce "
    r"a non-ASCII code point (\uXXXX, \xXX)"
)

_STACKED_QUANTIFIER_REASON = (
    "ECMA-262's `Quantifier` production admits exactly ONE quantifier per "
    "atom, optionally suffixed by a lazy `?`, so Node rejects `a++`, `a*+`, "
    "`a?+` and `a{1,2}+` outright as `SyntaxError: Nothing to repeat`. "
    "Python reads the very same text as a POSSESSIVE quantifier and compiles "
    "it happily - a silent change of meaning, which is the one outcome this "
    "guard exists to prevent. Only a lazy `?` may follow a quantifier"
)

_CLASS_ESCAPE_REASON = (
    r"only \s and \n are ported inside a character class; every other escape "
    "is either unproven there or means something different from what it "
    "means outside one"
)

_NON_LITERAL_REASON = (
    "only printable ASCII literals are supported. JavaScript matches a "
    "pattern against UTF-16 code units and Python against code points, so an "
    "astral character is two units in Node and one here (`/^.$/` is false in "
    "Node and true in Python for an emoji); and Python's `/i` would fold a "
    "non-ASCII letter with Unicode rules JavaScript's `/i` does not use"
)

_METACHARACTER_REASONS = {
    ".": (
        "JavaScript's `.` excludes `\\n`, `\\r`, U+2028 and U+2029 where "
        "Python's excludes only `\\n`, and the two engines disagree about "
        "what one `.` consumes in an astral character"
    ),
    "$": (
        "JavaScript's `$` matches only at end of input; Python's also matches "
        'just before a trailing newline, so `/a$/.test("a\\n")` is false in '
        "Node and true here"
    ),
    "]": "a `]` outside a character class is an unproven literal",
    "}": "a `}` outside a bounded quantifier is an unproven literal",
}

_CLASS_OPERATOR_REASONS = {
    "-": (
        "a class RANGE. JavaScript and Python do not accept the same ranges, "
        "and no live pattern uses one"
    ),
    "[": "a nested `[` inside a character class",
    "^": "a `^` that is not the class's leading negation",
}


def _translate_class(pattern: str, start: int, out: list[str], where: object) -> int:
    """Translate the `[...]` starting at `start`; return the index after it.

    In JavaScript `[]` is the EMPTY class and `[^]` the match-anything class:
    a `]` straight after the `[` CLOSES the class rather than joining it as a
    literal member, which is what Python's own parser would do. Both are
    refused here, so the boundary is still read JavaScript's way and neither
    can be silently reinterpreted as a one-member class.
    """
    cursor = start + 1
    body = ["["]
    if pattern[cursor : cursor + 1] == "^":
        body.append("^")
        cursor += 1
    members = 0
    while cursor < len(pattern):
        char = pattern[cursor]
        if char == "]":
            if members == 0:
                raise _refusal(
                    pattern,
                    "an empty character class",
                    "JavaScript's `[]` matches nothing and its `[^]` matches "
                    "anything; Python reads the `]` as a literal member and "
                    "builds a different set entirely",
                    where,
                )
            body.append("]")
            out.append("".join(body))
            return cursor + 1
        if char == "\\":
            following = pattern[cursor + 1 : cursor + 2]
            if following == "s":
                # The BODY, not a nested `[...]`: the announce-line prefix is
                # `[\s>*_"']`, and splicing a nested class in would make `[`
                # and `]` literal members and change what it accepts.
                body.append(_JS_WS_BODY)
            elif following == "n":
                body.append("\\n")
            elif following == "S":
                raise _refusal(
                    pattern,
                    r"\S inside a character class",
                    "Python has no set subtraction inside a class, so there "
                    "is nothing to translate it to",
                    where,
                )
            else:
                raise _refusal(
                    pattern,
                    f"the escape \\{following} inside a character class",
                    _CLASS_ESCAPE_REASON,
                    where,
                )
            cursor += 2
            members += 1
            continue
        if char in _CLASS_OPERATOR_REASONS:
            raise _refusal(
                pattern, f"`{char}` inside a character class", _CLASS_OPERATOR_REASONS[char], where
            )
        if not (char.isascii() and char.isprintable()):
            raise _refusal(
                pattern,
                f"the character {char!r} inside a character class",
                _NON_LITERAL_REASON,
                where,
            )
        body.append(char)
        members += 1
        cursor += 1
    raise _refusal(pattern, "an unterminated character class", "the `[` is never closed", where)


def js_pattern_to_python(pattern: str, *, where: object = None) -> str:
    """Translate a lifted JS regex into equivalent Python, or REFUSE it.

    Closed by default. The walk recognises exactly the constructs in the
    allowlist table above and raises `UnportableJavascriptPatternError` on
    anything else, so a construct nobody has checked against Node can never
    reach `re.compile`. Two of the admitted constructs need rewriting rather
    than copying:

    * `\\s`/`\\S` - `re.ASCII` narrows them below JavaScript's whitespace set,
      so they expand to an explicit class (to the class BODY when they are
      already inside one).
    * `{m,n}` - copied verbatim, but only once it has been confirmed to BE a
      bounded quantifier rather than a stray brace.

    It walks the source rather than running a regex over it, so it can tell an
    escape from a literal and a class member from an operator - a distinction
    a `str.replace` cannot make.
    """
    out: list[str] = []
    index = 0
    length = len(pattern)
    # What the token just emitted was: None, a greedy quantifier (`*`, `+`,
    # `?`, `{m,n}`) or one already made lazy by a trailing `?`. A quantifier
    # may only ever follow a non-quantifier - except the lazy `?`, which may
    # only ever follow a greedy one.
    quantified: str | None = None
    while index < length:
        char = pattern[index]
        if char == "\\":
            following = pattern[index + 1 : index + 2]
            if following == "s":
                out.append(f"[{_JS_WS_BODY}]")
            elif following == "S":
                out.append(f"[^{_JS_WS_BODY}]")
            elif following in ("b", "n"):
                out.append("\\" + following)
            else:
                raise _refusal(pattern, f"the escape \\{following}", _ESCAPE_REASON, where)
            index += 2
            quantified = None
            continue
        if char == "[":
            index = _translate_class(pattern, index, out, where)
            quantified = None
            continue
        if char == "(":
            if pattern.startswith("(?", index) and not pattern.startswith("(?!", index):
                raise _refusal(
                    pattern,
                    f"the group prefix `{pattern[index : index + 3]}`",
                    "only a plain `(` and a negative lookahead `(?!` are "
                    "ported; lookbehind, named groups and `(?:` are not",
                    where,
                )
            width = 3 if pattern.startswith("(?!", index) else 1
            out.append(pattern[index : index + width])
            index += width
            quantified = None
            continue
        if char == "{":
            found = _BOUNDED_QUANTIFIER.match(pattern, index)
            if found is None:
                raise _refusal(
                    pattern,
                    "a `{` that is not a bounded quantifier",
                    "JavaScript reads a stray `{` as a literal brace and "
                    "Python does not always agree",
                    where,
                )
            if quantified is not None:
                raise _refusal(
                    pattern,
                    f"the quantifier `{found.group(0)}` stacked on another quantifier",
                    _STACKED_QUANTIFIER_REASON,
                    where,
                )
            out.append(found.group(0))
            index = found.end()
            quantified = "greedy"
            continue
        if char in "^|)*+?":
            # `^` needs no translation: without `re.MULTILINE` Python's `^` is
            # already exactly JavaScript's, and `/m` is refused rather than
            # mapped. `*`, `+` and `?` are the greedy/lazy quantifier suffixes.
            if char == "?" and quantified == "greedy":
                # The one legitimate way a quantifier follows a quantifier:
                # `*?`, `+?`, `??`, `{m,n}?` are lazy in both engines, and
                # `[^\n]*?` is live in the matrix.
                quantified = "lazy"
            elif char in "*+?":
                if quantified is not None:
                    raise _refusal(
                        pattern,
                        f"the quantifier `{char}` stacked on another quantifier",
                        _STACKED_QUANTIFIER_REASON,
                        where,
                    )
                quantified = "greedy"
            else:
                quantified = None
            out.append(char)
            index += 1
            continue
        if char in _JS_METACHARACTERS:
            raise _refusal(pattern, f"`{char}`", _METACHARACTER_REASONS[char], where)
        if not (char.isascii() and char.isprintable()):
            raise _refusal(pattern, f"the character {char!r}", _NON_LITERAL_REASON, where)
        out.append(char)
        index += 1
        quantified = None
    return "".join(out)


# The one JavaScript regex flag this module translates. The live matrix uses
# `i` (the three announce-line literals) and nothing else, so the flag
# allowlist is derived exactly as the construct allowlist is. Every other
# flag - `s` included - is REFUSED rather than dropped or approximated:
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
# * `s` - dotAll, and `.` itself is not on the construct allowlist, so `/s`
#   can only ever qualify a construct that is already refused.
#
# `i` is safe precisely BECAUSE the walker admits no non-ASCII character:
# `re.ASCII | re.IGNORECASE` folds only ASCII, which is exactly JavaScript's
# `/i` for an ASCII pattern (JS refuses any mapping of a non-ASCII code unit
# onto an ASCII one, so `/security/i` does not match `ſecurity`). `/é/i`
# matches `É` in Node and would match nothing here - and never reaches this
# function, because `é` is refused as a literal.
_JS_FLAG_MAP = {"i": re.IGNORECASE}


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
    unportable = sorted(set(flags) - set(_JS_FLAG_MAP))
    if unportable:
        raise UnportableJavascriptPatternError(
            f"lifted JS regex /{pattern}/{flags} carries flag(s) "
            f"{''.join(unportable)!r} with no proven Python equivalent{site}; "
            "the port would silently drop them and stop agreeing with "
            "promptfoo. Port the flag before adding it to the matrix"
        )
    compiled = _JS_ASCII
    for flag in flags:
        compiled |= _JS_FLAG_MAP[flag]
    return compiled


def _js_compile(pattern: str, flags: str = "", where: object = None) -> re.Pattern[str]:
    """Compile a pattern LIFTED FROM JAVASCRIPT with JavaScript's semantics.

    Every construct in the pattern is on the allowlist and this result matches
    what `new RegExp(pattern, flags)` does, or this raises. The port makes no
    claim about a construct it has not admitted - it refuses it instead.
    """
    python_flags = _js_flags(pattern, flags, where)
    translated = js_pattern_to_python(pattern, where=where)
    try:
        return re.compile(translated, python_flags)
    except re.error as exc:
        # Allowlisted constructs, assembled into something Python's parser
        # still rejects: an unbalanced group, a quantifier with nothing to
        # quantify. It already fails loudly; this only gives it the guard's
        # own name and names the config.
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

    THE ONE PORT THAT DOES NOT DERIVE ITS PARAMETERS. The nine patterns below
    are TRANSCRIBED BY HAND from the inline JavaScript in
    `skill-implementing-with-tdd-retrospective.yaml`; dispatch selects them on
    the mere PRESENCE of `hasScopedRestore` in the source and never parses
    them out of it, unlike the two lifted-regex kinds. They are equal to
    Node's today (pinned by the offline differential), and the cost of that is
    worth stating rather than glossing: AN EDIT TO THE INLINE JAVASCRIPT WILL
    NOT MOVE THIS GATE, and the two copies can drift apart silently - someone
    tightening the destructive-command list in the YAML would move promptfoo's
    verdict and not this runner's, with nothing failing to say so. (The `/g`
    on the JS `.replace` literal is likewise not read here; `re.sub` replaces
    every occurrence, which is what `/g` means for `replace`.)

    The cheap guard that would close the drift - deliberately NOT built here,
    because re-engineering this port is out of scope - is a test that lifts
    every `/.../` literal out of that config's JS with the same
    `_JS_REGEX_BODY` reader and asserts the set equals these constants.
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

    This is the ONE compiled pattern that does not go through the portability
    guard, and deliberately so: it is not a lifted JavaScript pattern at all
    but Python assembled from `re.escape`, whose identity escapes (`\\-`,
    `\\&`) the guard's allowlist refuses on purpose. Routing it through would
    mean widening the allowlist to admit exactly the constructs that were just
    closed.

    What it borrows from the guard is the one property that matters:
    `IGNORECASE | ASCII` folds case the way JavaScript's `/i` does only while
    every heading is ASCII. That is true of all 21 headings today, but the
    catalogue is an editable markdown file, and a cased non-ASCII heading
    would diverge - Python with these flags fails to match `CAFÉ` against
    `café` where Node's `/i` matches. So the invariant is asserted at build
    time and fails loudly instead of being assumed.
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
            non_ascii = sorted(name for name in names if not name.isascii())
            if non_ascii:
                raise UnportableJavascriptPatternError(
                    f"non-ASCII technique heading(s) {non_ascii} in "
                    f"{self.catalogue_path}; this alternation compiles with "
                    "IGNORECASE|ASCII to match JavaScript's /i, which folds "
                    "ASCII only, so a cased non-ASCII heading would match in "
                    "Node and not here. Keep catalogue headings ASCII, or "
                    "port the case folding before adding one"
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

# JavaScript's regex-literal flag alphabet (ECMA-262 22.2.6). A character
# outside it is a SyntaxError in the literal, not an unported flag, so the
# dispatch below refuses the whole assert rather than handing `_js_flags`
# something JavaScript would never have parsed.
_JS_FLAG_ALPHABET = "dgimsuvy"

# A JavaScript `RegularExpressionBody`: no unescaped `/`, no line terminator.
# The greedy `.*` this used to carry ran through to the LAST slash, so
# `/x/i/.test(output)` - a SyntaxError in JavaScript - was silently
# reinterpreted here as the perfectly valid pattern `x/i` with no flags. A
# malformed literal must refuse, not be reinterpreted, so the body is spelled
# out and the flags are pinned to the real alphabet.
_JS_REGEX_BODY = r"(?:[^/\\\r\n\u2028\u2029]|\\[^\r\n\u2028\u2029])+"

_REGEX_TEST = re.compile(
    rf"^\s*/(?P<pattern>{_JS_REGEX_BODY})/(?P<flags>[{_JS_FLAG_ALPHABET}]*)"
    r"\.test\(\s*output\s*\)\s*;?\s*$"
)
# Deliberately loose: what a `regex-test` assert LOOKS like. Anything that
# matches this but not `_REGEX_TEST` is malformed JavaScript, and says so.
_REGEX_TEST_SHAPE = re.compile(r"^\s*/.*\.test\(\s*output\s*\)\s*;?\s*$")

# Same fix on the other lifted-regex path, so the two cannot drift: the old
# greedy `.+` would have run a `securityTerms` literal through to its last
# slash in exactly the same way.
_SECURITY_TERMS = re.compile(
    rf"securityTerms\s*=\s*/(?P<terms>{_JS_REGEX_BODY})/(?P<flags>[{_JS_FLAG_ALPHABET}]*)\s*;"
)


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

    if _REGEX_TEST_SHAPE.match(source):
        # It is shaped like a `regex-test` assert but is not a well-formed
        # JavaScript regex literal - `/x/i/.test(output)` is a SyntaxError in
        # JavaScript. Refusing beats reinterpreting: promptfoo would never
        # have produced a verdict for it at all.
        raise UnportableJavascriptPatternError(
            f"assert {source.strip()!r} is not a well-formed JavaScript regex "
            f"literal{_site(where)}; JavaScript would reject it at parse time. "
            "The body may not contain an unescaped `/` or a line terminator, "
            f"and the flags must come from {_JS_FLAG_ALPHABET!r}"
        )

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
