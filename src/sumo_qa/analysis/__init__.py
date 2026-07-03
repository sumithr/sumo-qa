# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Semantic / static-analysis adapters for QA recommendations (issue #212).

Typed cross-source analysis contracts plus normalization of analysis signals
into QA recommendation evidence. This package OWNS the signal contracts and their
normalization; it REUSES the epic-#353 repo-map ``imports`` graph (cross-file
impacted-symbol reach) and the #147 coverage/mutation artifacts (optional
signals), never re-deriving imports or redefining artifact shapes. See
``docs/ARCHITECTURE.md`` and ``docs/CONFIGURATION.md`` for the documented
integration points with #155, #156, and #147.

Import-safe with the lightweight core install: nothing here forces the optional
``[treesitter]`` extra. Symbol extraction is stdlib ``ast``; the optional import
graph is consulted only for cross-file impacted-symbol reach and degrades to a
recorded fallback when the extra is absent.
"""

from __future__ import annotations

from sumo_qa.analysis.analyzer import analyze_changes
from sumo_qa.analysis.artifacts import (
    COVERAGE_RELPATH,
    MUTATION_RELPATH,
    load_coverage_signal,
    load_mutation_signal,
)
from sumo_qa.analysis.contracts import (
    ANALYSIS_SCHEMA_VERSION,
    AdapterStatus,
    AnalysisConfidence,
    AnalysisFallback,
    AnalysisResult,
    ChangedSymbol,
    ImpactedSymbol,
    LikelyOwningTest,
    RecommendationEvidence,
    Symbol,
    SymbolKind,
)
from sumo_qa.analysis.diff import changed_lines_from_unified_diff
from sumo_qa.analysis.impact import impacted_symbols_via_imports
from sumo_qa.analysis.normalize import build_recommendation_evidence
from sumo_qa.analysis.python_adapter import (
    PYTHON_EXTENSIONS,
    PYTHON_LANGUAGE,
    PythonSymbolAdapter,
    extract_symbols,
    innermost_symbol,
    symbols_touching_lines,
)
from sumo_qa.analysis.registry import (
    LanguageAdapter,
    adapter_for_language,
    adapter_for_path,
    supported_languages,
)
from sumo_qa.analysis.test_mapping import map_changed_symbols_to_tests

__all__ = [
    "ANALYSIS_SCHEMA_VERSION",
    "COVERAGE_RELPATH",
    "MUTATION_RELPATH",
    "PYTHON_EXTENSIONS",
    "PYTHON_LANGUAGE",
    "AdapterStatus",
    "AnalysisConfidence",
    "AnalysisFallback",
    "AnalysisResult",
    "ChangedSymbol",
    "ImpactedSymbol",
    "LanguageAdapter",
    "LikelyOwningTest",
    "PythonSymbolAdapter",
    "RecommendationEvidence",
    "Symbol",
    "SymbolKind",
    "adapter_for_language",
    "adapter_for_path",
    "analyze_changes",
    "build_recommendation_evidence",
    "changed_lines_from_unified_diff",
    "extract_symbols",
    "impacted_symbols_via_imports",
    "innermost_symbol",
    "load_coverage_signal",
    "load_mutation_signal",
    "map_changed_symbols_to_tests",
    "supported_languages",
    "symbols_touching_lines",
]
