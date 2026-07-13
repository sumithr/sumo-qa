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
  A dynamic argument yields nothing — the no-literal form (``require $path;``), a
  **mixed** form that concatenates a non-static operand with a literal (``require
  $base . 'helpers.php';``, ``require ROOT . '/x.php';``, ``require
  dirname(__FILE__) . '/x.php';``), and a **ternary** (``require $cond ? 'a.php'
  : 'b.php';``, whose two branches are alternatives, not a concatenation): the
  concrete path depends on runtime state, so ``__DIR__`` is the only operand
  treated as a known static anchor. A **bare absolute** path (leading ``/`` with
  no ``__DIR__`` anchor, ``require '/helpers.php'``) is a filesystem-root path PHP
  resolves OUTSIDE the repo, so it yields nothing too (a ``__DIR__``-anchored
  leading-``/`` path is importer-relative and IS resolved).

Where these edges come from (NOT scan time today): a real ``scan_repo`` emits
ZERO ``.php`` edges of any kind. The foundation scanner does not map ``.php``
files (``repo_map_scanner._LANGUAGE_BY_EXT`` and ``_PROGRAMMING_LANGS`` both omit
``.php`` / ``php``), so no ``php`` node ever reaches the import-edge layer during
a scan. This resolver instead produces edges at the
:func:`~sumo_qa.repo_map_imports.infer_imports_edges` orchestrator layer, given
``php`` nodes supplied directly (see the orchestrator tests). No ``.php`` edge
(relative ``require`` / ``include`` OR PSR-4 ``use``) resolves at scan time.

The :class:`~sumo_qa.repo_map_resolvers.base.Resolver` ``resolve`` contract
passes only the importer path + ``file_set`` (no repo root, file contents, or
``composer.json``), so the PSR-4 namespace roots are injected at construction
(:meth:`PhpResolver.from_composer`) rather than read mid-scan; the
self-registered DEFAULT resolver carries no PSR-4 roots. Full scan-time
activation therefore requires TWO foundation changes, both out of this slice:
(1) the scanner must stamp ``.php`` -> ``php`` (add ``.php`` to
``_LANGUAGE_BY_EXT`` and ``php`` to ``_PROGRAMMING_LANGS``) so ``php`` nodes
exist at all, AND (2) the composer autoload roots must be threaded through the
scan so PSR-4 ``use`` edges (not just relative ``require`` / ``include`` edges)
resolve.

Known limitations (safe: each yields NO edge rather than a wrong one):

- **Grouped ``use``** (``use App\{Models\User, Models\Order};``) yields no edge.
  The grouped clauses nest under a ``namespace_use_group`` node rather than
  appearing as direct ``namespace_use_clause`` children of the declaration, and
  their names are group-relative, so :meth:`_use_imports` (which reads only the
  declaration's direct clause children) records nothing.
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
_CONDITIONAL_EXPR = "conditional_expression"  # a ternary `cond ? a : b`
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
# Magic constants that anchor a require/include path to the importing file's
# directory (`__DIR__ . '/x'`), making a leading-`/` literal importer-relative
# rather than a filesystem-root absolute path.
_DIR_ANCHORS = frozenset({"__DIR__"})
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
        of base dirs). A prefix appearing in BOTH sections keeps the base dirs
        of both, production (``autoload``) dirs first — composer merges the
        sections, so the dev root must not overwrite the production root. A
        missing/oddly-shaped block contributes no roots.
        """
        psr4: dict[str, list[str]] = {}
        for section in ("autoload", "autoload-dev"):
            block = composer.get(section) or {}
            if not isinstance(block, Mapping):  # pragma: no cover -- defensive: malformed composer
                continue
            mapping = block.get("psr-4") or {}
            if not isinstance(mapping, Mapping):  # pragma: no cover -- defensive: malformed psr-4
                continue
            for prefix, dirs in mapping.items():
                if isinstance(dirs, str):
                    psr4.setdefault(str(prefix), []).append(dirs)
                elif isinstance(dirs, Sequence):
                    psr4.setdefault(str(prefix), []).extend(str(d) for d in dirs)
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
        with no string literal (``require $path;``) yields None. A **mixed**
        argument that concatenates a NON-static operand with its literal(s) —
        a variable (``$base . 'helpers.php'``), a user constant
        (``ROOT . '/x.php'``), or a function call
        (``dirname(__FILE__) . '/x.php'``) — also yields None: the concrete path
        depends on runtime state, so resolving it from the literal fragment
        alone would emit a wrong edge (only the ``__DIR__`` magic constant is a
        known static anchor). A **bare absolute** literal (leading ``/`` with no
        ``__DIR__`` anchor, e.g. ``require '/helpers.php'``) is a filesystem-root
        path PHP resolves OUTSIDE the repo, so it yields None (no edge) rather
        than a wrong importer-relative one; a ``__DIR__``-anchored leading-``/``
        path (``__DIR__ . '/x'``) is importer-relative and IS kept."""
        path = PhpResolver._string_literal(node)
        if not path:
            return None
        if PhpResolver._has_dynamic_operand(node):
            return None
        if path.startswith("/") and not PhpResolver._is_dir_anchored(node):
            return None
        return RawImport(module=path, level=_LEVEL_REQUIRE, names=(), function_local=function_local)

    @staticmethod
    def _has_dynamic_operand(node: TSNode) -> bool:
        """True when the require/include argument is not a single static path.

        Two shapes make the concrete path depend on runtime state, so the
        require must be dropped (no edge) rather than resolved from whatever
        string literal(s) it contains:

        - a **non-static operand** concatenated with the literal(s) — a variable
          (``$base . 'x.php'``), a user constant (``ROOT . '/x.php'``), or a
          function call (``dirname(__FILE__) . '/x.php'``). Only the ``__DIR__``
          magic constant is a known static operand; any other identifier is
          detected as a ``name`` descendant outside ``_DIR_ANCHORS`` (a ``$var``
          carries an inner non-anchor ``name``, a call carries its callee
          ``name``, and a bare constant IS such a ``name``).
        - a **ternary** (``cond ? 'a.php' : 'b.php'``): the two branches are
          alternatives, not a concatenation, so joining their literals would
          fabricate a nonsense path (``a.phpb.php``). Any ``conditional_expression``
          descendant drops the require, regardless of the condition's shape (a
          bare ``true``/``1`` condition carries no ``name`` to catch otherwise).
        """
        return any(
            (d.kind == _NAME and d.text not in _DIR_ANCHORS) or d.kind == _CONDITIONAL_EXPR
            for d in node.descendants()
        )

    @staticmethod
    def _is_dir_anchored(node: TSNode) -> bool:
        """True when the require/include expression anchors its path to the
        importing file's directory via a ``__DIR__`` magic constant
        (``__DIR__ . '/x'``); this makes a leading-``/`` literal importer-relative
        (the ``/`` is a separator) rather than a filesystem-root absolute path."""
        return any(d.kind == _NAME and d.text in _DIR_ANCHORS for d in node.descendants())

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
        the most specific namespace wins. The matched prefix is replaced by its
        base directory and the namespace tail becomes a ``.php`` path. The
        LONGEST matching prefix is definitive (strict PSR-4): the first of its
        base dirs whose candidate exists is returned, and if none exists the
        lookup STOPS rather than falling back to a shorter matching prefix. A
        PSR-4 autoloader never falls back that way, so falling through to a
        shorter prefix could emit an autoloader-incorrect edge. The empty
        root-namespace prefix (``""``, composer's ``{"": "src/"}``) matches any
        FQN and maps its full namespace path under the base dir
        (``Acme\\Widget`` -> ``src/Acme/Widget.php``); sorted last, it only
        catches FQNs no more specific prefix claimed. No matching prefix
        (vendor / external) returns ``[]``."""
        for prefix, dirs in self._psr4:
            if fqn.startswith(prefix):
                relative = fqn[len(prefix) :].replace("\\", "/") + ".php"
                for base in dirs:
                    candidate = posixpath.normpath(posixpath.join(base, relative))
                    if candidate in file_set:
                        return [candidate]
                return []  # longest matching prefix is definitive; no shorter-prefix fallback
        return []


def _normalise_psr4(
    psr4: Mapping[str, str | Sequence[str]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Freeze a PSR-4 map into ``(prefix, base-dirs)`` pairs, longest-prefix-first.

    A non-empty prefix is normalised to end with ``\\`` (the PSR-4 separator);
    the **empty** prefix (composer's root-namespace mapping, ``{"": "src/"}``) is
    kept as ``""`` — it must match ANY FQN, and since extracted FQNs have their
    leading ``\\`` stripped, normalising it to ``"\\"`` would make it match none.
    Each base dir has its trailing ``/`` stripped (``.`` / empty → the repo root,
    ``""``). Sorting longest-prefix-first lets
    :meth:`PhpResolver._resolve_psr4` pick the most specific namespace by
    scanning in order (the empty root-namespace prefix sorts last, so it only
    catches FQNs no more specific prefix claimed).
    """
    normalised: list[tuple[str, tuple[str, ...]]] = []
    for prefix, value in psr4.items():
        full = prefix if not prefix or prefix.endswith("\\") else prefix + "\\"
        dirs = (value,) if isinstance(value, str) else tuple(value)
        normalised.append((full, tuple(_normalise_dir(d) for d in dirs)))
    normalised.sort(key=lambda item: len(item[0]), reverse=True)
    return tuple(normalised)


def _normalise_dir(directory: str) -> str:
    """Strip a base dir's trailing ``/``; map ``.`` / empty to the repo root."""
    trimmed = directory.rstrip("/")
    return "" if trimmed in ("", ".") else trimmed


register(PhpResolver())
