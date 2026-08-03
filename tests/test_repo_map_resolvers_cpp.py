# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Unit + orchestrator-integration tests for the C/C++ include resolver (#359).

``extract`` is tested against REAL tree-sitter output (skipped without the
extra); ``resolve`` is pure path arithmetic over a supplied file set and runs on
every interpreter. The orchestrator-integration test runs ``infer_imports_edges``
against REAL tree-sitter over a COMMITTED C++/C fixture mini-repo
(``tests/fixtures/repo_map/cpp_project``); scan-level activation over the same
fixture lives in ``tests/test_repo_map_scan_activation.py`` (#483).

Equivalence partitioning over the include classes — quoted-relative (resolves
by exact spelling), extensionless (exact spelling, never probed to a header
variant), angle-bracket (dropped: no proven include roots without #484
context), macro (dropped: no literal path), external/unresolved (no edge) —
plus boundary value analysis for the repo-root-escaping ``..`` traversal and
true negatives pinning the corrected #359 semantics: no header-extension
probing and no conventional ``include/``/``src/`` root guessing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sumo_qa.repo_map_imports import infer_imports_edges
from sumo_qa.repo_map_models import RepoMapNode
from sumo_qa.repo_map_resolvers import get_resolver, registered_languages
from sumo_qa.repo_map_resolvers.base import RawImport
from sumo_qa.repo_map_resolvers.cpp import C_CONFIG, CPP_CONFIG, CppResolver
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


def test_cpp_config_extensions_cover_probed_headers():
    # #483 reconciliation: the configs declare every header spelling the
    # scanner owns for them, including .hh/.hxx, so those files are scanned as
    # import producers (the scanner-side halves are contract-pinned in
    # tests/test_repo_map_resolver_scanner_contract.py).
    assert set(CPP_CONFIG.extensions) == {".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx"}
    assert set(C_CONFIG.extensions) == {".c", ".h"}


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
    # `#include <vector>` names no repo file without proven include roots
    # (#484); dropped.
    assert cpp_resolver.extract(b"#include <vector>\n") == []


@_needs_ts
def test_cpp_resolver_extract_macro_include_dropped():
    # `#include CONFIG_H` carries an identifier, not a path literal; the
    # concrete header depends on macro expansion, so no import is recorded
    # (#359: macro includes emit no edge).
    assert cpp_resolver.extract(b"#include CONFIG_H\n") == []


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


def test_cpp_resolver_resolve_from_repo_root_importer():
    # An importer at the repo root has no directory prefix; the include's own
    # spelling is the whole candidate path.
    imp = RawImport(module="lib/util.h", level=0, names=(), function_local=False)
    files = {"lib/util.h"}
    assert cpp_resolver.resolve("main.cpp", imp, files) == ["lib/util.h"]


def test_cpp_resolver_resolve_extensionless_exact_spelling():
    # `#include "config"` names a file literally called `config`; exact
    # spelling resolves it when it exists next to the importer.
    imp = RawImport(module="config", level=0, names=(), function_local=False)
    files = {"src/config"}
    assert cpp_resolver.resolve("src/main.cpp", imp, files) == ["src/config"]


def test_cpp_resolver_resolve_extensionless_does_not_probe_header_variants():
    # #359 corrected semantics: `#include "config"` must NOT match config.h
    # (or any probed header variant) — the preprocessor searches the exact
    # spelling, and probing fabricates an edge the compiler never makes.
    imp = RawImport(module="config", level=0, names=(), function_local=False)
    files = {"src/config.h", "src/config.hpp"}
    assert cpp_resolver.resolve("src/main.cpp", imp, files) == []


def test_cpp_resolver_resolve_does_not_guess_include_root():
    # #359 corrected semantics: a header that exists ONLY under a conventional
    # include/ root is not provably on the compiler's search path, so no edge
    # is emitted (under-edge until #484 supplies configured include dirs).
    imp = RawImport(module="core.h", level=0, names=(), function_local=False)
    files = {"include/core.h"}
    assert cpp_resolver.resolve("src/app/main.cpp", imp, files) == []


def test_cpp_resolver_resolve_does_not_guess_src_root():
    imp = RawImport(module="lib.h", level=0, names=(), function_local=False)
    files = {"src/lib.h"}
    assert cpp_resolver.resolve("app/main.cpp", imp, files) == []


def test_cpp_resolver_resolve_relative_match_unaffected_by_same_named_root_header():
    # The same header exists both next to the importer and under include/;
    # exactly the importer-relative file resolves (a single unambiguous edge).
    imp = RawImport(module="util.h", level=0, names=(), function_local=False)
    files = {"src/util.h", "include/util.h"}
    assert cpp_resolver.resolve("src/main.cpp", imp, files) == ["src/util.h"]


def test_cpp_resolver_resolve_parent_traversal_within_repo():
    imp = RawImport(module="../common/base.h", level=0, names=(), function_local=False)
    files = {"src/common/base.h"}
    assert cpp_resolver.resolve("src/app/main.cpp", imp, files) == ["src/common/base.h"]


def test_cpp_resolver_resolve_dot_segment_is_normalized():
    imp = RawImport(module="./util.h", level=0, names=(), function_local=False)
    files = {"src/util.h"}
    assert cpp_resolver.resolve("src/main.cpp", imp, files) == ["src/util.h"]


def test_cpp_resolver_resolve_escaping_repo_root_yields_nothing():
    # Boundary: more `..` segments than ancestor directories walks above the
    # repo root; it must not anchor at the root and fabricate an edge to a file
    # that happens to exist there.
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


def test_cpp_resolver_resolve_absolute_spelling_yields_nothing():
    # `#include "/util.h"` is a filesystem-absolute path the preprocessor
    # opens from the filesystem root, never relative to the importer. Anchoring
    # it at the importer's directory would fabricate src/util.h here.
    imp = RawImport(module="/util.h", level=0, names=(), function_local=False)
    files = {"src/util.h", "util.h"}
    assert cpp_resolver.resolve("src/main.cpp", imp, files) == []


def test_cpp_resolver_resolve_trailing_slash_spelling_yields_nothing():
    # `#include "util.h/"` names a directory path; POSIX open() of it as a
    # regular file fails (ENOTDIR), so the preprocessor never finds a header.
    # Collapsing the trailing slash to match src/util.h would fabricate an
    # edge in exactly the guessed-edge class this resolver eliminates.
    imp = RawImport(module="util.h/", level=0, names=(), function_local=False)
    files = {"src/util.h"}
    assert cpp_resolver.resolve("src/main.cpp", imp, files) == []


# ---------- orchestrator integration (real tree-sitter, committed fixture) ----------

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "repo_map" / "cpp_project"

# repo-relative path -> language the scanner stamps (see the activation tests
# in tests/test_repo_map_scan_activation.py for the same fixture through
# scan_repo itself); supplied directly here so this layer stays a focused
# orchestrator test.
_FIXTURE_FILES = {
    "src/main.cpp": "cpp",
    "src/util.h": "cpp",
    "src/config.h": "cpp",
    "src/dropme.h": "cpp",
    "src/helpers/format.h": "cpp",
    "src/view.hh": "cpp",
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
def test_cpp_resolver_orchestrator_emits_exactly_the_corrected_edges():
    edges = infer_imports_edges(_fixture_nodes(), _FIXTURE_ROOT)
    pairs = {(e.source, e.target) for e in edges}

    assert pairs == {
        # quoted includes resolved relative to the including file
        ("file:src/main.cpp", "file:src/util.h"),
        ("file:src/main.cpp", "file:src/helpers/format.h"),
        # a header (.hh) is itself an import producer
        ("file:src/view.hh", "file:src/util.h"),
        # the `c`-language registration resolves a quoted include too
        ("file:clib/lib.c", "file:clib/lib.h"),
    }
    # The exact set doubles as the #359 true negatives: main.cpp's
    # `#include "config"` matches no file (src/config.h exists but is never
    # probed), `#include "core.h"` matches no file (include/core.h exists but
    # conventional roots are never guessed), and `#include <dropme.h>` is an
    # angle-bracket include (src/dropme.h exists but no edge is emitted).


@_needs_ts
def test_cpp_resolver_orchestrator_drops_angle_bracket_system_include():
    # main.cpp does `#include <dropme.h>` AND src/dropme.h exists; without
    # proven include roots (#484) the angle-bracket include must under-edge
    # (discriminating: a quoted include of the same path would resolve
    # relative).
    edges = infer_imports_edges(_fixture_nodes(), _FIXTURE_ROOT)
    pairs = {(e.source, e.target) for e in edges}
    assert ("file:src/main.cpp", "file:src/dropme.h") not in pairs


@_needs_ts
def test_cpp_resolver_orchestrator_tags_includes_high_confidence():
    edges = infer_imports_edges(_fixture_nodes(), _FIXTURE_ROOT)
    assert edges  # fixture sanity
    assert all(e.confidence == "high" for e in edges)  # #include is module-level coupling
