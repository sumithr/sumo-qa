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

Where these edges come from (NOT scan time today): a real ``scan_repo`` emits
ZERO ``.php`` edges because the foundation scanner does not map ``.php`` files
(``repo_map_scanner._LANGUAGE_BY_EXT`` / ``_PROGRAMMING_LANGS`` omit ``php``), so
no ``php`` node reaches the import-edge layer during a scan. These edges are
produced at the ``infer_imports_edges`` orchestrator layer instead, given ``php``
nodes supplied directly (the orchestrator tests below supply them). The
``Resolver.resolve`` contract passes only the importer path + ``file_set`` (no
repo root / file contents / ``composer.json``), so PSR-4 namespace roots are
injected into ``PhpResolver`` at construction (``PhpResolver.from_composer``);
the registered DEFAULT resolver carries no PSR-4 roots (see
``test_default_resolver_has_no_psr4_roots``). Full scan-time activation needs TWO
foundation changes, deliberately out of this slice: the scanner must stamp
``.php`` -> ``php``, AND the composer autoload roots must be threaded through the
scan.
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
def test_extract_grouped_use_yields_no_edge_known_limitation():
    # Grouped `use App\{Models\User, Models\Order};` is a KNOWN LIMITATION: it
    # yields no import (pinned here, not a wrong edge). The grouped clauses nest
    # under a `namespace_use_group` node, not as direct `namespace_use_clause`
    # children of the declaration, and their names are group-relative, so
    # `_use_imports` (which reads only the declaration's direct clause children)
    # records nothing. Safe by omission; documented in the module docstring.
    src = b"<?php\nuse App\\Models\\{User, Order};\n"
    assert PhpResolver().extract(src) == []


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
def test_extract_mixed_variable_concat_require_yields_no_import():
    # Regression (codex #361 final-gate catch): `require $base . 'helpers.php';`
    # concatenates a VARIABLE with a literal. The concrete path depends on
    # `$base` at runtime, so resolving it from the `helpers.php` fragment alone
    # would emit a WRONG importer-relative edge whenever a same-named file sits
    # beside the importer. The mixed dynamic argument must yield NO import.
    assert PhpResolver().extract(b"<?php\nrequire $base . 'helpers.php';\n") == []


@_needs_ts
def test_extract_mixed_variable_concat_emits_no_edge_even_if_sibling_exists():
    # The concrete pre-fix defect: with `src/Controllers/helpers.php` present,
    # the resolver extracted "helpers.php" and resolved it importer-relative to
    # that sibling -> a wrong edge. The dynamic-operand guard drops the require
    # at extract, so no RawImport (and hence no edge) is ever produced.
    resolver = PhpResolver()
    raws = resolver.extract(b"<?php\nrequire $base . 'helpers.php';\n")
    assert raws == []
    file_set = {"src/Controllers/UserController.php", "src/Controllers/helpers.php"}
    edges = [
        target
        for raw in raws
        for target in resolver.resolve("src/Controllers/UserController.php", raw, file_set)
    ]
    assert edges == []


@_needs_ts
def test_extract_mixed_constant_concat_require_yields_no_import():
    # `require ROOT . '/x.php';` concatenates a user CONSTANT (unknown value)
    # with a literal -> unresolvable from paths alone -> no import. Only the
    # `__DIR__` magic constant is treated as a known static anchor.
    assert PhpResolver().extract(b"<?php\nrequire ROOT . '/x.php';\n") == []


@_needs_ts
def test_extract_mixed_function_call_concat_require_yields_no_import():
    # `require dirname(__FILE__) . '/x.php';` concatenates a function CALL with a
    # literal -> the call result is not statically known -> no import.
    assert PhpResolver().extract(b"<?php\nrequire dirname(__FILE__) . '/x.php';\n") == []


@_needs_ts
def test_extract_ternary_require_yields_no_import():
    # Regression (codex #361 final-gate catch): a ternary `require true ? 'a.php'
    # : 'b.php';` picks ONE branch at runtime -- the two string literals are
    # alternatives, not a concatenation -- so joining them would fabricate a
    # nonsense path (`a.phpb.php`). A bare `true`/`1` condition carries no `name`
    # to catch, so the ternary itself must drop the require -> no import.
    assert PhpResolver().extract(b"<?php\nrequire true ? 'a.php' : 'b.php';\n") == []


@_needs_ts
def test_extract_bare_absolute_require_yields_no_import():
    # `require '/helpers.php'` is a BARE absolute path: PHP resolves a leading-`/`
    # literal from the FILESYSTEM ROOT, not the importing file's directory, so it
    # points outside the repo and must yield NO import (dropping it here is what
    # keeps resolve from mistaking it for an importer-relative path). Contrast the
    # `__DIR__ . '/x'` form (test above), whose leading `/` is only a separator
    # and stays importer-relative.
    assert PhpResolver().extract(b"<?php\nrequire '/helpers.php';\n") == []


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


def test_resolve_psr4_longest_prefix_is_definitive_no_shorter_fallback():
    # Strict PSR-4: the LONGEST matching prefix wins definitively. If its file is
    # absent the resolver must NOT fall back to a shorter matching prefix, even
    # when the shorter prefix's file exists -- a real PSR-4 autoloader never does
    # that, so falling through would emit an autoloader-incorrect edge.
    r = PhpResolver({"App\\": "src/", "App\\Tests\\": "tests/"})
    imp = RawImport(module="App\\Tests\\UserTest", level=0, names=(), function_local=False)
    # Longest prefix `App\Tests\` -> tests/UserTest.php is ABSENT; the shorter
    # `App\` -> src/Tests/UserTest.php IS present (a discriminating collision).
    files = {"src/Tests/UserTest.php"}
    assert r.resolve("x.php", imp, files) == []


def test_resolve_psr4_root_dir_maps_to_repo_root():
    # A PSR-4 root mapped to "." (the repo root) drops the directory prefix.
    r = PhpResolver({"App\\": "."})
    imp = RawImport(module="App\\Top", level=0, names=(), function_local=False)
    assert r.resolve("a.php", imp, {"Top.php"}) == ["Top.php"]


def test_resolve_psr4_empty_root_namespace_prefix_maps_full_fqn():
    # composer's root-namespace mapping `{"": "src/"}` (an EMPTY PSR-4 prefix)
    # matches ANY FQN and maps its full namespace path under the base dir, so
    # `Acme\Widget` resolves to `src/Acme/Widget.php`. The empty prefix must NOT
    # be normalised to `\` (extracted FQNs have their leading `\` stripped, so a
    # `\` prefix would match nothing).
    r = PhpResolver({"": "src/"})
    imp = RawImport(module="Acme\\Widget", level=0, names=(), function_local=False)
    assert r.resolve("x.php", imp, {"src/Acme/Widget.php"}) == ["src/Acme/Widget.php"]


def test_resolve_psr4_empty_root_namespace_is_least_specific():
    # The empty root-namespace prefix is the LEAST specific: a more specific
    # prefix still wins, and the empty prefix only catches what no other claims.
    r = PhpResolver({"": "src/", "App\\": "lib/"})
    app = RawImport(module="App\\Thing", level=0, names=(), function_local=False)
    other = RawImport(module="Acme\\Widget", level=0, names=(), function_local=False)
    files = {"lib/Thing.php", "src/Acme/Widget.php"}
    assert r.resolve("x.php", app, files) == ["lib/Thing.php"]  # App\ wins
    assert r.resolve("x.php", other, files) == ["src/Acme/Widget.php"]  # empty catches


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


def test_from_composer_merges_duplicate_prefix_across_sections():
    # Composer MERGES the base dirs when the SAME PSR-4 prefix appears in both
    # `autoload` and `autoload-dev` (production dirs first); the dev root must
    # not OVERWRITE the production root. `App\Models\User` must keep resolving
    # via src/ (present in the file set, so an overwrite is discriminating),
    # and a dev-rooted class must still resolve via tests/.
    composer = {
        "autoload": {"psr-4": {"App\\": "src/"}},
        "autoload-dev": {"psr-4": {"App\\": "tests/"}},
    }
    r = PhpResolver.from_composer(composer)
    prod = RawImport(module="App\\Models\\User", level=0, names=(), function_local=False)
    dev = RawImport(module="App\\Unit\\UserTest", level=0, names=(), function_local=False)
    files = {"src/Models/User.php", "tests/Unit/UserTest.php"}
    assert r.resolve("x.php", prod, files) == ["src/Models/User.php"]
    assert r.resolve("x.php", dev, files) == ["tests/Unit/UserTest.php"]
    # Production dirs come FIRST: a class present under BOTH roots resolves via
    # the `autoload` dir, matching composer's merge order.
    both = RawImport(module="App\\Shared", level=0, names=(), function_local=False)
    assert r.resolve("x.php", both, {"src/Shared.php", "tests/Shared.php"}) == ["src/Shared.php"]


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
    # At the infer_imports_edges orchestrator layer with the registered DEFAULT
    # resolver (no composer), relative require edges resolve but PSR-4 use edges
    # do NOT (they need composer config injected). NOTE this is the orchestrator
    # layer given php nodes directly; a real scan_repo maps no .php files, so it
    # emits no php edges at all -- the documented foundation gap.
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
