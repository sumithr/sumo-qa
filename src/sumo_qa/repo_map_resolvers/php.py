# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
r"""PHP import resolver for the repo-map import-edge layer (#361).

A second resolver in the Approach-C framework the foundation (#354) shipped.
``extract`` reads imports off a tree-sitter parse of PHP source; ``resolve``
ports Understand-Anything's PHP path rules to map each raw import to the
repo-relative file(s) it references.

Two import kinds are recognised, distinguished by :attr:`RawImport.level`
(the field is shared across languages; each language owns its meaning):

- **PSR-4 ``use`` imports** (``level == 0``): ``use App\Models\User;`` names a
  fully-qualified class. It maps to a file via the PSR-4 autoload roots declared
  in ``composer.json`` (a namespace prefix → base directory, e.g. ``App\`` →
  ``src/``), so ``App\Models\User`` resolves to ``src/Models/User.php``. The
  **longest** matching prefix wins (PSR-4). A namespace matching no prefix is
  external/vendor and is dropped. ``use function`` / ``use const`` import a
  symbol, not a class, and are dropped (no class file to map).

- **``require`` / ``include`` imports** (``level == 1``, also the ``_once``
  variants): a filesystem path resolved **relative to the importing file's
  directory** (``require '../helpers.php'``, ``require __DIR__ . '/lib/db.php'``).
  A dynamic argument with no static string literal (``require $path;``) yields
  nothing.

Scan-time activation caveat (deliberately NOT wired here): the
:class:`~sumo_qa.repo_map_resolvers.base.Resolver` ``resolve`` contract passes
only the importer path + ``file_set`` — no repo root, file contents, or
``composer.json``. The PSR-4 namespace roots are therefore injected at
construction (:meth:`PhpResolver.from_composer`) rather than read mid-scan. The
self-registered DEFAULT resolver carries no PSR-4 roots, so at scan time
relative ``require`` / ``include`` edges resolve but PSR-4 ``use`` edges need the
parsed composer config injected. Threading composer-driven construction through
the scan (and teaching the scanner to stamp ``php`` on ``.php`` files) is a
foundation enhancement, out of this slice.
"""

from __future__ import annotations

import posixpath
from collections.abc import Mapping, Sequence

from sumo_qa.repo_map_resolvers.base import LanguageConfig, RawImport, register
from sumo_qa.repo_map_treesitter import TSNode, parse

PHP_CONFIG = LanguageConfig(
    id="php",
    extensions=(".php",),
    barrels=(),
)

# Grammar kinds, pinned to tree-sitter-language-pack's PHP grammar.
_NAMESPACE_USE_DECL = "namespace_use_declaration"  # `use A\B\C;`
_NAMESPACE_USE_CLAUSE = "namespace_use_clause"  # one imported name within a `use`
_QUALIFIED_NAME = "qualified_name"  # `A\B\C` (a namespaced name)
_NAME = "name"  # a single bare identifier
_STRING_CONTENT = "string_content"  # the text inside a string literal
_REQUIRE_EXPRS = frozenset(
    {
        "require_expression",
        "require_once_expression",
        "include_expression",
        "include_once_expression",
    }
)
# `use function` / `use const` carry one of these keyword tokens in the clause.
_SYMBOL_USE_KINDS = frozenset({"function", "const"})
# Lexical scopes whose body makes an import lazy/deferred (→ medium confidence).
_FUNCTION_KINDS = frozenset(
    {"function_definition", "method_declaration", "anonymous_function", "arrow_function"}
)

# RawImport.level encoding for PHP.
_LEVEL_USE = 0  # namespace `use` import; module is the FQN
_LEVEL_REQUIRE = 1  # filesystem require/include import; module is the path literal


class PhpResolver:
    """Approach-C resolver for PHP (ported from Understand-Anything).

    PSR-4 autoload roots (namespace prefix → base dir) are supplied at
    construction; the module-default registered resolver carries none (see the
    scan-time caveat in the module docstring). Build one from a parsed
    ``composer.json`` with :meth:`from_composer`.
    """

    config = PHP_CONFIG

    def __init__(self, psr4: Mapping[str, str | Sequence[str]] | None = None) -> None:
        self._psr4 = _normalise_psr4(psr4 or {})

    @classmethod
    def from_composer(cls, composer: Mapping[str, object]) -> PhpResolver:
        """Build a resolver from a parsed ``composer.json`` mapping.

        Reads the PSR-4 autoload roots from both ``autoload`` and
        ``autoload-dev`` (``psr-4`` blocks: namespace prefix → base dir or list
        of base dirs). A missing/oddly-shaped block contributes no roots.
        """
        psr4: dict[str, str | Sequence[str]] = {}
        for section in ("autoload", "autoload-dev"):
            block = composer.get(section) or {}
            if not isinstance(block, Mapping):  # pragma: no cover -- defensive: malformed composer
                continue
            mapping = block.get("psr-4") or {}
            if not isinstance(mapping, Mapping):  # pragma: no cover -- defensive: malformed psr-4
                continue
            for prefix, dirs in mapping.items():
                if isinstance(dirs, str):
                    psr4[str(prefix)] = dirs
                elif isinstance(dirs, Sequence):
                    psr4[str(prefix)] = [str(d) for d in dirs]
        return cls(psr4)

    def extract(self, src: bytes) -> list[RawImport]:
        """Return the imports in ``src`` as :class:`RawImport` records.

        Walks the parse tree, recording each ``use`` declaration (PSR-4 class
        imports) and each ``require`` / ``include`` expression (relative path
        imports). ``function_local`` is set when the statement is lexically
        inside a function / method body (a lazy import → medium confidence).
        """
        root = parse("php", src)
        raws: list[RawImport] = []
        self._collect(root, function_depth=0, out=raws)
        return raws

    def _collect(self, node: TSNode, *, function_depth: int, out: list[RawImport]) -> None:
        kind = node.kind
        if kind == _NAMESPACE_USE_DECL:
            out.extend(self._use_imports(node))
            return
        if kind in _REQUIRE_EXPRS:
            imp = self._require_import(node, function_depth > 0)
            if imp is not None:
                out.append(imp)
            return
        next_depth = function_depth + 1 if kind in _FUNCTION_KINDS else function_depth
        for child in node.children:
            self._collect(child, function_depth=next_depth, out=out)

    @staticmethod
    def _use_imports(decl: TSNode) -> list[RawImport]:
        """`use A\\B\\C;` (and aliased / unqualified forms) -> one RawImport per
        class clause. ``use function`` / ``use const`` clauses are skipped — a
        symbol import has no class file to map."""
        raws: list[RawImport] = []
        for clause in decl.children:
            if clause.kind != _NAMESPACE_USE_CLAUSE:
                continue
            if any(child.kind in _SYMBOL_USE_KINDS for child in clause.children):
                continue
            fqn = PhpResolver._clause_fqn(clause)
            if fqn:
                raws.append(RawImport(module=fqn, level=_LEVEL_USE, names=(), function_local=False))
        return raws

    @staticmethod
    def _clause_fqn(clause: TSNode) -> str:
        """The fully-qualified name a use-clause imports, leading ``\\`` stripped.

        Prefers the ``qualified_name`` child (``A\\B\\C``); falls back to the
        first bare ``name`` (``use User;``), which precedes any ``as`` alias in
        source order so the imported name — not the local alias — is returned."""
        fallback = ""
        for child in clause.children:
            if child.kind == _QUALIFIED_NAME:
                return child.text.lstrip("\\")
            if child.kind == _NAME and not fallback:
                fallback = child.text
        return fallback.lstrip("\\")

    @staticmethod
    def _require_import(node: TSNode, function_local: bool) -> RawImport | None:
        """A ``require`` / ``include`` expression -> one path RawImport, or None.

        The path is the concatenation of the expression's string literals, so
        ``__DIR__ . '/lib/db.php'`` yields ``/lib/db.php``. A dynamic argument
        with no string literal (``require $path;``) yields None."""
        path = PhpResolver._string_literal(node)
        if not path:
            return None
        return RawImport(module=path, level=_LEVEL_REQUIRE, names=(), function_local=function_local)

    @staticmethod
    def _string_literal(node: TSNode) -> str:
        """The concatenation of every string literal under ``node`` (in order)."""
        return "".join(d.text for d in node.descendants() if d.kind == _STRING_CONTENT)

    def resolve(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        """Map one raw import to the repo-relative file path(s) it references.

        Returns repo-relative paths that exist in ``file_set``; an empty list
        means the import points outside the repo (vendor namespace, missing
        file) or could not be resolved — never an error. PSR-4 ``use`` imports
        (``level == 0``) map via the injected autoload roots; ``require`` /
        ``include`` imports (``level == 1``) anchor to the importer's directory.
        """
        if imp.level == _LEVEL_REQUIRE:
            return self._resolve_require(importer, imp.module, file_set)
        return self._resolve_psr4(imp.module, file_set)

    @staticmethod
    def _resolve_require(importer: str, raw: str, file_set: set[str]) -> list[str]:
        """Resolve a ``require`` / ``include`` path relative to the importer's
        directory. A leading ``/`` (the ``__DIR__ . '/x'`` form) anchors to that
        directory, not the repo root, so it is stripped before joining."""
        importer_dir = posixpath.dirname(importer)
        candidate = posixpath.normpath(posixpath.join(importer_dir, raw.lstrip("/")))
        return [candidate] if candidate in file_set else []

    def _resolve_psr4(self, fqn: str, file_set: set[str]) -> list[str]:
        """Resolve a fully-qualified name via the PSR-4 autoload roots.

        Roots are tried longest-prefix-first (``self._psr4`` is pre-sorted), so
        a more specific namespace wins. The matched prefix is replaced by its
        base directory and the namespace tail becomes a ``.php`` path. Returns
        the first base-dir candidate that exists; no matching prefix (vendor /
        external) returns ``[]``."""
        for prefix, dirs in self._psr4:
            if fqn.startswith(prefix):
                relative = fqn[len(prefix) :].replace("\\", "/") + ".php"
                for base in dirs:
                    candidate = posixpath.normpath(posixpath.join(base, relative))
                    if candidate in file_set:
                        return [candidate]
        return []


def _normalise_psr4(
    psr4: Mapping[str, str | Sequence[str]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Freeze a PSR-4 map into ``(prefix, base-dirs)`` pairs, longest-prefix-first.

    Each prefix is normalised to end with ``\\`` (the PSR-4 separator), each base
    dir has its trailing ``/`` stripped (``.`` / empty → the repo root, ``""``).
    Sorting longest-prefix-first lets :meth:`PhpResolver._resolve_psr4` pick the
    most specific namespace by scanning in order.
    """
    normalised: list[tuple[str, tuple[str, ...]]] = []
    for prefix, value in psr4.items():
        full = prefix if prefix.endswith("\\") else prefix + "\\"
        dirs = (value,) if isinstance(value, str) else tuple(value)
        normalised.append((full, tuple(_normalise_dir(d) for d in dirs)))
    normalised.sort(key=lambda item: len(item[0]), reverse=True)
    return tuple(normalised)


def _normalise_dir(directory: str) -> str:
    """Strip a base dir's trailing ``/``; map ``.`` / empty to the repo root."""
    trimmed = directory.rstrip("/")
    return "" if trimmed in ("", ".") else trimmed


register(PhpResolver())
