# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""End-to-end ``scan_repo`` activation tests for C/C++, PHP, and C# (#483, #359).

Each test drives the REAL pipeline end to end: files on disk -> ``scan_repo``
-> classified nodes -> resolver dispatch -> ``imports`` edges, with the
tree-sitter extra present (skipped without it, except the degradation test,
which monkeypatches the availability flag). Assertions use EXACT expected edge
sets so an over-matching resolver cannot pass, and each language carries a true
negative:

- C/C++: quoted relative includes resolve by exact spelling; extensionless
  includes do NOT probe ``.h``/``.hpp`` variants; quoted includes do NOT
  resolve through conventional ``include/``/``src/`` roots; angle-bracket
  includes emit no edge (no proven include roots exist until #484 supplies
  repository context, so the correct behavior is under-edge).
- PHP: a relative ``require``/``include`` edge resolves with NO Composer
  context; PSR-4 ``use`` fan-out is deliberately NOT asserted (#484 owns the
  Composer root threading).
- C#: ``.cs`` files become ``source_file`` nodes stamped ``csharp`` and reach
  resolver dispatch (proven by a spy on the registered resolver); namespace
  fan-out edges are deliberately NOT asserted (#484 owns the namespace index).

Without the extra, the same files still classify as correctly typed source
nodes and the scan degrades through the existing single warning path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import sumo_qa.repo_map_imports as imports_mod
from sumo_qa.repo_map_models import RepoMap, RepoMapNode
from sumo_qa.repo_map_resolvers import get_resolver
from sumo_qa.repo_map_scanner import scan_repo
from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE

_needs_ts = pytest.mark.skipif(
    not TREESITTER_AVAILABLE,
    reason="tree-sitter not installed (the [treesitter] extra is absent)",
)

_FIXTURES = Path(__file__).parent / "fixtures" / "repo_map"


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8", newline="")


def _import_pairs(repo_map: RepoMap) -> set[tuple[str, str]]:
    return {(e.source, e.target) for e in repo_map.edges if e.type == "imports"}


def _node(repo_map: RepoMap, path: str) -> RepoMapNode:
    return next(n for n in repo_map.nodes if n.path == path)


# ---------- C/C++ (tmp_path mini-repos) ----------


@_needs_ts
def test_scan_cpp_quoted_relative_include_emits_exact_edges(tmp_path: Path):
    _write(tmp_path, "src/main.cpp", '#include "util.h"\n#include "helpers/format.h"\n')
    _write(tmp_path, "src/util.h", "#pragma once\n")
    _write(tmp_path, "src/helpers/format.h", "#pragma once\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    assert _import_pairs(repo_map) == {
        ("file:src/main.cpp", "file:src/util.h"),
        ("file:src/main.cpp", "file:src/helpers/format.h"),
    }
    main = _node(repo_map, "src/main.cpp")
    assert main.type == "source_file"
    assert main.language == "cpp"


@_needs_ts
def test_scan_c_quoted_include_emits_edge_and_stays_language_c(tmp_path: Path):
    _write(tmp_path, "clib/lib.c", '#include "lib.h"\n')
    _write(tmp_path, "clib/lib.h", "#pragma once\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    assert _import_pairs(repo_map) == {("file:clib/lib.c", "file:clib/lib.h")}
    assert _node(repo_map, "clib/lib.c").language == "c"
    # .h stamps the documented ambiguous-header default, cpp; the shared
    # extractor serves both C and C++, so the edge above still resolves.
    assert _node(repo_map, "clib/lib.h").language == "cpp"


@_needs_ts
def test_scan_mapped_header_is_an_import_producer(tmp_path: Path):
    # A header owned by the scanner (.hh, reconciled into CPP_CONFIG) that
    # itself contains a quoted include is scanned as an import PRODUCER, not
    # just a target.
    _write(tmp_path, "src/view.hh", '#pragma once\n#include "util.h"\n')
    _write(tmp_path, "src/util.h", "#pragma once\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    assert _import_pairs(repo_map) == {("file:src/view.hh", "file:src/util.h")}
    assert _node(repo_map, "src/view.hh").language == "cpp"


@_needs_ts
def test_scan_extensionless_include_does_not_probe_header_variants(tmp_path: Path):
    # #359: `#include "config"` names a file literally called `config`; the
    # preprocessor searches that exact spelling, so probing config.h would
    # fabricate an edge the compiler never makes. True negative: only the .h
    # variant exists -> NO edge.
    _write(tmp_path, "src/main.cpp", '#include "config"\n')
    _write(tmp_path, "src/config.h", "#pragma once\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    assert _import_pairs(repo_map) == set()


@_needs_ts
def test_scan_quoted_include_does_not_guess_conventional_roots(tmp_path: Path):
    # #359: fixed include/ and src/ root guesses cannot reproduce the
    # compiler's -I search order. A quoted include that does not resolve next
    # to its importer under-edges until #484 supplies configured include
    # directories. True negative: core.h exists ONLY under include/ -> NO edge.
    _write(tmp_path, "src/main.cpp", '#include "core.h"\n')
    _write(tmp_path, "include/core.h", "#pragma once\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    assert _import_pairs(repo_map) == set()


@_needs_ts
def test_scan_angle_bracket_includes_emit_no_edge(tmp_path: Path):
    # #359: without repository context there are no proven include roots, so
    # angle-bracket includes must under-edge. Discriminating: the SAME spelling
    # in quotes would resolve relative (src/core.h exists), so a false pass
    # cannot come from the file being absent.
    _write(tmp_path, "src/main.cpp", "#include <core.h>\n#include <vector>\n")
    _write(tmp_path, "src/core.h", "#pragma once\n")
    _write(tmp_path, "include/core.h", "#pragma once\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    assert _import_pairs(repo_map) == set()


@_needs_ts
def test_scan_committed_cpp_fixture_exact_edge_set():
    # The committed mini-repo end to end: exactly the four corrected-semantics
    # edges and nothing else. The fixture also carries the true negatives:
    # `#include "config"` (only config.h exists: no probe), `#include "core.h"`
    # (only include/core.h exists: no conventional-root guess), and
    # `#include <dropme.h>` (src/dropme.h exists: angle brackets drop).
    repo_map = scan_repo(_FIXTURES / "cpp_project", generator_version="t")
    assert _import_pairs(repo_map) == {
        ("file:src/main.cpp", "file:src/util.h"),
        ("file:src/main.cpp", "file:src/helpers/format.h"),
        ("file:src/view.hh", "file:src/util.h"),
        ("file:clib/lib.c", "file:clib/lib.h"),
    }
    assert _node(repo_map, "src/main.cpp").language == "cpp"
    assert _node(repo_map, "src/view.hh").language == "cpp"
    assert _node(repo_map, "clib/lib.c").language == "c"


# ---------- PHP (committed fixture, no Composer context) ----------


@_needs_ts
def test_scan_php_relative_require_emits_edge_without_composer_context():
    # The committed PHP fixture has a composer.json, but scan-time resolution
    # deliberately does NOT read it (#484 owns Composer root threading). The
    # relative `require __DIR__ . '/../helpers.php'` resolves; the PSR-4
    # `use App\Models\User;` and the vendor `use Monolog\Logger;` do not.
    # The exact-set assertion IS the PSR-4 true negative.
    repo_map = scan_repo(_FIXTURES / "php", generator_version="t")
    assert _import_pairs(repo_map) == {
        (
            "file:src/Controllers/UserController.php",
            "file:src/helpers.php",
        )
    }
    controller = _node(repo_map, "src/Controllers/UserController.php")
    assert controller.type == "source_file"
    assert controller.language == "php"


# ---------- C# (committed fixture, dispatch without namespace context) ----------


@_needs_ts
def test_scan_csharp_sources_reach_resolver_dispatch(monkeypatch):
    # .cs files must classify as csharp source nodes AND reach the registered
    # resolver (proven by a spy on extract). Namespace fan-out edges are
    # deliberately NOT asserted: the registered resolver's namespace index is
    # empty until #484 threads a per-scan index, so the exact edge set is
    # empty (a true negative pinning the #484 boundary).
    resolver = get_resolver("csharp")
    assert resolver is not None
    dispatched: list[int] = []
    # Patch the CLASS attribute, not the registered singleton instance: undoing
    # an instance-level patch would re-set the captured bound method as a
    # permanent instance attribute, shadowing any later class-level patch (a
    # test-order hazard on shared registry state).
    resolver_cls = type(resolver)
    real_extract = resolver_cls.extract

    def _spy(self: object, src: bytes):
        dispatched.append(len(src))
        return real_extract(self, src)

    monkeypatch.setattr(resolver_cls, "extract", _spy)

    repo_map = scan_repo(_FIXTURES / "csharp", generator_version="t")
    cs_nodes = [n for n in repo_map.nodes if n.path.endswith(".cs")]
    assert cs_nodes  # fixture sanity
    assert all(n.type == "source_file" and n.language == "csharp" for n in cs_nodes)
    assert len(dispatched) == len(cs_nodes)  # every .cs node reached extract
    assert _import_pairs(repo_map) == set()


# ---------- degradation without the tree-sitter extra ----------


def test_scan_without_extra_still_classifies_activated_languages(monkeypatch, tmp_path: Path):
    # Core-install behavior (#483): with the extra absent the newly activated
    # extensions still classify as correctly typed source nodes with the
    # intended language, no imports edges are emitted, and the scan degrades
    # through the existing SINGLE warning path.
    monkeypatch.setattr(imports_mod, "TREESITTER_AVAILABLE", False)
    _write(tmp_path, "src/main.cpp", '#include "util.h"\n')
    _write(tmp_path, "src/util.h", "#pragma once\n")
    _write(tmp_path, "clib/lib.c", '#include "lib.h"\n')
    _write(tmp_path, "src/index.php", "<?php\nrequire 'helpers.php';\n")
    _write(tmp_path, "src/Order.cs", "namespace App;\n")

    repo_map = scan_repo(tmp_path, generator_version="t")
    expected = {
        "src/main.cpp": "cpp",
        "src/util.h": "cpp",
        "clib/lib.c": "c",
        "src/index.php": "php",
        "src/Order.cs": "csharp",
    }
    for path, language in expected.items():
        node = _node(repo_map, path)
        assert node.type == "source_file"
        assert node.language == language
    assert _import_pairs(repo_map) == set()
    degradations = [w for w in repo_map.warnings if "treesitter" in w.message]
    assert len(degradations) == 1  # the one existing degradation warning, once
