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

from sumo_qa.repo_map_models import RepoMapNode, RepoMapWarning
from sumo_qa.repo_map_resolvers import get_resolver, registered_languages
from sumo_qa.repo_map_resolvers.base import RawImport, ScanContext
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


def test_resolve_absolute_paths_targets_dropped_but_relative_sibling_resolves():
    # CLASS (paths target): a paths TARGET that is absolute — POSIX ("/src/*") or a
    # Windows drive ("C:/x/*") — points OUTSIDE the repo. `_join_repo` would strip the
    # leading "/" (or fold the drive) and re-anchor it repo-relative, fabricating an
    # in-repo edge to src/util.ts (a phantom dependency). Both absolute targets must
    # be rejected. A VALID relative target in the SAME array ("lib/*") still resolves,
    # so the drop is surgical (no over-correction). Declaration order puts the absolute
    # targets FIRST, so a resolver that failed to drop them would (wrongly) return the
    # phantom src/util.ts edge instead of lib/util.ts.
    tsconfig = parse_tsconfig(
        '{"compilerOptions": {"paths": {"@x/*": ["/src/*", "C:/x/*", "lib/*"]}}}'
    )
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="@x/util", level=0, names=(), function_local=False)
    assert resolver.resolve("app.ts", imp, {"src/util.ts", "lib/util.ts"}) == ["lib/util.ts"]


def test_resolve_paths_target_only_absolute_yields_no_edge():
    # CLASS (paths target): when EVERY target of an alias is absolute (out-of-repo),
    # the alias resolves to nothing — never a phantom in-repo edge from stripping the
    # leading "/".
    tsconfig = parse_tsconfig('{"compilerOptions": {"paths": {"@y/*": ["/src/*"]}}}')
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="@y/util", level=0, names=(), function_local=False)
    assert resolver.resolve("app.ts", imp, {"src/util.ts"}) == []


def test_resolve_deep_escaping_relative_paths_target_yields_no_edge():
    # CLASS GUARD (paths target): a relative paths target whose `..` segments climb
    # FAR above the repo root ("../../../outside/*") lands outside the project, so it
    # names no in-repo file and yields no edge — the escaping-target half of the same
    # class as the absolute-target drop.
    tsconfig = parse_tsconfig(
        '{"compilerOptions": {"paths": {"@out/*": ["../../../outside/*"]}}}',
        config_dir="packages/app",
    )
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="@out/util", level=0, names=(), function_local=False)
    assert resolver.resolve("packages/app/src/main.ts", imp, {"outside/util.ts"}) == []


def test_parse_tsconfig_baseurl_outside_repo_drops_alias_config():
    # A baseUrl that points OUTSIDE the repo tree — either escaping via `..`
    # ("../../../out" from packages/app) or an absolute filesystem path ("/src") —
    # names no in-repo directory, so every paths/baseUrl target under it escapes
    # too. Parse must drop the WHOLE alias config (empty TsConfig) rather than
    # silently re-anchor the targets to the tsconfig directory.
    escaping = parse_tsconfig(
        '{"compilerOptions": {"baseUrl": "../../../out", "paths": {"@x/*": ["src/*"]}}}',
        config_dir="packages/app",
    )
    assert escaping == TsConfig()
    absolute = parse_tsconfig('{"compilerOptions": {"baseUrl": "/src", "paths": {"@x/*": ["*"]}}}')
    assert absolute == TsConfig()


def test_resolve_escaping_baseurl_emits_no_phantom_alias_edge():
    # An ESCAPING baseUrl ("../../../outside") points at a tree OUTSIDE the repo,
    # so `@x/*`: ["src/*"] targets escape too. It must NOT re-anchor to the config
    # directory: doing so maps `@x/tool` from packages/app/src/tool.ts onto the
    # real in-repo file packages/app/src/tool.ts — a PHANTOM edge (false
    # dependency), the worst repo-map failure. The alias must resolve to nothing.
    tsconfig = parse_tsconfig(
        '{"compilerOptions": {"baseUrl": "../../../outside", "paths": {"@x/*": ["src/*"]}}}',
        config_dir="packages/app",
    )
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="@x/tool", level=0, names=(), function_local=False)
    file_set = {"packages/app/src/tool.ts"}
    assert resolver.resolve("packages/app/src/tool.ts", imp, file_set) == []


def test_resolve_absolute_baseurl_emits_no_phantom_alias_edge():
    # An ABSOLUTE baseUrl ("/src") is a filesystem path outside the repo, not a
    # repo-relative directory. Reinterpreting it as repo-relative `src` maps a bare
    # `util` onto the same-named in-repo file src/util.ts — a PHANTOM edge. The
    # absolute baseUrl must emit no alias edge (path-only fallback).
    tsconfig = parse_tsconfig('{"compilerOptions": {"baseUrl": "/src"}}')
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="util", level=0, names=(), function_local=False)
    assert resolver.resolve("app.ts", imp, {"src/util.ts"}) == []


# ---------- resolve: Windows `\` path separators in baseUrl / paths ----------


def test_resolve_baseurl_with_windows_separators_normalizes_and_resolves():
    # A tsconfig authored on Windows may spell baseUrl with `\` ("src\\app"). The
    # repo-relative paths the resolver matches are always `/`-joined, so the `\`
    # must be normalized to `/` for a bare specifier to resolve: `util` under
    # baseUrl "src\\app" -> src/app/util.ts.
    tsconfig = parse_tsconfig('{"compilerOptions": {"baseUrl": "src\\\\app"}}')
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="util", level=0, names=(), function_local=False)
    assert resolver.resolve("src/app/main.ts", imp, {"src/app/util.ts"}) == ["src/app/util.ts"]


def test_resolve_paths_target_with_windows_separators_normalizes_and_resolves():
    # A `\`-separated paths TARGET ("src\\app/*") normalizes so the alias resolves
    # to the `/`-joined repo file: `@x/util` -> src/app/util.ts.
    tsconfig = parse_tsconfig('{"compilerOptions": {"paths": {"@x/*": ["src\\\\app/*"]}}}')
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="@x/util", level=0, names=(), function_local=False)
    assert resolver.resolve("src/main.ts", imp, {"src/app/util.ts"}) == ["src/app/util.ts"]


def test_resolve_paths_target_forward_slash_still_resolves():
    # Regression guard: the plain `/`-separated target keeps resolving; separator
    # normalization must be a no-op on an already-`/`-joined target.
    tsconfig = parse_tsconfig('{"compilerOptions": {"paths": {"@x/*": ["src/app/*"]}}}')
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="@x/util", level=0, names=(), function_local=False)
    assert resolver.resolve("src/main.ts", imp, {"src/app/util.ts"}) == ["src/app/util.ts"]


def test_parse_tsconfig_windows_drive_absolute_baseurl_drops_alias_config():
    # A Windows DRIVE-ABSOLUTE baseUrl points OUTSIDE the repo tree just like a
    # POSIX-absolute "/src": both the `\`-spelled "C:\\src" (normalized to "C:/src")
    # and the already-`/`-spelled "C:/src" name a filesystem drive path, so the WHOLE
    # alias config is dropped (empty TsConfig) rather than re-anchored repo-relative
    # into a phantom "C:/src/..." tree.
    backslash = parse_tsconfig(
        '{"compilerOptions": {"baseUrl": "C:\\\\src", "paths": {"@x/*": ["*"]}}}'
    )
    assert backslash == TsConfig()
    forward = parse_tsconfig('{"compilerOptions": {"baseUrl": "C:/src", "paths": {"@x/*": ["*"]}}}')
    assert forward == TsConfig()


def test_resolve_windows_drive_absolute_baseurl_emits_no_phantom_alias_edge():
    # A Windows DRIVE-ABSOLUTE baseUrl ("C:\\src") is a filesystem path outside the
    # repo, not a repo-relative directory. Normalizing `\` -> `/` yields "C:/src";
    # treating THAT as repo-relative would map a bare `util` onto the phantom in-repo
    # file "C:/src/util.ts" — a false dependency. The drive-absolute baseUrl must be
    # detected as absolute and drop the whole alias config -> no edge.
    tsconfig = parse_tsconfig('{"compilerOptions": {"baseUrl": "C:\\\\src"}}')
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="util", level=0, names=(), function_local=False)
    assert resolver.resolve("app.ts", imp, {"C:/src/util.ts"}) == []


# ---------- resolve: absolute import specifier + bare-drive baseUrl (#563) ----------


@pytest.mark.parametrize(
    "spec",
    ["/outside/pkg", "\\outside\\pkg", "C:/outside", "C:outside"],
)
def test_resolve_absolute_import_specifier_does_not_alias_resolve(spec):
    # An absolute import specifier — POSIX ("/outside/pkg"), UNC/backslash
    # ("\\outside\\pkg"), or a Windows drive with ("C:/outside") or WITHOUT
    # ("C:outside") a separator — names no repo-relative module. But a catch-all
    # `"*": ["src/fixed"]` alias uses its target VERBATIM (the specifier tail is
    # discarded for a non-wildcard target), so an unguarded resolver maps EVERY
    # specifier onto the phantom in-repo file src/fixed.ts. The absolute specifier
    # must be rejected before alias matching -> no edge.
    tsconfig = parse_tsconfig('{"compilerOptions": {"paths": {"*": ["src/fixed"]}}}')
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module=spec, level=0, names=(), function_local=False)
    assert resolver.resolve("app/main.ts", imp, {"src/fixed.ts"}) == []


def test_resolve_bare_non_relative_specifier_still_alias_resolves():
    # Guard is surgical: a normal bare (non-absolute) specifier still resolves
    # through the same catch-all alias, so dropping absolute specifiers does not
    # break ordinary baseUrl/paths aliasing.
    tsconfig = parse_tsconfig('{"compilerOptions": {"paths": {"*": ["src/fixed"]}}}')
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="anything", level=0, names=(), function_local=False)
    assert resolver.resolve("app/main.ts", imp, {"src/fixed.ts"}) == ["src/fixed.ts"]


def test_parse_tsconfig_bare_windows_drive_baseurl_drops_alias_config():
    # A Windows drive baseUrl with NO trailing separator ("C:") is still a
    # filesystem drive path outside the repo — the drive-absolute class does not
    # require a following slash. `_WINDOWS_DRIVE_RE`'s separator requirement let
    # "C:" through as a repo-relative directory; it must instead drop the WHOLE
    # alias config (empty TsConfig) rather than re-anchor targets under "C:".
    dropped = parse_tsconfig('{"compilerOptions": {"baseUrl": "C:", "paths": {"@x/*": ["*"]}}}')
    assert dropped == TsConfig()


def test_resolve_bare_windows_drive_baseurl_emits_no_phantom_alias_edge():
    # baseUrl "C:" (bare drive, no separator) must not resolve a bare `util` onto
    # the phantom in-repo file "C:/util.ts": the bare drive is absolute, so the
    # alias config is dropped -> no edge.
    tsconfig = parse_tsconfig('{"compilerOptions": {"baseUrl": "C:"}}')
    resolver = TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx", tsconfig=tsconfig)
    imp = RawImport(module="util", level=0, names=(), function_local=False)
    assert resolver.resolve("app.ts", imp, {"C:/util.ts"}) == []


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


def test_parse_tsconfig_jsonc_escaped_windows_baseurl_is_normalized():
    # A backslash-escaped string (a Windows-path baseUrl) survives comment/
    # trailing-comma stripping intact, and is THEN normalized `\` -> `/` so it
    # matches the `/`-joined repo paths (Windows-separator support). A stripper bug
    # that mangled the escape would yield a different value, so this still guards it.
    cfg = parse_tsconfig('{"compilerOptions": {"baseUrl": "src\\\\app"}}')
    assert cfg.base_url == "src/app"


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


# ---------- scan-local tsconfig context (#484 TS/JS slice): per-importer ----------
# ---------- nearest-config alias resolution, no singleton mutation, degradation ----------

_WORKSPACES = Path(__file__).parent / "fixtures" / "repo_map" / "ts_workspaces"


def _alias(module: str) -> RawImport:
    """A non-relative (alias/baseUrl) specifier, as the extractor emits it."""
    return RawImport(module=module, level=0, names=(), function_local=False)


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _prepared_on(
    root: Path, files: dict[str, str], warnings: list[RepoMapWarning] | None = None
) -> TypeScriptResolver:
    """Write ``files`` under ``root`` and prepare a scan-local resolver on them."""
    _write_tree(root, files)
    context = ScanContext(root=root, files=frozenset(files), warnings=warnings)
    return ts.prepare(context)


# Two sibling workspaces, each with its OWN tsconfig alias table.
_TWO_WORKSPACES = {
    "packages/app/tsconfig.json": (
        '{"compilerOptions": {"baseUrl": "src", "paths": {"@app/*": ["*"]}}}'
    ),
    "packages/app/src/main.ts": "export const a = 1;",
    "packages/app/src/widget.ts": "export const w = 1;",
    "packages/lib/tsconfig.json": (
        '{"compilerOptions": {"baseUrl": "src", "paths": {"@lib/*": ["*"]}}}'
    ),
    "packages/lib/src/main.ts": "export const b = 1;",
    "packages/lib/src/helper.ts": "export const h = 1;",
}


# ---- resolve: the prepared resolver selects the importer's NEAREST tsconfig ----


def test_prepared_resolver_resolves_an_importers_own_workspace_alias(tmp_path: Path):
    # `@app/widget` from packages/app/src/main.ts resolves against app's OWN
    # tsconfig (baseUrl src, "@app/*": ["*"]) -> packages/app/src/widget.ts.
    prepared = _prepared_on(tmp_path, _TWO_WORKSPACES)
    file_set = set(_TWO_WORKSPACES)
    assert prepared.resolve("packages/app/src/main.ts", _alias("@app/widget"), file_set) == [
        "packages/app/src/widget.ts"
    ]
    assert prepared.resolve("packages/lib/src/main.ts", _alias("@lib/helper"), file_set) == [
        "packages/lib/src/helper.ts"
    ]


def test_prepared_resolver_does_not_flatten_sibling_workspace_aliases(tmp_path: Path):
    # TRUE NEGATIVE: `@app/widget` from packages/lib/src/main.ts must NOT resolve
    # — lib's nearest tsconfig defines no `@app` alias. A resolver that flattened
    # both workspace configs into one alias table would (wrongly) reach
    # packages/app/src/widget.ts.
    prepared = _prepared_on(tmp_path, _TWO_WORKSPACES)
    file_set = set(_TWO_WORKSPACES)
    assert prepared.resolve("packages/lib/src/main.ts", _alias("@app/widget"), file_set) == []


def test_prepared_resolver_missing_config_is_silent_path_only_fallback(tmp_path: Path):
    # No tsconfig anywhere above the importer: an alias specifier is external
    # (dropped) with no warning — the silent path-only fallback.
    warnings: list[RepoMapWarning] = []
    files = {"src/main.ts": "export const a = 1;", "src/widget.ts": "export const w = 1;"}
    prepared = _prepared_on(tmp_path, files, warnings=warnings)
    assert prepared.resolve("src/main.ts", _alias("@app/widget"), set(files)) == []
    assert warnings == []


# ---- singleton immutability: the registered resolver is never mutated ----


@_needs_ts
def test_scan_preparation_never_mutates_the_registered_typescript_singleton():
    # A context-rich scan activates aliases scan-locally; the registered
    # singleton must stay path-only and keep dropping non-relative specifiers.
    scan_repo(_WORKSPACES, generator_version="t")
    singleton = get_resolver("typescript")
    assert singleton is not None
    file_set = {
        "packages/app/src/main.ts",
        "packages/app/src/widget.ts",
        "packages/app/tsconfig.json",
    }
    assert singleton.resolve("packages/app/src/main.ts", _alias("@app/widget"), file_set) == []


# ---- config degradation: malformed / non-UTF-8 / unreadable tsconfig ----


def test_prepared_malformed_tsconfig_degrades_with_one_other_warning(tmp_path: Path):
    warnings: list[RepoMapWarning] = []
    files = {
        "tsconfig.json": "{ this is not valid json",
        "src/main.ts": "export const a = 1;",
        "src/widget.ts": "export const w = 1;",
    }
    prepared = _prepared_on(tmp_path, files, warnings=warnings)
    # The scan completes and the alias is simply unavailable (path-only).
    assert prepared.resolve("src/main.ts", _alias("@app/widget"), set(files)) == []
    others = [w for w in warnings if w.kind == "other"]
    assert len(others) == 1
    assert others[0].path == "tsconfig.json"


def test_prepared_non_utf8_tsconfig_degrades_with_one_other_warning(tmp_path: Path):
    warnings: list[RepoMapWarning] = []
    (tmp_path / "tsconfig.json").write_bytes(b"\xff\xfe{}")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.ts").write_text("export const a = 1;", encoding="utf-8")
    files = {"tsconfig.json", "src/main.ts"}
    context = ScanContext(root=tmp_path, files=frozenset(files), warnings=warnings)
    prepared = ts.prepare(context)
    assert prepared.resolve("src/main.ts", _alias("@app/widget"), set(files)) == []
    others = [w for w in warnings if w.kind == "other"]
    assert len(others) == 1
    assert others[0].path == "tsconfig.json"


def test_prepared_unreadable_tsconfig_degrades_with_one_other_warning(tmp_path: Path, monkeypatch):
    warnings: list[RepoMapWarning] = []
    files = {"tsconfig.json": "{}", "src/main.ts": "export const a = 1;"}
    _write_tree(tmp_path, files)
    real_read = ScanContext.read

    def failing_read(self, rel_path: str):
        if rel_path == "tsconfig.json":
            return None  # simulate an unreadable config portably (no chmod on Windows)
        return real_read(self, rel_path)

    monkeypatch.setattr(ScanContext, "read", failing_read)
    context = ScanContext(root=tmp_path, files=frozenset(files), warnings=warnings)
    prepared = ts.prepare(context)
    assert prepared.resolve("src/main.ts", _alias("@app/widget"), set(files)) == []
    others = [w for w in warnings if w.kind == "other"]
    assert len(others) == 1
    assert others[0].path == "tsconfig.json"


# A NESTED broken tsconfig sits under an ancestor tsconfig that DOES define a
# matching alias — the shadowing regression fixture for Fix A.
_BROKEN_NESTED_UNDER_ALIASING_ANCESTOR = {
    # Ancestor (repo root) config: `@shared/*` -> shared/* would resolve a real file.
    "tsconfig.json": '{"compilerOptions": {"baseUrl": ".", "paths": {"@shared/*": ["shared/*"]}}}',
    "shared/thing.ts": "export const t = 1;",
    # Nested workspace whose OWN tsconfig is broken (would-be alias consumer).
    "packages/app/tsconfig.json": "{ this is not valid json",
    "packages/app/src/main.ts": 'import { t } from "@shared/thing";',
}


def test_prepared_broken_nested_tsconfig_shadows_ancestor_alias_no_leak(tmp_path: Path):
    # Fix A: a workspace whose OWN tsconfig is present-but-broken must fall back to
    # PATH-ONLY, never inherit an ancestor's alias table. If the broken nested config
    # registered NO index entry, `_nearest_tsconfig` would walk past it up to the root
    # config and (wrongly) resolve `@shared/thing` -> shared/thing.ts — an ancestor
    # leak. Registering an EMPTY TsConfig at the broken dir (mirroring the PHP
    # empty-root shadow) stops the walk there, so the aliased import resolves to
    # NOTHING. Still exactly one deterministic `other` warning (the nested config).
    warnings: list[RepoMapWarning] = []
    prepared = _prepared_on(tmp_path, _BROKEN_NESTED_UNDER_ALIASING_ANCESTOR, warnings=warnings)
    file_set = set(_BROKEN_NESTED_UNDER_ALIASING_ANCESTOR)
    assert prepared.resolve("packages/app/src/main.ts", _alias("@shared/thing"), file_set) == []
    others = [w for w in warnings if w.kind == "other"]
    assert len(others) == 1
    assert others[0].path == "packages/app/tsconfig.json"


def test_prepared_pathologically_nested_tsconfig_does_not_abort_scan(tmp_path: Path):
    # Fix B: a VALID but pathologically deeply-nested JSON tsconfig makes json.loads
    # raise RecursionError (the C scanner's recursion-call guard), which `_load_
    # tsconfig_json` must catch as malformed rather than let it propagate and abort
    # the whole scan. 200000 levels clears the guard on every supported runtime
    # (pre-3.12 gates at the Python recursion limit, 3.12+ at the C-stack limit), so
    # preparation completes and the alias degrades to path-only with one warning.
    warnings: list[RepoMapWarning] = []
    deep_json = "[" * 200000 + "]" * 200000  # syntactically valid, but nests too deep
    files = {
        "tsconfig.json": deep_json,
        "src/main.ts": "export const a = 1;",
        "src/widget.ts": "export const w = 1;",
    }
    prepared = _prepared_on(tmp_path, files, warnings=warnings)
    assert prepared.resolve("src/main.ts", _alias("@app/widget"), set(files)) == []
    others = [w for w in warnings if w.kind == "other"]
    assert len(others) == 1
    assert others[0].path == "tsconfig.json"


# ---- scan_repo integration on the committed sibling-workspace fixture ----


@_needs_ts
def test_scan_resolves_nearest_tsconfig_alias_per_workspace_exact_edge_set():
    # Decision table over (importer's nearest tsconfig, specifier) -> resolved edge:
    #   app/main + @app/widget -> app's config resolves      -> edge (positive)
    #   lib/main + @lib/helper -> lib's config resolves      -> edge (positive)
    #   lib/main + @app/widget -> lib's config has NO @app    -> NO edge (true negative)
    # A resolver that flattened both workspace configs into one alias table would
    # emit the third (phantom) cross-config edge, so the EXACT set below fails it.
    repo_map = scan_repo(_WORKSPACES, generator_version="t")
    import_edges = {(e.source, e.target): e for e in repo_map.edges if e.type == "imports"}
    pairs = set(import_edges)
    assert pairs == {
        ("file:packages/app/src/main.ts", "file:packages/app/src/widget.ts"),
        ("file:packages/lib/src/main.ts", "file:packages/lib/src/helper.ts"),
    }
    # Explicit true negative: the sibling-workspace alias resolved no edge.
    assert (
        "file:packages/lib/src/main.ts",
        "file:packages/app/src/widget.ts",
    ) not in pairs
    # Module-level ES imports -> high confidence; no dangling or self edges.
    assert all(e.confidence == "high" for e in import_edges.values())
    node_ids = {n.id for n in repo_map.nodes}
    for src, tgt in pairs:
        assert src in node_ids and tgt in node_ids
        assert src != tgt
