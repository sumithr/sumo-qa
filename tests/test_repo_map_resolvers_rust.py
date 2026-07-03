# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the Rust import resolver (#358).

``extract`` is tested against REAL tree-sitter output (skipped without the
extra); ``resolve`` is pure path arithmetic over a supplied file set and runs on
every interpreter; and a ``scan_repo`` integration parses a COMMITTED Rust
fixture crate end-to-end (real tree-sitter). Each ``resolve`` case names the UA
rule it exercises: mod module-file conventions, the crate/self/super anchors,
the leaf submodule-or-item duality, and the external-crate drop.

Every test name carries ``rust_resolver`` so ``pytest -k rust_resolver`` (the
issue's test command) selects exactly this module.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sumo_qa.repo_map_resolvers import get_resolver, registered_languages
from sumo_qa.repo_map_resolvers.base import RawImport
from sumo_qa.repo_map_resolvers.rust import RustResolver
from sumo_qa.repo_map_scanner import scan_repo
from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE

resolver = RustResolver()

_FIXTURE_CRATE = Path(__file__).resolve().parent / "fixtures" / "repo_map" / "rust_crate"

_needs_ts = pytest.mark.skipif(
    not TREESITTER_AVAILABLE,
    reason="tree-sitter not installed (the [treesitter] extra is absent)",
)


def _use(module: str, names: tuple[str, ...] = ()) -> RawImport:
    return RawImport(module=module, level=0, names=names, function_local=False)


def _mod(name: str) -> RawImport:
    return RawImport(module=name, level=1, names=(), function_local=False)


# ---------- registry ----------


def test_rust_resolver_is_registered():
    assert "rust" in registered_languages()
    assert get_resolver("rust") is not None


# ---------- extract (real tree-sitter) ----------


@_needs_ts
def test_rust_resolver_extract_mod_declaration():
    # `mod name;` -> a level-1 RawImport (a child module of the importer's module).
    (raw,) = resolver.extract(b"mod widgets;\n")
    assert raw.module == "widgets"
    assert raw.level == 1
    assert raw.names == ()


@_needs_ts
def test_rust_resolver_extract_inline_mod_maps_to_no_file_but_walks_body():
    # `mod inline { … }` defines the module in place (no file), but a `use`
    # nested in its body is still captured.
    raws = resolver.extract(b"mod inline {\n    use crate::deep::Thing;\n}\n")
    modules = [(r.module, r.level) for r in raws]
    assert ("inline", 1) not in modules  # the inline mod itself is NOT a file edge
    assert ("crate::deep::Thing", 0) in modules  # its nested use IS captured


@_needs_ts
def test_rust_resolver_extract_empty_inline_mod_yields_nothing():
    assert resolver.extract(b"mod empty {}\n") == []


@_needs_ts
def test_rust_resolver_extract_use_scoped_path():
    (raw,) = resolver.extract(b"use crate::foo::Thing;\n")
    assert raw.module == "crate::foo::Thing"
    assert raw.level == 0
    assert raw.names == ()


@_needs_ts
def test_rust_resolver_extract_pub_use_reexport_skips_visibility():
    # A `pub use` re-export: the leading visibility modifier must not derail the
    # path extraction.
    (raw,) = resolver.extract(b"pub use crate::a::B;\n")
    assert raw.module == "crate::a::B"


@_needs_ts
def test_rust_resolver_extract_use_group_collects_members():
    (raw,) = resolver.extract(b"use crate::g::{c, d};\n")
    assert raw.module == "crate::g"
    assert set(raw.names) == {"c", "d"}


@_needs_ts
def test_rust_resolver_extract_use_group_self_member_skipped():
    # `use a::{self, c}`: `self` means "the prefix module itself" (covered by the
    # module probe), so it is not a probeable member name.
    (raw,) = resolver.extract(b"use crate::g::{self, c};\n")
    assert raw.names == ("c",)


@_needs_ts
def test_rust_resolver_extract_use_wildcard_keeps_prefix_only():
    (raw,) = resolver.extract(b"use crate::w::*;\n")
    assert raw.module == "crate::w"
    assert raw.names == ()


@_needs_ts
def test_rust_resolver_extract_use_as_clause_drops_alias():
    (raw,) = resolver.extract(b"use crate::x::y as z;\n")
    assert raw.module == "crate::x::y"  # the imported path, not the local alias


@_needs_ts
def test_rust_resolver_extract_bare_single_use():
    # `use foo;` (one segment) extracts as a bare path; resolve drops it as
    # external (modern editions reach in-crate modules via crate/self/super).
    (raw,) = resolver.extract(b"use foo;\n")
    assert raw.module == "foo"
    assert raw.level == 0


@_needs_ts
def test_rust_resolver_extract_function_local_flagged_top_level_not():
    src = b"use crate::top::A;\nfn f() {\n    use crate::lazy::B;\n}\n"
    raws = {r.module: r for r in resolver.extract(src)}
    assert raws["crate::lazy::B"].function_local is True  # inside a fn body -> lazy
    assert raws["crate::top::A"].function_local is False  # module level -> tight


# ---------- resolve: mod declarations (module-file conventions) ----------


def test_rust_resolver_resolves_mod_sibling_file_from_crate_root():
    # `mod foo;` in the crate root resolves to a sibling `foo.rs`.
    files = {"src/foo.rs", "src/bar.rs"}
    assert resolver.resolve("src/main.rs", _mod("foo"), files) == ["src/foo.rs"]


def test_rust_resolver_resolves_mod_to_mod_rs_convention():
    # `mod foo;` resolves to `foo/mod.rs` when that is the form on disk.
    files = {"src/foo/mod.rs"}
    assert resolver.resolve("src/lib.rs", _mod("foo"), files) == ["src/foo/mod.rs"]


def test_rust_resolver_resolves_mod_child_under_a_mod_rs_owns_its_dir():
    # A `mod.rs` owns its OWN directory: `mod child;` in src/foo/mod.rs ->
    # src/foo/child.rs.
    files = {"src/foo/child.rs"}
    assert resolver.resolve("src/foo/mod.rs", _mod("child"), files) == ["src/foo/child.rs"]


def test_rust_resolver_resolves_mod_child_under_a_plain_file_uses_sibling_dir():
    # A non-mod, non-root `foo.rs` owns the sibling dir `foo/`: `mod helper;` in
    # src/foo.rs -> src/foo/helper.rs (NOT src/helper.rs).
    files = {"src/foo/helper.rs", "src/helper.rs"}
    assert resolver.resolve("src/foo.rs", _mod("helper"), files) == ["src/foo/helper.rs"]


# ---------- resolve: use paths (crate / self / super) ----------


def test_rust_resolver_resolves_use_crate_absolute_to_container_module():
    # `use crate::foo::Thing` -> Thing is an item in module foo -> src/foo.rs.
    files = {"src/main.rs", "src/foo.rs"}
    assert resolver.resolve("src/bar.rs", _use("crate::foo::Thing"), files) == ["src/foo.rs"]


def test_rust_resolver_resolves_use_crate_leaf_as_submodule():
    # `use crate::foo::widget` where widget is itself a submodule file ->
    # src/foo/widget.rs, and the parent module src/foo.rs is also probed.
    files = {"src/main.rs", "src/foo/widget.rs", "src/foo.rs"}
    assert resolver.resolve("src/bar.rs", _use("crate::foo::widget"), files) == [
        "src/foo/widget.rs",
        "src/foo.rs",
    ]


def test_rust_resolver_resolves_use_self_anchors_at_importer_module_dir():
    # `use self::helper::Helper` in src/foo.rs anchors at foo's module dir
    # (src/foo) -> src/foo/helper.rs.
    files = {"src/foo/helper.rs"}
    assert resolver.resolve("src/foo.rs", _use("self::helper::Helper"), files) == [
        "src/foo/helper.rs"
    ]


def test_rust_resolver_resolves_use_super_to_sibling_module():
    # `use super::sibling::Util` in src/foo/bar.rs walks to foo's dir (src/foo)
    # -> src/foo/sibling.rs.
    files = {"src/foo/sibling.rs"}
    assert resolver.resolve("src/foo/bar.rs", _use("super::sibling::Util"), files) == [
        "src/foo/sibling.rs"
    ]


def test_rust_resolver_resolves_use_super_super_walks_two_modules_up():
    # `super::super::x::Y` from src/a/b.rs anchors two modules up (at src) -> src/x.rs.
    files = {"src/lib.rs", "src/x.rs"}
    assert resolver.resolve("src/a/b.rs", _use("super::super::x::Y"), files) == ["src/x.rs"]


def test_rust_resolver_super_from_crate_root_yields_nothing():
    # A crate root has no parent module: `super::x` from src/lib.rs must not
    # anchor at the repo root and fabricate an edge.
    files = {"src/lib.rs", "x.rs"}
    assert resolver.resolve("src/lib.rs", _use("super::x"), files) == []


def test_rust_resolver_super_overshoot_past_crate_root_yields_nothing():
    # More supers than module depth (src/a/b -> 3 components, 4 supers) walks
    # above the module tree entirely -> nothing.
    files = {"src/lib.rs", "x.rs"}
    assert resolver.resolve("src/a/b.rs", _use("super::super::super::super::x"), files) == []


def test_rust_resolver_super_without_a_crate_root_yields_nothing():
    # No crate root in the file set: `super` must not anchor at the repo root.
    files = {"x.rs"}
    assert resolver.resolve("foo.rs", _use("super::x"), files) == []


# ---------- resolve: external drop ----------


def test_rust_resolver_external_std_path_is_dropped():
    files = {"src/main.rs", "src/io.rs"}  # src/io.rs present but std:: is external
    assert resolver.resolve("src/main.rs", _use("std::collections::HashMap"), files) == []


def test_rust_resolver_external_crate_path_is_dropped():
    # A bare leading segment is an external crate name (modern edition), dropped
    # even though a same-named file exists.
    files = {"src/main.rs", "src/serde.rs"}
    assert resolver.resolve("src/main.rs", _use("serde::Deserialize"), files) == []


def test_rust_resolver_use_crate_without_a_crate_root_is_dropped():
    # `crate::` cannot anchor when no lib.rs / main.rs is in the map.
    files = {"pkg/m.rs", "pkg/x.rs"}
    assert resolver.resolve("pkg/m.rs", _use("crate::x"), files) == []


# ---------- resolve: groups, wildcard, crate-root items, dedup ----------


def test_rust_resolver_resolves_group_container_and_each_member():
    files = {"src/lib.rs", "src/g.rs", "src/g/c.rs", "src/g/d.rs"}
    assert resolver.resolve("src/bar.rs", _use("crate::g", ("c", "d")), files) == [
        "src/g.rs",
        "src/g/c.rs",
        "src/g/d.rs",
    ]


def test_rust_resolver_resolves_wildcard_to_prefix_module_and_its_container():
    # `use crate::w::*` references the top-level module w; its container is the
    # crate root that declares it (the module-tree analogue of a package barrel).
    files = {"src/lib.rs", "src/w.rs"}
    assert resolver.resolve("src/bar.rs", _use("crate::w"), files) == ["src/w.rs", "src/lib.rs"]


def test_rust_resolver_resolves_item_directly_in_crate_root():
    # `use crate::Helper` where Helper is an item in the crate root file ->
    # the crate root (here lib.rs), via the dir-module fallback.
    files = {"src/lib.rs", "src/Helper.rs"}
    assert resolver.resolve("src/bar.rs", _use("crate::Helper"), files) == [
        "src/Helper.rs",
        "src/lib.rs",
    ]


def test_rust_resolver_resolves_against_a_crate_root_at_the_repo_root():
    # A flat crate whose root sits at the repo root (no src/): the empty anchor
    # dir resolves the crate root via lib.rs / main.rs.
    files = {"main.rs", "helper.rs"}
    assert resolver.resolve("main.rs", _use("crate::helper"), files) == ["helper.rs", "main.rs"]


def test_rust_resolver_dedups_colliding_candidates():
    # A container probe (module g -> g/mod.rs) and a member probe (g::mod ->
    # g/mod.rs) collide on one real file; dedup must collapse them to one entry.
    files = {"src/lib.rs", "src/g/mod.rs"}
    assert resolver.resolve("src/bar.rs", _use("crate::g", ("mod",)), files) == ["src/g/mod.rs"]


# ---------- bare-head grouped / glob use: crate/self/super reaching straight
# into a group or glob with NO intermediate module segment. tree-sitter emits
# the head as its own `crate` / `self` / `super` leaf (not a `scoped_identifier`),
# so these are extract-path regressions and must run through REAL tree-sitter to
# exercise `_first_path` — a constructed RawImport would bypass the bug (#358). ----------


@_needs_ts
def test_rust_resolver_bare_crate_group_resolves_each_member():
    # `use crate::{a, b}` heads straight into the group with a BARE `crate` leaf.
    # extract must still read that head (module == "crate", not ""), so members
    # resolve against the crate root dir -> src/a.rs, src/b.rs (with the crate
    # root itself as the group's container module).
    (raw,) = resolver.extract(b"use crate::{a, b};\n")
    assert raw.module == "crate"
    assert set(raw.names) == {"a", "b"}
    files = {"src/lib.rs", "src/a.rs", "src/b.rs"}
    assert resolver.resolve("src/bar.rs", raw, files) == ["src/lib.rs", "src/a.rs", "src/b.rs"]


@_needs_ts
def test_rust_resolver_bare_self_group_resolves_sibling_members():
    # `use self::{a, b}` from a module file (`src/foo/mod.rs`) anchors at that
    # file's own module dir, so a, b are sibling modules -> src/foo/a.rs,
    # src/foo/b.rs.
    (raw,) = resolver.extract(b"use self::{a, b};\n")
    assert raw.module == "self"
    assert set(raw.names) == {"a", "b"}
    files = {"src/foo/a.rs", "src/foo/b.rs"}
    assert resolver.resolve("src/foo/mod.rs", raw, files) == ["src/foo/a.rs", "src/foo/b.rs"]


@_needs_ts
def test_rust_resolver_bare_crate_glob_resolves_crate_root_module():
    # `use crate::*` is a bare-head glob; its prefix module IS the crate root, so
    # it resolves to the crate-root module file (here src/lib.rs).
    (raw,) = resolver.extract(b"use crate::*;\n")
    assert raw.module == "crate"
    assert raw.names == ()
    files = {"src/lib.rs"}
    assert resolver.resolve("src/bar.rs", raw, files) == ["src/lib.rs"]


@_needs_ts
def test_rust_resolver_bare_super_group_resolves_parent_module_members():
    # `use super::{a, b}` heads with a bare `super` leaf; from src/foo/bar.rs it
    # walks one module up to foo's dir, so a, b -> src/foo/a.rs, src/foo/b.rs.
    (raw,) = resolver.extract(b"use super::{a, b};\n")
    assert raw.module == "super"
    assert set(raw.names) == {"a", "b"}
    files = {"src/lib.rs", "src/foo/a.rs", "src/foo/b.rs"}
    assert resolver.resolve("src/foo/bar.rs", raw, files) == ["src/foo/a.rs", "src/foo/b.rs"]


# ---------- full group expansion: nested groups + aliased members. These are
# extract-path shapes (a nested `scoped_use_list` / a `use_as_clause` member)
# that tree-sitter only produces from real source, so a constructed RawImport
# would bypass the extraction bug — they must run through REAL tree-sitter (#358). ----------


@_needs_ts
def test_rust_resolver_nested_group_members_resolve():
    # `use crate::{a::{b, c}}`: the nested group expands under the prefix
    # `crate::a`, so members b, c resolve as submodules of a (and a itself as
    # their container). No spurious bare-`crate` edge for the routing prefix.
    (raw,) = resolver.extract(b"use crate::{a::{b, c}};\n")
    assert raw.module == "crate::a"
    assert set(raw.names) == {"b", "c"}
    files = {"src/lib.rs", "src/a.rs", "src/a/b.rs", "src/a/c.rs"}
    assert resolver.resolve("src/bar.rs", raw, files) == [
        "src/a.rs",
        "src/a/b.rs",
        "src/a/c.rs",
    ]


@_needs_ts
def test_rust_resolver_aliased_group_member_resolves_pre_as_path():
    # `use crate::{x as y}`: the alias is dropped and the pre-`as` path x resolves
    # (x as a submodule, plus the crate root as its item-container).
    (raw,) = resolver.extract(b"use crate::{x as y};\n")
    assert raw.module == "crate::x"
    assert raw.names == ()
    files = {"src/lib.rs", "src/x.rs"}
    assert resolver.resolve("src/bar.rs", raw, files) == ["src/x.rs", "src/lib.rs"]


@_needs_ts
def test_rust_resolver_nested_and_aliased_group_members_all_resolve():
    # The issue's exact shape `use crate::{a::{b, c}, d as e}`: extraction emits
    # the nested group (crate::a with members b, c) AND the aliased member's
    # pre-`as` path (crate::d) — NOT a bare `crate` container for the top prefix.
    raws = resolver.extract(b"use crate::{a::{b, c}, d as e};\n")
    assert [(r.module, r.names) for r in raws] == [("crate::a", ("b", "c")), ("crate::d", ())]
    files = {"src/lib.rs", "src/a/b.rs", "src/a/c.rs", "src/d.rs"}
    edges = {f for raw in raws for f in resolver.resolve("src/bar.rs", raw, files)}
    assert {"src/a/b.rs", "src/a/c.rs", "src/d.rs"} <= edges  # all three members emit an edge


@_needs_ts
def test_rust_resolver_group_mixes_plain_scoped_and_glob_members():
    # A group can mix a plain member (a), a scoped-path member (b::c) and a glob
    # member (w::*); each expands to its own edge alongside the plain group.
    raws = resolver.extract(b"use crate::{a, b::c, w::*};\n")
    assert {(r.module, r.names) for r in raws} == {
        ("crate", ("a",)),
        ("crate::b::c", ()),
        ("crate::w", ()),
    }
    files = {"src/lib.rs", "src/a.rs", "src/b/c.rs", "src/w.rs"}
    edges = {f for raw in raws for f in resolver.resolve("src/bar.rs", raw, files)}
    assert {"src/a.rs", "src/b/c.rs", "src/w.rs"} <= edges


# ---------- inline-module path context: an inline `mod` carries its name so a
# nested file-module declaration resolves under the enclosing module (#358). ----------


@_needs_ts
def test_rust_resolver_inline_mod_child_resolves_under_enclosing_module():
    # `mod outer { mod child; }`: `child` is a file-module of the INLINE `outer`,
    # so it lives at src/outer/child.rs — NOT the file's own src/child.rs. The
    # inline `mod` body must thread its name as the child's path prefix.
    (raw,) = resolver.extract(b"mod outer {\n    mod child;\n}\n")
    assert raw.module == "outer::child"
    assert raw.level == 1
    files = {"src/outer/child.rs", "src/child.rs"}
    assert resolver.resolve("src/main.rs", raw, files) == ["src/outer/child.rs"]


# ---------- inline-module use frame: a `self` / `super` use written inside an
# inline `mod` is authored in that inline module's frame; extract must rebase its
# head so resolve (which works in the FILE module's frame) anchors correctly.
# These are extraction-path rewrites, so they run through REAL tree-sitter — a
# constructed RawImport would bypass the inline-frame threading (#358). ----------


@_needs_ts
def test_rust_resolver_use_super_in_inline_mod_anchors_at_file_module():
    # The ubiquitous `mod tests { use super::Foo; }` in src/foo.rs: `super` from
    # the inline `foo::tests` module climbs to the FILE module `foo`, so `Foo` is
    # foo's item -> src/foo.rs. Before the fix this leaked to the crate root.
    (raw,) = resolver.extract(b"mod tests {\n    use super::Foo;\n}\n")
    files = {"src/lib.rs", "src/foo.rs"}
    assert resolver.resolve("src/foo.rs", raw, files) == ["src/foo.rs"]


@_needs_ts
def test_rust_resolver_use_super_glob_in_inline_mod_globs_file_module():
    # `mod tests { use super::*; }` — the single most common Rust test pattern:
    # the glob's prefix module is the FILE module foo -> src/foo.rs, not the crate
    # root.
    (raw,) = resolver.extract(b"mod tests {\n    use super::*;\n}\n")
    files = {"src/lib.rs", "src/foo.rs"}
    assert resolver.resolve("src/foo.rs", raw, files) == ["src/foo.rs"]


@_needs_ts
def test_rust_resolver_use_super_in_nested_inline_mod_anchors_at_enclosing_module():
    # `mod outer { mod inner { use super::Foo; } }` in src/foo.rs: `super` from
    # `foo::outer::inner` climbs one inline level to `foo::outer`, so `Foo` is an
    # item of the `outer` module -> src/foo/outer.rs (NOT the file module foo).
    (raw,) = resolver.extract(b"mod outer {\n    mod inner {\n        use super::Foo;\n    }\n}\n")
    files = {"src/lib.rs", "src/foo/outer.rs"}
    assert resolver.resolve("src/foo.rs", raw, files) == ["src/foo/outer.rs"]


@_needs_ts
def test_rust_resolver_use_self_in_inline_mod_deepens_anchor():
    # `mod x { use self::a::B; }` in src/foo.rs: `self` is the inline module
    # `foo::x`, so `a` is its submodule -> src/foo/x/a.rs.
    (raw,) = resolver.extract(b"mod x {\n    use self::a::B;\n}\n")
    files = {"src/lib.rs", "src/foo/x/a.rs"}
    assert resolver.resolve("src/foo.rs", raw, files) == ["src/foo/x/a.rs"]


@_needs_ts
def test_rust_resolver_use_super_super_in_inline_mod_climbs_above_file():
    # `mod tests { use super::super::X; }` in src/foo.rs: one `super` climbs out
    # of the inline `tests` to the file module foo, the second climbs above it to
    # the crate root -> X is a crate-root item (src/X.rs, crate root as container).
    (raw,) = resolver.extract(b"mod tests {\n    use super::super::X;\n}\n")
    files = {"src/lib.rs", "src/X.rs"}
    assert resolver.resolve("src/foo.rs", raw, files) == ["src/X.rs", "src/lib.rs"]


@_needs_ts
def test_rust_resolver_use_super_group_in_inline_mod_anchors_at_enclosing_module():
    # A grouped `mod x { use super::{a, b}; }` in src/foo.rs: the bare `super`
    # group head climbs out of the inline `x` to the file module foo, so a, b are
    # foo's submodules -> src/foo/a.rs, src/foo/b.rs.
    (raw,) = resolver.extract(b"mod x {\n    use super::{a, b};\n}\n")
    files = {"src/lib.rs", "src/foo/a.rs", "src/foo/b.rs"}
    assert resolver.resolve("src/foo.rs", raw, files) == ["src/foo/a.rs", "src/foo/b.rs"]


# ---------- Cargo bin / test / example / bench crate roots: a file directly
# under src/bin/, tests/, examples/ or benches/ is its OWN crate root, so its
# `crate::` anchors at that target (pure resolve — the module string alone drives
# it, so no tree-sitter is needed) (#358). ----------


def test_rust_resolver_crate_from_integration_test_anchors_at_test_root():
    # `crate::helpers::run` from an integration test tests/api.rs anchors at that
    # test's own crate root (tests/api) -> tests/api/helpers.rs. Before the fix
    # this found no lib.rs/main.rs ancestor and dropped the import entirely.
    files = {"tests/api.rs", "tests/api/helpers.rs"}
    assert resolver.resolve("tests/api.rs", _use("crate::helpers::run"), files) == [
        "tests/api/helpers.rs"
    ]


def test_rust_resolver_crate_from_bin_target_resolves_to_own_root():
    # `crate::Item` from a binary src/bin/tool.rs resolves to the binary's OWN
    # root (src/bin/tool.rs), not the sibling library crate — even though a
    # src/lib.rs exists, a binary's `crate::` names the binary crate.
    files = {"src/lib.rs", "src/bin/tool.rs"}
    assert resolver.resolve("src/bin/tool.rs", _use("crate::Item"), files) == ["src/bin/tool.rs"]


def test_rust_resolver_crate_from_bin_submodule_anchors_at_bin_root():
    # A submodule of a bin target (src/bin/tool/helper.rs, under the tool root's
    # sibling dir) still anchors `crate::` at the tool crate root -> its
    # src/bin/tool/config.rs.
    files = {"src/lib.rs", "src/bin/tool.rs", "src/bin/tool/config.rs"}
    assert resolver.resolve("src/bin/tool/helper.rs", _use("crate::config::load"), files) == [
        "src/bin/tool/config.rs"
    ]


def test_rust_resolver_crate_from_example_target_anchors_at_example_root():
    # An example examples/demo.rs is its own crate root too -> crate::util anchors
    # at examples/demo -> examples/demo/util.rs.
    files = {"src/lib.rs", "examples/demo.rs", "examples/demo/util.rs"}
    assert resolver.resolve("examples/demo.rs", _use("crate::util"), files) == [
        "examples/demo/util.rs",
        "examples/demo.rs",
    ]


def test_rust_resolver_tests_dir_nested_under_src_is_a_regular_module_not_a_target():
    # A `tests` component UNDER src/ is a normal module directory, not an
    # integration target: `crate::` from src/foo/tests/bar.rs still anchors at the
    # real library crate root (src) via lib.rs -> src/thing.rs (as a submodule)
    # and src/lib.rs (as the item container), NOT a src/foo/tests/bar target root.
    files = {"src/lib.rs", "src/foo/tests/bar.rs", "src/thing.rs"}
    assert resolver.resolve("src/foo/tests/bar.rs", _use("crate::thing"), files) == [
        "src/thing.rs",
        "src/lib.rs",
    ]


# ---------- crate-root disambiguation (pure resolve, no tree-sitter) ----------


def test_rust_resolver_crate_item_from_shared_module_defaults_to_lib_when_both_roots_present():
    # BOTH lib.rs and main.rs at the crate root, importer is a SHARED src/ module
    # (src/bar.rs) whose crate membership the path-only contract cannot determine.
    # A crate-root reference must emit ONE edge, not a spurious second: the
    # DOCUMENTED default anchors at the library root (lib.rs). (An importer that
    # is itself a crate root anchors at its OWN root instead -- see below.)
    files = {"src/lib.rs", "src/main.rs"}
    assert resolver.resolve("src/bar.rs", _use("crate::Helper"), files) == ["src/lib.rs"]


def test_rust_resolver_crate_item_from_main_anchors_at_main_not_lib_sibling():
    # BOTH lib.rs and main.rs present: `crate::` names the CALLER's OWN crate, so
    # a `use crate::AppState` from the BINARY root src/main.rs must resolve to
    # src/main.rs, NOT the library sibling src/lib.rs (the mixed lib+bin bug #358).
    files = {"src/lib.rs", "src/main.rs"}
    assert resolver.resolve("src/main.rs", _use("crate::AppState"), files) == ["src/main.rs"]


def test_rust_resolver_crate_item_from_lib_stays_at_lib_when_both_roots_present():
    # The mirror case: `use crate::AppState` from the LIBRARY root src/lib.rs must
    # still resolve to src/lib.rs (its own root), not leak to the bin sibling.
    files = {"src/lib.rs", "src/main.rs"}
    assert resolver.resolve("src/lib.rs", _use("crate::AppState"), files) == ["src/lib.rs"]


def test_rust_resolver_self_item_from_main_anchors_at_main_not_lib_sibling():
    # `self::` at a crate root probes the root module as the item container too,
    # so it must honour the caller's own root the same way `crate::` does: a
    # `use self::AppState` from src/main.rs resolves to src/main.rs, not lib.rs.
    files = {"src/lib.rs", "src/main.rs"}
    assert resolver.resolve("src/main.rs", _use("self::AppState"), files) == ["src/main.rs"]


@_needs_ts
def test_rust_resolver_crate_item_from_main_anchors_at_own_root_real_treesitter():
    # End-to-end through REAL tree-sitter: extract `use crate::AppState;` and
    # resolve it from src/main.rs with BOTH roots present -> src/main.rs (#358).
    (raw,) = resolver.extract(b"use crate::AppState;\n")
    assert raw.module == "crate::AppState"
    files = {"src/lib.rs", "src/main.rs"}
    assert resolver.resolve("src/main.rs", raw, files) == ["src/main.rs"]


def test_rust_resolver_nested_module_named_main_owns_its_sibling_dir():
    # A module reached as `main.rs` but nested BELOW the real crate root is a
    # plain module, not a crate root: `mod widget;` in src/foo/main.rs resolves
    # to its sibling dir src/foo/main/widget.rs, NOT src/foo/widget.rs.
    files = {
        "src/lib.rs",
        "src/foo/main.rs",
        "src/foo/main/widget.rs",
        "src/foo/widget.rs",
    }
    assert resolver.resolve("src/foo/main.rs", _mod("widget"), files) == ["src/foo/main/widget.rs"]


# ---------- scan_repo integration (real tree-sitter, committed fixture) ----------


@_needs_ts
def test_rust_resolver_scan_emits_import_edges_on_committed_fixture():
    # End-to-end on the committed crate: mod + crate/self/super uses all resolve,
    # and the external `std` use is dropped.
    repo_map = scan_repo(_FIXTURE_CRATE, generator_version="t")
    import_edges = {(e.source, e.target): e for e in repo_map.edges if e.type == "imports"}
    pairs = set(import_edges)
    assert pairs == {
        ("file:src/main.rs", "file:src/foo.rs"),  # mod foo; + use crate::foo::Thing
        ("file:src/main.rs", "file:src/bar.rs"),  # mod bar;
        ("file:src/foo.rs", "file:src/foo/helper.rs"),  # mod helper; + use self::helper
        ("file:src/foo.rs", "file:src/bar.rs"),  # use super::bar::Bar
        ("file:src/bar.rs", "file:src/foo.rs"),  # use crate::foo::Thing
    }
    assert all(e.confidence == "high" for e in import_edges.values())  # all module-level
    # External std is dropped: every edge endpoint is a real fixture node.
    node_ids = {n.id for n in repo_map.nodes}
    for src, tgt in pairs:
        assert src in node_ids and tgt in node_ids
