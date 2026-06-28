# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Unit tests for the PHP import resolver (#361).

``extract`` is tested against REAL tree-sitter output (skipped without the
extra), including a committed ``.php`` fixture mini-repo under
``tests/fixtures/repo_map/php/``; ``resolve`` is pure path arithmetic over a
supplied file set and a PSR-4 map, and runs on every interpreter. Each
``resolve`` case names the UA PHP rule it exercises: PSR-4 ``use`` mapping via
the ``composer.json`` autoload roots (longest namespace-prefix wins), relative
``require``/``include`` paths anchored to the importing file, and vendor /
external namespaces dropped.

Scan-time activation caveat: the ``Resolver.resolve`` contract passes only the
importer path + ``file_set`` (no repo root / file contents / ``composer.json``),
so the PSR-4 namespace roots are injected into ``PhpResolver`` at construction
(``PhpResolver.from_composer``) rather than read mid-scan. The registered
DEFAULT resolver therefore carries no PSR-4 roots — relative ``require``/
``include`` edges still resolve at scan time, but PSR-4 ``use`` edges need the
parsed composer config injected (see ``test_default_resolver_has_no_psr4_roots``
and the orchestrator tests). Wiring composer-driven construction through the
scan is a foundation enhancement, deliberately out of this slice.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from sumo_qa.repo_map_imports import infer_imports_edges
from sumo_qa.repo_map_models import RepoMapNode
from sumo_qa.repo_map_resolvers import get_resolver, registered_languages
from sumo_qa.repo_map_resolvers.base import RawImport, register
from sumo_qa.repo_map_resolvers.php import PhpResolver
from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "repo_map" / "php"

# A resolver wired with the fixture's PSR-4 roots, for the pure resolve cases.
resolver = PhpResolver({"App\\": "src/"})

_needs_ts = pytest.mark.skipif(
    not TREESITTER_AVAILABLE,
    reason="tree-sitter not installed (the [treesitter] extra is absent)",
)


# ---------- registry ----------


def test_php_resolver_is_registered():
    assert "php" in registered_languages()
    assert get_resolver("php") is not None


# ---------- extract (real tree-sitter) ----------


@_needs_ts
def test_extract_use_maps_namespace_class():
    (raw,) = PhpResolver().extract(b"<?php\nuse App\\Models\\User;\n")
    assert raw.module == "App\\Models\\User"  # the fully-qualified name as written
    assert raw.level == 0  # 0 = namespace `use` import
    assert raw.function_local is False


@_needs_ts
def test_extract_aliased_use_keeps_fqn_not_alias():
    # `use App\Models\Order as O;` -> the FQN, not the local alias `O`.
    (raw,) = PhpResolver().extract(b"<?php\nuse App\\Models\\Order as O;\n")
    assert raw.module == "App\\Models\\Order"


@_needs_ts
def test_extract_leading_backslash_use_is_stripped():
    # A leading root separator is not part of the namespace prefix.
    (raw,) = PhpResolver().extract(b"<?php\nuse \\App\\Models\\User;\n")
    assert raw.module == "App\\Models\\User"


@_needs_ts
def test_extract_unqualified_use_uses_bare_name():
    # `use User;` (a single, unqualified name) -> module is the bare name.
    (raw,) = PhpResolver().extract(b"<?php\nuse User;\n")
    assert raw.module == "User"


@_needs_ts
def test_extract_use_function_is_skipped():
    # `use function` / `use const` import a SYMBOL, not a PSR-4 class, so they
    # carry no class file to map and must be dropped (mapping them via PSR-4
    # would fabricate an edge to a class file that does not exist).
    assert PhpResolver().extract(b"<?php\nuse function App\\helpers\\format;\n") == []
    assert PhpResolver().extract(b"<?php\nuse const App\\config\\TIMEOUT;\n") == []


@_needs_ts
def test_extract_require_and_include_relative_paths():
    raws = PhpResolver().extract(b"<?php\nrequire 'helpers.php';\ninclude '../shared/util.php';\n")
    by_module = {(r.module, r.level) for r in raws}
    assert ("helpers.php", 1) in by_module  # 1 = filesystem require/include import
    assert ("../shared/util.php", 1) in by_module


@_needs_ts
def test_extract_require_once_dir_concat_keeps_string_literal():
    # `require_once __DIR__ . '/lib/db.php'` -> the concatenated path literal;
    # `__DIR__` resolves to the importing file's directory (handled in resolve).
    (raw,) = PhpResolver().extract(b"<?php\nrequire_once __DIR__ . '/lib/db.php';\n")
    assert raw.module == "/lib/db.php"
    assert raw.level == 1


@_needs_ts
def test_extract_dynamic_require_yields_no_import():
    # `require $path;` has no static path literal -> nothing to resolve.
    assert PhpResolver().extract(b"<?php\nrequire $path;\n") == []


@_needs_ts
def test_extract_top_level_require_not_function_local():
    (raw,) = PhpResolver().extract(b"<?php\nrequire 'top.php';\n")
    assert raw.function_local is False


@_needs_ts
def test_extract_function_local_require_is_flagged():
    # A require inside a function body is a lazy/deferred import -> medium
    # confidence downstream, so it is flagged function_local.
    src = b"<?php\nfunction loader() {\n    require 'deferred.php';\n}\n"
    (raw,) = PhpResolver().extract(src)
    assert raw.function_local is True


@_needs_ts
def test_extract_method_local_require_is_flagged():
    # A require inside a class method body is equally lazy -> function_local.
    src = b"<?php\nclass C {\n    public function m() {\n        require 'm.php';\n    }\n}\n"
    (raw,) = PhpResolver().extract(src)
    assert raw.function_local is True


@_needs_ts
def test_extract_from_committed_fixture_controller():
    # Real tree-sitter over a COMMITTED .php fixture: the controller's three
    # imports (PSR-4 use, vendor use, relative require via __DIR__).
    src = (FIXTURE_ROOT / "src/Controllers/UserController.php").read_bytes()
    modules = {(r.module, r.level) for r in PhpResolver().extract(src)}
    assert ("App\\Models\\User", 0) in modules  # PSR-4 use
    assert ("Monolog\\Logger", 0) in modules  # vendor use (dropped at resolve)
    assert ("/../helpers.php", 1) in modules  # relative require via __DIR__


# ---------- resolve (pure, runs everywhere) ----------


def test_resolve_psr4_use_maps_to_file():
    # PSR-4: namespace-prefix `App\` -> dir `src/`, so `App\Models\User`
    # resolves to `src/Models/User.php`.
    imp = RawImport(module="App\\Models\\User", level=0, names=(), function_local=False)
    files = {"src/Models/User.php"}
    assert resolver.resolve("src/Controllers/UserController.php", imp, files) == [
        "src/Models/User.php"
    ]


def test_resolve_psr4_longest_prefix_wins():
    # Two PSR-4 roots, one a prefix of the other. `App\Tests\UserTest` must map
    # via the LONGER prefix `App\Tests\` -> `tests/`, never the shorter `App\`
    # -> `src/Tests/UserTest.php` (present in the file set, so the choice is
    # discriminating).
    r = PhpResolver({"App\\": "src/", "App\\Tests\\": "tests/"})
    imp = RawImport(module="App\\Tests\\UserTest", level=0, names=(), function_local=False)
    files = {"tests/UserTest.php", "src/Tests/UserTest.php"}
    assert r.resolve("x.php", imp, files) == ["tests/UserTest.php"]


def test_resolve_psr4_root_dir_maps_to_repo_root():
    # A PSR-4 root mapped to "." (the repo root) drops the directory prefix.
    r = PhpResolver({"App\\": "."})
    imp = RawImport(module="App\\Top", level=0, names=(), function_local=False)
    assert r.resolve("a.php", imp, {"Top.php"}) == ["Top.php"]


def test_resolve_vendor_namespace_dropped():
    # A namespace with no matching PSR-4 prefix is external/vendor -> no edge.
    imp = RawImport(module="Monolog\\Logger", level=0, names=(), function_local=False)
    assert resolver.resolve("src/app.php", imp, {"src/Models/User.php"}) == []


def test_resolve_psr4_class_file_absent_yields_nothing():
    # A namespace that matches a PSR-4 prefix but whose file does not exist in
    # the repo yields no edge (no dangling target).
    imp = RawImport(module="App\\Models\\Ghost", level=0, names=(), function_local=False)
    assert resolver.resolve("src/app.php", imp, {"src/Models/User.php"}) == []


def test_resolve_relative_require_anchors_to_importer_dir():
    # `require '../helpers.php'` from src/Controllers/ walks up to src/.
    imp = RawImport(module="../helpers.php", level=1, names=(), function_local=False)
    files = {"src/helpers.php"}
    assert resolver.resolve("src/Controllers/UserController.php", imp, files) == ["src/helpers.php"]


def test_resolve_require_dir_leading_slash_is_importer_relative():
    # The `__DIR__ . '/../helpers.php'` form arrives as `/../helpers.php`; the
    # leading separator anchors to the importer's directory, not the repo root.
    imp = RawImport(module="/../helpers.php", level=1, names=(), function_local=False)
    files = {"src/helpers.php"}
    assert resolver.resolve("src/Controllers/UserController.php", imp, files) == ["src/helpers.php"]


def test_resolve_relative_require_target_absent_yields_nothing():
    imp = RawImport(module="missing.php", level=1, names=(), function_local=False)
    assert resolver.resolve("src/app.php", imp, {"src/app.php"}) == []


def test_default_resolver_has_no_psr4_roots():
    # The module-default resolver (no composer injected) carries no PSR-4 roots,
    # so PSR-4 `use` imports drop. Scan-time PSR-4 activation needs the parsed
    # composer config injected -- a foundation enhancement, out of this slice.
    imp = RawImport(module="App\\Models\\User", level=0, names=(), function_local=False)
    assert PhpResolver().resolve("src/app.php", imp, {"src/Models/User.php"}) == []


# ---------- from_composer (PSR-4 map construction) ----------


def test_from_composer_builds_psr4_map_from_committed_composer():
    composer = json.loads((FIXTURE_ROOT / "composer.json").read_text(encoding="utf-8"))
    r = PhpResolver.from_composer(composer)
    imp = RawImport(module="App\\Models\\User", level=0, names=(), function_local=False)
    assert r.resolve("src/app.php", imp, {"src/Models/User.php"}) == ["src/Models/User.php"]


def test_from_composer_includes_autoload_dev_roots():
    composer = {
        "autoload": {"psr-4": {"App\\": "src/"}},
        "autoload-dev": {"psr-4": {"App\\Tests\\": "tests/"}},
    }
    r = PhpResolver.from_composer(composer)
    imp = RawImport(module="App\\Tests\\Unit", level=0, names=(), function_local=False)
    assert r.resolve("x.php", imp, {"tests/Unit.php"}) == ["tests/Unit.php"]


def test_from_composer_psr4_prefix_with_list_of_dirs():
    # PSR-4 allows a prefix to map to a LIST of base dirs; each is probed in
    # order and the first existing file wins.
    composer = {"autoload": {"psr-4": {"App\\": ["src/", "lib/"]}}}
    r = PhpResolver.from_composer(composer)
    imp = RawImport(module="App\\Thing", level=0, names=(), function_local=False)
    assert r.resolve("a.php", imp, {"lib/Thing.php"}) == ["lib/Thing.php"]


def test_from_composer_tolerates_missing_autoload():
    r = PhpResolver.from_composer({})
    imp = RawImport(module="App\\X", level=0, names=(), function_local=False)
    assert r.resolve("a.php", imp, {"src/X.php"}) == []


# ---------- orchestrator integration (real tree-sitter, committed fixture) ----------


@pytest.fixture
def php_registry_with_composer() -> Iterator[None]:
    """Register a composer-configured PhpResolver for the orchestrator path,
    then restore the module-default (empty-PSR-4) resolver after the test."""
    composer = json.loads((FIXTURE_ROOT / "composer.json").read_text(encoding="utf-8"))
    register(PhpResolver.from_composer(composer))
    try:
        yield
    finally:
        register(PhpResolver())  # restore the module-default


@_needs_ts
def test_orchestrator_emits_psr4_and_require_edges_from_committed_fixture(
    php_registry_with_composer: None,
):
    # End-to-end through infer_imports_edges over the COMMITTED php fixture, with
    # the resolver configured from composer.json: a PSR-4 `use` edge AND a
    # relative `require` edge, with the vendor `use` (Monolog) producing no edge.
    nodes = [
        RepoMapNode(
            id="file:src/Controllers/UserController.php",
            type="source_file",
            path="src/Controllers/UserController.php",
            language="php",
        ),
        RepoMapNode(
            id="file:src/Models/User.php",
            type="source_file",
            path="src/Models/User.php",
            language="php",
        ),
        RepoMapNode(
            id="file:src/helpers.php",
            type="source_file",
            path="src/helpers.php",
            language="php",
        ),
    ]
    edges = infer_imports_edges(nodes, FIXTURE_ROOT)
    pairs = {(e.source, e.target) for e in edges}
    controller = "file:src/Controllers/UserController.php"
    assert (controller, "file:src/Models/User.php") in pairs  # PSR-4 use
    assert (controller, "file:src/helpers.php") in pairs  # relative require
    # The vendor use (Monolog\Logger) maps to no node -> no dangling edge.
    assert all("Monolog" not in t and "Logger" not in t for _, t in pairs)
    # every edge endpoint resolves to a real node
    node_ids = {n.id for n in nodes}
    for e in edges:
        assert e.source in node_ids and e.target in node_ids


@_needs_ts
def test_orchestrator_default_resolver_emits_require_but_not_psr4(tmp_path: Path):
    # With the registered DEFAULT resolver (no composer), relative require edges
    # still resolve at scan time, but PSR-4 use edges do NOT (they need composer
    # config injected) -- the documented scan-time foundation gap, asserted.
    (tmp_path / "src" / "Models").mkdir(parents=True)
    (tmp_path / "src" / "a.php").write_text(
        "<?php\nrequire 'b.php';\nuse App\\Models\\User;\n", encoding="utf-8", newline=""
    )
    (tmp_path / "src" / "b.php").write_text("<?php\n", encoding="utf-8", newline="")
    (tmp_path / "src" / "Models" / "User.php").write_text("<?php\n", encoding="utf-8", newline="")
    nodes = [
        RepoMapNode(id="file:src/a.php", type="source_file", path="src/a.php", language="php"),
        RepoMapNode(id="file:src/b.php", type="source_file", path="src/b.php", language="php"),
        RepoMapNode(
            id="file:src/Models/User.php",
            type="source_file",
            path="src/Models/User.php",
            language="php",
        ),
    ]
    pairs = {(e.source, e.target) for e in infer_imports_edges(nodes, tmp_path)}
    assert ("file:src/a.php", "file:src/b.php") in pairs  # relative require resolves
    assert ("file:src/a.php", "file:src/Models/User.php") not in pairs  # PSR-4 needs composer
