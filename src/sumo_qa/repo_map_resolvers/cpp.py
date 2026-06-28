# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""C/C++ include resolver for the repo-map import-edge layer (#359).

An Approach-C resolver in the framework the foundation (#354) shipped. ``extract``
reads ``#include`` directives off a tree-sitter parse of C/C++ source; ``resolve``
ports Understand-Anything's C++ include rules to map each quoted include to the
repo-relative file(s) it references.

Resolution rules (ported from UA):

- **Quoted includes** (``#include "foo.h"``) are resolved first relative to the
  including file's own directory, then against common include roots
  (``include/``, ``src/``). The first candidate base that matches an existing
  file wins, so a header next to the importer beats a same-named header under an
  include root (mirroring the preprocessor's quoted-include search order).
- **Header-extension probing**: an extensionless include (``#include "config"``)
  probes the header extensions ``.h/.hpp/.hh/.hxx``; an include that already
  names an extension is matched exactly and never fuzzy-matched to a different
  extension (a broken include the real preprocessor would also fail to find).
- **System includes** (``#include <vector>``) are angle-bracketed system/library
  headers, not repo files; they are dropped at extraction and never resolved.
- **Repo-root escape**: a ``..`` traversal that walks above the repo root cannot
  reference an in-repo file, so that candidate base is discarded rather than
  anchored at the root (which would fabricate a false edge).

An ``#include`` is a compile-time textual inclusion, never a lazy/deferred
import, so every extracted include is ``function_local=False`` (→ ``high``
confidence downstream). The same resolver is registered under both ``cpp`` and
``c``; the cpp grammar parses C ``#include`` directives identically, so one
implementation serves both language ids.
"""

from __future__ import annotations

from sumo_qa.repo_map_resolvers.base import LanguageConfig, RawImport, register
from sumo_qa.repo_map_treesitter import TSNode, parse

CPP_CONFIG = LanguageConfig(
    id="cpp",
    extensions=(".cpp", ".cc", ".cxx", ".h", ".hpp"),
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

# Header extensions probed for an extensionless include (`#include "config"`).
_HEADER_EXTS = (".h", ".hpp", ".hh", ".hxx")

# Repo-root-anchored roots a quoted include is searched against, after the
# importer's own directory. Order is precedence: the first match wins.
_INCLUDE_ROOTS = ("include", "src")


class CppResolver:
    """Approach-C resolver for C/C++ includes (registered as ``cpp`` and ``c``)."""

    def __init__(self, config: LanguageConfig = CPP_CONFIG) -> None:
        self.config = config

    def extract(self, src: bytes) -> list[RawImport]:
        """Return the quoted ``#include`` directives in ``src`` as RawImports.

        Walks the parse tree for ``preproc_include`` nodes. A quoted include
        (``#include "foo.h"``) yields one :class:`RawImport` whose ``module`` is
        the path inside the quotes; an angle-bracketed system include
        (``#include <vector>``) is dropped. ``level``/``names`` are unused for C++
        (no relative-dot or specifier concept) and ``function_local`` is always
        ``False`` — an ``#include`` is module-level textual inclusion, never lazy.
        """
        root = parse("cpp", src)
        raws: list[RawImport] = []
        for node in root.descendants():
            if node.kind != _PREPROC_INCLUDE:
                continue
            path = self._include_path(node)
            if path:  # empty -> a system include (dropped) or a malformed directive
                raws.append(RawImport(module=path, level=0, names=(), function_local=False))
        return raws

    @staticmethod
    def _include_path(node: TSNode) -> str:
        """The quoted include path of a ``preproc_include`` node, or ''.

        A quoted include exposes a ``string_literal`` child whose
        ``string_content`` is the path without the quotes; a system include
        exposes a ``system_lib_string`` (the ``<...>``) which is dropped (returns
        '' so the caller skips it)."""
        for child in node.children:
            if child.kind == _STRING_LITERAL:
                return CppResolver._string_content(child)
            if child.kind == _SYSTEM_LIB_STRING:
                return ""  # `<...>` system header: not a repo import
        return ""  # pragma: no cover -- defensive: a preproc_include always has a path child

    @staticmethod
    def _string_content(node: TSNode) -> str:
        """The inner text of a ``string_literal`` (the path without quotes)."""
        for child in node.children:
            if child.kind == _STRING_CONTENT:
                return child.text
        return ""  # pragma: no cover -- defensive: a non-empty quoted include has content

    def resolve(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        """Map one quoted include to the repo-relative file path(s) it references.

        Tries each candidate base (the importer's own directory first, then the
        include roots) in precedence order and returns the first base that
        matches an existing file. An empty list means the include points outside
        the repo (system header already dropped at extraction, or an unresolved
        path) — never an error. Results are de-duplicated preserving first-seen
        order; a quoted include normally resolves to exactly one file.
        """
        for base in self._candidate_bases(importer, imp.module):
            hits: list[str] = []
            for cand in self._probe(base):
                if cand in file_set and cand not in hits:
                    hits.append(cand)
            if hits:
                return hits
        return []

    @staticmethod
    def _candidate_bases(importer: str, include: str) -> list[str]:
        """Candidate base paths for an include, in search-precedence order.

        First the path relative to the importer's own directory, then each
        repo-root include root (``include/``, ``src/``). A base that walks above
        the repo root is discarded; duplicates (e.g. an importer already under
        ``include/``) are collapsed so a base is probed once."""
        importer_dir = importer.rsplit("/", 1)[0] if "/" in importer else ""
        bases: list[str] = []
        relative = _normalize(f"{importer_dir}/{include}" if importer_dir else include)
        if relative is not None:
            bases.append(relative)
        for root in _INCLUDE_ROOTS:
            rooted = _normalize(f"{root}/{include}")
            if rooted is not None and rooted not in bases:
                bases.append(rooted)
        return bases

    @staticmethod
    def _probe(base: str) -> list[str]:
        """Candidate file paths for a base.

        An include that already names a file extension is probed exactly; an
        extensionless include also probes each header extension
        (``.h/.hpp/.hh/.hxx``)."""
        candidates = [base]
        last = base.rsplit("/", 1)[-1]
        if "." not in last:  # extensionless include -> probe header extensions
            candidates.extend(base + ext for ext in _HEADER_EXTS)
        return candidates


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
