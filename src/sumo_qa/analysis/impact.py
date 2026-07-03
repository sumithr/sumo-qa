# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Impacted-symbol reach across the repo-map ``imports`` graph (issue #212).

A changed symbol can break callers in OTHER files. This finds them by REUSING
the epic-#353 ``imports`` edges — it never re-derives imports. For each file that
imports a changed file, the symbols in that importer which reference a changed
symbol's leaf name are ``impacted``.

Pure: the caller supplies the importer sources and the import map (the set of
importer paths per imported path). That import map is projected from a
tree-sitter-scanned repo-map, so when the ``[treesitter]`` extra is absent the
caller passes no map and the composition records a ``missing_optional_dependency``
fallback (see :mod:`sumo_qa.analysis.analyzer`) instead of calling here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sumo_qa.analysis.contracts import AnalysisConfidence, ChangedSymbol, ImpactedSymbol
from sumo_qa.analysis.python_adapter import innermost_symbol
from sumo_qa.analysis.references import collect_references
from sumo_qa.analysis.registry import adapter_for_path


def impacted_symbols_via_imports(
    changed_symbols: Sequence[ChangedSymbol],
    importer_sources: Mapping[str, bytes],
    importers_by_imported: Mapping[str, set[str]],
) -> list[ImpactedSymbol]:
    """Symbols in importer files that reference a changed symbol.

    ``importers_by_imported`` maps an imported (changed) file path to the set of
    files that import it (from the #353 ``imports`` edges). For each importer
    whose source is supplied and parseable, a reference to a changed leaf name is
    attributed to the innermost enclosing symbol; a module-level reference (no
    enclosing symbol) is skipped. Rows are deduplicated by
    ``(importer, symbol, referenced leaf)`` and sorted.
    """
    changed_leaves_by_file: dict[str, set[str]] = {}
    for changed in changed_symbols:
        leaf = changed.symbol.qualname.rsplit(".", 1)[-1]
        changed_leaves_by_file.setdefault(changed.path, set()).add(leaf)

    seen: set[tuple[str, str, str]] = set()
    results: list[ImpactedSymbol] = []
    for imported_path in sorted(importers_by_imported):
        leaves = changed_leaves_by_file.get(imported_path)
        if not leaves:
            continue  # imported file contributed no changed symbols: nothing to reach
        for importer_path in sorted(importers_by_imported[imported_path]):
            adapter = adapter_for_path(importer_path)
            if adapter is None:
                continue  # importer is an unsupported language: cannot extract its symbols
            src = importer_sources.get(importer_path)
            if src is None:
                continue  # importer source not supplied
            refs = collect_references(src)
            if refs is None:
                continue  # importer does not parse
            symbols = adapter.extract_symbols(src)
            for ref in refs:
                if ref.name not in leaves:
                    continue
                enclosing = innermost_symbol(symbols, ref.lineno)
                if enclosing is None:
                    continue  # module-level reference: no enclosing symbol to attribute
                key = (importer_path, enclosing.qualname, ref.name)
                if key in seen:
                    continue
                seen.add(key)
                confidence: AnalysisConfidence = "high" if ref.called else "medium"
                results.append(
                    ImpactedSymbol(
                        path=importer_path,
                        qualname=enclosing.qualname,
                        references=ref.name,
                        confidence=confidence,
                    )
                )
    return sorted(results, key=lambda i: (i.path, i.qualname, i.references))
