# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Unit + integration tests for the Go import resolver (#356).

``extract`` is tested against REAL tree-sitter output (skipped without the
``[treesitter]`` extra), including a parse of the COMMITTED Go fixture under
``tests/fixtures/repo_map_go/``. ``resolve`` is pure path arithmetic over a
supplied file set and runs on every interpreter. Each ``resolve`` case names the
UA Go rule it exercises: nearest-``go.mod`` discovery, module-prefix stripping,
package-level fan-out (one import path -> every ``.go`` file in the package
dir), multi-module governance (the nearest enclosing ``go.mod`` wins), and the
external/stdlib drop. A ``scan_repo`` integration test ties them together on the
committed multi-module fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sumo_qa.repo_map_resolvers import get_resolver, registered_languages
from sumo_qa.repo_map_resolvers.base import RawImport
from sumo_qa.repo_map_resolvers.go import GoResolver
from sumo_qa.repo_map_scanner import scan_repo
from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE

resolver = GoResolver()

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "repo_map_go" / "monorepo"

_needs_ts = pytest.mark.skipif(
    not TREESITTER_AVAILABLE,
    reason="tree-sitter not installed (the [treesitter] extra is absent)",
)


# ---------- registry ----------


def test_go_resolver_is_registered():
    assert "go" in registered_languages()
    assert get_resolver("go") is not None


# ---------- extract (real tree-sitter) ----------


@_needs_ts
def test_go_resolver_extract_single_import():
    (raw,) = resolver.extract(b'package main\n\nimport "fmt"\n')
    assert raw.module == "fmt"
    assert raw.level == 0  # Go has no relative imports
    assert raw.names == ()  # package-level fan-out needs no specifiers
    assert raw.function_local is False  # Go imports are always file-level


@_needs_ts
def test_go_resolver_extract_grouped_imports_ignore_alias_blank_dot():
    # A grouped block mixing a plain, an aliased (`m`), a blank (`_`) and a dot
    # (`.`) import. The alias/blank/dot tokens are siblings of the path literal,
    # so the extracted module is the path string in every case - never the alias.
    src = (
        b"package main\n\n"
        b"import (\n"
        b'\t"os"\n'
        b'\tm "example.com/proj/pkg/util"\n'
        b'\t_ "example.com/proj/internal/side"\n'
        b'\t. "example.com/proj/dotpkg"\n'
        b")\n"
    )
    modules = {r.module for r in resolver.extract(src)}
    assert modules == {
        "os",
        "example.com/proj/pkg/util",
        "example.com/proj/internal/side",
        "example.com/proj/dotpkg",
    }
    assert all(
        r.level == 0 and r.names == () and r.function_local is False for r in resolver.extract(src)
    )


@_needs_ts
def test_go_resolver_extract_raw_string_import_path():
    # Go's grammar allows a raw (back-quoted) string literal as an import path;
    # the unquoted path must be recovered the same as an interpreted literal.
    (raw,) = resolver.extract(b"package main\n\nimport `fmt`\n")
    assert raw.module == "fmt"


@_needs_ts
def test_go_resolver_extract_reads_committed_fixture():
    # Real tree-sitter output over the COMMITTED fixture file (issue AC).
    src = (_FIXTURE_ROOT / "app" / "main.go").read_bytes()
    modules = {r.module for r in resolver.extract(src)}
    assert modules == {
        "fmt",
        "example.com/root/lib/util",
        "github.com/ext/widget",
    }


# ---------- resolve (pure, runs everywhere) ----------


def test_go_resolver_resolve_discovers_go_mod_and_strips_module_prefix():
    # go.mod at the repo root -> module root is "". The module prefix
    # (example.com/m) is stripped and the remainder maps to the package dir.
    imp = RawImport(module="example.com/m/pkg/util", level=0, names=(), function_local=False)
    files = {"go.mod", "app/main.go", "pkg/util/x.go"}
    assert resolver.resolve("app/main.go", imp, files) == ["pkg/util/x.go"]


def test_go_resolver_resolve_fans_out_to_every_file_in_the_package_dir():
    # Go imports are package-level: one import path -> an edge to EVERY .go file
    # in the target directory, returned sorted for determinism.
    imp = RawImport(module="example.com/m/pkg/util", level=0, names=(), function_local=False)
    files = {"go.mod", "app/main.go", "pkg/util/a.go", "pkg/util/b.go"}
    assert resolver.resolve("app/main.go", imp, files) == ["pkg/util/a.go", "pkg/util/b.go"]


def test_go_resolver_resolve_excludes_test_files_from_package_fan_out():
    # `*_test.go` files are NOT compiled into the imported package for a
    # production import, so the package fan-out must skip them: importing the
    # util package yields an edge ONLY to foo.go, never to foo_test.go (which
    # would forge a false source->test edge). Every Go repo with tests hits this.
    imp = RawImport(module="example.com/m/pkg/util", level=0, names=(), function_local=False)
    files = {"go.mod", "app/main.go", "pkg/util/foo.go", "pkg/util/foo_test.go"}
    assert resolver.resolve("app/main.go", imp, files) == ["pkg/util/foo.go"]


def test_go_resolver_resolve_nearest_go_mod_governs_in_multi_module_repo():
    # Nested module: service/go.mod is the importer's NEAREST enclosing go.mod,
    # so example.com/service/core resolves under service/, never against the
    # outer root module (the decoy core/root.go must NOT be reached).
    imp = RawImport(module="example.com/service/core", level=0, names=(), function_local=False)
    files = {
        "go.mod",
        "service/go.mod",
        "service/cmd/run.go",
        "service/core/c.go",
        "core/root.go",  # same trailing segment under the OUTER module - a decoy
    }
    assert resolver.resolve("service/cmd/run.go", imp, files) == ["service/core/c.go"]


def test_go_resolver_resolve_prefers_longest_matching_suffix_over_a_shallow_decoy():
    # The module prefix is stripped by matching the LONGEST import-path suffix
    # that is a real package dir, so example.com/proj/pkg/util resolves to
    # pkg/util/, never the coincidental shallow util/ (over-stripping guard).
    # decoy.go (a root-level .go file) also exercises the no-"/" parent path.
    imp = RawImport(module="example.com/proj/pkg/util", level=0, names=(), function_local=False)
    files = {"go.mod", "util/z.go", "pkg/util/a.go", "decoy.go", "app/main.go"}
    assert resolver.resolve("app/main.go", imp, files) == ["pkg/util/a.go"]


def test_go_resolver_resolve_external_package_yields_nothing():
    # An import whose path matches no package dir under the module is external
    # (a third-party dependency) -> dropped, no edge.
    imp = RawImport(module="github.com/ext/widget", level=0, names=(), function_local=False)
    files = {"go.mod", "app/main.go", "pkg/util/a.go"}
    assert resolver.resolve("app/main.go", imp, files) == []


def test_go_resolver_resolve_stdlib_import_yields_nothing():
    # A standard-library import (no module-prefix match) -> dropped.
    imp = RawImport(module="fmt", level=0, names=(), function_local=False)
    files = {"go.mod", "app/main.go", "pkg/util/a.go"}
    assert resolver.resolve("app/main.go", imp, files) == []


def test_go_resolver_resolve_without_enclosing_go_mod_yields_nothing():
    # No go.mod on any ancestor of the importer -> the module prefix is unknown,
    # so nothing can be stripped and resolution drops (GOPATH-mode is out of
    # scope for the import graph).
    imp = RawImport(module="example.com/m/pkg", level=0, names=(), function_local=False)
    files = {"loose/a.go", "pkg/x.go"}
    assert resolver.resolve("loose/a.go", imp, files) == []


def test_go_resolver_resolve_empty_import_yields_nothing():
    # Defensive: an empty import path resolves to nothing.
    imp = RawImport(module="", level=0, names=(), function_local=False)
    files = {"go.mod", "app/main.go"}
    assert resolver.resolve("app/main.go", imp, files) == []


def test_go_resolver_resolve_module_root_import_is_not_resolved_to_root_package():
    # REGRESSION (round-3): a prior fix added an EMPTY import-path suffix pass so
    # an import equal to the module path resolved to the module-root package
    # (root-level .go files). Under the path-only contract that pass is UNSAFE:
    # the module-root package also matches EVERY unresolved stdlib/external
    # import (which likewise strips down to nothing local), so it forged a
    # systematic false edge from every such import to the root .go files. With
    # root-level .go files present, an external dependency (github.com/ext/widget)
    # and a stdlib import (fmt) must BOTH resolve to [] - no edge to the root
    # package. (A bare module-root import is dropped for the same reason: a
    # pinned Known limitation - the resolver cannot distinguish it from an
    # external import without the go.mod `module` directive, which the path-only
    # contract does not expose.)
    files = {"go.mod", "a_root.go", "b_root.go", "app/main.go", "pkg/util/a.go"}
    external = RawImport(module="github.com/ext/widget", level=0, names=(), function_local=False)
    stdlib = RawImport(module="fmt", level=0, names=(), function_local=False)
    assert resolver.resolve("app/main.go", external, files) == []
    assert resolver.resolve("app/main.go", stdlib, files) == []


def test_go_resolver_resolve_does_not_cross_a_nested_go_mod_boundary():
    # A root-module importer must NOT resolve a root-relative import path into a
    # subdirectory that has its OWN go.mod (a distinct nested module). service/
    # is a separate module, so the candidate service/core is reached only by
    # crossing service/go.mod and must be skipped -> no false cross-module edge.
    imp = RawImport(module="example.com/root/service/core", level=0, names=(), function_local=False)
    files = {
        "go.mod",
        "service/go.mod",  # nested module boundary between root and service/core
        "app/main.go",
        "service/core/c.go",
    }
    assert resolver.resolve("app/main.go", imp, files) == []


def test_go_resolver_resolve_boundary_rejection_does_not_fall_through_to_a_decoy():
    # Regression: when the LONGEST real package-dir match (service/core) is
    # rejected for crossing a nested go.mod, resolution must DROP the import (it
    # belongs to the nested service/ module) - it must NOT fall through to a
    # SHORTER same-module suffix that shares the trailing segment. Here a
    # root-level core/ dir would be that decoy; a false edge to it is the bug.
    imp = RawImport(
        module="example.com/root/service/core", level=0, names=(), function_local=False
    )
    files = {
        "go.mod",
        "service/go.mod",  # nested module: service/core is a DIFFERENT module
        "app/main.go",
        "service/core/c.go",  # the real (nested-module) target - out of scope
        "core/root.go",  # root-level decoy sharing the trailing segment `core`
    }
    assert resolver.resolve("app/main.go", imp, files) == []


def test_go_resolver_resolve_external_name_collision_is_a_known_limitation():
    # KNOWN LIMITATION (pinned): the path-only resolve() contract does not expose
    # the go.mod `module` directive, so the module prefix is stripped structurally
    # by suffix matching. An EXTERNAL import whose trailing segment collides with
    # a real local package dir is therefore indistinguishable from a local import
    # and yields a (false) edge. Proper disambiguation needs the module path and
    # is out of scope for #356; this test pins current behaviour so a future fix
    # is a deliberate, reviewed change rather than a silent regression.
    imp = RawImport(module="github.com/ext/widget", level=0, names=(), function_local=False)
    files = {"go.mod", "app/main.go", "widget/w.go"}
    assert resolver.resolve("app/main.go", imp, files) == ["widget/w.go"]


# ---------- scan_repo integration (real tree-sitter, committed fixture) ----------


@_needs_ts
def test_go_resolver_scan_fixture_fans_out_and_respects_module_boundaries():
    repo_map = scan_repo(_FIXTURE_ROOT, generator_version="t")
    imports = {(e.source, e.target): e for e in repo_map.edges if e.type == "imports"}

    # Package-level fan-out: app/main.go imports the util PACKAGE -> edges to
    # BOTH files of that package, at high (file-level) confidence.
    assert imports[("file:app/main.go", "file:lib/util/parse.go")].confidence == "high"
    assert ("file:app/main.go", "file:lib/util/format.go") in imports

    # Nested module: service/cmd/run.go resolves against service/go.mod.
    assert ("file:service/cmd/run.go", "file:service/core/core.go") in imports

    # External (github.com/ext/widget) and stdlib (fmt) are dropped: the only
    # edges out of app/main.go are the two util files.
    app_targets = {t for (s, t) in imports if s == "file:app/main.go"}
    assert app_targets == {"file:lib/util/parse.go", "file:lib/util/format.go"}

    # Nearest-go.mod governance: the service importer does not bleed into the
    # outer root module (no edge to lib/util or app).
    svc_targets = {t for (s, t) in imports if s == "file:service/cmd/run.go"}
    assert svc_targets == {"file:service/core/core.go"}
