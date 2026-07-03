# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the typed analysis contracts (issue #212)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sumo_qa.analysis.contracts import (
    ANALYSIS_SCHEMA_VERSION,
    AnalysisFallback,
    AnalysisResult,
    ChangedSymbol,
    ImpactedSymbol,
    LikelyOwningTest,
    RecommendationEvidence,
    Symbol,
)
from sumo_qa.scorecard_models import CoverageSignal, MutationSignal


def _symbol(qualname: str = "mod.func", start: int = 1, end: int = 3) -> Symbol:
    return Symbol(qualname=qualname, kind="function", start_line=start, end_line=end)


def test_symbol_valid_span_including_single_line():
    sym = _symbol(start=5, end=5)
    assert sym.start_line == 5
    assert sym.end_line == 5


def test_symbol_rejects_end_before_start():
    with pytest.raises(ValidationError, match="end_line must be >= start_line"):
        Symbol(qualname="f", kind="function", start_line=9, end_line=3)


def test_symbol_forbids_extra_field():
    with pytest.raises(ValidationError):
        Symbol(qualname="f", kind="function", start_line=1, end_line=2, bogus=1)


def test_symbol_requires_nonempty_qualname():
    with pytest.raises(ValidationError):
        Symbol(qualname="", kind="function", start_line=1, end_line=2)


def test_changed_symbol_wraps_a_symbol():
    cs = ChangedSymbol(path="pkg/a.py", symbol=_symbol())
    assert cs.path == "pkg/a.py"
    assert cs.symbol.qualname == "mod.func"


def test_impacted_symbol_carries_confidence():
    imp = ImpactedSymbol(path="pkg/b.py", qualname="caller", references="func", confidence="medium")
    assert imp.confidence == "medium"
    assert imp.references == "func"


def test_likely_owning_test_defaults_test_symbol_to_none():
    t = LikelyOwningTest(
        test_path="tests/test_a.py",
        changed_path="pkg/mod.py",
        changed_symbol="mod.func",
        confidence="high",
        reason="calls func",
    )
    assert t.test_symbol is None
    assert t.changed_path == "pkg/mod.py"


def test_analysis_fallback_shape():
    fb = AnalysisFallback(status="unsupported_language", subject="a.kt", message="no adapter")
    assert fb.status == "unsupported_language"


def test_recommendation_evidence_defaults_are_empty_lists():
    ev = RecommendationEvidence()
    assert ev.risk_notes == []
    assert ev.test_focus == []
    assert ev.review_focus == []
    assert ev.citations == []


def test_analysis_result_defaults_and_schema_version():
    res = AnalysisResult()
    assert res.schema_version == ANALYSIS_SCHEMA_VERSION == "1.0"
    assert res.changed_symbols == []
    assert res.coverage is None
    assert res.mutation is None
    assert res.is_degraded() is False
    assert res.fallback_statuses() == []


def test_analysis_result_normalises_a_tuple_to_a_list():
    # The list-normalising validator must coerce a supplied sequence to a
    # concrete list so the field round-trips as a JSON array.
    res = AnalysisResult(changed_symbols=(ChangedSymbol(path="a.py", symbol=_symbol()),))
    assert isinstance(res.changed_symbols, list)
    assert res.changed_symbols[0].path == "a.py"


def test_analysis_result_reports_distinct_fallback_statuses_sorted():
    res = AnalysisResult(
        fallbacks=[
            AnalysisFallback(status="parse_error", subject="a.py", message="x"),
            AnalysisFallback(status="parse_error", subject="b.py", message="y"),
            AnalysisFallback(status="unsupported_language", subject="c.kt", message="z"),
        ]
    )
    assert res.is_degraded() is True
    assert res.fallback_statuses() == ["parse_error", "unsupported_language"]


def test_analysis_result_carries_reused_coverage_and_mutation_signals():
    res = AnalysisResult(
        coverage=CoverageSignal(line_percent=72.0, freshness="fresh"),
        mutation=MutationSignal(survivors=2, freshness="fresh"),
    )
    assert res.coverage is not None and res.coverage.line_percent == 72.0
    assert res.mutation is not None and res.mutation.survivors == 2
