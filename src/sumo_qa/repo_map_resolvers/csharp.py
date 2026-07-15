# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
r"""C# import resolver for the repo-map import-edge layer (#362, epic #353).

Ports Understand-Anything's C# rules into the Approach-C framework the
foundation (#354) shipped. C# is the framework's first language whose imports
do **not** map to files one-to-one: a ``using`` names a *namespace*, and a
namespace can be declared by any number of ``.cs`` files across the project. So
resolution is package-level fan-out — ``using X`` links to **every** project
file that declares ``namespace X``.

Resolution rules (ported from UA):

- **``using`` → namespace, not file.** ``extract`` pulls each plain ``using``
  (and ``global using``) directive off the parse as a :class:`RawImport` whose
  ``module`` is the dotted namespace. ``using static T`` (imports a type's
  static members) is NOT a namespace import and is skipped. ``using Alias =
  Namespace`` (an alias directive) records the RIGHT-HAND-SIDE namespace (the
  alias name is ignored), so it fans out to that namespace's declaring files
  exactly as a plain ``using Namespace;`` would. tree-sitter cannot tell a
  namespace alias from a type alias, so a type alias's RHS is recorded too, but
  it simply misses the namespace index and resolves to nothing. A leading
  ``global::`` alias qualifier (``using global::X.Y;``) is stripped during
  extraction: it forces root-namespace lookup but names the SAME namespace as
  ``using X.Y;``, so both resolve identically.
- **Namespace fan-out via a cross-file index.** A namespace's declaring files
  can only be known by reading *other* files, so the resolver carries a
  ``namespace -> {declaring file path}`` index (built by
  :meth:`index_namespaces` over the project's sources). ``resolve`` looks the
  ``using`` up in that index and returns every declaring file that exists in
  ``file_set`` (minus the importer itself — no self-edge).
- **``System.*`` and external assemblies dropped.** ``System`` and any
  ``System.*`` namespace is the BCL/framework root and is dropped explicitly.
  Any other namespace with no declaring project file (an external NuGet
  assembly, e.g. ``Newtonsoft.Json``) misses the index and resolves to nothing.

.. note:: Scan-time namespace index (per project)

   The Approach-C ``resolve(importer, imp, file_set)`` contract is **path-only**
   — it never sees other files' *contents*, which is exactly what the namespace
   index needs. So the index is built by a per-scan pre-pass, :meth:`prepare` —
   the scan-local preparation hook the #484 foundation shipped (#525): it reads
   every ``.cs`` source through the scan's
   :class:`~sumo_qa.repo_map_resolvers.base.ScanContext` and returns a FRESH
   resolver carrying the index as scan-local state, so the registered
   module-level singleton is never mutated with repository data (that would leak
   one scan's namespaces into the next). Since #483 the scanner classifies
   ``.cs`` as ``csharp`` (so every ``.cs`` file reaches this resolver during a
   real ``scan_repo``); ``.csproj`` project files classify as manifest nodes
   (#542) so their LOCATION is visible in ``ScanContext.files``.

   The index is scoped **per PROJECT boundary**: a namespace's declaring files
   are grouped by the owning ``.csproj`` (the nearest ancestor directory holding
   one), and ``resolve`` fans a ``using`` out within the importer's own project
   AND into any project it explicitly references (see below). The ``.csproj``'s
   LOCATION alone marks the boundary and the namespace-index grouping; its XML is
   not consulted for either, so a UTF-8 ``.csproj`` whose XML is invalid is still
   a usable boundary whose project's ``.cs`` namespaces index normally. A
   ``using`` naming a namespace declared in an UNREFERENCED different project
   resolves to nothing — there is no repository-global fan-out once project
   ownership is known. A ``.cs`` file with no owning ``.csproj`` falls back to
   path-only resolution (no fan-out). The only "unusable" ``.csproj`` is one that
   is UNREADABLE or non-UTF-8: it still bounds its own directory from its LOCATION
   — so its files do not leak into an ancestor project — but its namespace index
   stays EMPTY, so every ``using`` in it falls back to path-only resolution,
   with one deterministic ``other`` warning. The flat, repository-wide
   :meth:`index_namespaces` / :meth:`declared_namespaces` capability remains for
   direct callers and unit tests.

.. note:: Cross-project ``<ProjectReference>`` edges (#548)

   Per-project scoping has ONE explicit escape hatch: an SDK ``.csproj`` may name
   another project as a build dependency via
   ``<ProjectReference Include="..\Other\Other.csproj"/>``. When that element is
   present, a ``using`` in the referencing project ALSO fans out into the
   referenced project's declarers, so a namespace declared in an explicitly
   referenced project resolves. This is the one place the manifest's XML *is*
   parsed (tolerantly, local-name matched, ignoring any MSBuild XML namespace);
   the boundary and the namespace-index grouping stay location-only. References
   are DIRECT ONLY (not transitive): if A references B and B references C, a
   ``using`` in A resolves into B but not into C. Include paths use MSBuild
   backslashes and are resolved relative to the referencing ``.csproj``'s own
   directory, and a reference resolves ONLY when its exact referenced ``.csproj``
   is itself a scanned project: a ``<ProjectReference>`` naming a ``.csproj`` that
   is not among the scan's projects contributes nothing, so a dangling reference
   never over-matches a DIFFERENT project that merely shares the referenced
   directory. A manifest that is unreadable, non-UTF-8, or unparseable as XML
   contributes no references (its own boundary and namespace index are
   unaffected); a scanned manifest declaring a DTD is refused to close the
   entity-expansion denial-of-service vector — the scan never aborts on a bad
   ``.csproj`` (ANY parse failure, ``ParseError`` or not, yields no references).

.. note:: Known limitation — project-wide global-using application

   A ``global using`` (e.g. ``global using MyApp.Models;`` in a
   ``GlobalUsings.cs``) applies *project-wide* in C#: other files that use types
   from ``MyApp.Models`` without a local ``using`` implicitly import it too.
   This resolver emits the edge from the ``global using``'s OWN declaring file
   (project-scoped like any other ``using``), but does NOT re-apply one file's
   global usings to its SIBLING files. The orchestrator's per-file
   ``extract(bytes)`` / ``resolve(importer, imp, file_set)`` contract exposes no
   per-file hook for injecting a project's implicit imports into a file that has
   no matching directive of its own, so sibling application stays out of scope
   here.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

from sumo_qa.repo_map_resolvers.base import (
    LanguageConfig,
    RawImport,
    ScanContext,
    register,
)
from sumo_qa.repo_map_treesitter import TSNode, parse

if TYPE_CHECKING:  # pragma: no cover -- typing-only import, never executed
    from collections.abc import Mapping

CSHARP_CONFIG = LanguageConfig(
    id="csharp",
    extensions=(".cs",),
)

# Grammar kinds, pinned to tree-sitter-language-pack's C# grammar (probed
# against the installed binding).
_USING_DIRECTIVE = "using_directive"  # `using X;` / `global using X;` / `using static T;`
_NAMESPACE_DECL = "namespace_declaration"  # `namespace X { ... }`
_FILE_SCOPED_NAMESPACE_DECL = "file_scoped_namespace_declaration"  # `namespace X;`
_QUALIFIED_NAME = "qualified_name"  # `A.B.C`
_ALIAS_QUALIFIED_NAME = "alias_qualified_name"  # `global::A` / `Extern::A`
_IDENTIFIER = "identifier"  # a single-segment name `A`
_STATIC = "static"  # the `static` token of `using static T`

# The `global::` alias qualifier forces root-namespace lookup; it names the SAME
# namespace as the unqualified spelling, so it is stripped during extraction so
# `using global::X.Y;` resolves identically to `using X.Y;`.
_GLOBAL_QUALIFIER = "global::"


def _normalize_namespace(namespace: str | None) -> str | None:
    """Strip a leading ``global::`` alias qualifier; pass ``None`` through.

    ``global::X.Y`` and ``X.Y`` name the same namespace, so the qualifier is
    removed before the module reaches the index (``None`` — a ``using static``
    or nameless directive — stays ``None``).
    """
    if namespace is not None and namespace.startswith(_GLOBAL_QUALIFIER):
        return namespace[len(_GLOBAL_QUALIFIER) :]
    return namespace


# The BCL/framework namespace root. `System` and any `System.*` namespace is
# dropped explicitly so it never fans out even if a project file (perversely)
# declares a same-named namespace.
_BCL_ROOT = "System"

# C# source + project-manifest suffixes.
_CS = ".cs"
_CSPROJ = ".csproj"

# One deterministic `other` warning per unusable project manifest. A `.csproj`
# that cannot be read or decoded as UTF-8 still bounds its directory as a project
# (its LOCATION marks the boundary, so its `.cs` files do not leak into an
# ancestor project), but its namespaces are NOT indexed — that project's index
# stays empty, so its files fall back to path-only resolution (no namespace
# fan-out) rather than aborting the scan.
_UNUSABLE_PROJECT_MESSAGE = (
    "unreadable or non-UTF-8 .csproj ignored by the csharp import resolver; "
    "its project's namespace fan-out falls back to path-only resolution"
)

# MSBuild `<ProjectReference Include="..\Other\Other.csproj"/>` element/attribute
# names, matched by LOCAL name so an old-style csproj's MSBuild XML namespace
# (`xmlns="http://schemas.microsoft.com/developer/msbuild/2003"`) does not hide
# them.
_PROJECT_REFERENCE_TAG = "ProjectReference"
_INCLUDE_ATTR = "Include"


def _local_name(tag: str) -> str:
    """The element's local name, dropping any ``{namespace}`` ElementTree prefix.

    SDK-style projects carry no XML namespace (``<Project Sdk="...">``); old-style
    projects namespace every tag, and ElementTree renders that as
    ``{http://...}ProjectReference``. Splitting on the closing brace yields the
    bare local name in both shapes.
    """
    return tag.rsplit("}", 1)[-1]


def _clean_utf8_csproj_text(raw: bytes) -> str | None:
    """Decode a ``.csproj``'s bytes as clean UTF-8 XML text, or ``None`` if unusable.

    A real ``.csproj`` is UTF-8 XML text with NO NUL bytes. Returns the decoded
    text only when ``raw`` decodes as UTF-8 AND contains no NUL character;
    otherwise ``None`` — the caller then routes the manifest to the SAME unusable
    / non-UTF-8 handling as an undecodable one (empty namespace index + one
    deterministic ``other`` warning at the boundary; no cross-project references).

    The NUL check is what closes the BOM-less UTF-16 bypass: a UTF-16LE/BE
    ``.csproj`` is NUL-interleaved ASCII, and every NUL byte is valid UTF-8
    (``U+0000``), so ``raw.decode("utf-8")`` alone accepts it. ElementTree would
    then auto-detect UTF-16 from the ``<?xml`` prolog / BOM and PROCESS an
    interleaved-NUL ``<!DOCTYPE>`` (the byte-level ``b"<!DOCTYPE"`` guard cannot
    match ``<\x00!\x00D\x00...``), reopening the entity-expansion (billion-laughs)
    denial-of-service vector and letting an entity-expanded ``<ProjectReference>``
    emit a phantom cross-project edge. Rejecting NUL-bearing content keeps such a
    manifest out of ``ET.fromstring`` entirely.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "\x00" in text:
        return None
    return text


def _parse_project_references(
    raw: bytes, csproj_dir: str, project_files: frozenset[str] | None = None
) -> set[str]:
    """The project ROOT directories a ``.csproj`` references, or an empty set.

    Parses ``raw`` tolerantly and reads every
    ``<ProjectReference Include="..."/>``: MSBuild spells the ``Include`` path
    with backslashes relative to the referencing ``.csproj``'s own directory
    (``csproj_dir``), so each is normalized to forward slashes, joined onto
    ``csproj_dir``, and reduced to the referenced project's ROOT directory (the
    directory holding the referenced ``.csproj``).

    When ``project_files`` is given — the scan's set of every scanned ``.csproj``
    path — a reference resolves ONLY if the exact referenced ``.csproj`` is among
    them. A reference to a ``.csproj`` that is not a known project contributes
    nothing: it names a project that does not exist in the scan, so it must not
    over-match a DIFFERENT project that merely shares the referenced directory
    (verifying the reference names an actual project, not just a directory that
    happens to hold one). When ``project_files`` is ``None`` (direct callers /
    unit tests of the parser), every parseable Include contributes its root
    directory unverified.

    Any parse failure yields no references and never propagates: expat raises
    ``ET.ParseError`` on malformed XML but also non-``ParseError`` exceptions on
    untrusted content (e.g. ``LookupError`` for an unloadable ``encoding="..."``
    prolog declaration), and the goal here is that a bad ``.csproj`` never aborts
    the scan — it simply contributes no cross-project edges (the manifest still
    bounds its project by LOCATION and its own ``.cs`` namespaces still index).

    A scanned ``.csproj`` is untrusted repository content, so a manifest that
    declares a DTD is refused outright (returns no references): expat expands
    internal entities, which is the billion-laughs / quadratic-blowup
    denial-of-service vector, and a real ``.csproj`` never carries a ``DOCTYPE``.
    The XML ``DOCTYPE`` keyword is case-sensitive uppercase, so the literal-byte
    check catches every DTD expat would otherwise process — but ONLY in clean
    UTF-8. A BOM-less UTF-16 manifest interleaves NULs (``<\x00!\x00D\x00...``),
    hiding the DTD from the byte check while still decoding as UTF-8 (NUL is a
    valid UTF-8 code point), so expat would auto-detect UTF-16 and process it
    anyway. So NUL-bearing (or otherwise non-UTF-8) bytes are rejected before
    ``ET.fromstring`` via :func:`_clean_utf8_csproj_text`: a real ``.csproj`` is
    UTF-8 text with no NUL bytes, and rejecting the rest keeps the UTF-16 DTD /
    entity-expansion path unreachable.
    """
    if b"<!DOCTYPE" in raw:
        return set()
    if _clean_utf8_csproj_text(raw) is None:
        # NUL-bearing (UTF-16/UTF-32/binary) or non-UTF-8 bytes: not real
        # `.csproj` text. Bail before `ET.fromstring`, so a BOM-less UTF-16
        # manifest — whose interleaved-NUL DTD the byte guard above cannot see —
        # never reaches expat's UTF-16 auto-detection and DTD processing.
        return set()
    try:
        root = ET.fromstring(raw)
    except Exception:  # noqa: BLE001 -- untrusted .csproj: any parse failure -> no refs, never abort
        return set()
    references: set[str] = set()
    for element in root.iter():
        if _local_name(element.tag) != _PROJECT_REFERENCE_TAG:
            continue
        include = element.get(_INCLUDE_ATTR)
        if not include:
            continue
        target = posixpath.normpath(posixpath.join(csproj_dir, include.replace("\\", "/")))
        if project_files is not None and target not in project_files:
            continue  # reference to a .csproj that is not a known project: no edge
        references.add(target.rsplit("/", 1)[0] if "/" in target else "")
    return references


@dataclass(frozen=True)
class _ProjectIndex:
    """Scan-local, per-project namespace context for one repository scan (#542).

    Built by :meth:`CSharpResolver.prepare` from the scan's bounded source
    reads, carried only by the scan-local resolver instance, and discarded with
    the scan — never attached to the registered singleton.

    - ``project_by_file`` — each ``.cs`` file whose project ownership is known,
      mapped to its owning PROJECT ROOT (the nearest ancestor directory holding
      a ``.csproj``, readable or not). A file with no owning project is absent:
      its ``using`` directives resolve to nothing (path-only fallback).
    - ``declarers_by_project`` — for each owning project, the ``namespace ->
      declaring files`` index built ONLY from that project's own ``.cs`` files.
      A ``using`` fans out within the importer's project AND into any project it
      explicitly references (see ``references_by_project``), so a namespace
      declared in an UNREFERENCED other project resolves to nothing (the
      cross-project true negative). A project whose ``.csproj`` is unusable
      (unreadable / non-UTF-8) still owns its files (bounding them from
      ancestors) but appears here with an EMPTY map, so every ``using`` in it
      resolves to nothing — path-only, no leak.
    - ``references_by_project`` — for each project, the ROOT directories of the
      projects it names via ``<ProjectReference Include="..."/>`` in its
      ``.csproj`` (DIRECT references only; not transitive). A ``using`` in the
      importer's project also fans out into these referenced projects' declarers.
      A project with no references (or whose ``.csproj`` could not be read /
      parsed) is absent, keeping the per-project boundary.
    """

    project_by_file: Mapping[str, str]
    declarers_by_project: Mapping[str, Mapping[str, frozenset[str]]]
    references_by_project: Mapping[str, frozenset[str]]

    def declarers(self, importer: str, namespace: str) -> frozenset[str]:
        """Files declaring ``namespace`` in ``importer``'s project or a referenced one.

        Draws from ``importer``'s own project AND every project it DIRECTLY
        references via ``<ProjectReference>``. Empty when ``importer`` has no
        known project (path-only fallback) or the namespace is declared in no
        such project — an external assembly, or a namespace owned by an
        UNREFERENCED project (the cross-project true negative).
        """
        project = self.project_by_file.get(importer)
        if project is None:
            return frozenset()
        own = self.declarers_by_project[project].get(namespace, frozenset())
        referenced = self.references_by_project.get(project, ())
        if not referenced:
            return own
        found = set(own)
        for ref in referenced:
            found.update(self.declarers_by_project.get(ref, {}).get(namespace, frozenset()))
        return frozenset(found)


class CSharpResolver:
    """Approach-C resolver for C# (namespace fan-out via a cross-file index)."""

    config = CSHARP_CONFIG

    def __init__(self, index: _ProjectIndex | None = None) -> None:
        # Scan-local per-project context; `None` for the registered path-only
        # singleton (see `prepare`). When present, `resolve` scopes namespace
        # fan-out to the importer's own project instead of the flat index below.
        self._index = index
        # namespace -> set of repo-relative paths that declare it. The flat,
        # repository-wide index used by DIRECT callers (unit tests, the #362
        # `index_namespaces` capability); empty until `index_namespaces` runs.
        # At scan time the orchestrator dispatches through `prepare`'s per-project
        # `_index`, so the registered singleton's flat index stays empty.
        self._namespace_index: dict[str, set[str]] = {}

    def extract(self, src: bytes) -> list[RawImport]:
        """Return the namespace ``using`` directives in ``src`` as records.

        Each plain ``using X;`` / ``global using X;`` yields a
        :class:`RawImport` whose ``module`` is the dotted namespace, and an
        alias ``using Alias = X;`` yields one whose ``module`` is the
        RIGHT-HAND-SIDE namespace ``X`` (the alias name is ignored). ``using
        static T`` (type statics) is skipped — it is not a namespace import. C#
        using directives are always file-/namespace-level (never inside a method
        body), so ``level`` is ``0``, ``names`` is empty, and
        ``function_local`` is ``False``.
        """
        root = parse("csharp", src)
        raws: list[RawImport] = []
        for node in root.descendants():
            if node.kind != _USING_DIRECTIVE:
                continue
            namespace = self._using_namespace(node)
            if namespace is not None:
                raws.append(RawImport(module=namespace, level=0, names=(), function_local=False))
        return raws

    @staticmethod
    def _using_namespace(node: TSNode) -> str | None:
        """The dotted namespace a ``using`` directive brings in, or ``None``.

        ``using static T`` (imports a type's static members) is not a namespace
        import and yields ``None``. Otherwise the namespace is the directive's
        LAST name child: a plain ``using X;`` / ``global using X;`` has exactly
        one name node (``X``), while an alias ``using Alias = X;`` has two
        (``[Alias, X]``) and the namespace is always the right-hand ``X`` — the
        alias name precedes the ``=`` token, so the RHS is last. tree-sitter
        cannot distinguish a namespace alias from a type alias; a type alias's
        RHS is returned too but simply misses the namespace index and resolves
        to nothing.

        A ``global::`` alias qualifier (parsed as a ``qualified_name`` whose text
        keeps the prefix, e.g. ``global::X.Y``, or as a single-segment
        ``alias_qualified_name`` like ``global::X``) is stripped: it forces
        root-namespace lookup but names the SAME namespace as the unqualified
        spelling, so ``using global::X.Y;`` resolves identically to
        ``using X.Y;``.
        """
        kinds = {child.kind for child in node.children}
        if _STATIC in kinds:
            return None
        namespace: str | None = None
        for child in node.children:
            if child.kind in (_QUALIFIED_NAME, _ALIAS_QUALIFIED_NAME, _IDENTIFIER):
                namespace = child.text
        return _normalize_namespace(namespace)

    def declared_namespaces(self, src: bytes) -> set[str]:
        """The set of namespaces ``src`` declares (block, file-scoped, nested).

        ``namespace A.B { ... }`` and ``namespace A.B;`` each declare ``A.B``;
        a nested ``namespace Inner`` inside ``namespace Outer`` declares the
        full dotted ``Outer.Inner`` (C# composes the enclosing namespace into
        the child's fully-qualified name).
        """
        root = parse("csharp", src)
        out: set[str] = set()
        self._collect_namespaces(root, prefix="", out=out)
        return out

    def _collect_namespaces(self, node: TSNode, *, prefix: str, out: set[str]) -> None:
        if node.kind in (_NAMESPACE_DECL, _FILE_SCOPED_NAMESPACE_DECL):
            name = self._namespace_name(node)
            if name is None:  # pragma: no cover -- defensive: a namespace decl always has a name
                return
            full = f"{prefix}.{name}" if prefix else name
            out.add(full)
            for child in node.children:
                self._collect_namespaces(child, prefix=full, out=out)
            return
        for child in node.children:
            self._collect_namespaces(child, prefix=prefix, out=out)

    @staticmethod
    def _namespace_name(node: TSNode) -> str | None:
        """The dotted name of a namespace declaration (the child after
        ``namespace``), or ``None``."""
        for child in node.children:
            if child.kind in (_QUALIFIED_NAME, _IDENTIFIER):
                return child.text
        return None  # pragma: no cover -- defensive: a namespace decl always has a name

    def index_namespaces(self, sources: Mapping[str, bytes]) -> dict[str, set[str]]:
        """Build (and store) the ``namespace -> {declaring file}`` index.

        ``sources`` maps each repo-relative ``.cs`` path to its bytes. The index
        is stored on the resolver so :meth:`resolve` can fan a ``using`` out to
        the namespace's declaring files; it is also returned so the index is
        directly inspectable/testable. Replaces any previously-stored index.
        """
        index: dict[str, set[str]] = {}
        for path, src in sources.items():
            for namespace in self.declared_namespaces(src):
                index.setdefault(namespace, set()).add(path)
        self._namespace_index = index
        return index

    def resolve(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        """Fan a ``using`` out to the project files that declare its namespace.

        Returns every repo-relative path that declares ``imp.module``, exists in
        ``file_set``, and is not the importer itself (no self-edge), sorted for
        determinism. ``System`` / ``System.*`` (the BCL/framework root) and any
        namespace with no declaring file resolve to ``[]`` — never an error, the
        normal "not-ours" outcome.

        With a scan-local :class:`_ProjectIndex` (a prepared instance), the
        declaring files are drawn from the importer's own project AND any project
        it explicitly references via ``<ProjectReference>`` (#548), so a namespace
        declared in an UNREFERENCED different project does not resolve (#542).
        Otherwise the flat, repository-wide index is used (direct callers / the
        registered singleton, whose flat index is empty).
        """
        namespace = imp.module
        if namespace == _BCL_ROOT or namespace.startswith(f"{_BCL_ROOT}."):
            return []
        declarers = self._declarers(importer, namespace)
        return sorted(path for path in declarers if path in file_set and path != importer)

    def _declarers(self, importer: str, namespace: str) -> frozenset[str]:
        """Files declaring ``namespace`` — project-scoped when prepared, else flat."""
        if self._index is not None:
            return self._index.declarers(importer, namespace)
        flat = self._namespace_index.get(namespace)
        return frozenset(flat) if flat is not None else frozenset()

    # ---------- scan-local preparation (#525 foundation, #542 C# slice) ----------

    def prepare(self, context: ScanContext) -> CSharpResolver:
        """Derive a scan-local resolver carrying per-project namespace context.

        Reads only ``.cs`` sources and ``.csproj`` manifests, always through the
        context's bounded, memoized reads — no unbounded second repository read.
        Returns a NEW resolver instance so the registered singleton never carries
        repository data; everything derived here dies with the scan. A ``.csproj``
        that is unreadable or non-UTF-8 still bounds its directory (so its files
        never leak into an ancestor project) but leaves that project's namespace
        index EMPTY — path-only resolution — and yields one deterministic
        ``other`` warning; an unreadable ``.cs`` source contributes no namespaces
        — neither aborts the scan. Parses with tree-sitter, so callers reach
        preparation only behind the orchestrator's availability gate (the same
        contract as :meth:`extract`).
        """
        boundaries, usable, references = self._project_roots(context)
        project_by_file: dict[str, str] = {}
        # Match the scanner's case-insensitive classification (it stamps by
        # `.suffix.lower()`, so `Order.CS` is a `csharp` node): a case-sensitive
        # suffix test here would skip an uppercase-extension file the scanner DID
        # classify as C#, dropping its namespace from the index on a
        # case-sensitive filesystem.
        for path in sorted(f for f in context.files if f.lower().endswith(_CS)):
            owner = self._owning_project(path, boundaries)
            if owner is not None:
                project_by_file[path] = owner
        declarers: dict[str, dict[str, set[str]]] = {
            project: {} for project in set(project_by_file.values())
        }
        for path, project in project_by_file.items():
            if project not in usable:
                # Broken project: its files are owned (shadowing them from an
                # ancestor project) but its namespaces are NOT indexed, so the
                # empty map leaves every `using` in it path-only — no leak.
                continue
            src = context.read(path)
            if src is None:
                continue  # unreadable source: no namespaces from it, never an abort
            for namespace in self.declared_namespaces(src):
                declarers[project].setdefault(namespace, set()).add(path)
        return CSharpResolver(
            index=_ProjectIndex(
                project_by_file=project_by_file,
                declarers_by_project={
                    project: {ns: frozenset(files) for ns, files in ns_map.items()}
                    for project, ns_map in declarers.items()
                },
                references_by_project={
                    project: frozenset(refs) for project, refs in references.items()
                },
            )
        )

    @staticmethod
    def _project_roots(
        context: ScanContext,
    ) -> tuple[set[str], set[str], dict[str, set[str]]]:
        """Project boundaries, the usable subset, and the reference graph.

        Returns ``(boundaries, usable, references)``:

        - ``boundaries`` — every ``.csproj`` directory. A ``.csproj``'s LOCATION,
          not its contents, marks a project boundary (an SDK-style project globs
          the ``.cs`` files beneath its directory); the boundary is location-only,
          so every ``.csproj`` in the scan bounds its directory REGARDLESS of its
          XML validity, and even a manifest whose bytes cannot be read still bounds
          from its path. :meth:`_owning_project` walks this set, so even a broken
          manifest stops the walk at its own directory — its files never leak into
          an ancestor project.
        - ``usable`` — the boundaries whose ``.csproj`` could be read AND is clean
          UTF-8 XML text (decodes as UTF-8 with NO NUL bytes — a NUL marks a
          BOM-less UTF-16/UTF-32 or binary file masquerading as UTF-8, since NUL
          is a valid UTF-8 code point). Only these have their ``.cs`` namespaces
          indexed by :meth:`prepare`. A boundary NOT in ``usable`` is UNREADABLE
          or non-UTF-8 (including NUL-bearing UTF-16; never merely invalid XML):
          its project keeps an empty namespace index (path-only resolution) and
          emits one deterministic ``other`` warning. The scan continues rather
          than aborting.
        - ``references`` — for each project ROOT, the set of project ROOTs it names
          via ``<ProjectReference Include="..."/>`` (direct only). Only usable,
          UTF-8 manifests are parsed for references; an unreadable, non-UTF-8, or
          malformed-XML manifest simply contributes none. The referencing project
          is keyed by its ``.csproj``'s own directory.
        """
        boundaries: set[str] = set()
        usable: set[str] = set()
        references: dict[str, set[str]] = {}
        # Case-insensitive suffix test, matching the scanner's `.suffix.lower()`
        # classification (so `App.CSPROJ` is a manifest node): a case-sensitive
        # test would miss an uppercase-extension manifest the scanner DID classify,
        # so its directory would not bound a project on a case-sensitive filesystem.
        project_files = sorted(f for f in context.files if f.lower().endswith(_CSPROJ))
        # The set of every scanned `.csproj` path — the scan's known projects. A
        # `<ProjectReference>` resolves ONLY when its exact referenced `.csproj` is
        # in this set, so a reference to a NON-EXISTENT project cannot over-match a
        # different project that merely shares the referenced directory.
        known_projects = frozenset(project_files)
        for csproj in project_files:
            directory = csproj.rsplit("/", 1)[0] if "/" in csproj else ""
            boundaries.add(directory)
            raw = context.read(csproj)
            if raw is None:
                context.warn_config(_UNUSABLE_PROJECT_MESSAGE, csproj)
                continue
            if _clean_utf8_csproj_text(raw) is None:
                # Undecodable UTF-8, or decodable-but-NUL-bearing (a BOM-less
                # UTF-16/UTF-32 manifest whose NUL bytes are valid UTF-8): not
                # real `.csproj` text. Treat as unusable so its namespaces are not
                # indexed and its references are never parsed — the UTF-16 DTD /
                # entity-expansion path is unreachable — while its LOCATION still
                # bounds the project. One deterministic `other` warning.
                context.warn_config(_UNUSABLE_PROJECT_MESSAGE, csproj)
                continue
            usable.add(directory)
            refs = _parse_project_references(raw, directory, known_projects)
            if refs:
                references.setdefault(directory, set()).update(refs)
        return boundaries, usable, references

    @staticmethod
    def _owning_project(cs_file: str, roots: set[str]) -> str | None:
        """The nearest ancestor project root that owns ``cs_file``, or ``None``.

        Walks the file's own directory and each ancestor up to the repo root,
        returning the first that holds a ``.csproj`` (usable or not — the boundary
        is marked by location). ``None`` when no ancestor is a project root — the
        file's ``using`` directives then resolve to nothing (missing-config
        path-only fallback).
        """
        parts = cs_file.split("/")[:-1]  # directory components of the file
        for i in range(len(parts), -1, -1):
            candidate = "/".join(parts[:i])
            if candidate in roots:
                return candidate
        return None


register(CSharpResolver())
