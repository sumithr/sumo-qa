# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for normalizing signals into recommendation evidence (issue #212 AC#6)."""

from __future__ import annotations

from sumo_qa.analysis.contracts import (
    AnalysisFallback,
    ChangedSymbol,
    ImpactedSymbol,
    LikelyOwningTest,
    Symbol,
)
from sumo_qa.analysis.normalize import build_recommendation_evidence
from sumo_qa.scorecard_models import CoverageSignal, MutationSignal


def _changed(qualname: str, path: str = "pkg/mod.py") -> ChangedSymbol:
    return ChangedSymbol(
        path=path, symbol=Symbol(qualname=qualname, kind="method", start_line=1, end_line=2)
    )


def test_changed_symbols_become_risk_notes_and_citations():
    ev = build_recommendation_evidence(
        changed_symbols=[_changed("Order.total")],
        impacted_symbols=[],
        likely_tests=[
            LikelyOwningTest(
                test_path="tests/test_o.py",
                changed_path="pkg/mod.py",
                changed_symbol="Order.total",
                test_symbol="test_total",
                confidence="high",
                reason="calls total",
            )
        ],
    )
    assert "changed method pkg/mod.py::Order.total" in ev.risk_notes
    assert "pkg/mod.py::Order.total" in ev.citations
    assert ev.test_focus == ["tests/test_o.py::test_total"]
    assert "tests/test_o.py::test_total" in ev.citations


def test_missing_owning_tests_is_called_out_when_symbols_changed():
    ev = build_recommendation_evidence(
        changed_symbols=[_changed("Order.total")],
        impacted_symbols=[],
        likely_tests=[],
    )
    assert any("no likely owning tests" in note for note in ev.risk_notes)


def test_impacted_symbols_drive_review_focus():
    ev = build_recommendation_evidence(
        changed_symbols=[_changed("run", path="pkg/core.py")],
        impacted_symbols=[
            ImpactedSymbol(
                path="pkg/caller.py", qualname="use", references="run", confidence="high"
            )
        ],
        likely_tests=[],
    )
    assert "pkg/caller.py::use" in ev.review_focus
    assert "pkg/core.py::run" in ev.review_focus


def test_coverage_and_mutation_signals_change_the_evidence():
    ev = build_recommendation_evidence(
        changed_symbols=[_changed("run")],
        impacted_symbols=[],
        likely_tests=[],
        coverage=CoverageSignal(line_percent=72.0, freshness="fresh"),
        mutation=MutationSignal(survivors=4, freshness="stale"),
    )
    assert "line coverage 72% (fresh)" in ev.risk_notes
    assert "4 mutation survivor(s) (stale)" in ev.risk_notes
    assert "line coverage 72% (fresh)" in ev.citations


def test_signals_without_measurements_add_no_notes():
    # A coverage/mutation signal present but carrying no measurement must not
    # invent a note (it is "not measured", not "0%").
    ev = build_recommendation_evidence(
        changed_symbols=[_changed("run")],
        impacted_symbols=[],
        likely_tests=[
            LikelyOwningTest(
                test_path="t.py",
                changed_path="pkg/mod.py",
                changed_symbol="run",
                confidence="high",
                reason="calls run",
            )
        ],
        coverage=CoverageSignal(freshness="unknown"),
        mutation=MutationSignal(freshness="unknown"),
    )
    assert not any("coverage" in n for n in ev.risk_notes)
    assert not any("survivor" in n for n in ev.risk_notes)


def test_bare_test_path_used_when_enclosing_test_unknown():
    ev = build_recommendation_evidence(
        changed_symbols=[_changed("run")],
        impacted_symbols=[],
        likely_tests=[
            LikelyOwningTest(
                test_path="tests/mod_level.py",
                changed_path="pkg/mod.py",
                changed_symbol="run",
                confidence="high",
                reason="calls run",
            )
        ],
    )
    assert ev.test_focus == ["tests/mod_level.py"]


def test_fallbacks_are_recorded_as_degraded_notes():
    ev = build_recommendation_evidence(
        changed_symbols=[],
        impacted_symbols=[],
        likely_tests=[],
        fallbacks=[
            AnalysisFallback(
                status="missing_optional_dependency", subject="tree-sitter", message="no extra"
            )
        ],
    )
    assert any("degraded (missing_optional_dependency): no extra" in n for n in ev.risk_notes)
