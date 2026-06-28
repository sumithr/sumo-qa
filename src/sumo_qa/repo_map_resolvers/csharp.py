# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""C# import resolver for the repo-map import-edge layer (#362, epic #353).

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
  static members) and ``using Alias = X`` (an alias) are NOT namespace imports
  and are skipped.
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

.. note::

   The Approach-C ``resolve(importer, imp, file_set)`` contract is **path-only**
   — it never sees other files' *contents*, which is exactly what the namespace
   index needs. So the index is a first-class, separately-tested resolver
   capability (:meth:`index_namespaces` / :meth:`declared_namespaces`) rather
   than something ``resolve`` can build itself. At scan time the registered
   resolver's index is empty (nothing populates it through the path-only
   contract), so wiring this resolver into ``scan_repo`` needs a foundation
   enhancement: a pre-pass that builds the namespace index across all ``.cs``
   files and hands it to the resolver. The foundation also does not yet
   classify ``.cs`` as a source language (``repo_map_scanner``'s
   ``_LANGUAGE_BY_EXT`` / ``_PROGRAMMING_LANGS`` omit it). Both are foundation
   changes and are out of scope here (#362 ships the resolver + its index
   capability; the scan-time wiring is a follow-on).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sumo_qa.repo_map_resolvers.base import LanguageConfig, RawImport, register
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
_IDENTIFIER = "identifier"  # a single-segment name `A`
_STATIC = "static"  # the `static` token of `using static T`
_EQUALS = "="  # the `=` token of `using Alias = X`

# The BCL/framework namespace root. `System` and any `System.*` namespace is
# dropped explicitly so it never fans out even if a project file (perversely)
# declares a same-named namespace.
_BCL_ROOT = "System"


class CSharpResolver:
    """Approach-C resolver for C# (namespace fan-out via a cross-file index)."""

    config = CSHARP_CONFIG

    def __init__(self) -> None:
        # namespace -> set of repo-relative paths that declare it. Empty until
        # `index_namespaces` is called; `resolve` returns nothing while empty.
        self._namespace_index: dict[str, set[str]] = {}

    def extract(self, src: bytes) -> list[RawImport]:
        """Return the namespace ``using`` directives in ``src`` as records.

        Each plain ``using X;`` / ``global using X;`` yields a
        :class:`RawImport` whose ``module`` is the dotted namespace. ``using
        static T`` (type statics) and ``using Alias = X`` (alias) are skipped —
        they are not namespace imports. C# using directives are always
        file-/namespace-level (never inside a method body), so ``level`` is
        ``0``, ``names`` is empty, and ``function_local`` is ``False``.
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
        """The dotted namespace of a plain ``using`` directive, or ``None``.

        Returns ``None`` for ``using static T`` (a ``static`` token) and
        ``using Alias = X`` (an ``=`` token) — neither is a namespace import.
        Otherwise the namespace is the directive's sole ``qualified_name`` /
        ``identifier`` child (``global using`` and ``using`` differ only by a
        leading ``global`` keyword token, so both reach here).
        """
        kinds = {child.kind for child in node.children}
        if _STATIC in kinds or _EQUALS in kinds:
            return None
        for child in node.children:
            if child.kind in (_QUALIFIED_NAME, _IDENTIFIER):
                return child.text
        return None  # pragma: no cover -- defensive: a plain using always has a name node

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
        namespace with no declaring project file (external assemblies) resolve
        to ``[]`` — never an error, the normal "not-ours" outcome. Empty until
        :meth:`index_namespaces` has populated the cross-file index.
        """
        namespace = imp.module
        if namespace == _BCL_ROOT or namespace.startswith(f"{_BCL_ROOT}."):
            return []
        declarers = self._namespace_index.get(namespace)
        if declarers is None:
            return []
        return sorted(path for path in declarers if path in file_set and path != importer)


register(CSharpResolver())
