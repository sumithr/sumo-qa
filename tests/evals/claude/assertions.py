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
    "RetrospectiveRestoreEvaluator",
    "RegexTestEvaluator",
    "RubricAssertion",
    "RubricNotExecutableError",
    "SecurityRelevanceEvaluator",
    "UnportedJavascriptAssertionError",
    "UnsupportedAssertionTypeError",
    "catalogue_technique_names",
    "evaluator_for",
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

_JS_FLAG_MAP = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}
_REASONS = re.compile(r"reason:\s*'((?:[^'\\]|\\.)*)'")

# Every ported pattern compiles with re.ASCII. Python's Unicode defaults are
# NOT JavaScript's for the three constructs these patterns use:
#
# * `re.IGNORECASE` folds `\u017f` (long s) onto `s` and `\u212a` (Kelvin sign)
#   onto `k`; JavaScript's `/i` refuses any mapping of a non-ASCII code unit
#   onto an ASCII one, so `/security/i` does NOT match `\u017fecurity`.
# * `\b` and `\w` are Unicode-aware in Python and ASCII-only in JavaScript,
#   so `/\bxss\b/` matches inside `\u00e9xss\u00e9` in JS but not in Python.
#
# Every pattern in the matrix and every heading in knowledge/techniques.md is
# ASCII, so ASCII-only folding is exactly JavaScript's folding for them.
#
# KNOWN RESIDUAL: re.ASCII also narrows `\s`/`\S` to ASCII whitespace, where
# JavaScript's `\s` additionally covers U+00A0, U+1680, U+2000-U+200A,
# U+2028, U+2029, U+202F, U+205F, U+3000 and U+FEFF. The only live pattern
# using `\s` is the announce-line prefix class `[\s>*_"']{0,8}`, so the
# divergence needs a candidate to open its answer with an exotic Unicode
# space; rewriting a lifted pattern to paper over it would break the "the
# pattern lives in one place, the config" contract this port is built on.
_JS_ASCII = re.ASCII


def _js_flags(flags: str) -> int:
    compiled = _JS_ASCII
    for flag in flags:
        compiled |= _JS_FLAG_MAP.get(flag, 0)
    return compiled


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
    kind: str = field(default="regex-test", init=False)

    def evaluate(self, output: str, context_vars: Mapping[str, Any]) -> AssertionResult:
        del context_vars
        matcher = re.compile(self.pattern, _js_flags(self.flags))
        if matcher.search(output or ""):
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
    kind: str = field(default="security-relevance", init=False)

    def evaluate(self, output: str, context_vars: Mapping[str, Any]) -> AssertionResult:
        lowered = str(output or "").lower()
        mentions = re.search(self.terms, lowered, _JS_ASCII) is not None
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
        re.compile(r"git\s+show\s+\S+:\S+\s*>\s*\S+", _JS_ASCII),
        re.compile(r"git\s+checkout\s+\S+\s+--\s+\S+", _JS_ASCII),
    )
    _SCOPED_PATHSPEC = re.compile(r"git\s+checkout\s+[^\n]*?\s--\s+\S+", _JS_ASCII)
    _DESTRUCTIVE = (
        re.compile(r"git\s+reset\s+--hard", _JS_ASCII),
        re.compile(r"git\s+clean\b", _JS_ASCII),
    )
    _BARE_CHECKOUT = re.compile(r"git\s+checkout\s+(?!--\s|HEAD\s+--)[^\n]*", _JS_ASCII)
    _RETURN_REVERSE = (
        re.compile(r"git\s+checkout\s+--\s+\S+", _JS_ASCII),
        re.compile(r"git\s+checkout\s+HEAD\s+--\s+\S+", _JS_ASCII),
        re.compile(r"git\s+restore\b", _JS_ASCII),
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

    match = _REGEX_TEST.match(source)
    if match:
        return RegexTestEvaluator(match.group("pattern"), match.group("flags"))

    if "security_must_appear" in source:
        terms = _SECURITY_TERMS.search(source)
        reasons = _reasons(source)
        if terms and len(reasons) >= 3:
            return SecurityRelevanceEvaluator(terms.group("terms"), tuple(reasons))

    if "hasScopedRestore" in source:
        reasons = _reasons(source)
        if len(reasons) >= 4:
            return RetrospectiveRestoreEvaluator(tuple(reasons))

    raise UnportedJavascriptAssertionError(
        "no Python evaluator for this javascript assert "
        f"({assertion.config_path or assertion.origin}); port it before "
        "adding it to the matrix"
    )
