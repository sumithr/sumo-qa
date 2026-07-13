# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Unit + integration tests for the TypeScript/JavaScript import resolver (#355).

``extract`` is tested against REAL tree-sitter output (skipped without the
``[treesitter]`` extra); ``resolve`` is pure path arithmetic over a supplied
file set and runs on every interpreter. The file set and the ``tsconfig.json``
used by the alias cases come from a COMMITTED mini-repo
(``tests/fixtures/repo_map/ts_import_repo``), and the orchestrator integration
test scans that same committed fixture through ``scan_repo`` — real tree-sitter,
no mocked parser output. Each ``resolve`` case names the UA rule it exercises:
relative dot-anchoring with extension probing, ``index.*`` barrels, tsconfig
``paths``/``baseUrl`` aliasing, and the bare/external drop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sumo_qa.repo_map_models import RepoMapNode
from sumo_qa.repo_map_resolvers import get_resolver, registered_languages
from sumo_qa.repo_map_resolvers.base import RawImport
from sumo_qa.repo_map_resolvers.typescript import (
    JAVASCRIPT_CONFIG,
    TYPESCRIPT_CONFIG,
    TsConfig,
    TypeScriptResolver,
    parse_tsconfig,
)
from sumo_qa.repo_map_scanner import scan_repo
from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE

ts = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx")
js = TypeScriptResolver(JAVASCRIPT_CONFIG, grammar="javascript")

_FIXTURE = Path(__file__).parent / "fixtures" / "repo_map" / "ts_import_repo"

# The committed mini-repo's repo-relative file set, the same paths scan_repo
# would stamp on nodes — so resolve() unit cases run against real fixture paths.
_FILE_SET = {
    "src/app.ts",
    "src/util.ts",
    "src/config.ts",
    "src/components/index.ts",
    "src/components/Button.tsx",
    "src/ui/App.jsx",
    "legacy/old.js",
    "tsconfig.json",
}


_needs_ts = pytest.mark.skipif(
    not TREESITTER_AVAILABLE,
    reason="tree-sitter not installed (the [treesitter] extra is absent)",
)


# ---------- registry ----------


def test_typescript_and_javascript_are_registered():
    languages = registered_languages()
    assert "typescript" in languages
    assert "javascript" in languages
    assert get_resolver("typescript") is not None
    assert get_resolver("javascript") is not None


def test_registered_resolvers_carry_matching_config_id():
    assert get_resolver("typescript").config.id == "typescript"
    assert get_resolver("javascript").config.id == "javascript"


# ---------- extract (real tree-sitter) ----------


@_needs_ts
def test_extract_named_default_and_namespace_imports():
    src = (
        b"import { a, b } from './named';\n"
        b"import Def from '../def';\n"
        b"import * as ns from '@app/util';\n"
    )
    modules = {(r.module, r.function_local) for r in ts.extract(src)}
    assert ("./named", False) in modules
    assert ("../def", False) in modules
    assert ("@app/util", False) in modules


@_needs_ts
def test_extract_side_effect_import_has_specifier():
    (raw,) = ts.extract(b"import './side-effect';\n")
    assert raw.module == "./side-effect"
    assert raw.function_local is False


@_needs_ts
def test_extract_reexport_names_the_module_but_plain_export_does_not():
    # `export { x } from './re'` and `export * from './star'` re-export a module;
    # a plain `export const y = ...` (and `export default '...'`) name no module.
    raws = ts.extract(
        b"export { x } from './re';\n"
        b"export * from './star';\n"
        b"export const y = 1;\n"
        b"export default 'not-a-module';\n"
    )
    modules = {r.module for r in raws}
    assert modules == {"./re", "./star"}


@_needs_ts
def test_extract_require_and_dynamic_import():
    src = b"const m = require('./req');\nconst p = import('./dyn');\n"
    modules = {r.module for r in js.extract(src)}
    assert modules == {"./req", "./dyn"}


@_needs_ts
def test_extract_flags_function_local_require_but_not_top_level():
    # A top-level require is eager (high); a require nested in a function body is
    # lazy (medium) — mirrors the Python resolver's function_local semantics.
    src = b"const top = require('./top');\nfunction f(){ const a = require('./infn'); }\n"
    by_module = {r.module: r for r in js.extract(src)}
    assert by_module["./top"].function_local is False
    assert by_module["./infn"].function_local is True


@_needs_ts
def test_extract_import_require_clause_specifier():
    # TS import-require `import foo = require('./foo')` carries its specifier as a
    # `string` nested in an `import_require_clause`, not a direct statement child;
    # it is a module-level (eager) import, so function_local is False.
    (raw,) = ts.extract(b'import foo = require("./foo");\n')
    assert raw.module == "./foo"
    assert raw.function_local is False


def test_import_require_specifier_resolves_to_ts_source():
    # End-to-end for the import-require form: the extracted `./foo` resolves to
    # its `.ts` file (extract tested above under real tree-sitter).
    imp = RawImport(module="./foo", level=0, names=(), function_local=False)
    assert ts.resolve("src/app.ts", imp, {"src/app.ts", "src/foo.ts"}) == ["src/foo.ts"]


@_needs_ts
def test_extract_bare_specifier_is_captured_as_module():
    # extract does no resolution — a bare specifier is still captured; the drop
    # happens in resolve (no file_set match).
    (raw,) = ts.extract(b"import _ from 'lodash';\n")
    assert raw.module == "lodash"


@_needs_ts
def test_extract_ignores_non_import_calls():
    # A plain function call is not a require / dynamic import -> no specifier.
    assert ts.extract(b"doThing('x');\nconst y = compute(2);\n") == []


@_needs_ts
def test_extract_computed_require_is_skipped():
    # require(<variable>) carries no static string -> nothing to resolve.
    assert js.extract(b"const x = require(dynamicName);\n") == []


@_needs_ts
def test_extract_empty_specifier_literal():
    # `import ''` is degenerate: the string node has no fragment, so the module
    # is the empty string (resolve drops it — see the resolve guard below).
    (raw,) = ts.extract(b"import '';\n")
    assert raw.module == ""


# ---------- resolve: relative + extension probing ----------


def test_resolve_relative_import_probes_extension():
    # `./util` from src/app.ts -> src/util.ts (extension probing).
    imp = RawImport(module="./util", level=0, names=(), function_local=False)
    assert ts.resolve("src/app.ts", imp, _FILE_SET) == ["src/util.ts"]


def test_resolve_relative_directory_import_resolves_index_barrel():
    # `./components` from src/app.ts -> src/components/index.ts (barrel).
    imp = RawImport(module="./components", level=0, names=(), function_local=False)
    assert ts.resolve("src/app.ts", imp, _FILE_SET) == ["src/components/index.ts"]


def test_resolve_parent_relative_barrel_across_directories():
    # `../components` from src/ui/App.jsx -> src/components/index.ts.
    imp = RawImport(module="../components", level=0, names=(), function_local=False)
    assert js.resolve("src/ui/App.jsx", imp, _FILE_SET) == ["src/components/index.ts"]


def test_resolve_js_specifier_falls_back_to_ts_source():
    # A `.js` specifier resolves to its `.ts` source sibling (TS emits .js, the
    # author imports the source) — './util.js' -> src/util.ts.
    imp = RawImport(module="./util.js", level=0, names=(), function_local=False)
    assert ts.resolve("src/app.ts", imp, _FILE_SET) == ["src/util.ts"]


def test_resolve_relative_overshoot_past_root_yields_nothing():
    # More `..` than there are ancestor directories cannot resolve (boundary).
    imp = RawImport(module="../../../util", level=0, names=(), function_local=False)
    assert ts.resolve("src/app.ts", imp, _FILE_SET) == []


def test_resolve_relative_import_probes_mjs_and_cjs_extensions():
    # The scanner assigns .mjs/.cjs the `javascript` language, so an import must be
    # able to RESOLVE to one — `./esm` -> pkg/esm.mjs, `./legacy` -> pkg/legacy.cjs.
    file_set = {"pkg/main.js", "pkg/esm.mjs", "pkg/legacy.cjs"}
    esm = RawImport(module="./esm", level=0, names=(), function_local=False)
    cjs = RawImport(module="./legacy", level=0, names=(), function_local=False)
    assert js.resolve("pkg/main.js", esm, file_set) == ["pkg/esm.mjs"]
    assert js.resolve("pkg/main.js", cjs, file_set) == ["pkg/legacy.cjs"]


def test_resolve_directory_import_resolves_mjs_and_cjs_barrels():
    # `.mjs`/`.cjs` are probe extensions, so the `index.*` barrels must include
    # them too: a directory import `./pkg` reaches pkg/index.mjs, `./pkg2` reaches
    # pkg2/index.cjs (both javascript-language files the scanner assigns).
    file_set = {"app.js", "pkg/index.mjs", "pkg2/index.cjs"}
    esm = RawImport(module="./pkg", level=0, names=(), function_local=False)
    cjs = RawImport(module="./pkg2", level=0, names=(), function_local=False)
    assert js.resolve("app.js", esm, file_set) == ["pkg/index.mjs"]
    assert js.resolve("app.js", cjs, file_set) == ["pkg2/index.cjs"]


def test_resolve_extension_precedence_picks_first_match_only():
    # When both util.ts and util.js exist, `./util` resolves to the higher-
    # precedence util.ts ONLY (TS picks a single module by _PROBE_EXTENSIONS
    # precedence) — probing stops at the first match, never emitting both.
    file_set = {"src/app.ts", "src/util.ts", "src/util.js"}
    imp = RawImport(module="./util", level=0, names=(), function_local=False)
    assert ts.resolve("src/app.ts", imp, file_set) == ["src/util.ts"]


def test_resolve_barrel_precedence_picks_first_match_only():
    # When a directory has BOTH pkg/index.ts and pkg/index.js, the directory
    # import `./pkg` resolves to the higher-precedence pkg/index.ts ONLY (TS
    # picks a single barrel by _INDEX_BARRELS precedence) — the barrel loop stops
    # at the first existing barrel, never emitting both edges.
    file_set = {"src/app.ts", "src/pkg/index.ts", "src/pkg/index.js"}
    imp = RawImport(module="./pkg", level=0, names=(), function_local=False)
    assert ts.resolve("src/app.ts", imp, file_set) == ["src/pkg/index.ts"]


def test_resolve_explicit_js_extension_prefers_exact_file_over_ts_sibling():
    # An explicit `./util.js` with BOTH util.js and util.ts present resolves to
    # util.js ALONE — the exact file IS the target; the `.js` -> `.ts` rewrite is
    # only a fallback when the `.js` file is absent (never a second edge).
    file_set = {"src/app.ts", "src/util.js", "src/util.ts"}
    imp = RawImport(module="./util.js", level=0, names=(), function_local=False)
    assert ts.resolve("src/app.ts", imp, file_set) == ["src/util.js"]


def test_resolve_file_shadows_directory_index_barrel():
    # TS resolution prefers a same-named FILE over a directory's index barrel, so
    # `./components` with BOTH components.ts and components/index.ts present
    # resolves to the file only (no phantom barrel edge).
    file_set = {"src/app.ts", "src/components.ts", "src/components/index.ts"}
    imp = RawImport(module="./components", level=0, names=(), function_local=False)
    assert ts.resolve("src/app.ts", imp, file_set) == ["src/components.ts"]


# ---------- resolve: external / bare ----------


def test_resolve_bare_specifier_without_tsconfig_is_dropped():
    # No tsconfig injected (the registered-resolver shape): a non-relative bare
    # specifier is external -> no edge.
    imp = RawImport(module="lodash", level=0, names=(), function_local=False)
    assert ts.resolve("src/app.ts", imp, _FILE_SET) == []


def test_resolve_external_under_baseurl_still_dropped_when_no_file():
    # Even with a baseUrl, a bare package name resolves to no repo file -> dropped
    # (there is no src/react.ts), so react/lodash stay external.
    tsconfig = parse_tsconfig((_FIXTURE / "tsconfig.json").read_text())
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="react", level=0, names=(), function_local=False)
    assert resolver.resolve("src/app.ts", imp, _FILE_SET) == []


# ---------- resolve: tsconfig paths / baseUrl aliases ----------


def test_parse_tsconfig_reads_baseurl_and_paths():
    tsconfig = parse_tsconfig((_FIXTURE / "tsconfig.json").read_text())
    assert tsconfig.base_url == "src"
    paths = dict(tsconfig.paths)
    # targets are resolved repo-relative (joined through baseUrl="src").
    assert paths["@app/*"] == ("src/*",)
    assert paths["@config"] == ("src/config.ts",)


def test_parse_tsconfig_tolerates_jsonc_comments_and_trailing_commas():
    # Real tsconfig.json files are JSONC — line/block comments and trailing commas.
    text = """
    {
      // module resolution
      "compilerOptions": {
        "baseUrl": "src", /* root for non-relative imports */
        "paths": {
          "@app/*": ["*"],
        },
      },
    }
    """
    tsconfig = parse_tsconfig(text)
    assert tsconfig.base_url == "src"
    assert dict(tsconfig.paths)["@app/*"] == ("src/*",)


def test_resolve_tsconfig_wildcard_path_alias():
    # `@app/config` -> paths "@app/*": ["*"] under baseUrl src -> src/config.ts.
    tsconfig = parse_tsconfig((_FIXTURE / "tsconfig.json").read_text())
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="@app/config", level=0, names=(), function_local=False)
    assert resolver.resolve("src/app.ts", imp, _FILE_SET) == ["src/config.ts"]


def test_resolve_tsconfig_exact_path_alias():
    # `@config` -> exact paths "@config": ["config.ts"] under baseUrl src.
    tsconfig = parse_tsconfig((_FIXTURE / "tsconfig.json").read_text())
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="@config", level=0, names=(), function_local=False)
    assert resolver.resolve("src/app.ts", imp, _FILE_SET) == ["src/config.ts"]


def test_resolve_baseurl_non_relative_specifier():
    # With baseUrl="src" and no matching paths pattern, `util` resolves from the
    # baseUrl root -> src/util.ts (TS baseUrl semantics).
    tsconfig = parse_tsconfig((_FIXTURE / "tsconfig.json").read_text())
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="util", level=0, names=(), function_local=False)
    assert resolver.resolve("src/app.ts", imp, _FILE_SET) == ["src/util.ts"]


def test_resolve_empty_specifier_yields_nothing():
    # An empty module string resolves to nothing (the degenerate `import ''`).
    imp = RawImport(module="", level=0, names=(), function_local=False)
    assert ts.resolve("src/app.ts", imp, _FILE_SET) == []


def test_resolve_wildcard_pattern_with_non_wildcard_target():
    # A wildcard pattern may map every match onto a single non-wildcard target
    # (a shim): "@app/*": ["util.ts"] -> any "@app/x" resolves to src/util.ts.
    tsconfig = parse_tsconfig(
        '{"compilerOptions": {"baseUrl": "src", "paths": {"@app/*": ["util.ts"]}}}'
    )
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="@app/anything", level=0, names=(), function_local=False)
    assert resolver.resolve("src/app.ts", imp, _FILE_SET) == ["src/util.ts"]


def test_resolve_alias_miss_without_baseurl_is_external():
    # paths but no baseUrl: a specifier matching no pattern has no baseUrl root to
    # fall back to -> external (dropped).
    tsconfig = parse_tsconfig('{"compilerOptions": {"paths": {"@x/*": ["lib/*"]}}}')
    assert tsconfig.base_url is None  # fixture sanity
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="@other/thing", level=0, names=(), function_local=False)
    assert resolver.resolve("src/app.ts", imp, _FILE_SET) == []


def test_resolve_catch_all_star_pattern_alias():
    # A bare "*" catch-all captures the whole specifier: "*": ["src/*"] maps ANY
    # non-relative name into src/ -> `util` resolves to src/util.ts.
    tsconfig = parse_tsconfig('{"compilerOptions": {"paths": {"*": ["src/*"]}}}')
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="util", level=0, names=(), function_local=False)
    assert resolver.resolve("src/app.ts", imp, _FILE_SET) == ["src/util.ts"]


def test_resolve_root_wildcard_target_substitutes_tail():
    # A root-level wildcard target under baseUrl ".": "@/*": ["*"] normalizes the
    # target to bare "*" (no directory prefix), which must still substitute the
    # captured tail -> `@/src/util` resolves to src/util.ts, not a literal "*".
    tsconfig = parse_tsconfig('{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["*"]}}}')
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="@/src/util", level=0, names=(), function_local=False)
    assert resolver.resolve("src/app.ts", imp, _FILE_SET) == ["src/util.ts"]


def test_resolve_root_wildcard_target_dot_slash_spelling():
    # The "./*" spelling of the same root target normalizes identically ("./" is
    # collapsed by the repo join), so it must resolve the same way.
    tsconfig = parse_tsconfig('{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./*"]}}}')
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="@/src/util", level=0, names=(), function_local=False)
    assert resolver.resolve("src/app.ts", imp, _FILE_SET) == ["src/util.ts"]


def test_resolve_alias_uses_first_resolving_target_only():
    # A paths array tries targets in order and uses the FIRST that resolves (TS
    # module resolution): ["dist/*", "src/*"] where only src/ exists yields the
    # src edge only, never a phantom dist edge.
    tsconfig = parse_tsconfig('{"compilerOptions": {"paths": {"@app/*": ["dist/*", "src/*"]}}}')
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="@app/util", level=0, names=(), function_local=False)
    assert resolver.resolve("src/app.ts", imp, _FILE_SET) == ["src/util.ts"]


def test_resolve_alias_target_escaping_repo_root_yields_no_edge():
    # A paths target that climbs above the repo root ("../shared/*") points outside
    # the project, so it resolves to no in-repo file (no fabricated in-repo edge).
    tsconfig = parse_tsconfig('{"compilerOptions": {"paths": {"@shared/*": ["../shared/*"]}}}')
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="@shared/util", level=0, names=(), function_local=False)
    assert resolver.resolve("src/app.ts", imp, _FILE_SET) == []


def test_resolve_baseurl_specifier_escaping_root_yields_no_edge():
    # The baseUrl-side analogue of relative overshoot: a non-relative specifier
    # whose embedded `..` climbs above the baseUrl root names no in-repo file.
    tsconfig = parse_tsconfig('{"compilerOptions": {"baseUrl": "src"}}')
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="foo/../../../bar", level=0, names=(), function_local=False)
    assert resolver.resolve("src/app.ts", imp, _FILE_SET) == []


# ---------- parse_tsconfig: malformed / JSONC tolerance ----------


def test_parse_tsconfig_tolerates_malformed_shapes():
    # A scan must not crash on a partial/garbage tsconfig.
    assert parse_tsconfig("[]") == parse_tsconfig("{}")  # non-object -> empty config
    assert parse_tsconfig('{"compilerOptions": 7}').base_url is None  # non-object options
    # a non-list paths target is skipped, valid siblings survive.
    cfg = parse_tsconfig('{"compilerOptions": {"paths": {"@bad": "nope", "@good": ["lib"]}}}')
    keys = dict(cfg.paths)
    assert "@bad" not in keys
    assert keys["@good"] == ("lib",)


def test_parse_tsconfig_baseurl_dot_is_repo_root():
    # baseUrl "." resolves to the tsconfig directory (repo root when config_dir="").
    assert parse_tsconfig('{"compilerOptions": {"baseUrl": "."}}').base_url == ""


def test_parse_tsconfig_joins_parent_relative_targets_through_config_dir():
    # A path target with `..` is resolved against the tsconfig directory.
    cfg = parse_tsconfig(
        '{"compilerOptions": {"baseUrl": ".", "paths": {"@s/*": ["../shared/*"]}}}',
        config_dir="frontend",
    )
    assert dict(cfg.paths)["@s/*"] == ("shared/*",)


def test_parse_tsconfig_tolerates_jsonc_escaped_string():
    # A backslash-escaped string (e.g. a Windows path) must survive comment/
    # trailing-comma stripping intact.
    cfg = parse_tsconfig('{"compilerOptions": {"baseUrl": "src\\\\app"}}')
    assert cfg.base_url == "src\\app"


def test_parse_tsconfig_returns_empty_on_malformed_json():
    # A syntactically broken tsconfig (unterminated object) must not raise — a
    # scan degrades to no aliases rather than crashing.
    assert parse_tsconfig("{") == TsConfig()
    assert parse_tsconfig("{") == parse_tsconfig("{}")


def test_parse_tsconfig_drops_target_escaping_repo_root():
    # A path target that escapes above the repo root is dropped (not clamped to a
    # fake in-repo path), leaving the alias with an empty target list.
    cfg = parse_tsconfig('{"compilerOptions": {"paths": {"@shared/*": ["../shared/*"]}}}')
    assert dict(cfg.paths)["@shared/*"] == ()


# ---------- orchestrator integration (real scan of the committed mini-repo) ----------


@_needs_ts
def test_scan_emits_typescript_javascript_import_edges_on_committed_fixture():
    repo_map = scan_repo(_FIXTURE, generator_version="t")
    edges = {(e.source, e.target): e for e in repo_map.edges if e.type == "imports"}

    # relative import + extension probing (TS)
    assert ("file:src/app.ts", "file:src/util.ts") in edges
    assert edges[("file:src/app.ts", "file:src/util.ts")].confidence == "high"
    # relative directory import -> index barrel (TS)
    assert ("file:src/app.ts", "file:src/components/index.ts") in edges
    # function-local require -> medium confidence (TS)
    assert edges[("file:src/app.ts", "file:src/config.ts")].confidence == "medium"
    # parent-relative barrel from a .jsx file (JS, tsx/jsx grammar path)
    assert ("file:src/ui/App.jsx", "file:src/components/index.ts") in edges
    # cross-directory require from a .js file (JS)
    assert ("file:legacy/old.js", "file:src/util.ts") in edges


@_needs_ts
def test_scan_drops_external_bare_specifiers_on_committed_fixture():
    repo_map = scan_repo(_FIXTURE, generator_version="t")
    targets = {e.target for e in repo_map.edges if e.type == "imports"}
    # lodash / react are external packages — never resolved to a repo node.
    assert all("lodash" not in t and "react" not in t for t in targets)
    # every imports-edge endpoint is a real node in the map (no dangling edges).
    node_ids = {n.id for n in repo_map.nodes}
    for e in repo_map.edges:
        if e.type == "imports":
            assert e.source in node_ids and e.target in node_ids


def test_unsupported_language_node_has_no_typescript_resolver():
    # Sanity dispatch guard: a language with no resolver returns None.
    assert get_resolver("brainfuck") is None
    # And a non-source node language id we do support still dispatches.
    node = RepoMapNode(id="file:x.ts", type="source_file", path="x.ts", language="typescript")
    assert get_resolver(node.language) is not None
