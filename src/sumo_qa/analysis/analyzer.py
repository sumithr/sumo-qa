# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Compose the analysis adapters into one normalized result (issue #212).

``analyze_changes`` stitches the per-language changed-symbol extraction, the
epic-#353 import-graph impacted-symbol reach, the changed-symbol -> likely-test
mapping, and the optional #147 coverage/mutation signals into a single
:class:`AnalysisResult`, recording a clean :class:`AnalysisFallback` for every
degradation:

* an UNSUPPORTED language (no adapter for the file): the file is skipped;
* an UNPARSEABLE source (``SyntaxError``): that file is skipped, others proceed;
* the ABSENT ``[treesitter]`` extra: cross-file impacted-symbol reach is skipped
  (the import graph it needs cannot be built) while the lightweight core
  (changed symbols + test mapping) still runs;
* a MISSING import graph: the extra IS present but no projected ``imports`` map
  was supplied (the repo-map was absent/stale, or the caller never projected it),
  so cross-file reach is skipped and the reason is recorded, not left silent.

The changed-symbol and test-mapping passes never depend on the optional parser,
so a missing extra degrades reach WITHOUT losing the core signals — the "keep
normal install lightweight" contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sumo_qa.analysis.contracts import (
    AnalysisFallback,
    AnalysisResult,
    ChangedSymbol,
    ImpactedSymbol,
)
from sumo_qa.analysis.impact import impacted_symbols_via_imports
from sumo_qa.analysis.normalize import build_recommendation_evidence
from sumo_qa.analysis.registry import adapter_for_path
from sumo_qa.analysis.test_mapping import map_changed_symbols_to_tests
from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE
from sumo_qa.scorecard_models import CoverageSignal, MutationSignal


def analyze_changes(
    *,
    changed_sources: Mapping[str, bytes],
    changed_lines: Mapping[str, set[int]],
    test_sources: Mapping[str, bytes] | None = None,
    importer_sources: Mapping[str, bytes] | None = None,
    importers_by_imported: Mapping[str, set[str]] | None = None,
    coverage: CoverageSignal | None = None,
    mutation: MutationSignal | None = None,
    extra_fallbacks: Sequence[AnalysisFallback] = (),
) -> AnalysisResult:
    """Normalize a set of changed files into an :class:`AnalysisResult`.

    ``changed_sources`` maps a changed file path to its (new) source bytes;
    ``changed_lines`` maps the same path to the new-side line numbers that
    changed (e.g. from :func:`sumo_qa.analysis.diff.changed_lines_from_unified_diff`).
    ``test_sources`` is the repo's test files for the likely-test mapping.

    Cross-file impacted symbols are computed only when ``importers_by_imported``
    is supplied (projected from the #353 ``imports`` edges of a tree-sitter-scanned
    repo-map via :func:`sumo_qa.analysis.impact.importers_from_repo_map`). When it
    is ``None`` and the ``[treesitter]`` extra is absent, a
    ``missing_optional_dependency`` fallback is recorded; when the extra is present
    but no map was supplied, a ``missing_import_graph`` fallback is recorded
    instead. Either way the skipped cross-file reach is explained, never silent.
    ``extra_fallbacks`` lets a caller thread in fallbacks it already collected
    (e.g. a malformed coverage artifact).
    """
    test_sources = test_sources or {}
    fallbacks: list[AnalysisFallback] = list(extra_fallbacks)

    changed_symbols: list[ChangedSymbol] = []
    for path in sorted(changed_sources):
        adapter = adapter_for_path(path)
        if adapter is None:
            fallbacks.append(
                AnalysisFallback(
                    status="unsupported_language",
                    subject=path,
                    message=f"no analysis adapter for {path}; changed-symbol extraction skipped",
                )
            )
            continue
        try:
            symbols = adapter.extract_symbols(changed_sources[path])
        except SyntaxError as exc:
            fallbacks.append(
                AnalysisFallback(
                    status="parse_error",
                    subject=path,
                    message=f"could not parse {path}: {exc.msg}",
                )
            )
            continue
        touched = adapter.symbols_touching_lines(symbols, changed_lines.get(path, set()))
        changed_symbols.extend(ChangedSymbol(path=path, symbol=sym) for sym in touched)

    impacted: list[ImpactedSymbol] = []
    if importers_by_imported is None:
        if not TREESITTER_AVAILABLE:
            fallbacks.append(
                AnalysisFallback(
                    status="missing_optional_dependency",
                    subject="tree-sitter",
                    message=(
                        "the [treesitter] extra is not installed, so the imports graph is "
                        "unavailable; cross-file impacted-symbol reach is skipped"
                    ),
                )
            )
        else:
            fallbacks.append(
                AnalysisFallback(
                    status="missing_import_graph",
                    subject="imports-graph",
                    message=(
                        "the [treesitter] extra is installed but no imports graph was supplied "
                        "(the .sumo-qa/repo-map.json was absent or stale, or its imports edges "
                        "were not projected via importers_from_repo_map); cross-file "
                        "impacted-symbol reach is skipped"
                    ),
                )
            )
    else:
        impacted = impacted_symbols_via_imports(
            changed_symbols, importer_sources or {}, importers_by_imported
        )

    likely_tests = map_changed_symbols_to_tests(changed_symbols, test_sources)

    evidence = build_recommendation_evidence(
        changed_symbols=changed_symbols,
        impacted_symbols=impacted,
        likely_tests=likely_tests,
        coverage=coverage,
        mutation=mutation,
        fallbacks=fallbacks,
    )

    return AnalysisResult(
        changed_symbols=changed_symbols,
        impacted_symbols=impacted,
        likely_tests=likely_tests,
        coverage=coverage,
        mutation=mutation,
        fallbacks=fallbacks,
        evidence=evidence,
    )
