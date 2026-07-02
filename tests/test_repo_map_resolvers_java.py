# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Unit tests for the Java import resolver (#357).

``extract`` is tested against REAL tree-sitter output (skipped without the
``[treesitter]`` extra); ``resolve`` is pure path arithmetic over a supplied
file set and runs on every interpreter. An orchestrator integration test drives
a Java mini-repo through ``scan_repo`` end-to-end (real tree-sitter). Each
``resolve`` case names the UA Java rule it exercises: fully-qualified-name ->
source-root file mapping, wildcard package fan-out, JDK/external drop, the
path-boundary anchor that keeps suffix matching honest, and the static-import
type mapping.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sumo_qa.repo_map_resolvers import get_resolver, registered_languages
from sumo_qa.repo_map_resolvers.base import RawImport
from sumo_qa.repo_map_resolvers.java import JavaResolver
from sumo_qa.repo_map_scanner import scan_repo
from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE

resolver = JavaResolver()

_needs_ts = pytest.mark.skipif(
    not TREESITTER_AVAILABLE,
    reason="tree-sitter not installed (the [treesitter] extra is absent)",
)


# ---------- registry ----------


def test_java_resolver_is_registered():
    # In-process sanity: the java resolver is discoverable by id.
    assert "java" in registered_languages()
    assert get_resolver("java") is not None


def test_java_registered_via_package_init_not_direct_module_import():
    # Regression guard for the registration wiring. This *test module* imports
    # `...java` directly (line 22) for `JavaResolver`, whose module-level
    # register() side effect would make the in-process check above pass even if
    # the package __init__ stopped importing the java module - so the in-process
    # check does NOT cover package-level registration. Run the check in a FRESH
    # interpreter that imports ONLY the package: if __init__.py drops the java
    # import, the java module never loads, register() never runs, and
    # get_resolver("java") is None -> this fails.
    probe = (
        "import sys\n"
        "import sumo_qa.repo_map_resolvers as pkg\n"
        "assert 'sumo_qa.repo_map_resolvers.java' in sys.modules, "
        "'package __init__ did not import the java module'\n"
        "assert pkg.get_resolver('java') is not None, "
        "'java resolver not registered via package __init__'\n"
        "assert 'java' in pkg.registered_languages()\n"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# ---------- extract (real tree-sitter) ----------


@_needs_ts
def test_extract_single_type_import():
    (raw,) = resolver.extract(b"import a.b.C;\n")
    assert raw.module == "a.b.C"  # the fully-qualified type name
    assert raw.level == 0  # Java has no relative imports
    assert raw.names == ()
    assert raw.function_local is False  # Java imports are always top-level


@_needs_ts
def test_extract_wildcard_package_import_flags_fan_out():
    (raw,) = resolver.extract(b"import a.b.*;\n")
    assert raw.module == "a.b"  # the package, asterisk stripped
    assert raw.names == ("*",)  # the package fan-out marker resolve() reads


@_needs_ts
def test_extract_static_member_import_drops_member():
    # `import static a.b.C.method` -> the TYPE is a.b.C; the member `method` is
    # not a file, so extract drops it, leaving the resolvable type name.
    (raw,) = resolver.extract(b"import static a.b.C.method;\n")
    assert raw.module == "a.b.C"
    assert raw.names == ()


@_needs_ts
def test_extract_static_wildcard_import_is_type_not_package():
    # `import static a.b.C.*` imports all static members of the TYPE a.b.C - a
    # single type file, NOT a package fan-out, so it carries no "*" marker.
    (raw,) = resolver.extract(b"import static a.b.C.*;\n")
    assert raw.module == "a.b.C"
    assert raw.names == ()


@_needs_ts
def test_extract_nested_type_import_keeps_full_dotted_name():
    # `import a.b.Outer.Inner` imports the nested type Inner. extract keeps the
    # full dotted name; resolve is what truncates it to the declaring top-level
    # type's file (a nested type has no file of its own).
    (raw,) = resolver.extract(b"import a.b.Outer.Inner;\n")
    assert raw.module == "a.b.Outer.Inner"
    assert raw.names == ()  # not a package fan-out


@_needs_ts
def test_extract_static_nested_member_import_drops_only_trailing_member():
    # `import static a.b.Outer.Inner.CONST` -> the type is the nested a.b.Outer.Inner;
    # only the trailing member CONST is dropped (resolve truncates further to the
    # top-level type).
    (raw,) = resolver.extract(b"import static a.b.Outer.Inner.CONST;\n")
    assert raw.module == "a.b.Outer.Inner"
    assert raw.names == ()


@_needs_ts
def test_extract_skips_package_declaration_and_collects_only_imports():
    src = b"package com.example;\nimport a.b.C;\nimport d.e.F;\nclass X {}\n"
    mods = sorted(r.module for r in resolver.extract(src))
    assert mods == ["a.b.C", "d.e.F"]  # the `package` decl is not an import


@_needs_ts
def test_extract_multiple_imports():
    raws = resolver.extract(b"import a.b.C;\nimport a.b.D;\n")
    assert sorted(r.module for r in raws) == ["a.b.C", "a.b.D"]


@_needs_ts
def test_extract_survives_malformed_source_and_extracts_partially():
    # tree-sitter is error-recovering: broken syntax parses to a tree with ERROR
    # nodes rather than raising. extract must not blow up on it and should still
    # recover the well-formed import that precedes the broken class body.
    src = b"import a.b.C;\nclass X { void m( { }\n"
    raws = resolver.extract(src)  # must not raise
    assert [r.module for r in raws] == ["a.b.C"]


# ---------- resolve (pure, runs everywhere) ----------


def test_resolve_fqn_to_source_root_file():
    # `import a.b.C` -> src/main/java/a/b/C.java: the FQN's dotted path maps to a
    # file under a source root (Maven/Gradle layout).
    imp = RawImport(module="a.b.C", level=0, names=(), function_local=False)
    files = {"src/main/java/a/b/C.java", "src/main/java/a/b/D.java"}
    assert resolver.resolve("src/main/java/app/Main.java", imp, files) == [
        "src/main/java/a/b/C.java"
    ]


def test_resolve_fqn_with_no_source_root_prefix():
    # A flat layout: a/b/C.java directly at the repo root resolves too (the
    # source-root prefix is empty).
    imp = RawImport(module="a.b.C", level=0, names=(), function_local=False)
    files = {"a/b/C.java"}
    assert resolver.resolve("app/Main.java", imp, files) == ["a/b/C.java"]


def test_resolve_wildcard_package_import_fans_out_to_all_package_files():
    # `import a.b.*` -> every .java directly in package dir a/b; sub-packages and
    # sibling packages are NOT part of the fan-out.
    imp = RawImport(module="a.b", level=0, names=("*",), function_local=False)
    files = {
        "src/main/java/a/b/C.java",
        "src/main/java/a/b/D.java",
        "src/main/java/a/b/sub/Deep.java",  # sub-package: excluded
        "src/main/java/a/Other.java",  # different package: excluded
        "src/main/java/a/b/notes.txt",  # non-.java in the package dir: excluded
        "Root.java",  # default-package (slash-less) .java: excluded
    }
    assert resolver.resolve("src/main/java/app/Main.java", imp, files) == [
        "src/main/java/a/b/C.java",
        "src/main/java/a/b/D.java",
    ]


def test_resolve_external_package_yields_nothing():
    # A class absent from the repo is external -> no edge (no file matches).
    imp = RawImport(module="com.google.common.base.Joiner", level=0, names=(), function_local=False)
    files = {"src/main/java/app/Main.java"}
    assert resolver.resolve("src/main/java/app/Main.java", imp, files) == []


def test_resolve_jdk_package_dropped_even_if_a_shadow_file_exists():
    # java.* is dropped by the JDK guard. Discriminator: a file matching the
    # suffix is PRESENT, so without the guard suffix-matching would fabricate an
    # edge; the guard must drop it regardless.
    imp = RawImport(module="java.util.List", level=0, names=(), function_local=False)
    files = {"java/util/List.java"}  # present, but java.* must still be dropped
    assert resolver.resolve("src/main/java/app/Main.java", imp, files) == []


def test_resolve_javax_package_dropped():
    imp = RawImport(module="javax.swing.JFrame", level=0, names=(), function_local=False)
    files = {"javax/swing/JFrame.java"}
    assert resolver.resolve("src/main/java/app/Main.java", imp, files) == []


def test_resolve_jdk_wildcard_dropped():
    # The JDK guard fires before the fan-out branch: `import java.util.*` drops.
    imp = RawImport(module="java.util", level=0, names=("*",), function_local=False)
    files = {"java/util/List.java", "java/util/Map.java"}
    assert resolver.resolve("src/main/java/app/Main.java", imp, files) == []


def test_resolve_suffix_match_anchors_at_a_path_boundary():
    # FQN b.C must match only at a path-segment boundary (`/b/C.java`), never as a
    # bare string suffix. `lib/C.java` must NOT satisfy `b.C` (the `b` in `lib`
    # is not a path segment); only `x/b/C.java` does. Guards the substring/token-
    # confusion failure mode of suffix matching.
    imp = RawImport(module="b.C", level=0, names=(), function_local=False)
    files = {"lib/C.java", "x/b/C.java"}
    assert resolver.resolve("app/Main.java", imp, files) == ["x/b/C.java"]


def test_resolve_static_member_import_maps_to_type_file():
    # extract drops the member, so resolve sees module="a.b.C" and maps it to the
    # in-repo type file.
    imp = RawImport(module="a.b.C", level=0, names=(), function_local=False)
    files = {"src/main/java/a/b/C.java"}
    assert resolver.resolve("src/main/java/app/Main.java", imp, files) == [
        "src/main/java/a/b/C.java"
    ]


def test_resolve_nested_type_import_maps_to_top_level_type_file():
    # `import a.b.Outer.Inner` -> the nested type Inner lives in the top-level
    # type Outer's file a/b/Outer.java. Discriminator: a decoy a/b/Outer/Inner.java
    # (the literal dotted path) is PRESENT; without truncation resolve would match
    # it, so the top-level file must be chosen and the decoy left unmatched.
    imp = RawImport(module="a.b.Outer.Inner", level=0, names=(), function_local=False)
    files = {
        "src/main/java/a/b/Outer.java",
        "src/main/java/a/b/Outer/Inner.java",  # decoy: the literal nested path
    }
    assert resolver.resolve("src/main/java/app/Main.java", imp, files) == [
        "src/main/java/a/b/Outer.java"
    ]


def test_resolve_static_nested_member_import_maps_to_top_level_type_file():
    # `import static a.b.Outer.Inner.CONST` -> extract leaves module=a.b.Outer.Inner
    # (member dropped); resolve truncates the remaining nested type to its
    # declaring top-level type file a/b/Outer.java.
    imp = RawImport(module="a.b.Outer.Inner", level=0, names=(), function_local=False)
    files = {"src/main/java/a/b/Outer.java"}
    assert resolver.resolve("src/main/java/app/Main.java", imp, files) == [
        "src/main/java/a/b/Outer.java"
    ]


def test_resolve_nested_jdk_type_is_still_dropped():
    # The JDK guard keys off the top-level package, so a nested JDK type
    # (java.util.Map.Entry) is dropped like any java.* import - even with a
    # shadow file present.
    imp = RawImport(module="java.util.Map.Entry", level=0, names=(), function_local=False)
    files = {"java/util/Map.java"}
    assert resolver.resolve("src/main/java/app/Main.java", imp, files) == []


def test_resolve_all_lowercase_fqn_falls_back_to_full_path():
    # No uppercase-initial segment (an unconventional all-lowercase class): the
    # top-level-type truncation finds no type boundary and falls back to the full
    # path, preserving the plain-type mapping a/b/c -> a/b/c.java.
    imp = RawImport(module="a.b.c", level=0, names=(), function_local=False)
    files = {"a/b/c.java"}
    assert resolver.resolve("app/Main.java", imp, files) == ["a/b/c.java"]


def test_resolve_is_deterministic_across_multiple_source_roots():
    # The same FQN exists under two source roots (main + test). Both resolve and
    # the result is sorted, so the order is byte-stable.
    imp = RawImport(module="a.b.C", level=0, names=(), function_local=False)
    files = {"src/test/java/a/b/C.java", "src/main/java/a/b/C.java"}
    assert resolver.resolve("src/main/java/app/Main.java", imp, files) == [
        "src/main/java/a/b/C.java",
        "src/test/java/a/b/C.java",
    ]


# ---------- orchestrator integration (real tree-sitter, scan_repo) ----------


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8", newline="")


@_needs_ts
def test_scan_emits_java_import_edges_end_to_end(tmp_path: Path):
    # A Java mini-repo in Maven layout: App imports a single type (Helper) and
    # fans out a wildcard package (model.*). scan_repo must emit `imports` edges
    # for both, through real tree-sitter, at high confidence (top-level imports).
    _write(
        tmp_path,
        "src/main/java/com/example/App.java",
        "package com.example;\n"
        "import com.example.util.Helper;\n"
        "import com.example.model.*;\n"
        "class App {}\n",
    )
    _write(
        tmp_path,
        "src/main/java/com/example/util/Helper.java",
        "package com.example.util;\nclass Helper {}\n",
    )
    _write(
        tmp_path,
        "src/main/java/com/example/model/User.java",
        "package com.example.model;\nclass User {}\n",
    )
    _write(
        tmp_path,
        "src/main/java/com/example/model/Order.java",
        "package com.example.model;\nclass Order {}\n",
    )

    repo_map = scan_repo(tmp_path, generator_version="t")
    import_edges = {(e.source, e.target): e for e in repo_map.edges if e.type == "imports"}
    app = "file:src/main/java/com/example/App.java"
    helper = "file:src/main/java/com/example/util/Helper.java"
    user = "file:src/main/java/com/example/model/User.java"
    order = "file:src/main/java/com/example/model/Order.java"

    # exactly three import edges, all from App: the single type + the wildcard
    # fan-out to BOTH model files (and nothing else).
    assert set(import_edges) == {(app, helper), (app, user), (app, order)}
    # top-level imports -> high confidence.
    assert all(e.confidence == "high" for e in import_edges.values())


@_needs_ts
def test_scan_drops_external_java_imports_end_to_end(tmp_path: Path):
    # A JDK import and a third-party import resolve to no in-repo file, so
    # scan_repo emits no import edges (external dropped).
    _write(
        tmp_path,
        "src/main/java/com/example/App.java",
        "package com.example;\n"
        "import java.util.List;\n"
        "import com.google.common.base.Joiner;\n"
        "class App {}\n",
    )
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert [e for e in repo_map.edges if e.type == "imports"] == []
