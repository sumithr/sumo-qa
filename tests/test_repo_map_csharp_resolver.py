# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Unit tests for the C# import resolver (#362).

``extract`` and ``declared_namespaces`` are tested against REAL tree-sitter
output over COMMITTED ``.cs`` fixtures (skipped without the ``[treesitter]``
extra); ``resolve`` is pure namespace-index lookup and runs on every
interpreter. The orchestrator integration drives ``infer_imports_edges`` over
the committed C# mini-project with the resolver's cross-file namespace index
populated.

C# rules ported from Understand-Anything: a ``using`` names a NAMESPACE, not a
file, so it resolves to every project file that DECLARES that namespace
(package-level fan-out). ``System.*`` and external assemblies (no declaring
project file) yield no edge. ``using static`` (type-statics) is dropped; an
alias ``using Alias = X`` records its RIGHT-HAND-SIDE namespace ``X`` (the alias
name is ignored) and fans out just like a plain ``using X;``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import sumo_qa.repo_map_imports as imports_mod
from sumo_qa.repo_map_imports import infer_imports_edges
from sumo_qa.repo_map_models import RepoMapNode
from sumo_qa.repo_map_resolvers import get_resolver, registered_languages
from sumo_qa.repo_map_resolvers.base import RawImport
from sumo_qa.repo_map_resolvers.csharp import CSharpResolver
from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE

_FIXTURES = Path(__file__).parent / "fixtures" / "repo_map" / "csharp"

resolver = CSharpResolver()

_needs_ts = pytest.mark.skipif(
    not TREESITTER_AVAILABLE,
    reason="tree-sitter not installed (the [treesitter] extra is absent)",
)


# ---------- registry ----------


def test_csharp_resolver_is_registered():
    assert "csharp" in registered_languages()
    assert get_resolver("csharp") is not None


def test_csharp_config_owns_cs_extension():
    assert resolver.config.id == "csharp"
    assert resolver.config.extensions == (".cs",)


# ---------- extract (real tree-sitter, committed fixtures) ----------


@_needs_ts
def test_extract_using_directives_are_namespaces_in_source_order():
    src = (_FIXTURES / "Controllers" / "HomeController.cs").read_bytes()
    raws = resolver.extract(src)
    assert [r.module for r in raws] == [
        "System",
        "System.Collections.Generic",
        "MyApp.Models",
        "MyApp.Services",
        "Newtonsoft.Json",
    ]
    # Every C# using directive is a module-level (non-lazy) namespace import with
    # no per-specifier names (the whole namespace is brought in).
    assert all(r.level == 0 and not r.function_local and r.names == () for r in raws)


@_needs_ts
def test_extract_records_alias_rhs_skips_static_keeps_plain_and_global():
    # `global using MyApp.Shared` and plain `using MyApp.Models` are namespace
    # imports; `using static System.Math` (type statics) is dropped; the alias
    # `using Alias = MyApp.Models.Order` records its RIGHT-HAND-SIDE
    # `MyApp.Models.Order` (a type alias here: it misses the namespace index and
    # resolves to nothing, but extract still records the RHS in source order).
    src = (_FIXTURES / "Edge" / "Directives.cs").read_bytes()
    assert [r.module for r in resolver.extract(src)] == [
        "MyApp.Shared",
        "MyApp.Models.Order",
        "MyApp.Models",
    ]


# ---------- declared_namespaces (real tree-sitter, committed fixtures) ----------


@_needs_ts
def test_declared_namespaces_block_form():
    src = (_FIXTURES / "Services" / "OrderService.cs").read_bytes()
    assert resolver.declared_namespaces(src) == {"MyApp.Services"}


@_needs_ts
def test_declared_namespaces_file_scoped_form():
    src = (_FIXTURES / "Models" / "Customer.cs").read_bytes()
    assert resolver.declared_namespaces(src) == {"MyApp.Models"}


@_needs_ts
def test_declared_namespaces_nested_yields_full_dotted_names():
    # Nested namespaces declare the parent AND the dotted child.
    src = (_FIXTURES / "Edge" / "Directives.cs").read_bytes()
    assert resolver.declared_namespaces(src) == {"MyApp.Edge", "MyApp.Edge.Inner"}


# ---------- cross-file namespace index (real tree-sitter, committed fixtures) ----------


@_needs_ts
def test_index_maps_namespace_to_all_declaring_files_fan_out():
    # Two files declare `MyApp.Models` (one block-scoped, one file-scoped); the
    # index fans that namespace out to BOTH declaring files.
    sources = {
        rel: (_FIXTURES / rel).read_bytes()
        for rel in ("Models/Order.cs", "Models/Customer.cs", "Services/OrderService.cs")
    }
    index = CSharpResolver().index_namespaces(sources)
    assert index["MyApp.Models"] == {"Models/Order.cs", "Models/Customer.cs"}
    assert index["MyApp.Services"] == {"Services/OrderService.cs"}


# ---------- resolve (pure namespace-index lookup, runs everywhere) ----------


def _resolver_with_index(index: dict[str, set[str]]) -> CSharpResolver:
    r = CSharpResolver()
    r._namespace_index = {ns: set(paths) for ns, paths in index.items()}
    return r


@_needs_ts
def test_alias_directive_records_rhs_namespace_and_fans_out():
    # A NAMESPACE alias `using Models = MyApp.Models;`: the alias NAME is ignored
    # and the RHS namespace `MyApp.Models` is recorded, so it fans out to the
    # files declaring `MyApp.Models` exactly as a plain `using MyApp.Models;`
    # would (#362 review fix — the alias was previously dropped entirely).
    raws = resolver.extract(b"using Models = MyApp.Models;\n")
    assert [r.module for r in raws] == ["MyApp.Models"]

    r = _resolver_with_index({"MyApp.Models": {"Models/Order.cs", "Models/Customer.cs"}})
    files = {"Models/Order.cs", "Models/Customer.cs", "Controllers/HomeController.cs"}
    assert r.resolve("Controllers/HomeController.cs", raws[0], files) == [
        "Models/Customer.cs",
        "Models/Order.cs",
    ]


def test_resolve_using_fans_out_to_namespace_declaring_files_sorted():
    r = _resolver_with_index({"MyApp.Models": {"Models/Order.cs", "Models/Customer.cs"}})
    imp = RawImport(module="MyApp.Models", level=0, names=(), function_local=False)
    files = {"Models/Order.cs", "Models/Customer.cs", "Controllers/HomeController.cs"}
    assert r.resolve("Controllers/HomeController.cs", imp, files) == [
        "Models/Customer.cs",
        "Models/Order.cs",
    ]


def test_resolve_external_namespace_not_in_index_yields_nothing():
    r = _resolver_with_index({"MyApp.Models": {"Models/Order.cs"}})
    imp = RawImport(module="Newtonsoft.Json", level=0, names=(), function_local=False)
    files = {"Models/Order.cs", "Controllers/HomeController.cs"}
    assert r.resolve("Controllers/HomeController.cs", imp, files) == []


def test_resolve_system_dotted_namespace_is_dropped_even_if_declared():
    # `System.*` is the BCL/framework root and is dropped EXPLICITLY, not merely
    # via an index miss: even a (perverse) project file declaring `System.Text`
    # yields no edge. Without the explicit drop the index hit would resolve.
    r = _resolver_with_index({"System.Text": {"Weird/System.cs"}})
    imp = RawImport(module="System.Text", level=0, names=(), function_local=False)
    files = {"Weird/System.cs", "App.cs"}
    assert r.resolve("App.cs", imp, files) == []


def test_resolve_bare_system_namespace_is_dropped():
    r = _resolver_with_index({"System": {"Weird/System.cs"}})
    imp = RawImport(module="System", level=0, names=(), function_local=False)
    assert r.resolve("App.cs", imp, {"Weird/System.cs"}) == []


def test_resolve_system_prefix_substring_is_not_dropped():
    # Substring-confusion guard (equivalence partitioning): `SystemX.Utils` is a
    # DIFFERENT namespace that merely starts with the letters "System"; the BCL
    # drop keys on `System` exactly or the `System.` dotted prefix, never a bare
    # substring, so this must still resolve.
    r = _resolver_with_index({"SystemX.Utils": {"Lib/SystemX.cs"}})
    imp = RawImport(module="SystemX.Utils", level=0, names=(), function_local=False)
    files = {"Lib/SystemX.cs", "App.cs"}
    assert r.resolve("App.cs", imp, files) == ["Lib/SystemX.cs"]


def test_resolve_excludes_files_not_in_file_set():
    # A namespace declarer that is not among the scanned nodes (absent from
    # file_set) is excluded: resolve only returns paths that exist in the map.
    r = _resolver_with_index({"MyApp.Models": {"Models/Order.cs", "Stale/Ghost.cs"}})
    imp = RawImport(module="MyApp.Models", level=0, names=(), function_local=False)
    files = {"Models/Order.cs", "App.cs"}  # Ghost.cs absent
    assert r.resolve("App.cs", imp, files) == ["Models/Order.cs"]


def test_resolve_excludes_the_importer_itself():
    # A file that declares a namespace AND imports it gets no self-edge: the
    # importer is excluded from its own fan-out.
    r = _resolver_with_index({"MyApp.Models": {"Models/Order.cs", "Models/Customer.cs"}})
    imp = RawImport(module="MyApp.Models", level=0, names=(), function_local=False)
    files = {"Models/Order.cs", "Models/Customer.cs"}
    assert r.resolve("Models/Order.cs", imp, files) == ["Models/Customer.cs"]


def test_resolve_with_empty_index_yields_nothing():
    # The default (unpopulated) resolver — today's scan-time state — resolves
    # nothing: the cross-file namespace index must be built and loaded first.
    imp = RawImport(module="MyApp.Models", level=0, names=(), function_local=False)
    assert CSharpResolver().resolve("App.cs", imp, {"Models/Order.cs"}) == []


# ---------- orchestrator integration (real tree-sitter, committed fixtures) ----------


@_needs_ts
def test_infer_imports_edges_emits_csharp_namespace_fan_out(monkeypatch):
    # Build source nodes for the committed C# mini-project, populate the
    # resolver's cross-file namespace index, and run the orchestrator end-to-end:
    # the controller's `using MyApp.Models` fans out to BOTH declaring files,
    # `using MyApp.Services` resolves to the one, and System.*/Newtonsoft yield
    # no edge.
    rels = [
        "Models/Order.cs",
        "Models/Customer.cs",
        "Services/OrderService.cs",
        "Controllers/HomeController.cs",
    ]
    nodes = [
        RepoMapNode(id=f"file:{rel}", type="source_file", path=rel, language="csharp")
        for rel in rels
    ]
    populated = CSharpResolver()
    populated.index_namespaces({rel: (_FIXTURES / rel).read_bytes() for rel in rels})
    monkeypatch.setattr(
        imports_mod,
        "get_resolver",
        lambda lang: populated if lang == "csharp" else None,
    )

    edges = infer_imports_edges(nodes, _FIXTURES)
    pairs = {(e.source, e.target) for e in edges}
    controller = "file:Controllers/HomeController.cs"
    assert (controller, "file:Models/Order.cs") in pairs
    assert (controller, "file:Models/Customer.cs") in pairs  # fan-out: second declarer
    assert (controller, "file:Services/OrderService.cs") in pairs
    # external assembly / BCL namespaces produce no edge
    assert all("Newtonsoft" not in e.target for e in edges)
    assert {e.reason for e in edges} == {"imports MyApp.Models", "imports MyApp.Services"}
    # module-level usings -> high confidence; no dangling edges
    assert all(e.confidence == "high" for e in edges)
    node_ids = {n.id for n in nodes}
    assert all(e.source in node_ids and e.target in node_ids for e in edges)
    # exactly the three resolved fan-out edges, nothing fabricated
    assert len(edges) == 3
