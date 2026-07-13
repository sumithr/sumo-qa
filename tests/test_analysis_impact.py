# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for import-graph impacted-symbol reach (issue #212; reuses #353)."""

from __future__ import annotations

from sumo_qa.analysis.contracts import ChangedSymbol, Symbol
from sumo_qa.analysis.impact import impacted_symbols_via_imports, importers_from_repo_map
from sumo_qa.repo_map_models import RepoMapEdge


def _changed(qualname: str, path: str) -> ChangedSymbol:
    return ChangedSymbol(
        path=path, symbol=Symbol(qualname=qualname, kind="function", start_line=1, end_line=3)
    )


def test_caller_that_calls_a_changed_symbol_is_high_confidence_impacted():
    changed = [_changed("run", "pkg/core.py")]
    importer_sources = {
        "pkg/caller.py": b"from pkg.core import run\n\ndef use():\n    return run()\n",
    }
    impacted = impacted_symbols_via_imports(
        changed, importer_sources, {"pkg/core.py": {"pkg/caller.py"}}
    )
    assert len(impacted) == 1
    assert impacted[0].path == "pkg/caller.py"
    assert impacted[0].qualname == "use"
    assert impacted[0].references == "run"
    assert impacted[0].confidence == "high"


def test_caller_that_only_names_a_changed_symbol_is_medium_confidence():
    changed = [_changed("run", "pkg/core.py")]
    importer_sources = {
        "pkg/namer.py": b"from pkg.core import run\n\ndef pick():\n    return run\n"
    }
    impacted = impacted_symbols_via_imports(
        changed, importer_sources, {"pkg/core.py": {"pkg/namer.py"}}
    )
    assert [(i.qualname, i.confidence) for i in impacted] == [("pick", "medium")]


def test_repeated_reference_in_the_same_symbol_is_deduplicated():
    changed = [_changed("run", "pkg/core.py")]
    importer_sources = {
        "pkg/caller.py": b"from pkg.core import run\n\ndef use():\n    run()\n    return run()\n",
    }
    impacted = impacted_symbols_via_imports(
        changed, importer_sources, {"pkg/core.py": {"pkg/caller.py"}}
    )
    assert len(impacted) == 1


def test_module_level_reference_is_skipped():
    changed = [_changed("run", "pkg/core.py")]
    importer_sources = {"pkg/modlevel.py": b"from pkg.core import run\nrun()\n"}
    impacted = impacted_symbols_via_imports(
        changed, importer_sources, {"pkg/core.py": {"pkg/modlevel.py"}}
    )
    assert impacted == []


def test_reference_to_a_non_changed_name_is_ignored():
    changed = [_changed("run", "pkg/core.py")]
    importer_sources = {"pkg/caller.py": b"def use():\n    other()\n"}
    impacted = impacted_symbols_via_imports(
        changed, importer_sources, {"pkg/core.py": {"pkg/caller.py"}}
    )
    assert impacted == []


def test_imported_file_with_no_changed_symbols_contributes_nothing():
    changed = [_changed("run", "pkg/core.py")]
    importer_sources = {"pkg/caller.py": b"def use():\n    run()\n"}
    # `pkg/other.py` is in the graph but has no changed symbols -> skipped.
    impacted = impacted_symbols_via_imports(
        changed,
        importer_sources,
        {"pkg/core.py": {"pkg/caller.py"}, "pkg/other.py": {"pkg/caller.py"}},
    )
    assert [i.path for i in impacted] == ["pkg/caller.py"]


def test_unsupported_importer_language_is_skipped():
    changed = [_changed("run", "pkg/core.py")]
    importer_sources = {"docs/notes.md": b"run() everywhere\n"}
    impacted = impacted_symbols_via_imports(
        changed, importer_sources, {"pkg/core.py": {"docs/notes.md"}}
    )
    assert impacted == []


def test_missing_importer_source_is_skipped():
    changed = [_changed("run", "pkg/core.py")]
    impacted = impacted_symbols_via_imports(changed, {}, {"pkg/core.py": {"pkg/absent.py"}})
    assert impacted == []


def test_unparseable_importer_is_skipped():
    changed = [_changed("run", "pkg/core.py")]
    importer_sources = {"pkg/broken.py": b"def (:\n"}
    impacted = impacted_symbols_via_imports(
        changed, importer_sources, {"pkg/core.py": {"pkg/broken.py"}}
    )
    assert impacted == []


def _edge(source: str, target: str, edge_type: str = "imports") -> RepoMapEdge:
    return RepoMapEdge(source=source, target=target, type=edge_type, confidence="high", reason="x")


def test_importers_from_repo_map_inverts_file_prefixed_imports_edges():
    # The scanner stamps file:{path} node ids; the projection strips the prefix
    # and inverts source->target into imported-path -> {importer paths}.
    edges = [
        _edge("file:pkg/caller.py", "file:pkg/core.py"),
        _edge("file:pkg/other.py", "file:pkg/core.py"),
        # A non-imports edge (e.g. likely_tests) contributes nothing.
        _edge("file:tests/test_core.py", "file:pkg/core.py", edge_type="likely_tests"),
    ]
    assert importers_from_repo_map(edges) == {"pkg/core.py": {"pkg/caller.py", "pkg/other.py"}}


def test_importers_from_repo_map_projection_reaches_the_impacted_symbol():
    changed = [_changed("run", "pkg/core.py")]
    importer_sources = {
        "pkg/caller.py": b"from pkg.core import run\n\ndef use():\n    return run()\n",
    }
    projected = importers_from_repo_map([_edge("file:pkg/caller.py", "file:pkg/core.py")])
    impacted = impacted_symbols_via_imports(changed, importer_sources, projected)
    assert [(i.path, i.qualname) for i in impacted] == [("pkg/caller.py", "use")]
