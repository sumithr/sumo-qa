# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Normalize analysis signals into QA recommendation evidence (#212, AC#6).

Turns the changed symbols, impacted symbols, likely tests, and optional
coverage/mutation signals into :class:`RecommendationEvidence`: concrete,
deduplicated, sorted anchors (files, ``path::qualname`` symbols, ``test::name``
tests) plus ordered one-line risk notes, so a recommendation cites WHERE to look
instead of staying generic. Pure and deterministic — this is the step that makes
"recommendations can cite concrete files, symbols, tests, or analysis evidence"
true rather than aspirational.
"""

from __future__ import annotations

from collections.abc import Sequence

from sumo_qa.analysis.contracts import (
    AnalysisFallback,
    ChangedSymbol,
    ImpactedSymbol,
    LikelyOwningTest,
    RecommendationEvidence,
)
from sumo_qa.scorecard_models import CoverageSignal, MutationSignal


def _symbol_anchor(path: str, qualname: str) -> str:
    """A concrete, checkable ``path::qualname`` reference."""
    return f"{path}::{qualname}"


def _test_anchor(test: LikelyOwningTest) -> str:
    """A test anchor — ``path::test_name`` when the enclosing test is known,
    else the bare test path."""
    if test.test_symbol:
        return f"{test.test_path}::{test.test_symbol}"
    return test.test_path


def build_recommendation_evidence(
    *,
    changed_symbols: Sequence[ChangedSymbol],
    impacted_symbols: Sequence[ImpactedSymbol],
    likely_tests: Sequence[LikelyOwningTest],
    coverage: CoverageSignal | None = None,
    mutation: MutationSignal | None = None,
    fallbacks: Sequence[AnalysisFallback] = (),
) -> RecommendationEvidence:
    """Compose the analysis signals into render-ready recommendation evidence."""
    risk_notes: list[str] = []
    citations: list[str] = []

    for changed in changed_symbols:
        anchor = _symbol_anchor(changed.path, changed.symbol.qualname)
        risk_notes.append(f"changed {changed.symbol.kind} {anchor}")
        citations.append(anchor)

    for impacted in impacted_symbols:
        citations.append(_symbol_anchor(impacted.path, impacted.qualname))

    test_focus: list[str] = []
    for test in likely_tests:
        anchor = _test_anchor(test)
        test_focus.append(anchor)
        citations.append(anchor)

    if changed_symbols and not likely_tests:
        risk_notes.append(
            "no likely owning tests found for the changed symbols; "
            "locate or add coverage before merge"
        )

    if coverage is not None and coverage.line_percent is not None:
        note = f"line coverage {coverage.line_percent:g}% ({coverage.freshness})"
        risk_notes.append(note)
        citations.append(note)

    if mutation is not None and mutation.survivors is not None:
        note = f"{mutation.survivors} mutation survivor(s) ({mutation.freshness})"
        risk_notes.append(note)
        citations.append(note)

    for fallback in fallbacks:
        risk_notes.append(f"degraded ({fallback.status}): {fallback.message}")

    review_focus = [_symbol_anchor(i.path, i.qualname) for i in impacted_symbols]
    review_focus += [_symbol_anchor(c.path, c.symbol.qualname) for c in changed_symbols]

    return RecommendationEvidence(
        risk_notes=risk_notes,
        test_focus=_dedup_sorted(test_focus),
        review_focus=_dedup_sorted(review_focus),
        citations=_dedup_sorted(citations),
    )


def _dedup_sorted(items: list[str]) -> list[str]:
    return sorted(set(items))
