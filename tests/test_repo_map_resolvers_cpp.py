# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Unit + orchestrator-integration tests for the C/C++ include resolver (#359).

``extract`` is tested against REAL tree-sitter output (skipped without the
extra); ``resolve`` is pure path arithmetic over a supplied file set and runs on
every interpreter. The orchestrator-integration test runs ``infer_imports_edges``
against REAL tree-sitter over a COMMITTED C++/C fixture mini-repo
(``tests/fixtures/repo_map/cpp_project``).

Equivalence partitioning over the include classes — quoted-relative,
quoted-via-include-root, extensionless-header-probe, angle-bracket-system
(dropped), external/unresolved — plus boundary value analysis for the
repo-root-escaping ``..`` traversal.

Note on scan_repo integration: the scanner's ``_LANGUAGE_BY_EXT`` does not (yet)
map ``.cpp/.cc/.cxx/.h/.hpp/.c`` to ``cpp``/``c``, so ``scan_repo`` stamps
``language=None`` on those files and the orchestrator skips them. The resolver is
therefore exercised through ``infer_imports_edges`` directly with language-stamped
nodes — the same orchestrator entry point ``scan_repo`` calls — until the
scanner extension map is extended (a foundation change out of this slice's scope).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sumo_qa.repo_map_imports import infer_imports_edges
from sumo_qa.repo_map_models import RepoMapNode
from sumo_qa.repo_map_resolvers import get_resolver, registered_languages
from sumo_qa.repo_map_resolvers.base import RawImport
from sumo_qa.repo_map_resolvers.cpp import CppResolver
from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE

cpp_resolver = CppResolver()

_needs_ts = pytest.mark.skipif(
    not TREESITTER_AVAILABLE,
    reason="tree-sitter not installed (the [treesitter] extra is absent)",
)


# ---------- registry ----------


def test_cpp_resolver_is_registered_for_cpp():
    assert "cpp" in registered_languages()
    assert get_resolver("cpp") is not None


def test_cpp_resolver_is_registered_for_c():
    assert "c" in registered_languages()
    assert get_resolver("c") is not None


# ---------- extract (real tree-sitter) ----------


@_needs_ts
def test_cpp_resolver_extract_quoted_include():
    (raw,) = cpp_resolver.extract(b'#include "foo.h"\n')
    assert raw.module == "foo.h"
    assert raw.level == 0
    assert raw.names == ()
    assert raw.function_local is False  # an #include is always module-level coupling


@_needs_ts
def test_cpp_resolver_extract_quoted_subdirectory_include():
    (raw,) = cpp_resolver.extract(b'#include "sub/bar.hpp"\n')
    assert raw.module == "sub/bar.hpp"  # the path keeps its subdirectory


@_needs_ts
def test_cpp_resolver_extract_extensionless_quoted_include():
    (raw,) = cpp_resolver.extract(b'#include "config"\n')
    assert raw.module == "config"  # extensionless includes are kept verbatim


@_needs_ts
def test_cpp_resolver_extract_angle_bracket_system_include_dropped():
    # `#include <vector>` is a system header -> not a repo import; dropped.
    assert cpp_resolver.extract(b"#include <vector>\n") == []


@_needs_ts
def test_cpp_resolver_extract_mixed_keeps_only_quoted_includes():
    raws = cpp_resolver.extract(b'#include "a.h"\n#include <stdio.h>\n#include "b.h"\n')
    assert [r.module for r in raws] == ["a.h", "b.h"]  # the system include is dropped


# ---------- resolve (pure, runs everywhere) ----------


def test_cpp_resolver_resolve_relative_to_including_file():
    imp = RawImport(module="util.h", level=0, names=(), function_local=False)
    files = {"src/main.cpp", "src/util.h"}
    assert cpp_resolver.resolve("src/main.cpp", imp, files) == ["src/util.h"]


def test_cpp_resolver_resolve_relative_subdirectory():
    imp = RawImport(module="helpers/format.h", level=0, names=(), function_local=False)
    files = {"src/helpers/format.h"}
    assert cpp_resolver.resolve("src/main.cpp", imp, files) == ["src/helpers/format.h"]


def test_cpp_resolver_resolve_via_include_root():
    # Not next to the importer -> resolves under the `include/` root.
    imp = RawImport(module="core.h", level=0, names=(), function_local=False)
    files = {"include/core.h"}
    assert cpp_resolver.resolve("src/app/main.cpp", imp, files) == ["include/core.h"]


def test_cpp_resolver_resolve_via_src_include_root():
    imp = RawImport(module="lib.h", level=0, names=(), function_local=False)
    files = {"src/lib.h"}
    assert cpp_resolver.resolve("app/main.cpp", imp, files) == ["src/lib.h"]


def test_cpp_resolver_resolve_extensionless_probes_header_extension():
    # `#include "config"` (no extension) probes header extensions -> config.h.
    imp = RawImport(module="config", level=0, names=(), function_local=False)
    files = {"src/config.h"}
    assert cpp_resolver.resolve("src/main.cpp", imp, files) == ["src/config.h"]


def test_cpp_resolver_resolve_extensionless_probes_hpp_extension():
    imp = RawImport(module="widget", level=0, names=(), function_local=False)
    files = {"src/widget.hpp"}
    assert cpp_resolver.resolve("src/main.cpp", imp, files) == ["src/widget.hpp"]


def test_cpp_resolver_resolve_relative_beats_include_root():
    # The same header exists both next to the importer and under an include root;
    # the relative match wins and only one edge is emitted.
    imp = RawImport(module="util.h", level=0, names=(), function_local=False)
    files = {"src/util.h", "include/util.h"}
    assert cpp_resolver.resolve("src/main.cpp", imp, files) == ["src/util.h"]


def test_cpp_resolver_resolve_dedups_relative_and_include_root_base():
    # The importer lives under include/, so its relative directory and the
    # include-root produce the SAME candidate base; it is probed once -> one edge.
    imp = RawImport(module="core.h", level=0, names=(), function_local=False)
    files = {"include/core.h"}
    assert cpp_resolver.resolve("include/app.cpp", imp, files) == ["include/core.h"]


def test_cpp_resolver_resolve_parent_traversal_within_repo():
    imp = RawImport(module="../common/base.h", level=0, names=(), function_local=False)
    files = {"src/common/base.h"}
    assert cpp_resolver.resolve("src/app/main.cpp", imp, files) == ["src/common/base.h"]


def test_cpp_resolver_resolve_dot_segment_is_normalized():
    imp = RawImport(module="./util.h", level=0, names=(), function_local=False)
    files = {"src/util.h"}
    assert cpp_resolver.resolve("src/main.cpp", imp, files) == ["src/util.h"]


def test_cpp_resolver_resolve_escaping_repo_root_yields_nothing():
    # Boundary: more `..` segments than ancestor directories walks above the repo
    # root; it must not anchor at the root and fabricate an edge to a file that
    # happens to exist there.
    imp = RawImport(module="../../../etc/passwd.h", level=0, names=(), function_local=False)
    files = {"src/main.cpp", "etc/passwd.h"}
    assert cpp_resolver.resolve("src/main.cpp", imp, files) == []


def test_cpp_resolver_resolve_exact_extension_does_not_cross_probe():
    # `#include "foo.h"` names an exact file; it must NOT fuzzy-match foo.hpp
    # (that would be a broken include the real preprocessor also fails to find).
    imp = RawImport(module="foo.h", level=0, names=(), function_local=False)
    files = {"src/foo.hpp"}
    assert cpp_resolver.resolve("src/main.cpp", imp, files) == []


def test_cpp_resolver_resolve_external_not_found_yields_nothing():
    imp = RawImport(module="nonexistent.h", level=0, names=(), function_local=False)
    files = {"src/main.cpp"}
    assert cpp_resolver.resolve("src/main.cpp", imp, files) == []


# ---------- orchestrator integration (real tree-sitter, committed fixture) ----------

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "repo_map" / "cpp_project"

# repo-relative path -> language the scanner WOULD stamp once the extension map
# is extended; supplied directly here so the orchestrator dispatches the resolver.
_FIXTURE_FILES = {
    "src/main.cpp": "cpp",
    "src/util.h": "cpp",
    "src/config.h": "cpp",
    "src/dropme.h": "cpp",
    "src/helpers/format.h": "cpp",
    "include/core.h": "cpp",
    "clib/lib.c": "c",
    "clib/lib.h": "cpp",
}


def _fixture_nodes() -> list[RepoMapNode]:
    return [
        RepoMapNode(id=f"file:{rel}", type="source_file", path=rel, language=lang)
        for rel, lang in _FIXTURE_FILES.items()
    ]


@_needs_ts
def test_cpp_resolver_orchestrator_emits_quoted_include_edges():
    edges = infer_imports_edges(_fixture_nodes(), _FIXTURE_ROOT)
    pairs = {(e.source, e.target) for e in edges}

    # quoted include resolved relative to the including file
    assert ("file:src/main.cpp", "file:src/util.h") in pairs
    assert ("file:src/main.cpp", "file:src/helpers/format.h") in pairs
    # extensionless quoted include resolved via header-extension probing
    assert ("file:src/main.cpp", "file:src/config.h") in pairs
    # quoted include resolved via the include/ root (not next to the importer)
    assert ("file:src/main.cpp", "file:include/core.h") in pairs
    # the `c`-language registration resolves a quoted include too
    assert ("file:clib/lib.c", "file:clib/lib.h") in pairs


@_needs_ts
def test_cpp_resolver_orchestrator_drops_angle_bracket_system_include():
    # main.cpp does `#include <dropme.h>` AND src/dropme.h exists; the angle
    # bracket means "system header", so NO edge to it (discriminating: a quoted
    # include of the same path would resolve relative).
    edges = infer_imports_edges(_fixture_nodes(), _FIXTURE_ROOT)
    pairs = {(e.source, e.target) for e in edges}
    assert ("file:src/main.cpp", "file:src/dropme.h") not in pairs


@_needs_ts
def test_cpp_resolver_orchestrator_tags_includes_high_confidence():
    edges = infer_imports_edges(_fixture_nodes(), _FIXTURE_ROOT)
    assert edges  # fixture sanity
    assert all(e.confidence == "high" for e in edges)  # #include is module-level coupling
