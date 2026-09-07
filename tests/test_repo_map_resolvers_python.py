# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Unit tests for the Python import resolver (#354).

``extract`` is tested against REAL tree-sitter output (skipped without the
extra); ``resolve`` is pure path arithmetic over a supplied file set and runs
on every interpreter. Each ``resolve`` case names the UA rule it exercises:
relative dot-anchoring, PEP 420 namespace packages, sys.path walk-up
(deepest-first), specifier submodule probing, the wildcard/qualified skips, and
regular-package-over-module precedence (#461).
"""

from __future__ import annotations

import pytest

from sumo_qa.repo_map_resolvers import get_resolver, registered_languages
from sumo_qa.repo_map_resolvers.base import RawImport
from sumo_qa.repo_map_resolvers.python import PythonResolver
from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE

resolver = PythonResolver()


# ---------- registry ----------


def test_python_resolver_is_registered():
    assert "python" in registered_languages()
    assert get_resolver("python") is not None


def test_unknown_language_has_no_resolver():
    assert get_resolver("cobol") is None


# ---------- extract (real tree-sitter) ----------

_needs_ts = pytest.mark.skipif(
    not TREESITTER_AVAILABLE,
    reason="tree-sitter not installed (the [treesitter] extra is absent)",
)


@_needs_ts
def test_extract_plain_and_dotted_imports():
    raws = resolver.extract(b"import os\nimport os.path\n")
    modules = [(r.module, r.level, r.function_local) for r in raws]
    assert ("os", 0, False) in modules
    assert ("os.path", 0, False) in modules


@_needs_ts
def test_extract_from_import_collects_specifiers():
    (raw,) = resolver.extract(b"from a.b import c, d\n")
    assert raw.module == "a.b"
    assert raw.level == 0
    assert set(raw.names) == {"c", "d"}


@_needs_ts
def test_extract_relative_levels():
    raws = resolver.extract(b"from . import x\nfrom ..pkg import y\n")
    by_level = {r.level: r for r in raws}
    assert by_level[1].module == ""  # `from .` has no module tail
    assert by_level[2].module == "pkg"  # `from ..pkg` keeps the tail


@_needs_ts
def test_extract_aliased_specifier_uses_imported_name_not_alias():
    (raw,) = resolver.extract(b"from m import n as alias\n")
    assert raw.names == ("n",)  # the imported name, not the local alias


@_needs_ts
def test_extract_wildcard_yields_no_specifier():
    (raw,) = resolver.extract(b"from x import *\n")
    assert raw.module == "x"
    assert raw.names == ()  # `*` is not a probeable specifier


@_needs_ts
def test_extract_aliased_plain_import_uses_dotted_module_not_alias():
    # `import a.b as c` -> module is the dotted path `a.b`, not the local alias.
    (raw,) = resolver.extract(b"import a.b as c\n")
    assert raw.module == "a.b"
    assert raw.level == 0
    assert raw.names == ()


@_needs_ts
def test_extract_function_local_flagged_class_body_not():
    src = b"def fn():\n    import json\nclass K:\n    import sys\n"
    raws = {r.module: r for r in resolver.extract(src)}
    assert raws["json"].function_local is True  # nested in a function body -> lazy
    assert raws["sys"].function_local is False  # class body is module-level coupling


# ---------- resolve (pure, runs everywhere) ----------


def test_resolve_absolute_module_to_file():
    imp = RawImport(module="pkg.mod", level=0, names=(), function_local=False)
    files = {"pkg/mod.py", "other.py"}
    assert resolver.resolve("app/main.py", imp, files) == ["pkg/mod.py"]


def test_resolve_pep420_namespace_package_without_init():
    # PEP 420: a directory need not contain __init__.py to be a package. The
    # module resolves to the barrel when present, and to a submodule even when
    # the parent has no __init__.py.
    imp = RawImport(module="ns", level=0, names=("sub",), function_local=False)
    files = {"ns/sub.py"}  # note: no ns/__init__.py
    assert resolver.resolve("app/main.py", imp, files) == ["ns/sub.py"]


def test_resolve_relative_dot_anchors_to_importer_package():
    # `from . import sibling` resolves inside the importer's own package.
    imp = RawImport(module="", level=1, names=("sibling",), function_local=False)
    files = {"pkg/a.py", "pkg/sibling.py"}
    assert resolver.resolve("pkg/a.py", imp, files) == ["pkg/sibling.py"]


def test_resolve_relative_two_dots_walks_up_one_package():
    # `from .. import x` from pkg/sub/a.py anchors at pkg/, not pkg/sub/.
    imp = RawImport(module="", level=2, names=("shared",), function_local=False)
    files = {"pkg/sub/a.py", "pkg/shared.py", "pkg/sub/shared.py"}
    assert resolver.resolve("pkg/sub/a.py", imp, files) == ["pkg/shared.py"]


def test_resolve_relative_overshoot_past_root_yields_nothing():
    # More dots than there are ancestor packages cannot resolve.
    imp = RawImport(module="", level=5, names=("x",), function_local=False)
    files = {"pkg/a.py", "x.py"}
    assert resolver.resolve("pkg/a.py", imp, files) == []


def test_resolve_relative_consuming_all_package_components_yields_nothing():
    # Boundary: a 2-component package (pkg/sub/) with 3 dots consumes BOTH
    # components and walks past the top-level package. Python rejects this
    # ("attempted relative import beyond top-level package"); it must NOT anchor
    # at the repo root and fabricate an edge to a root-level x.py.
    imp = RawImport(module="", level=3, names=("x",), function_local=False)
    files = {"pkg/sub/a.py", "x.py"}
    assert resolver.resolve("pkg/sub/a.py", imp, files) == []


def test_resolve_absolute_syspath_walkup_prefers_deepest_root():
    # The same module name exists under two candidate roots; the deepest
    # ancestor of the importer (src/app/) must win over the shallower (src/).
    imp = RawImport(module="util", level=0, names=(), function_local=False)
    files = {"src/app/util.py", "src/util.py", "src/app/main.py"}
    assert resolver.resolve("src/app/main.py", imp, files) == ["src/app/util.py"]


def test_resolve_specifier_submodule_probing():
    # `from pkg import sub` may name a submodule, not a member -> probe pkg/sub.py.
    imp = RawImport(module="pkg", level=0, names=("sub",), function_local=False)
    files = {"pkg/sub.py"}
    assert resolver.resolve("app/main.py", imp, files) == ["pkg/sub.py"]


def test_resolve_dotted_module_does_not_probe_under_a_shadowing_module():
    # A top-level module `pkg.py` shadows a same-named package dir `pkg/`; a
    # module has no submodules, so `import pkg.sub` must resolve to the module
    # `pkg.py`, never fabricate an edge to `pkg/sub.py` under the shadowed dir.
    imp = RawImport(module="pkg.sub", level=0, names=(), function_local=False)
    files = {"pkg.py", "pkg/sub.py"}
    assert resolver.resolve("app/main.py", imp, files) == ["pkg.py"]


def test_resolve_from_import_does_not_probe_submodule_under_a_shadowing_module():
    # `from pkg import sub` records module="pkg", names=("sub",). A top-level
    # module `pkg.py` shadows a same-named package dir, and a module has no
    # submodules, so the specifier `sub` is a member of `pkg.py`, never the
    # submodule `pkg/sub.py`. Resolution must collapse to the module `pkg.py`
    # and NOT fabricate an edge to `pkg/sub.py` (the dotted-form round-1 guard
    # only fires for >=2 module parts, so the from-import path needs its own).
    imp = RawImport(module="pkg", level=0, names=("sub",), function_local=False)
    files = {"pkg.py", "pkg/sub.py"}
    assert resolver.resolve("app/main.py", imp, files) == ["pkg.py"]


def test_resolve_from_import_real_package_submodule_still_resolves_both():
    # Overcorrection guard: when `pkg` is a REAL package (has pkg/__init__.py,
    # no shadowing pkg.py), `from pkg import sub` must STILL resolve to both the
    # package barrel and the submodule pkg/sub.py.
    imp = RawImport(module="pkg", level=0, names=("sub",), function_local=False)
    files = {"pkg/__init__.py", "pkg/sub.py"}
    assert resolver.resolve("app/main.py", imp, files) == ["pkg/__init__.py", "pkg/sub.py"]


def test_resolve_from_import_namespace_package_submodule_still_resolves():
    # Overcorrection guard: a PEP 420 namespace package (dir without
    # __init__.py and no shadowing pkg.py) must still resolve the submodule.
    imp = RawImport(module="ns", level=0, names=("sub",), function_local=False)
    files = {"ns/sub.py"}  # no ns/__init__.py, no ns.py
    assert resolver.resolve("app/main.py", imp, files) == ["ns/sub.py"]


def test_resolve_relative_from_import_does_not_probe_submodule_under_a_shadowing_module():
    # The shadowing guard must apply to RELATIVE imports too. `from .sub import
    # child` in pkg/a.py anchors the base module at pkg/sub; a module pkg/sub.py
    # shadows the same-named package dir, so `child` is a member of that module,
    # never the submodule pkg/sub/child.py. Resolution must collapse to pkg/sub.py
    # and NOT fabricate an edge to pkg/sub/child.py (which is in the file set, so
    # the guard is discriminating: without it the relative path also emits it).
    imp = RawImport(module="sub", level=1, names=("child",), function_local=False)
    files = {"pkg/a.py", "pkg/sub.py", "pkg/sub/child.py"}
    assert resolver.resolve("pkg/a.py", imp, files) == ["pkg/sub.py"]


def test_resolve_relative_from_import_real_package_submodule_still_resolves_both():
    # Overcorrection guard for the relative path: when the relative base is a
    # REAL package (pkg/sub/__init__.py, no shadowing pkg/sub.py), `from .sub
    # import child` must STILL resolve both the package barrel and the submodule.
    imp = RawImport(module="sub", level=1, names=("child",), function_local=False)
    files = {"pkg/a.py", "pkg/sub/__init__.py", "pkg/sub/child.py"}
    assert resolver.resolve("pkg/a.py", imp, files) == [
        "pkg/sub/__init__.py",
        "pkg/sub/child.py",
    ]


def test_resolve_relative_intermediate_component_shadowing():
    # The intermediate-component shadow guard must apply to relative imports too.
    # `from ..a.sub import x` in pkg/sub/m.py anchors at pkg/a/sub; a module
    # pkg/a.py shadows the package dir pkg/a/, so the import resolves to pkg/a.py
    # and never descends to fabricate pkg/a/sub.py (present in the file set, so
    # the guard is discriminating).
    imp = RawImport(module="a.sub", level=2, names=("x",), function_local=False)
    files = {"pkg/sub/m.py", "pkg/a.py", "pkg/a/sub.py"}
    assert resolver.resolve("pkg/sub/m.py", imp, files) == ["pkg/a.py"]


def test_resolve_qualified_specifier_is_skipped():
    # A dotted specifier is not a plain submodule name; only the module itself
    # is probed, never a fabricated `pkg/a.b.py`. The fabricated path is present
    # in the file set so the skip is discriminating: dropping the guard would
    # additionally emit `pkg/a.b.py`.
    imp = RawImport(module="pkg", level=0, names=("a.b",), function_local=False)
    files = {"pkg/__init__.py", "pkg/a.b.py"}
    assert resolver.resolve("app/main.py", imp, files) == ["pkg/__init__.py"]


def test_resolve_external_package_yields_nothing():
    # An import that matches no file in the repo is external -> no edge.
    imp = RawImport(module="requests", level=0, names=("get",), function_local=False)
    files = {"app/main.py"}
    assert resolver.resolve("app/main.py", imp, files) == []


def test_resolve_dedups_module_and_specifier_collisions():
    # `from pkg import __init__` must yield exactly one edge, pkg/__init__.py:
    # the barrel is the module-level hit, and the specifier `__init__` names an
    # attribute every module object carries, so no submodule probe runs (and
    # even if one did, it would land on the same file and be de-duplicated).
    imp = RawImport(module="pkg", level=0, names=("__init__",), function_local=False)
    files = {"pkg/__init__.py"}
    assert resolver.resolve("app/main.py", imp, files) == ["pkg/__init__.py"]


# ---------- regular-package-over-module precedence (#461) ----------
#
# When both `p.py` and `p/__init__.py` exist at the same import path, the
# Python runtime imports the regular package and never the module. Every
# ambiguous case below puts BOTH leaf candidates in the file set so the test
# discriminates: without the precedence rule the resolver also emits the
# losing `p.py` edge. Decision table over (module exists, barrel exists,
# descendant exists) crossed with the three import forms.

_AMBIGUOUS_LEAF = {"pkg/__init__.py", "pkg/x.py", "pkg/x/__init__.py", "pkg/a.py"}


def test_resolve_dotted_import_prefers_regular_package_over_same_named_module():
    # `import pkg.x`: the runtime selects pkg/x/__init__.py; pkg/x.py is the
    # losing candidate and must not become an edge.
    imp = RawImport(module="pkg.x", level=0, names=(), function_local=False)
    assert resolver.resolve("app/main.py", imp, _AMBIGUOUS_LEAF) == ["pkg/x/__init__.py"]


def test_resolve_from_import_prefers_regular_package_and_keeps_containing_barrel():
    # `from pkg import x`: the containing barrel pkg/__init__.py stays a valid
    # dependency; the leaf keeps only the package barrel, never pkg/x.py.
    imp = RawImport(module="pkg", level=0, names=("x",), function_local=False)
    assert resolver.resolve("app/main.py", imp, _AMBIGUOUS_LEAF) == [
        "pkg/__init__.py",
        "pkg/x/__init__.py",
    ]


def test_resolve_relative_from_import_prefers_regular_package_like_absolute():
    # `from . import x` inside pkg/a.py must land on exactly the same result as
    # the absolute `from pkg import x`: one shared precedence implementation.
    imp = RawImport(module="", level=1, names=("x",), function_local=False)
    absolute = RawImport(module="pkg", level=0, names=("x",), function_local=False)
    relative_result = resolver.resolve("pkg/a.py", imp, _AMBIGUOUS_LEAF)
    assert relative_result == resolver.resolve("app/main.py", absolute, _AMBIGUOUS_LEAF)
    assert relative_result == ["pkg/__init__.py", "pkg/x/__init__.py"]


def test_resolve_only_module_present_keeps_the_module():
    # Overcorrection guard: with no same-named package, `import pkg.x` still
    # resolves to the module pkg/x.py.
    imp = RawImport(module="pkg.x", level=0, names=(), function_local=False)
    files = {"pkg/__init__.py", "pkg/x.py"}
    assert resolver.resolve("app/main.py", imp, files) == ["pkg/x.py"]


def test_resolve_only_package_barrel_present_keeps_the_barrel():
    # Overcorrection guard: with no same-named module, `import pkg.x` resolves
    # to the package barrel pkg/x/__init__.py.
    imp = RawImport(module="pkg.x", level=0, names=(), function_local=False)
    files = {"pkg/__init__.py", "pkg/x/__init__.py"}
    assert resolver.resolve("app/main.py", imp, files) == ["pkg/x/__init__.py"]


def test_resolve_module_beside_namespace_dir_still_wins_and_suppresses_descent():
    # PR #460 shadowing preserved: pkg/x.py beside a same-named NAMESPACE dir
    # (pkg/x/child.py, no pkg/x/__init__.py) is still the module, and the
    # descent to pkg/x/child.py stays suppressed for both import forms.
    files = {"pkg/__init__.py", "pkg/x.py", "pkg/x/child.py"}
    from_form = RawImport(module="pkg.x", level=0, names=("child",), function_local=False)
    dotted_form = RawImport(module="pkg.x.child", level=0, names=(), function_local=False)
    assert resolver.resolve("app/main.py", from_form, files) == ["pkg/x.py"]
    assert resolver.resolve("app/main.py", dotted_form, files) == ["pkg/x.py"]


def test_resolve_regular_package_beside_module_keeps_child_resolvable():
    # A regular package (pkg/x/__init__.py) beside a same-named module is the
    # package, so its real child stays reachable: the shadowing guard must NOT
    # fire on pkg/x.py. Both import forms reach pkg/x/child.py and neither
    # emits the losing pkg/x.py.
    files = {"pkg/__init__.py", "pkg/x.py", "pkg/x/__init__.py", "pkg/x/child.py"}
    from_form = RawImport(module="pkg.x", level=0, names=("child",), function_local=False)
    dotted_form = RawImport(module="pkg.x.child", level=0, names=(), function_local=False)
    assert resolver.resolve("app/main.py", from_form, files) == [
        "pkg/x/__init__.py",
        "pkg/x/child.py",
    ]
    assert resolver.resolve("app/main.py", dotted_form, files) == ["pkg/x/child.py"]


def test_resolve_precedence_keeps_candidate_order_and_dedup_deterministic():
    # Mixed specifiers: `x` is ambiguous (package wins), `y` is a plain module,
    # and `x` repeats. Output follows source order of the specifiers with the
    # containing barrel first, and the repeated specifier collapses to one edge.
    imp = RawImport(module="pkg", level=0, names=("x", "y", "x"), function_local=False)
    files = _AMBIGUOUS_LEAF | {"pkg/y.py"}
    assert resolver.resolve("app/main.py", imp, files) == [
        "pkg/__init__.py",
        "pkg/x/__init__.py",
        "pkg/y.py",
    ]


def test_resolve_relative_intermediate_regular_package_beside_module_keeps_descent():
    # Relative counterpart of the loosened intermediate guard: `from ..x.sub
    # import y` in pkg/sub/m.py anchors at pkg/x/sub. pkg/x.py sits beside a
    # REGULAR package pkg/x/__init__.py, so it does not shadow and descent to
    # pkg/x/sub.py continues; the losing pkg/x.py never appears. Discriminating:
    # the pre-fix guard collapsed this to ["pkg/x.py"].
    imp = RawImport(module="x.sub", level=2, names=("y",), function_local=False)
    files = {"pkg/sub/m.py", "pkg/x.py", "pkg/x/__init__.py", "pkg/x/sub.py"}
    assert resolver.resolve("pkg/sub/m.py", imp, files) == ["pkg/x/sub.py"]


# ---------- root walk stops at the root whose regular package owns the head ----------


def test_resolve_absolute_stops_at_root_whose_regular_package_lacks_the_leaf():
    # Codex finding on #461: app/pkg/__init__.py (beside a losing app/pkg.py)
    # wins the head component under the nearest root, so CPython searches ONLY
    # that package for `child` and raises ModuleNotFoundError; it never falls
    # through to the unrelated root-level pkg/child.py. No edge at all.
    imp = RawImport(module="pkg.child", level=0, names=(), function_local=False)
    files = {"app/main.py", "app/pkg.py", "app/pkg/__init__.py", "pkg/child.py"}
    assert resolver.resolve("app/main.py", imp, files) == []


def test_resolve_absolute_regular_package_without_leaf_does_not_fall_through_to_shallower_root():
    # Same rule without the ambiguous leaf: a plain regular package under the
    # nearest root that lacks `child` owns the import; the shallower root's
    # pkg/child.py is not on that package's search path.
    imp = RawImport(module="pkg.child", level=0, names=(), function_local=False)
    files = {"app/main.py", "app/pkg/__init__.py", "pkg/child.py"}
    assert resolver.resolve("app/main.py", imp, files) == []


def test_resolve_absolute_namespace_portion_still_merges_across_roots():
    # Overcorrection guard (PEP 420): when NO root has a regular package or
    # module for `pkg`, every `pkg/` dir is a namespace portion and CPython
    # merges them, so pkg/child.py under the shallower root still resolves
    # even though the nearest root has its own pkg/other.py portion.
    imp = RawImport(module="pkg.child", level=0, names=(), function_local=False)
    files = {"app/main.py", "app/pkg/other.py", "pkg/child.py"}
    assert resolver.resolve("app/main.py", imp, files) == ["pkg/child.py"]


def test_resolve_from_import_regular_package_at_nearest_root_wins_over_shallower_package():
    # `from pkg import child`: the nearest root's regular package is the hit
    # (child may be a member of it); the shallower root's pkg/__init__.py and
    # pkg/child.py must not be reached.
    imp = RawImport(module="pkg", level=0, names=("child",), function_local=False)
    files = {"app/main.py", "app/pkg/__init__.py", "pkg/__init__.py", "pkg/child.py"}
    assert resolver.resolve("app/main.py", imp, files) == ["app/pkg/__init__.py"]


def test_resolve_absolute_intermediate_regular_package_under_namespace_head_stops_walk():
    # Codex follow-up on #461: `pkg` is a namespace portion under app/ but
    # `pkg.sub` is a REGULAR package there (app/pkg/sub/__init__.py, beside a
    # losing app/pkg/sub.py). CPython confines `child` to that package and
    # raises; the shallower root's pkg/sub/child.py is unreachable. No edge.
    imp = RawImport(module="pkg.sub.child", level=0, names=(), function_local=False)
    files = {"app/main.py", "app/pkg/sub.py", "app/pkg/sub/__init__.py", "pkg/sub/child.py"}
    assert resolver.resolve("app/main.py", imp, files) == []


def test_resolve_absolute_nested_namespace_portions_still_merge_across_roots():
    # Overcorrection guard: with NO regular package at any level under app/
    # (app/pkg/sub/ holds only other.py), both `pkg` and `pkg.sub` are
    # namespace packages whose portions merge across roots, so pkg/sub/child.py
    # under the shallower root resolves (verified against CPython).
    imp = RawImport(module="pkg.sub.child", level=0, names=(), function_local=False)
    files = {"app/main.py", "app/pkg/sub/other.py", "pkg/sub/child.py"}
    assert resolver.resolve("app/main.py", imp, files) == ["pkg/sub/child.py"]


# ---------- PEP 420: a regular package anywhere on the path beats namespace portions ----------


def test_resolve_absolute_regular_package_at_shallower_root_beats_nearer_namespace_portion():
    # sys.path order is [app, repo]. app/pkg/ has no __init__.py, so it is only
    # a namespace PORTION; pkg/__init__.py at the shallower root is a regular
    # package and wins outright (PEP 420 discards the portions), so `child` is
    # looked up under pkg/ only. Both import forms agree (verified in CPython).
    files = {"app/main.py", "app/pkg/child.py", "pkg/__init__.py", "pkg/child.py"}
    dotted = RawImport(module="pkg.child", level=0, names=(), function_local=False)
    from_form = RawImport(module="pkg", level=0, names=("child",), function_local=False)
    assert resolver.resolve("app/main.py", dotted, files) == ["pkg/child.py"]
    assert resolver.resolve("app/main.py", from_form, files) == [
        "pkg/__init__.py",
        "pkg/child.py",
    ]


def test_resolve_absolute_regular_intermediate_under_discarded_portion_does_not_claim():
    # pkg/__init__.py at the repo root wins the head, so app/pkg/ is discarded
    # entirely; its regular app/pkg/sub/__init__.py is never consulted. Under
    # pkg/, `sub` is a namespace dir and pkg/sub/child.py resolves.
    files = {"app/main.py", "app/pkg/sub/__init__.py", "pkg/__init__.py", "pkg/sub/child.py"}
    dotted = RawImport(module="pkg.sub.child", level=0, names=(), function_local=False)
    from_form = RawImport(module="pkg.sub", level=0, names=("child",), function_local=False)
    assert resolver.resolve("app/main.py", dotted, files) == ["pkg/sub/child.py"]
    assert resolver.resolve("app/main.py", from_form, files) == ["pkg/sub/child.py"]


# ---------- relative imports inside a namespace package split across roots ----------


def test_resolve_relative_import_merges_namespace_portions_from_shallower_roots():
    # app/pkg/ has no __init__.py, and neither does pkg/ at the repo root: with
    # sys.path [app, repo] both are portions of the namespace package `pkg`, so
    # `from . import x` in app/pkg/m.py finds pkg/x.py (verified in CPython).
    imp = RawImport(module="", level=1, names=("x",), function_local=False)
    files = {"app/pkg/m.py", "pkg/x.py"}
    assert resolver.resolve("app/pkg/m.py", imp, files) == ["pkg/x.py"]


def test_resolve_relative_import_never_escapes_a_regular_package_chain():
    # pkg/ is a regular package (pkg/__init__.py), so the importer is pkg.sub.m
    # rooted at the repo root and `from . import x` is `pkg.sub.x`, confined to
    # pkg/sub/. The unrelated top-level sub/ (and b/) must never be merged in
    # as a "portion" of the anchored package.
    imp = RawImport(module="", level=1, names=("x",), function_local=False)
    files = {"pkg/__init__.py", "pkg/sub/m.py", "sub/x.py"}
    assert resolver.resolve("pkg/sub/m.py", imp, files) == []
    deeper = {"pkg/__init__.py", "pkg/a/__init__.py", "pkg/a/b/m.py", "b/x.py"}
    assert resolver.resolve("pkg/a/b/m.py", imp, deeper) == []


def test_resolve_relative_import_does_not_guess_a_root_above_a_namespace_parent():
    # Deliberate under-edge. If app/ were the sys.path root, pkg.sub would be a
    # namespace package spanning app/pkg/sub and pkg/sub and `from .. import x`
    # in app/pkg/sub/deep/m.py would find pkg/sub/x.py. Nothing in the file set
    # says app/ is the root rather than app/pkg/, so the deepest candidate is
    # taken and no cross-root portion is fabricated.
    imp = RawImport(module="", level=2, names=("x",), function_local=False)
    files = {"app/pkg/sub/deep/m.py", "pkg/sub/x.py"}
    assert resolver.resolve("app/pkg/sub/deep/m.py", imp, files) == []


def test_resolve_relative_import_under_edges_when_a_shallower_root_owns_the_package():
    # pkg/__init__.py at the repo root makes `pkg` a regular package there, so
    # app/pkg/ is NOT part of it (CPython: `import pkg.m` raises). The importer's
    # own directory is not the package its dots name, so no edge is guessed.
    imp = RawImport(module="", level=1, names=("x",), function_local=False)
    files = {"app/pkg/m.py", "pkg/__init__.py", "pkg/x.py"}
    assert resolver.resolve("app/pkg/m.py", imp, files) == []


def test_resolve_relative_import_regular_package_at_anchor_ignores_shallower_portions():
    # The importer's own directory IS the regular package (app/pkg/__init__.py),
    # which confines the lookup: pkg/x.py at the repo root is never reached.
    imp = RawImport(module="", level=1, names=("x",), function_local=False)
    files = {"app/pkg/m.py", "app/pkg/__init__.py", "pkg/x.py"}
    assert resolver.resolve("app/pkg/m.py", imp, files) == ["app/pkg/__init__.py"]


def test_resolve_from_import_specifier_that_is_a_module_attribute_is_not_a_submodule():
    # `from pkg import __init__` binds the attribute every module object carries
    # (types.ModuleType has `__init__`), so CPython never imports a submodule
    # and pkg/__init__/__init__.py must not become an edge.
    imp = RawImport(module="pkg", level=0, names=("__init__",), function_local=False)
    files = {"app/main.py", "pkg/__init__.py", "pkg/__init__/__init__.py"}
    assert resolver.resolve("app/main.py", imp, files) == ["pkg/__init__.py"]


def test_resolve_from_import_specifier_named_like_a_type_attribute_is_still_a_submodule():
    # `mro`, `__mro__`, `__call__` live on `type`, not on a module INSTANCE, so
    # `from pkg import mro` does try the submodule pkg/mro.py. Only names a
    # module instance itself answers to (`__init__`, `__doc__`) are skipped.
    imp = RawImport(module="pkg", level=0, names=("mro",), function_local=False)
    files = {"app/main.py", "pkg/__init__.py", "pkg/mro.py"}
    assert resolver.resolve("app/main.py", imp, files) == ["pkg/__init__.py", "pkg/mro.py"]


def test_resolve_from_import_loader_added_attribute_is_not_a_submodule():
    # `__path__`, `__file__`, `__cached__` and `__builtins__` are set on a real
    # imported package by its loader, so `from pkg import __path__` binds the
    # attribute and CPython never imports a submodule; a file literally named
    # pkg/__path__.py must not become an edge.
    files = {"app/main.py", "pkg/__init__.py", "pkg/__path__.py", "pkg/__file__.py"}
    for name in ("__path__", "__file__"):
        imp = RawImport(module="pkg", level=0, names=(name,), function_local=False)
        assert resolver.resolve("app/main.py", imp, files) == ["pkg/__init__.py"], name


def test_resolve_relative_import_regular_package_at_anchor_ignores_a_root_level_module():
    # app/pkg/sub/ is a regular package and app/pkg/ is not, so the anchored
    # package is `sub` rooted at app/pkg/. A pkg.py at the repo root would only
    # shadow it if the repo root were on sys.path AND app/pkg/ were not, which
    # nothing in the file set indicates; the importer's own package resolves.
    imp = RawImport(module="", level=1, names=("x",), function_local=False)
    files = {"app/pkg/sub/m.py", "app/pkg/sub/__init__.py", "app/pkg/sub/x.py", "pkg.py"}
    assert resolver.resolve("app/pkg/sub/m.py", imp, files) == [
        "app/pkg/sub/__init__.py",
        "app/pkg/sub/x.py",
    ]
