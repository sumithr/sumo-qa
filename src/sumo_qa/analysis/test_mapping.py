# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Map changed symbols to their likely owning tests (issue #212, AC#4).

Given the changed symbols and the source of the repo's test files, find the
tests that reference a changed symbol by its leaf name. Deterministic and
dependency-free (stdlib ``ast`` via :mod:`sumo_qa.analysis.references`): a test
that CALLS the symbol is ``high`` confidence; one that merely NAMES it is
``medium``. The enclosing ``def`` is recorded when the reference sits inside one,
so a recommendation can point at the exact test, not only the file.

This is the symbol-granular complement to the #156 file-level ``likely_tests``
edge: #156 maps a changed FILE to its test files; this maps a changed SYMBOL to
the specific tests that exercise it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sumo_qa.analysis.contracts import AnalysisConfidence, ChangedSymbol, LikelyOwningTest
from sumo_qa.analysis.references import collect_references


def _leaf(qualname: str) -> str:
    """The trailing component of a dotted qualname (``Order.total`` -> ``total``)."""
    return qualname.rsplit(".", 1)[-1]


def map_changed_symbols_to_tests(
    changed_symbols: Sequence[ChangedSymbol],
    test_sources: Mapping[str, bytes],
) -> list[LikelyOwningTest]:
    """Likely owning tests for ``changed_symbols`` across ``test_sources``.

    ``test_sources`` maps a test-file path to its source bytes. Output rows are
    one per ``(test_path, enclosing def, changed symbol)`` triple, where the
    changed symbol is identified by both its path and qualname; rows are
    deduplicated and sorted for determinism. An unparseable test file is skipped
    cleanly.
    """
    changed_by_leaf: dict[str, list[ChangedSymbol]] = {}
    for changed in changed_symbols:
        changed_by_leaf.setdefault(_leaf(changed.symbol.qualname), []).append(changed)

    results: list[LikelyOwningTest] = []
    for test_path in sorted(test_sources):
        refs = collect_references(test_sources[test_path])
        if refs is None:
            continue  # test file does not parse: nothing to match against
        # (enclosing def, leaf) -> was the leaf ever CALLED here.
        called_by_key: dict[tuple[str | None, str], bool] = {}
        for ref in refs:
            if ref.name in changed_by_leaf:
                key = (ref.enclosing, ref.name)
                called_by_key[key] = called_by_key.get(key, False) or ref.called
        for (enclosing, leaf), called in sorted(
            called_by_key.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])
        ):
            confidence: AnalysisConfidence = "high" if called else "medium"
            verb = "calls" if called else "references"
            for changed in changed_by_leaf[leaf]:
                results.append(
                    LikelyOwningTest(
                        test_path=test_path,
                        changed_path=changed.path,
                        changed_symbol=changed.symbol.qualname,
                        test_symbol=enclosing,
                        confidence=confidence,
                        reason=f"{test_path} {verb} {leaf}",
                    )
                )
    return sorted(
        results,
        key=lambda t: (
            t.test_path,
            t.changed_path,
            t.changed_symbol,
            t.test_symbol or "",
            t.confidence,
        ),
    )
