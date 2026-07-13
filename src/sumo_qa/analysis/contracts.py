# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Typed cross-source analysis contracts for QA recommendations (issue #212).

This module owns the CONTRACT layer for the semantic/static-analysis adapter
work: the normalized signal shapes that let repo-understanding artifacts feed
CONSISTENT evidence into QA recommendations, instead of every consumer
re-deriving changed symbols, impacted callers, or test ownership ad hoc.

Scope discipline (issue #212 vs epic #353):

* #353 owns repo-map ``imports`` edge extraction, the per-language resolvers,
  and the tree-sitter adapter framework. This layer REUSES that output (the
  resolved ``imports`` edges) — it does not re-extract imports or duplicate the
  resolver framework.
* #212 owns these typed contracts plus the normalization of analysis signals
  into QA recommendation evidence.

Everything here is pure data: no I/O, no inference. Producers fill the fields;
:class:`RecommendationEvidence` is the render-ready projection a QA report or an
MCP tool cites (concrete files, symbols, tests) so a recommendation is
evidence-backed rather than generic. The optional coverage/mutation signals
REUSE the #147 :class:`~sumo_qa.scorecard_models.CoverageSignal` /
:class:`~sumo_qa.scorecard_models.MutationSignal` so a signal that flows through
this layer is the same one the readiness scorecard already consumes.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sumo_qa.scorecard_models import CoverageSignal, MutationSignal

ANALYSIS_SCHEMA_VERSION: Final[Literal["1.0"]] = "1.0"

#: Confidence on a derived analysis signal. Mirrors the repo-map
#: ``EdgeConfidence`` vocabulary so an ``imports``-edge confidence maps 1:1 onto
#: an analysis signal without a second scale to reconcile.
AnalysisConfidence = Literal["low", "medium", "high"]

#: The kind of a source symbol. ``method`` is distinguished from ``function`` so
#: a changed method reads as ``Class.method``, not a bare free function.
SymbolKind = Literal["function", "method", "class"]

#: Explicit fallback status for one adapter step. Every value is a CLEAN
#: degradation, never a crash: an unsupported language, a missing optional parser
#: dependency, an imports graph that was never supplied, an unparseable source, or
#: a malformed artifact each surface a status the caller can branch on instead of
#: an exception. ``missing_import_graph`` is distinct from
#: ``missing_optional_dependency``: the parser IS installed, but no projected
#: ``imports`` map reached the analyzer (a repo-map that was absent, stale, or
#: never projected), so skipped cross-file reach is still explained rather than
#: silent. There is no ``ok`` member: a fallback exists only to record that a step
#: could not run fully.
AdapterStatus = Literal[
    "unsupported_language",
    "missing_optional_dependency",
    "missing_import_graph",
    "parse_error",
    "invalid_artifact",
]


class Symbol(BaseModel):
    """One source symbol with its 1-based, inclusive line span.

    ``qualname`` is the dotted path from the module root (``Order.total`` for a
    method on ``Order``); ``start_line``/``end_line`` bound the symbol so a set
    of changed line numbers can be mapped onto the symbols they touch.
    """

    model_config = ConfigDict(extra="forbid")

    qualname: str = Field(min_length=1, description="Dotted name, e.g. 'Order.total' for a method.")
    kind: SymbolKind
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def _end_after_start(self) -> Symbol:
        # A span whose end precedes its start could never contain a changed line
        # and would silently drop the symbol from every mapping; reject it.
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self


class ChangedSymbol(BaseModel):
    """A symbol whose line span intersects the changed lines of its file."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    symbol: Symbol


class ImpactedSymbol(BaseModel):
    """A symbol in ANOTHER file that references a changed symbol.

    Reached over the repo-map ``imports`` graph (#353 output): the importer file
    both imports the changed file and names the changed symbol's leaf.
    ``references`` is that leaf name; ``confidence`` is ``high`` when the
    reference is a call, ``medium`` when the name merely appears.
    """

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    qualname: str = Field(min_length=1)
    references: str = Field(min_length=1, description="The changed-symbol leaf name it references.")
    confidence: AnalysisConfidence


class LikelyOwningTest(BaseModel):
    """A test that likely owns a changed symbol: it references the symbol name.

    ``changed_path`` plus ``changed_symbol`` identify the changed symbol: the leaf
    name alone is ambiguous (``pkg/a.py::run`` and ``pkg/b.py::run`` share the
    ``run`` qualname), so the file path keeps otherwise-identical rows distinct and
    lets evidence say WHICH changed symbol a test likely owns. ``confidence`` is
    ``high`` when the test CALLS the symbol, ``medium`` when it merely names it.
    ``test_symbol`` records the enclosing ``def`` when the reference sits inside
    one, so a recommendation points at the exact test, not only the file.
    ``reason`` is a one-line, human-checkable justification.
    """

    model_config = ConfigDict(extra="forbid")

    test_path: str = Field(min_length=1)
    changed_path: str = Field(min_length=1, description="Path of the changed symbol's file.")
    changed_symbol: str = Field(min_length=1, description="qualname of the changed symbol.")
    test_symbol: str | None = Field(default=None, description="Enclosing test function, if known.")
    confidence: AnalysisConfidence
    reason: str = Field(min_length=1)


class AnalysisFallback(BaseModel):
    """A clean degradation record: one adapter step could not run fully.

    ``subject`` is the path or language the degradation concerns; ``message`` is
    the human explanation. The presence of a fallback is how absence of a signal
    is EXPLAINED rather than left silent.
    """

    model_config = ConfigDict(extra="forbid")

    status: AdapterStatus
    subject: str = Field(min_length=1, description="The path or language the fallback concerns.")
    message: str = Field(min_length=1)


class RecommendationEvidence(BaseModel):
    """The render-ready projection a QA recommendation cites (issue #212 AC#6).

    ``risk_notes`` are ordered one-line human strings (narrative order is
    meaningful, so they are NOT sorted). ``test_focus``/``review_focus``/
    ``citations`` are deduplicated, sorted anchor lists — concrete, checkable
    references (file paths, ``path::qualname`` symbol refs, ``test::name`` test
    refs) so a recommendation names WHERE to look instead of staying generic.
    """

    model_config = ConfigDict(extra="forbid")

    risk_notes: list[str] = Field(default_factory=list)
    test_focus: list[str] = Field(default_factory=list)
    review_focus: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Top-level normalized analysis over a set of changed files (issue #212).

    Composes the per-language changed-symbol extraction, the import-graph
    impacted-symbol reach (#353 reuse), the changed-symbol -> likely-test
    mapping, and the OPTIONAL #147 coverage/mutation signals into one typed
    result, plus the render-ready :class:`RecommendationEvidence`. ``fallbacks``
    records every clean degradation (unsupported language, absent tree-sitter
    extra, unparseable source, malformed artifact) so a missing signal is always
    accounted for, never silent.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = ANALYSIS_SCHEMA_VERSION
    changed_symbols: list[ChangedSymbol] = Field(default_factory=list)
    impacted_symbols: list[ImpactedSymbol] = Field(default_factory=list)
    likely_tests: list[LikelyOwningTest] = Field(default_factory=list)
    coverage: CoverageSignal | None = None
    mutation: MutationSignal | None = None
    fallbacks: list[AnalysisFallback] = Field(default_factory=list)
    evidence: RecommendationEvidence = Field(default_factory=RecommendationEvidence)

    @field_validator("changed_symbols", "impacted_symbols", "likely_tests")
    @classmethod
    def _lists_are_lists(cls, value: list) -> list:
        # Defensive normalisation so a caller passing a tuple/generator still
        # round-trips as a JSON array; pydantic accepts the sequence and this
        # keeps the stored attribute a concrete list.
        return list(value)

    def fallback_statuses(self) -> list[AdapterStatus]:
        """The distinct fallback statuses present, sorted — the quick answer to
        "did anything degrade, and how?" without walking every fallback."""
        return sorted({fb.status for fb in self.fallbacks})

    def is_degraded(self) -> bool:
        """True when any adapter step fell back to a clean degradation."""
        return bool(self.fallbacks)
