# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""End-to-end ``scan_repo`` tests for C# project-scoped namespace resolution (#542).

The C# resolver's namespace fan-out needs a cross-file, per-scan pre-pass: a
``using`` names a NAMESPACE, and a namespace is declared by any number of
``.cs`` files, so the declaring-file set can only be known by reading OTHER
files. #542 wires that pre-pass through the #525 scan-local preparation hook:
``CSharpResolver.prepare`` builds a ``namespace -> declaring files`` index
scoped to each ``.csproj`` PROJECT boundary as scan-local state on a fresh
resolver instance, and ``resolve`` fans a ``using`` out within the importer's
own project (and, since #548, into projects it explicitly references via
``<ProjectReference>``). Nothing repository-derived ever reaches the registered
module-level singleton.

Every test drives the REAL pipeline (files on disk -> ``scan_repo`` -> nodes ->
prepared resolver dispatch -> ``imports`` edges) with tree-sitter present
(skipped without it). Assertions use EXACT edge sets so a resolver that
over-matches (a repository-global fan-out ignoring project boundaries) cannot
pass, and an UNREFERENCED cross-project ``using`` is the true negative: a
namespace declared in project A must NOT resolve a ``using`` in an unrelated
project B.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sumo_qa.repo_map_models import RepoMap
from sumo_qa.repo_map_resolvers import get_resolver
from sumo_qa.repo_map_resolvers.base import RawImport, ScanContext
from sumo_qa.repo_map_scanner import scan_repo
from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE

_needs_ts = pytest.mark.skipif(
    not TREESITTER_AVAILABLE,
    reason="tree-sitter not installed (the [treesitter] extra is absent)",
)

_FIXTURES = Path(__file__).parent / "fixtures" / "repo_map"
_PROJECTS = _FIXTURES / "csharp_projects"
_PROJECT_REFS = _FIXTURES / "csharp_project_refs"

# The committed two-project fixture's expected in-project fan-out edges.
_HOME = "file:ProjectA/Controllers/HomeController.cs"
_ORDER = "file:ProjectA/Models/Order.cs"
_GLOBAL = "file:ProjectA/GlobalUsings.cs"
_ORDER_SERVICE = "file:ProjectA/Services/OrderService.cs"
_CONSUMER = "file:ProjectB/Consumer.cs"
_WIDGET = "file:ProjectB/Widgets/Widget.cs"


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8", newline="")


def _import_pairs(repo_map: RepoMap) -> set[tuple[str, str]]:
    return {(e.source, e.target) for e in repo_map.edges if e.type == "imports"}


# ---------- headline: exact in-project edges + cross-project true negatives ----------


@_needs_ts
def test_scan_csharp_project_scoped_fan_out_exact_edges():
    # ProjectA: a plain `using ProjectA.Models` (HomeController -> Order) and a
    # `global using ProjectA.Services` (GlobalUsings -> OrderService) each fan
    # out to the in-project declarer. ProjectB: a plain `using ProjectB.Widgets`
    # (Consumer -> Widget) resolves in-project. The EXACT set is the whole
    # assertion: it pins both true negatives (HomeController's cross-project
    # `using ProjectB.Widgets`, Consumer's cross-project `using ProjectA.Models`)
    # as ABSENT, and `using System` as dropped. A repository-global fan-out that
    # ignored `.csproj` boundaries would add the two cross-project edges and fail.
    repo_map = scan_repo(_PROJECTS, generator_version="t")
    pairs = _import_pairs(repo_map)
    assert pairs == {
        (_HOME, _ORDER),
        (_GLOBAL, _ORDER_SERVICE),
        (_CONSUMER, _WIDGET),
    }
    # Spelled-out true negatives (a namespace in project A must not resolve a
    # `using` in project B, and vice versa).
    assert (_CONSUMER, _ORDER) not in pairs
    assert (_HOME, _WIDGET) not in pairs
    # All edges are module-level usings -> high confidence, no dangling edges.
    imports = [e for e in repo_map.edges if e.type == "imports"]
    assert all(e.confidence == "high" for e in imports)
    node_ids = {n.id for n in repo_map.nodes}
    assert all(e.source in node_ids and e.target in node_ids for e in imports)
    assert {e.reason for e in imports} == {
        "imports ProjectA.Models",
        "imports ProjectA.Services",
        "imports ProjectB.Widgets",
    }


# ---------- the registered singleton is never mutated with repo data ----------


@_needs_ts
def test_scan_preparation_never_mutates_the_registered_csharp_singleton():
    # A context-rich scan resolves in-project fan-out through a PREPARED,
    # scan-local instance; the registered module-level singleton must stay
    # path-only (empty flat index, no scan-local `_index`) so no scan's
    # namespaces leak into the next.
    repo_map = scan_repo(_PROJECTS, generator_version="t")
    assert (_HOME, _ORDER) in _import_pairs(repo_map)
    singleton = get_resolver("csharp")
    assert singleton is not None
    imp = RawImport(module="ProjectA.Models", level=0, names=(), function_local=False)
    files = {"ProjectA/Controllers/HomeController.cs", "ProjectA/Models/Order.cs"}
    # Even right after the scan, the singleton resolves nothing for an in-project
    # namespace — its state was never touched.
    assert singleton.resolve("ProjectA/Controllers/HomeController.cs", imp, files) == []
    assert singleton._index is None
    assert singleton._namespace_index == {}


# ---------- helpers for tmp-repo isolation / degradation tests ----------

_SDK_CSPROJ = '<Project Sdk="Microsoft.NET.Sdk"></Project>\n'
# App/Consumer.cs `using App.Models;` -> App/Models/Order.cs (the sole declarer
# of App.Models), when App/App.csproj establishes the project boundary.
_APP_PAIR = ("file:App/Consumer.cs", "file:App/Models/Order.cs")


def _proj_repo(root: Path, *, csproj: bool = True) -> None:
    """A one-project C# repo whose in-project `using` discriminates preparation."""
    if csproj:
        _write(root, "App/App.csproj", _SDK_CSPROJ)
    _write(root, "App/Models/Order.cs", "namespace App.Models;\n\npublic class Order { }\n")
    _write(
        root,
        "App/Consumer.cs",
        "using App.Models;\n\nnamespace App;\n\npublic class Consumer { Order o = new Order(); }\n",
    )


def _csproj_ref(*includes: str) -> str:
    """An SDK-style `.csproj` declaring one `<ProjectReference>` per Include.

    Includes are spelled with MSBuild backslashes so the tests exercise the
    resolver's backslash normalization.
    """
    refs = "".join(f'    <ProjectReference Include="{inc}" />\n' for inc in includes)
    return (
        '<Project Sdk="Microsoft.NET.Sdk">\n  <ItemGroup>\n' + refs + "  </ItemGroup>\n</Project>\n"
    )


# ---------- sequential / concurrent scans share nothing ----------


@_needs_ts
def test_sequential_scans_do_not_share_prepared_csharp_state(tmp_path: Path):
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    _proj_repo(repo_a)  # has .csproj -> in-project edge
    _proj_repo(repo_b, csproj=False)  # no .csproj -> path-only fallback, no edge
    map_a_first = scan_repo(repo_a, generator_version="t")
    map_b = scan_repo(repo_b, generator_version="t")
    map_a_second = scan_repo(repo_a, generator_version="t")
    assert _APP_PAIR in _import_pairs(map_a_first)
    # Repo A's project context must not leak into repo B's scan...
    assert _APP_PAIR not in _import_pairs(map_b)
    # ...and repo B's scan must leave no residue that changes repo A.
    assert _import_pairs(map_a_second) == _import_pairs(map_a_first)


@_needs_ts
def test_concurrent_scans_use_isolated_csharp_preparation(tmp_path: Path):
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    _proj_repo(repo_a)
    _proj_repo(repo_b, csproj=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(scan_repo, repo_a, generator_version="t")
        future_b = pool.submit(scan_repo, repo_b, generator_version="t")
        map_a = future_a.result()
        map_b = future_b.result()
    assert _APP_PAIR in _import_pairs(map_a)
    assert _APP_PAIR not in _import_pairs(map_b)


# ---------- project-boundary shapes: root-level .csproj, missing config ----------


@_needs_ts
def test_scan_root_level_csproj_owns_the_whole_repo(tmp_path: Path):
    # A `.csproj` at the repo root (no directory prefix) is a single project that
    # owns every `.cs` file beneath it, so the in-project `using` resolves.
    _write(tmp_path, "App.csproj", _SDK_CSPROJ)
    _write(tmp_path, "Models/Order.cs", "namespace App.Models;\n\npublic class Order { }\n")
    _write(
        tmp_path,
        "Consumer.cs",
        "using App.Models;\n\nnamespace App;\n\npublic class Consumer { Order o = new Order(); }\n",
    )
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert ("file:Consumer.cs", "file:Models/Order.cs") in _import_pairs(repo_map)


@_needs_ts
def test_missing_csproj_is_silent_path_only_fallback(tmp_path: Path):
    # `.cs` files with no owning `.csproj` fall back to path-only resolution: no
    # namespace fan-out and — since the config is merely absent, not broken — no
    # warning.
    _proj_repo(tmp_path, csproj=False)
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert _import_pairs(repo_map) == set()
    assert not [w for w in repo_map.warnings if w.kind == "other"]


# ---------- extension case-insensitivity matches the scanner's classification ----------


@_needs_ts
def test_scan_uppercase_extension_csharp_files_resolve_like_the_scanner(tmp_path: Path):
    # The scanner classifies extensions case-insensitively (`.suffix.lower()` in
    # `_file_to_node`/`_classify`), so `Order.CS` still stamps `csharp` and
    # `App.CSPROJ` a manifest. The resolver's preparation MUST match that
    # case-insensitivity: if `prepare`/`_project_roots` filtered `.cs`/`.csproj`
    # case-sensitively, an uppercase-extension file the scanner DID classify as
    # C# would be skipped by preparation -> its namespace never indexed and its
    # owning `.csproj` never bounding the project, so its in-project `using` edge
    # silently disappears on a case-sensitive filesystem (a false negative).
    #
    # The uppercase project carries BOTH an uppercase `.CSPROJ` boundary AND an
    # uppercase `.CS` declarer, so its edge resolves only when preparation matches
    # BOTH filters to the scanner. The lowercase project (the already-supported
    # spelling) is included in the SAME exact edge set to pin that the existing
    # lowercase behaviour is unchanged. Distinct namespace roots (`Up.*` vs
    # `Low.*`) keep the fan-out strictly in-project.
    _write(tmp_path, "Up/App.CSPROJ", _SDK_CSPROJ)
    _write(tmp_path, "Up/Order.CS", "namespace Up.Models;\n\npublic class Order { }\n")
    _write(
        tmp_path,
        "Up/Consumer.cs",
        "using Up.Models;\n\nnamespace Up;\n\npublic class Consumer { Order o = new Order(); }\n",
    )
    _write(tmp_path, "Low/App.csproj", _SDK_CSPROJ)
    _write(tmp_path, "Low/Order.cs", "namespace Low.Models;\n\npublic class Order { }\n")
    _write(
        tmp_path,
        "Low/Consumer.cs",
        "using Low.Models;\n\nnamespace Low;\n\npublic class Consumer { Order o = new Order(); }\n",
    )
    repo_map = scan_repo(tmp_path, generator_version="t")
    # EXACT edge set: the uppercase pair proves the fix; the lowercase pair proves
    # no regression. A resolver that skipped the uppercase file would drop the
    # first pair and fail this assertion.
    assert _import_pairs(repo_map) == {
        ("file:Up/Consumer.cs", "file:Up/Order.CS"),
        ("file:Low/Consumer.cs", "file:Low/Order.cs"),
    }
    # No spurious `other` warning: both `.csproj` manifests are readable UTF-8, so
    # neither the uppercase nor the lowercase project degrades to path-only.
    assert not [w for w in repo_map.warnings if w.kind == "other"]


# ---------- unusable .csproj / unreadable source degrade, never abort ----------


@_needs_ts
def test_malformed_csproj_degrades_with_one_deterministic_other_warning(tmp_path: Path):
    _proj_repo(tmp_path)
    (tmp_path / "App" / "App.csproj").write_bytes(b"\xff\xfe<Project>\n")  # non-UTF-8
    repo_map = scan_repo(tmp_path, generator_version="t")
    # The unusable manifest still bounds its project, but with an EMPTY namespace
    # index, so the in-project fan-out is withheld (path-only) and the scan
    # completes, flagging the broken manifest with one deterministic warning.
    assert _APP_PAIR not in _import_pairs(repo_map)
    others = [w for w in repo_map.warnings if w.kind == "other"]
    assert len(others) == 1
    assert others[0].path == "App/App.csproj"
    # Deterministic: a second scan of the same state emits the identical warning.
    again = scan_repo(tmp_path, generator_version="t")
    assert [(w.kind, w.message, w.path) for w in again.warnings if w.kind == "other"] == [
        (w.kind, w.message, w.path) for w in others
    ]


@_needs_ts
def test_unreadable_csproj_degrades_with_one_other_warning(tmp_path: Path, monkeypatch):
    _proj_repo(tmp_path)
    real_read = ScanContext.read

    def failing_read(self, rel_path: str):
        if rel_path == "App/App.csproj":
            return None  # simulate an unreadable config portably (no chmod on Windows)
        return real_read(self, rel_path)

    monkeypatch.setattr(ScanContext, "read", failing_read)
    repo_map = scan_repo(tmp_path, generator_version="t")
    # The unreadable manifest still bounds its project, but with an EMPTY namespace
    # index, so the in-project fan-out is withheld (path-only); only the warning
    # marks it broken.
    assert _APP_PAIR not in _import_pairs(repo_map)
    others = [w for w in repo_map.warnings if w.kind == "other"]
    assert len(others) == 1
    assert others[0].path == "App/App.csproj"


@_needs_ts
def test_broken_nested_csproj_bounds_its_project_no_ancestor_leak(tmp_path: Path):
    # A NESTED directory's broken `.csproj` still establishes its OWN project
    # boundary from its LOCATION (not its contents), so a `.cs` file inside it
    # cannot resolve a `using` naming an ANCESTOR project's namespace: the
    # boundary is what withholds the cross-project edge, not the file's contents.
    # Root project (App.csproj at the repo root) owns Root.cs, which declares the
    # root namespace `RootApp`. The nested project's Leaf.cs does `using RootApp`.
    # If the broken nested `.csproj` failed to establish a boundary, Leaf.cs would
    # fall through to the ANCESTOR root project and leak an edge to Root.cs; with
    # the boundary established from location, Leaf.cs is owned by the nested
    # project — whose namespace index is EMPTY (a broken manifest is not indexed),
    # so the `using` resolves to nothing (path-only, no leak).
    _write(tmp_path, "App.csproj", _SDK_CSPROJ)
    _write(tmp_path, "Root.cs", "namespace RootApp;\n\npublic class Root { }\n")
    _write(
        tmp_path,
        "Nested/Leaf.cs",
        "using RootApp;\n\nnamespace Nested;\n\npublic class Leaf { }\n",
    )
    (tmp_path / "Nested" / "Nested.csproj").write_bytes(b"\xff\xfe<Project>\n")  # unreadable
    repo_map = scan_repo(tmp_path, generator_version="t")
    pairs = _import_pairs(repo_map)
    # EXACT edge set: an ancestor-leak edge (Nested/Leaf.cs -> Root.cs) would make
    # this non-empty and fail the assertion.
    assert pairs == set()
    assert ("file:Nested/Leaf.cs", "file:Root.cs") not in pairs
    # The broken nested manifest still emits exactly one deterministic `other`
    # warning at its own path — the boundary is established, but the scan flags
    # that its contents could not be validated.
    others = [w for w in repo_map.warnings if w.kind == "other"]
    assert len(others) == 1
    assert others[0].path == "Nested/Nested.csproj"


@_needs_ts
def test_unreadable_csharp_source_is_skipped_without_warning(tmp_path: Path, monkeypatch):
    # An unreadable `.cs` source contributes no namespaces to the index, so a
    # `using` that would have resolved to it withholds its edge. Unlike a bad
    # `.csproj`, a source read failure degrades SILENTLY (no `other` warning).
    _proj_repo(tmp_path)  # App/Models/Order.cs is the sole declarer of App.Models
    real_read = ScanContext.read

    def failing_read(self, rel_path: str):
        if rel_path == "App/Models/Order.cs":
            return None
        return real_read(self, rel_path)

    monkeypatch.setattr(ScanContext, "read", failing_read)
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert _APP_PAIR not in _import_pairs(repo_map)
    assert not [w for w in repo_map.warnings if w.kind == "other"]


# ---------- global:: qualifier resolves like the unqualified form (#548) ----------


@_needs_ts
def test_scan_global_qualified_using_resolves_like_unqualified(tmp_path: Path):
    # `using global::App.Models;` names the same namespace as `using App.Models;`.
    # After the `global::` alias qualifier is stripped it fans out to the
    # in-project declarer exactly as the unqualified form does. Before the strip
    # the `global::App.Models` module misses the index and no edge is emitted.
    _write(tmp_path, "App/App.csproj", _SDK_CSPROJ)
    _write(tmp_path, "App/Models/Order.cs", "namespace App.Models;\n\npublic class Order { }\n")
    _write(
        tmp_path,
        "App/Consumer.cs",
        "using global::App.Models;\n\nnamespace App;\n\n"
        "public class Consumer { Order o = new Order(); }\n",
    )
    repo_map = scan_repo(tmp_path, generator_version="t")
    assert _import_pairs(repo_map) == {_APP_PAIR}


# ---------- <ProjectReference> cross-project edges (#548) ----------


@_needs_ts
def test_scan_project_reference_resolves_cross_project_edge():
    # ProjectC's ProjectC.csproj declares
    # `<ProjectReference Include="..\ProjectD\ProjectD.csproj"/>`, so a
    # `using ProjectD.Models` in ProjectC RESOLVES to ProjectD's declarer even
    # though it names another project's namespace. The EXACT edge set pins three
    # things at once:
    #   * the referenced edge resolves (ProjectC/Consumer.cs -> ProjectD/.../Thing.cs);
    #   * an UNREFERENCED cross-project `using` stays the true negative
    #     (ProjectC references ProjectD but NOT ProjectF, so
    #     `using ProjectF.Widgets` emits no edge);
    #   * the reference is DIRECTIONAL (ProjectD does not reference ProjectC, so
    #     ProjectD/Back.cs's `using ProjectC.App` emits no edge).
    repo_map = scan_repo(_PROJECT_REFS, generator_version="t")
    pairs = _import_pairs(repo_map)
    assert pairs == {("file:ProjectC/Consumer.cs", "file:ProjectD/Models/Thing.cs")}
    # Spelled-out true negatives.
    assert ("file:ProjectC/Consumer.cs", "file:ProjectF/Widgets/Gadget.cs") not in pairs
    assert ("file:ProjectD/Back.cs", "file:ProjectC/Consumer.cs") not in pairs
    # Every csproj is readable UTF-8, so no degradation warning.
    assert not [w for w in repo_map.warnings if w.kind == "other"]
    imports = [e for e in repo_map.edges if e.type == "imports"]
    assert all(e.confidence == "high" for e in imports)


@_needs_ts
def test_scan_project_reference_is_direct_only_not_transitive(tmp_path: Path):
    # ProjectReference resolution is DIRECT-ONLY. ProjectC references ProjectD and
    # ProjectD references ProjectG, but ProjectC does NOT reference ProjectG, so a
    # `using ProjectG.Deep` in ProjectC does not resolve; the DIRECT
    # `using ProjectD.Stuff` does. The exact edge set pins the direct-only choice
    # (a transitive implementation would additionally emit the ProjectG edge).
    _write(tmp_path, "ProjectC/ProjectC.csproj", _csproj_ref("..\\ProjectD\\ProjectD.csproj"))
    _write(
        tmp_path,
        "ProjectC/Use.cs",
        "using ProjectD.Stuff;\nusing ProjectG.Deep;\n\nnamespace ProjectC;\n\n"
        "public class Use { }\n",
    )
    _write(tmp_path, "ProjectD/ProjectD.csproj", _csproj_ref("..\\ProjectG\\ProjectG.csproj"))
    _write(tmp_path, "ProjectD/Mid.cs", "namespace ProjectD.Stuff;\n\npublic class Mid { }\n")
    _write(tmp_path, "ProjectG/ProjectG.csproj", _SDK_CSPROJ)
    _write(tmp_path, "ProjectG/Deep.cs", "namespace ProjectG.Deep;\n\npublic class Deep { }\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    pairs = _import_pairs(repo_map)
    assert pairs == {("file:ProjectC/Use.cs", "file:ProjectD/Mid.cs")}
    assert ("file:ProjectC/Use.cs", "file:ProjectG/Deep.cs") not in pairs


@_needs_ts
def test_scan_project_reference_to_nonexistent_csproj_adds_no_edge(tmp_path: Path):
    # A `<ProjectReference>` naming a `.csproj` that does NOT exist must not
    # over-match a DIFFERENT project that merely shares the referenced directory.
    # ProjectA references `..\ProjectB\Missing.csproj` (which is absent), but
    # ProjectB/ProjectB.csproj (a different project) DOES exist in that directory
    # and declares namespace `Shared`. Reducing the dangling reference to its bare
    # directory `ProjectB/` would wrongly fan `using Shared` out to ProjectB's
    # declarer; the reference must resolve to the referenced project ONLY when that
    # exact `.csproj` is a known project, so this yields NO cross-project edge.
    _write(tmp_path, "ProjectA/ProjectA.csproj", _csproj_ref("..\\ProjectB\\Missing.csproj"))
    _write(
        tmp_path,
        "ProjectA/Use.cs",
        "using Shared;\n\nnamespace ProjectA;\n\npublic class Use { }\n",
    )
    _write(tmp_path, "ProjectB/ProjectB.csproj", _SDK_CSPROJ)
    _write(tmp_path, "ProjectB/Thing.cs", "namespace Shared;\n\npublic class Thing { }\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    pairs = _import_pairs(repo_map)
    # EXACT edge set: a phantom edge (ProjectA/Use.cs -> ProjectB/Thing.cs) from the
    # dangling reference would make this non-empty and fail the assertion.
    assert pairs == set()
    assert ("file:ProjectA/Use.cs", "file:ProjectB/Thing.cs") not in pairs
    # The referenced `.csproj` does not exist, but the directory's real manifest is
    # readable UTF-8, so nothing degrades: no `other` warning.
    assert not [w for w in repo_map.warnings if w.kind == "other"]


@_needs_ts
def test_scan_unknown_encoding_csproj_does_not_abort_scan(tmp_path: Path):
    # A `.csproj` whose XML prolog declares an encoding expat cannot load
    # (`encoding="x-unknown"`) makes `ET.fromstring` raise a NON-`ParseError`
    # (`LookupError`). A guard that only caught `ParseError` would let it escape and
    # abort the whole scan. Any parse failure must instead yield no references and
    # never crash: the manifest still decodes as UTF-8, so its boundary holds and
    # its own `.cs` namespaces index, resolving the in-project `using`.
    _write(
        tmp_path,
        "App/App.csproj",
        '<?xml version="1.0" encoding="x-unknown"?>\n<Project Sdk="Microsoft.NET.Sdk"></Project>\n',
    )
    _write(tmp_path, "App/Models/Order.cs", "namespace App.Models;\n\npublic class Order { }\n")
    _write(
        tmp_path,
        "App/Consumer.cs",
        "using App.Models;\n\nnamespace App;\n\npublic class Consumer { Order o = new Order(); }\n",
    )
    repo_map = scan_repo(tmp_path, generator_version="t")
    # The scan completed (no abort) and the manifest's own namespaces still indexed.
    assert _APP_PAIR in _import_pairs(repo_map)
    # It decodes as UTF-8, so it is not "unusable": no `other` warning.
    assert not [w for w in repo_map.warnings if w.kind == "other"]


@_needs_ts
def test_malformed_xml_csproj_indexes_own_namespaces_but_adds_no_reference(tmp_path: Path):
    # A UTF-8 `.csproj` whose XML is INVALID is still usable: its boundary holds
    # and its own `.cs` namespaces index (so an in-project `using` resolves), but
    # its `<ProjectReference>` cannot be parsed, so no cross-project edge is added
    # for it. Because the bytes decode as UTF-8, there is NO `other` warning
    # (unlike an unreadable / non-UTF-8 manifest).
    _write(
        tmp_path,
        "ProjectH/ProjectH.csproj",
        '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup>'
        '<ProjectReference Include="..\\ProjectI\\ProjectI.csproj" >'  # unclosed -> invalid XML
        "</Project>\n",
    )
    _write(tmp_path, "ProjectH/Own.cs", "namespace ProjectH.Own;\n\npublic class Own { }\n")
    _write(
        tmp_path,
        "ProjectH/Use.cs",
        "using ProjectH.Own;\nusing ProjectI.Thing;\n\nnamespace ProjectH;\n\n"
        "public class Use { }\n",
    )
    _write(tmp_path, "ProjectI/ProjectI.csproj", _SDK_CSPROJ)
    _write(tmp_path, "ProjectI/Thing.cs", "namespace ProjectI.Thing;\n\npublic class Thing { }\n")
    repo_map = scan_repo(tmp_path, generator_version="t")
    pairs = _import_pairs(repo_map)
    # Own-namespace fan-out still works (the manifest is usable UTF-8, just bad XML).
    assert ("file:ProjectH/Use.cs", "file:ProjectH/Own.cs") in pairs
    # The unparseable <ProjectReference> yields no cross-project edge.
    assert ("file:ProjectH/Use.cs", "file:ProjectI/Thing.cs") not in pairs
    # Invalid XML is not "unusable": no `other` warning.
    assert not [w for w in repo_map.warnings if w.kind == "other"]


# ---------- BOM-less UTF-16 .csproj bypass is closed (security, #548) ----------


@_needs_ts
def test_scan_bomless_utf16_csproj_is_unusable_no_phantom_edge(tmp_path: Path):
    # A BOM-less UTF-16LE `.csproj` is NUL-laced ASCII XML: every NUL byte is
    # valid UTF-8 (`U+0000`), so `raw.decode("utf-8")` passes it, and the
    # byte-level `b"<!DOCTYPE"` guard misses the interleaved-NUL DTD
    # (`<\x00!\x00D\x00...`). expat would then auto-detect UTF-16 from the `<?xml`
    # prolog, PROCESS the DTD (entity-expansion / billion-laughs DoS), and expand
    # `&d;` into a `<ProjectReference>` naming ProjectD — emitting a phantom
    # cross-project edge. A `.csproj` with NUL bytes is not real UTF-8 XML text,
    # so it is treated as unusable/non-UTF-8: its project keeps an EMPTY namespace
    # index (path-only) and contributes NO references, exactly like an unreadable
    # / non-UTF-8 manifest, with one deterministic `other` warning. So NEITHER the
    # entity-expanded cross-project edge (Consumer -> ProjectD/Thing) NOR
    # ProjectC's own in-project fan-out (Consumer -> Own) forms — both appear
    # before the fix (the phantom edge proves the DTD was processed).
    _write(tmp_path, "ProjectC/Own.cs", "namespace ProjectC.Own;\n\npublic class Own { }\n")
    _write(
        tmp_path,
        "ProjectC/Consumer.cs",
        "using ProjectD.Models;\nusing ProjectC.Own;\n\nnamespace ProjectC;\n\n"
        "public class Consumer { }\n",
    )
    _write(tmp_path, "ProjectD/ProjectD.csproj", _SDK_CSPROJ)
    _write(
        tmp_path,
        "ProjectD/Models/Thing.cs",
        "namespace ProjectD.Models;\n\npublic class Thing { }\n",
    )
    utf16 = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE Project [ <!ENTITY d "..\\ProjectD\\ProjectD.csproj"> ]>\n'
        '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup>'
        '<ProjectReference Include="&d;" />'
        "</ItemGroup></Project>\n"
    ).encode("utf-16-le")  # BOM-less UTF-16LE: decodes as UTF-8, NUL-laced
    (tmp_path / "ProjectC" / "ProjectC.csproj").write_bytes(utf16)
    repo_map = scan_repo(tmp_path, generator_version="t")
    pairs = _import_pairs(repo_map)
    # EXACT edge set: the UTF-16 manifest is unusable, so both the phantom
    # cross-project edge and ProjectC's in-project fan-out are withheld.
    assert pairs == set()
    assert ("file:ProjectC/Consumer.cs", "file:ProjectD/Models/Thing.cs") not in pairs
    assert ("file:ProjectC/Consumer.cs", "file:ProjectC/Own.cs") not in pairs
    # One deterministic `other` warning at the UTF-16 manifest's own path.
    others = [w for w in repo_map.warnings if w.kind == "other"]
    assert len(others) == 1
    assert others[0].path == "ProjectC/ProjectC.csproj"
    again = scan_repo(tmp_path, generator_version="t")
    assert [(w.kind, w.message, w.path) for w in again.warnings if w.kind == "other"] == [
        (w.kind, w.message, w.path) for w in others
    ]
