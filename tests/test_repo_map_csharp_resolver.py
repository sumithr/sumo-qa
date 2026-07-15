# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Unit tests for the C# import resolver (#362).

``extract`` and ``declared_namespaces`` are tested against REAL tree-sitter
output over COMMITTED ``.cs`` fixtures (skipped without the ``[treesitter]``
extra); ``resolve`` is pure namespace-index lookup and runs on every
interpreter. End-to-end orchestrator / ``scan_repo`` integration — the
per-project preparation pass and its cross-project true negatives — lives in
``tests/test_repo_map_csharp_scan.py`` (#542); this suite covers the resolver's
units and the flat, repository-wide index used by direct callers.

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


# ---------- global:: alias-qualifier normalization (#548, real tree-sitter) ----------


@_needs_ts
def test_extract_strips_leading_global_qualifier_dotted():
    # `using global::MyApp.Models;` names the SAME namespace as
    # `using MyApp.Models;`; the `global::` alias qualifier only forces
    # root-namespace lookup and must be stripped so the extracted module matches
    # an indexed `namespace MyApp.Models`. Without the strip it keeps the
    # `global::` prefix and misses the index.
    raws = resolver.extract(b"using global::MyApp.Models;\n")
    assert [r.module for r in raws] == ["MyApp.Models"]
    # And once stripped it fans out exactly like the unqualified form.
    r = _resolver_with_index({"MyApp.Models": {"Models/Order.cs", "Models/Customer.cs"}})
    files = {"Models/Order.cs", "Models/Customer.cs", "App.cs"}
    assert r.resolve("App.cs", raws[0], files) == ["Models/Customer.cs", "Models/Order.cs"]


@_needs_ts
def test_extract_strips_leading_global_qualifier_single_segment():
    # A single-segment `using global::App;` parses as an alias-qualified name (not
    # a plain qualified_name); stripping the `global::` qualifier still yields the
    # bare `App` namespace rather than dropping the directive entirely.
    assert [r.module for r in resolver.extract(b"using global::App;\n")] == ["App"]


# ---------- .csproj <ProjectReference> parsing (#548) ----------


def test_parse_project_references_resolves_backslash_include_to_root_dir():
    from sumo_qa.repo_map_resolvers.csharp import _parse_project_references

    # MSBuild spells Include with backslashes and points at the referenced
    # `.csproj`; the reference is the referenced project's ROOT directory.
    raw = (
        b'<Project Sdk="Microsoft.NET.Sdk">'
        b"<ItemGroup>"
        b'<ProjectReference Include="..\\ProjectD\\ProjectD.csproj" />'
        b"</ItemGroup></Project>"
    )
    assert _parse_project_references(raw, "ProjectC") == {"ProjectD"}


def test_parse_project_references_matches_local_name_ignoring_xml_namespace():
    from sumo_qa.repo_map_resolvers.csharp import _parse_project_references

    # An old-style (non-SDK) csproj carries the MSBuild XML namespace on every
    # tag; matching by LOCAL name still finds the ProjectReference.
    raw = (
        b'<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">'
        b'<ItemGroup><ProjectReference Include="..\\Other\\Other.csproj" />'
        b"</ItemGroup></Project>"
    )
    assert _parse_project_references(raw, "Solution/Web") == {"Solution/Other"}


def test_parse_project_references_skips_reference_without_include():
    from sumo_qa.repo_map_resolvers.csharp import _parse_project_references

    raw = b'<Project><ItemGroup><ProjectReference Update="x" /></ItemGroup></Project>'
    assert _parse_project_references(raw, "ProjectC") == set()


def test_parse_project_references_root_level_include_has_empty_root_dir():
    from sumo_qa.repo_map_resolvers.csharp import _parse_project_references

    # A repo-root referencing csproj (dir "") pointing at another root-level
    # csproj resolves to the repo root itself ("").
    raw = b'<Project><ItemGroup><ProjectReference Include="Other.csproj" /></ItemGroup></Project>'
    assert _parse_project_references(raw, "") == {""}


def test_parse_project_references_malformed_xml_yields_no_references():
    from sumo_qa.repo_map_resolvers.csharp import _parse_project_references

    # Unparseable XML must not crash: it simply contributes no references.
    raw = b'<Project><ItemGroup><ProjectReference Include="..\\D\\D.csproj" >'  # unclosed
    assert _parse_project_references(raw, "C") == set()


def test_parse_project_references_unknown_encoding_yields_no_references():
    from sumo_qa.repo_map_resolvers.csharp import _parse_project_references

    # A `.csproj` whose XML prolog names an encoding expat cannot load makes
    # `ET.fromstring` raise a NON-`ParseError` (`LookupError`). A parser that only
    # guarded `ParseError` would let it escape and abort the scan; ANY parse
    # failure over untrusted `.csproj` content must instead yield no references.
    raw = (
        b'<?xml version="1.0" encoding="x-unknown"?>'
        b'<Project><ItemGroup><ProjectReference Include="..\\D\\D.csproj" />'
        b"</ItemGroup></Project>"
    )
    assert _parse_project_references(raw, "C") == set()


def test_parse_project_references_verifies_target_against_known_projects():
    from sumo_qa.repo_map_resolvers.csharp import _parse_project_references

    # When the scan's known-project set is supplied, a reference resolves ONLY if
    # the exact referenced `.csproj` is among the scanned projects. A reference to a
    # `.csproj` that does not exist contributes nothing even when a DIFFERENT
    # project shares its directory (no over-match to a sibling); a reference whose
    # exact `.csproj` IS a known project resolves to that project's root directory.
    raw = (
        b'<Project Sdk="Microsoft.NET.Sdk"><ItemGroup>'
        b'<ProjectReference Include="..\\B\\Missing.csproj" />'
        b'<ProjectReference Include="..\\D\\D.csproj" />'
        b"</ItemGroup></Project>"
    )
    known = frozenset({"A/A.csproj", "B/B.csproj", "D/D.csproj"})
    # `B/Missing.csproj` is absent (only `B/B.csproj` exists) -> dropped; `D/D.csproj`
    # is a known project -> its root `D` resolves.
    assert _parse_project_references(raw, "A", known) == {"D"}


def test_parse_project_references_refuses_dtd_to_block_entity_expansion():
    from sumo_qa.repo_map_resolvers.csharp import _parse_project_references

    # A scanned `.csproj` is untrusted repository content. A DOCTYPE is the
    # billion-laughs / entity-expansion denial-of-service vector, so a manifest
    # declaring one is refused OUTRIGHT (no references, no expansion) rather than
    # handed to expat.
    raw = (
        b'<?xml version="1.0"?>\n'
        b"<!DOCTYPE lolz [\n"
        b' <!ENTITY lol "lol">\n'
        b' <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">\n'
        b' <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">\n'
        b"]>\n"
        b'<Project><ItemGroup><ProjectReference Include="&lol2;" />'
        b"</ItemGroup></Project>"
    )
    assert _parse_project_references(raw, "C") == set()


def test_parse_project_references_refuses_bomless_utf16_dtd_and_reference():
    from sumo_qa.repo_map_resolvers.csharp import _parse_project_references

    # A BOM-less UTF-16LE `.csproj` is NUL-interleaved ASCII XML. Every NUL byte
    # is valid UTF-8 (`U+0000`), so `raw.decode("utf-8")` alone accepts it, and
    # the interleaved NULs (`<\x00!\x00D\x00...`) mean the byte-level
    # `b"<!DOCTYPE"` guard never matches the DTD. expat would then auto-detect
    # UTF-16 from the `<?xml` prolog and PROCESS the DTD, expanding `&d;` into a
    # phantom `<ProjectReference>` (the entity-expansion DoS vector AND a wrong
    # cross-project edge). A real `.csproj` is UTF-8 text with no NUL bytes, so a
    # NUL-bearing manifest is treated as non-UTF-8 and contributes NO references,
    # never reaching `ET.fromstring`.
    xml = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE Project [ <!ENTITY d "..\\D\\D.csproj"> ]>\n'
        '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup>'
        '<ProjectReference Include="&d;" />'
        "</ItemGroup></Project>"
    )
    raw = xml.encode("utf-16-le")  # BOM-less UTF-16LE: valid UTF-8 bytes, NUL-laced
    # The two current guards both fail to catch this: the bytes decode as UTF-8,
    # and the byte-level DOCTYPE check cannot see the interleaved-NUL DTD.
    assert raw.decode("utf-8")  # old validation passed it
    assert b"<!DOCTYPE" not in raw  # byte DTD guard misses the interleaved-NUL DTD
    # The NUL rejection closes both: no reference, DTD never handed to expat.
    assert _parse_project_references(raw, "C", frozenset({"D/D.csproj"})) == set()
