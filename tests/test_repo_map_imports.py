# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the import-edge orchestrator and its scanner integration (#354).

The orchestrator (``infer_imports_edges``) and the ``scan_repo`` integration
run against REAL tree-sitter output over fixture mini-repos (skipped without
the extra). The graceful-degradation path (extra absent) is exercised by
monkeypatching the availability flag, so BOTH paths are covered regardless of
whether the extra is installed in the running environment. A consumer
pass-through test proves ``analyze_diff_impact`` inherits import edges with no
change to that module.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import sumo_qa.repo_map_imports as imports_mod
from sumo_qa.repo_map_impact import analyze_diff_impact
from sumo_qa.repo_map_imports import infer_imports_edges
from sumo_qa.repo_map_models import RepoMapNode
from sumo_qa.repo_map_scanner import scan_repo
from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE

_needs_ts = pytest.mark.skipif(
    not TREESITTER_AVAILABLE,
    reason="tree-sitter not installed (the [treesitter] extra is absent)",
)


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8", newline="")


def _import_edges(repo_map) -> list:
    return [e for e in repo_map.edges if e.type == "imports"]


# ---------- scan_repo integration: confidence by import position ----------


@_needs_ts
def test_scan_emits_import_edges_with_confidence(tmp_path: Path):
    # a.py: module-level import of b -> high. b.py: function-local import of c
    # -> medium. c.py: class-body import of d -> high.
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/a.py", "from pkg import b\n")
    _write(tmp_path, "pkg/b.py", "def lazy():\n    from pkg import c\n")
    _write(tmp_path, "pkg/c.py", "class K:\n    from pkg import d\n")
    _write(tmp_path, "pkg/d.py", "x = 1\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    edges = {(e.source, e.target): e for e in _import_edges(repo_map)}

    # module-level -> high
    assert edges[("file:pkg/a.py", "file:pkg/b.py")].confidence == "high"
    # function-local -> medium
    assert edges[("file:pkg/b.py", "file:pkg/c.py")].confidence == "medium"
    # class-body -> high
    assert edges[("file:pkg/c.py", "file:pkg/d.py")].confidence == "high"


@_needs_ts
def test_scan_still_emits_likely_tests_alongside_imports(tmp_path: Path):
    # Both edge types coexist: a source + its conventionally-named test.
    _write(tmp_path, "calc.py", "def add(a, b):\n    return a + b\n")
    _write(tmp_path, "helper.py", "import calc\n")
    _write(tmp_path, "test_calc.py", "import calc\n\ndef test_add():\n    assert calc\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    types = {e.type for e in repo_map.edges}
    assert "imports" in types
    assert "likely_tests" in types


@_needs_ts
def test_scan_edges_are_globally_sorted_across_both_edge_types(tmp_path: Path):
    # The documented contract (docs/REPO-MAP.md): the FULL edge list is sorted by
    # (source, target). Concatenating per-layer-sorted likely_tests + imports
    # lists is not enough: an imports edge whose source sorts BEFORE a
    # likely_tests edge's source breaks the global order.
    #
    # Fixture: test_calc.py imports calc.py -> both a likely_tests edge AND an
    # imports edge from file:test_calc.py. aaa.py imports calc.py -> an imports
    # edge from file:aaa.py, which sorts before file:test_calc.py. With plain
    # concatenation the likely_tests (test_calc -> calc) precedes the imports
    # (aaa -> calc), so the combined list is NOT globally ascending.
    _write(tmp_path, "calc.py", "def add(a, b):\n    return a + b\n")
    _write(tmp_path, "aaa.py", "import calc\n")
    _write(tmp_path, "test_calc.py", "import calc\n\ndef test_add():\n    assert calc\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    types = {e.type for e in repo_map.edges}
    assert "imports" in types and "likely_tests" in types  # fixture sanity
    keys = [(e.source, e.target) for e in repo_map.edges]
    assert keys == sorted(keys)  # the WHOLE edge list is globally ascending


# ---------- node-only edges (no dangling) ----------


@_needs_ts
def test_import_of_unmapped_target_emits_no_edge(tmp_path: Path):
    # main.py imports a real sibling (mapped) and an external package
    # (unmapped). Only the mapped one yields an edge - no dangling edge to the
    # external import.
    _write(tmp_path, "main.py", "import sibling\nimport requests\n")
    _write(tmp_path, "sibling.py", "x = 1\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    targets = {e.target for e in _import_edges(repo_map)}
    assert "file:sibling.py" in targets
    assert all("requests" not in t for t in targets)
    # every edge endpoint resolves to a real node
    node_ids = {n.id for n in repo_map.nodes}
    for e in _import_edges(repo_map):
        assert e.source in node_ids
        assert e.target in node_ids


# ---------- dedup: strongest confidence per (source, target) ----------


@_needs_ts
def test_dedup_keeps_strongest_confidence(tmp_path: Path):
    # a.py imports b at module level (high) AND lazily inside a function
    # (medium). The pair collapses to a single high edge.
    _write(tmp_path, "a.py", "import b\n\ndef lazy():\n    import b\n")
    _write(tmp_path, "b.py", "x = 1\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    pair_edges = [
        e for e in _import_edges(repo_map) if (e.source, e.target) == ("file:a.py", "file:b.py")
    ]
    assert len(pair_edges) == 1
    assert pair_edges[0].confidence == "high"


# ---------- determinism: stable edge ordering ----------


@_needs_ts
def test_import_edges_are_sorted_and_stable(tmp_path: Path):
    # a.py imports c THEN b, so the natural insertion order is non-ascending
    # ([(a,c), (a,b)]) - that non-ascending fixture is what makes the assertion
    # below non-tautological. This test exercises scan_repo(), which re-sorts the
    # WHOLE edge list (repo_map_scanner.py: edges.sort by (source, target, type))
    # after the layers are concatenated, so it is that combined re-sort that puts
    # (a,b) before (a,c); removing the scanner's combined sort leaves the
    # assertion below RED (deleting only the imports orchestrator's per-layer
    # sort does not, since the scanner re-sort still orders the result).
    _write(tmp_path, "a.py", "import c\nimport b\n")
    _write(tmp_path, "b.py", "import c\n")
    _write(tmp_path, "c.py", "x = 1\n")

    first = _import_edges(scan_repo(tmp_path, generator_version="t"))
    second = _import_edges(scan_repo(tmp_path, generator_version="t"))
    keys_first = [(e.source, e.target) for e in first]
    keys_second = [(e.source, e.target) for e in second]
    assert keys_first == sorted(keys_first)  # sorted by (source, target)
    assert keys_first == keys_second  # byte-stable across runs


# ---------- consumer pass-through (analyze_diff_impact inherits imports) ----------


@_needs_ts
def test_analyze_diff_impact_surfaces_import_neighbour(tmp_path: Path):
    # server.py imports server_schemas.py (the #335 gold case). A diff touching
    # server.py must surface server_schemas.py as an affected node - proving the
    # consumer inherits import edges with no change to repo_map_impact.
    _write(tmp_path, "server.py", "import server_schemas\n")
    _write(tmp_path, "server_schemas.py", "SCHEMA = {}\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    impact = analyze_diff_impact(repo_map, ["server.py"])
    affected_paths = {n.path for n in impact.affected_nodes}
    assert "server_schemas.py" in affected_paths


# ---------- graceful degradation (extra absent) ----------


def test_missing_extra_returns_no_edges_and_warns(monkeypatch, tmp_path: Path):
    # Force the no-extra path regardless of the running environment.
    monkeypatch.setattr(imports_mod, "TREESITTER_AVAILABLE", False)
    nodes = [
        RepoMapNode(id="file:a.py", type="source_file", path="a.py", language="python"),
        RepoMapNode(id="file:b.py", type="source_file", path="b.py", language="python"),
    ]
    warnings: list = []
    edges = infer_imports_edges(nodes, tmp_path, warnings)
    assert edges == []
    assert len(warnings) == 1
    assert warnings[0].kind == "unsupported_language"
    assert "treesitter" in warnings[0].message


def test_missing_extra_tolerates_no_warning_sink(monkeypatch, tmp_path: Path):
    # When no warnings list is supplied, the no-extra path still returns [] and
    # does not raise.
    monkeypatch.setattr(imports_mod, "TREESITTER_AVAILABLE", False)
    nodes = [RepoMapNode(id="file:a.py", type="source_file", path="a.py", language="python")]
    assert infer_imports_edges(nodes, tmp_path) == []


def test_scan_with_missing_extra_still_produces_likely_tests(monkeypatch, tmp_path: Path):
    # The headline degradation contract: with the extra absent, scan_repo still
    # succeeds, still emits likely_tests edges, emits no imports edges, and
    # records the degradation warning.
    monkeypatch.setattr(imports_mod, "TREESITTER_AVAILABLE", False)
    _write(tmp_path, "calc.py", "def add(a, b):\n    return a + b\n")
    _write(tmp_path, "test_calc.py", "import calc\n\ndef test_add():\n    assert calc\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    types = {e.type for e in repo_map.edges}
    assert "likely_tests" in types
    assert "imports" not in types
    assert any("treesitter" in w.message for w in repo_map.warnings)


# ---------- language dispatch ----------


@_needs_ts
def test_unsupported_language_node_is_skipped(tmp_path: Path):
    # A non-Python source node (no registered resolver) yields no import edges
    # and is not an error.
    _write(tmp_path, "main.rs", "use std::io;\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert _import_edges(repo_map) == []


@_needs_ts
def test_no_self_edge_when_module_resolves_to_importer(tmp_path: Path):
    # pkg/__init__.py does `from pkg import helper`. The module probe resolves
    # `pkg` to pkg/__init__.py - the importer itself. That self-resolution must
    # not produce a self-edge; only the helper submodule edge survives.
    _write(tmp_path, "pkg/__init__.py", "from pkg import helper\n")
    _write(tmp_path, "pkg/helper.py", "x = 1\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    edges = _import_edges(repo_map)
    assert all(e.source != e.target for e in edges)
    targets = {e.target for e in edges}
    assert "file:pkg/helper.py" in targets
    assert "file:pkg/__init__.py" not in targets


@_needs_ts
def test_unreadable_source_file_yields_no_edges_not_an_error(monkeypatch, tmp_path: Path):
    # A file that races to unreadable mid-scan must degrade to "no edges from
    # it", never raise. Force the read failure via a patched opener.
    _write(tmp_path, "a.py", "import b\n")
    _write(tmp_path, "b.py", "x = 1\n")

    nodes = [
        RepoMapNode(id="file:a.py", type="source_file", path="a.py", language="python"),
        RepoMapNode(id="file:b.py", type="source_file", path="b.py", language="python"),
    ]
    real_open = Path.open

    def _explode(self, *args, **kwargs):
        if self.name == "a.py":
            raise OSError("simulated unreadable file")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _explode)
    # a.py is unreadable -> skipped; b.py has no in-repo imports -> no edges.
    assert infer_imports_edges(nodes, tmp_path) == []
