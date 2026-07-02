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
