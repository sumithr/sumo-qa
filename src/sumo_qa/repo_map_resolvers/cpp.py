# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""C/C++ include resolver for the repo-map import-edge layer (#359).

An Approach-C resolver in the framework the foundation (#354) shipped.
``extract`` reads ``#include`` directives off a tree-sitter parse of C/C++
source; ``resolve`` maps each quoted include to the repo-relative file it
references via the one search-order element the preprocessor guarantees
without build configuration: the including file's own directory, searched with
the include's exact spelling.

Resolution rules (#359, corrected from the original Understand-Anything port):

- **Quoted includes** (``#include "foo.h"``) resolve relative to the including
  file's directory using the exact normalized spelling. The C preprocessor
  searches the header spelling exactly: ``#include "config"`` names a file
  literally called ``config``, so header extensions are never synthesized
  (probing ``.h``/``.hpp`` variants can fabricate an edge the compiler would
  never make). Spellings are POSIX forward-slash paths: a backslash spelling
  (``#include "sub\\util.h"``, accepted by MSVC) is not normalized and never
  resolves (under-edge). An extensionless include can resolve at this layer,
  but a file with no extension never classifies as a repo-map node, so a scan
  cannot emit an edge to one (the no-dangling-edges rule); the exact-spelling
  contract still matters at scan level because it is what stops the ``.h``
  probing above.
- **No conventional include roots.** Fixed ``include/``/``src/`` root guesses
  cannot reproduce the compiler's ``-I`` search order, so a quoted include
  that does not resolve next to its importer under-edges (no edge) rather
  than guessing. Resolution through configured include directories arrives
  with per-repository context (#484, preferably from
  ``compile_commands.json``).
- **Angle-bracket includes** (``#include <project/foo.h>``) resolve only
  through proven include directories, which do not exist without that same
  repository context (#484). Until then they are dropped at extraction and
  emit no edge (under-edge, pinned by fixture true negatives).
- **Macro includes** (``#include CONFIG_H``) name no literal path (the
  argument is an ``identifier``, expanded at compile time), so they are
  dropped at extraction.
- **Repo-root escape**: a ``..`` traversal that walks above the repo root
  cannot reference an in-repo file, so the include yields no edge rather than
  being anchored at the root (which would fabricate a false edge).

An ``#include`` is a compile-time textual inclusion, never a lazy/deferred
import, so every extracted include is ``function_local=False`` (giving
``high`` confidence downstream). The same resolver is registered under both
``cpp`` and ``c``; the cpp grammar parses C ``#include`` directives
identically, so one implementation serves both language ids. The extension
tuples below are the resolver side of the scanner-ownership contract
(``tests/test_repo_map_resolver_scanner_contract.py``): ``.h`` is deliberately
declared by BOTH configs because the scanner stamps ``.h`` as ``cpp`` (its
documented ambiguous-header default) while the shared extractor serves both
languages.
"""

from __future__ import annotations

from sumo_qa.repo_map_resolvers.base import LanguageConfig, RawImport, register
from sumo_qa.repo_map_treesitter import TSNode, parse

CPP_CONFIG = LanguageConfig(
    id="cpp",
    extensions=(".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx"),
    barrels=(),
)
C_CONFIG = LanguageConfig(id="c", extensions=(".c", ".h"), barrels=())

# Grammar kinds, pinned to tree-sitter-language-pack's C/C++ grammar (probed
# against the installed binding; the orchestrator-integration test re-asserts
# them against real tree-sitter output).
_PREPROC_INCLUDE = "preproc_include"  # one `#include ...` directive
_STRING_LITERAL = "string_literal"  # the `"..."` of a quoted include
_STRING_CONTENT = "string_content"  # the path inside the quotes, no delimiters
_SYSTEM_LIB_STRING = "system_lib_string"  # the `<...>` of a system include


class CppResolver:
    """Approach-C resolver for C/C++ includes (registered as ``cpp`` and ``c``)."""

    def __init__(self, config: LanguageConfig = CPP_CONFIG) -> None:
        self.config = config

    def extract(self, src: bytes) -> list[RawImport]:
        """Return the quoted ``#include`` directives in ``src`` as RawImports.

        Walks the parse tree for ``preproc_include`` nodes. A quoted include
        (``#include "foo.h"``) yields one :class:`RawImport` whose ``module`` is
        the path inside the quotes; an angle-bracketed include
        (``#include <vector>``) and a macro include (``#include CONFIG_H``) are
        dropped. ``level``/``names`` are unused for C++ (no relative-dot or
        specifier concept) and ``function_local`` is always ``False`` — an
        ``#include`` is module-level textual inclusion, never lazy.
        """
        root = parse("cpp", src)
        raws: list[RawImport] = []
        for node in root.descendants():
            if node.kind != _PREPROC_INCLUDE:
                continue
            path = self._include_path(node)
            if path:  # empty -> an angle-bracket or macro include (dropped)
                raws.append(RawImport(module=path, level=0, names=(), function_local=False))
        return raws

    @staticmethod
    def _include_path(node: TSNode) -> str:
        """The quoted include path of a ``preproc_include`` node, or ''.

        A quoted include exposes a ``string_literal`` child whose
        ``string_content`` is the path without the quotes. A system include
        exposes a ``system_lib_string`` (the ``<...>``) and a macro include an
        ``identifier``; both return '' so the caller drops them."""
        for child in node.children:
            if child.kind == _STRING_LITERAL:
                return CppResolver._string_content(child)
            if child.kind == _SYSTEM_LIB_STRING:
                return ""  # `<...>`: no proven include roots without #484 context
        return ""  # macro include (`#include CONFIG_H`): no literal path

    @staticmethod
    def _string_content(node: TSNode) -> str:
        """The inner text of a ``string_literal`` (the path without quotes)."""
        for child in node.children:
            if child.kind == _STRING_CONTENT:
                return child.text
        return ""  # pragma: no cover -- defensive: a non-empty quoted include has content

    def resolve(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        """Map one quoted include to the repo-relative file it references.

        The include's exact normalized spelling is resolved against the
        importing file's own directory: the one candidate base the
        preprocessor's quoted-include search guarantees without build
        configuration. Returns the single matching repo file, or an empty list
        when the include escapes the repo root or names no existing file
        (external header, unresolved path, or a conventional-root layout that
        needs #484's configured include directories). Under-edging is the
        contract: no edge is always preferable to a guessed edge.

        A leading-``/`` spelling (``#include "/usr/local/foo.h"``) is a
        filesystem-absolute path the preprocessor opens from the filesystem
        root, never relative to the importer, so anchoring it at the importer's
        directory (or the repo root) would fabricate an edge; it yields nothing.
        A trailing-``/`` spelling (``#include "util.h/"``) names a directory
        path the preprocessor cannot open as a regular file (POSIX ENOTDIR),
        so matching the file of the same stem would fabricate an edge too.
        """
        if imp.module.startswith("/") or imp.module.endswith("/"):
            return []  # absolute or directory spelling: the preprocessor finds no file
        importer_dir = importer.rsplit("/", 1)[0] if "/" in importer else ""
        target = _normalize(f"{importer_dir}/{imp.module}" if importer_dir else imp.module)
        if target is not None and target in file_set:
            return [target]
        return []


def _normalize(path: str) -> str | None:
    """Collapse ``.``/``..`` segments to a repo-relative path, or ``None``.

    Returns ``None`` when a ``..`` walks above the repo root (the include cannot
    reference an in-repo file, so it must not be anchored at the root)."""
    parts: list[str] = []
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                return None  # walks above the repo root
            parts.pop()
        else:
            parts.append(seg)
    return "/".join(parts)


register(CppResolver(CPP_CONFIG))
register(CppResolver(C_CONFIG))
