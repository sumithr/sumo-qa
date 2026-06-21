# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Unit tests for the Python import resolver (#354).

``extract`` is tested against REAL tree-sitter output (skipped without the
extra); ``resolve`` is pure path arithmetic over a supplied file set and runs
on every interpreter. Each ``resolve`` case names the UA rule it exercises:
relative dot-anchoring, PEP-328 namespace packages, sys.path walk-up
(deepest-first), specifier submodule probing, and the wildcard/qualified skips.
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


def test_resolve_pep328_namespace_package_without_init():
    # PEP-328: a directory need not contain __init__.py to be a package. The
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
    # If module-probe and specifier-probe land on the SAME existing file, it
    # appears once. `from pkg import __init__` probes pkg/__init__.py as the
    # module barrel AND as the submodule pkg/__init__.py, so both probes collide
    # on one real file; dedup must collapse them to a single entry.
    imp = RawImport(module="pkg", level=0, names=("__init__",), function_local=False)
    files = {"pkg/__init__.py"}
    assert resolver.resolve("app/main.py", imp, files) == ["pkg/__init__.py"]
