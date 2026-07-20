# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""TypeScript / JavaScript import resolver for the repo-map import-edge layer.

The TS/JS half of the Approach-C framework the foundation (#354) shipped, built
to the same contract as the Python reference resolver. ``extract`` reads import
specifiers off a real tree-sitter parse; ``resolve`` ports Understand-Anything's
TypeScript module-resolution rules to map each specifier to the repo-relative
file(s) it references, purely over the supplied file set.

Extraction covers the five ways TS/JS names a module:

- ES ``import`` — named / default / namespace / side-effect
  (``import './x'``), all carrying the specifier as a ``string`` child;
- re-export ``export … from '…'`` and ``export * from '…'`` (a plain
  ``export const`` / ``export default 'literal'`` names no module);
- TS import-require ``import foo = require('…')`` — the specifier is a
  ``string`` nested in an ``import_require_clause``, not a direct statement child;
- CommonJS ``require('…')`` and dynamic ``import('…')`` (call expressions).

A ``require`` / dynamic ``import`` nested in a function body is tagged
``function_local`` (→ ``medium`` confidence downstream, the lazy/deferred
signal); ES ``import``/``export`` statements are hoisted module-level (→
``high``). The specifier is stored verbatim in :attr:`RawImport.module`;
TypeScript resolution is path-shaped, not dot-level-shaped, so ``level`` is
always ``0`` and ``names`` is always empty.

Resolution rules (ported from UA):

- **Relative specifiers** (``./x``, ``../y``) anchor at the importer's directory
  and probe the TS/JS extension set (``.ts``, ``.tsx``, ``.d.ts``, ``.js``,
  ``.jsx``) plus the ``index.*`` barrels for a directory import. A specifier
  written with a ``.js``/``.jsx`` extension resolves to the exact file when it
  exists, else falls back to its ``.ts``/``.tsx`` source sibling (TS emits
  ``.js``; authors import the source).
- **tsconfig ``paths`` / ``baseUrl`` aliases** map a non-relative specifier to
  one or more repo roots before probing (``@app/*`` → ``src/app/*``;
  ``baseUrl: "src"`` makes a bare ``util`` resolve from ``src/``). The alias
  config comes either from a :class:`TsConfig` injected at construction, or —
  during a real scan — from scan-local preparation (see below). Windows backslash
  separators in a ``baseUrl`` / ``paths`` target are normalized to ``/`` so they
  match the ``/``-joined repo paths. A tsconfig's ``extends`` field is ignored
  (no base-config inheritance): only the config's own ``baseUrl`` / ``paths`` are
  read.
- **Bare specifiers** with no alias/baseUrl hit (``react``, ``lodash``,
  ``@scope/pkg``) are external → an empty list, the normal "not ours" outcome.

**Scan-local tsconfig context (#484 TS/JS slice).** The base
:class:`~sumo_qa.repo_map_resolvers.base.Resolver`
``resolve(importer, imp, file_set)`` contract passes neither the repo root nor
file contents, so a resolver cannot itself read ``tsconfig.json`` mid-``resolve``.
The two resolvers self-registered here therefore carry **no** tsconfig and stay
path-only (relative imports + barrels — the bulk of intra-repo TS/JS edges).
Alias/baseUrl resolution is activated by the preparation lifecycle:
:meth:`TypeScriptResolver.prepare` derives a :class:`_TsConfigIndex` from the
scan's bounded source reads — every ``tsconfig.json`` parsed and keyed by its
own directory — and returns a NEW scan-local resolver carrying it, so the
registered singleton is never mutated with repository data and sequential /
concurrent scans share nothing. A real ``scan_repo`` then resolves each
importer's non-relative specifiers against its NEAREST applicable tsconfig
(:meth:`_nearest_tsconfig`); unrelated workspaces' alias tables are never
flattened into one. A missing config is the silent path-only fallback; an
unreadable or malformed config degrades to path-only with one deterministic
``other`` warning, never aborting the scan.

**Known limitations (alias matcher).** Two precision gaps in the ``paths``
matcher, independent of scan activation:

- Matched ``paths`` patterns are tried in JSON declaration order, not by
  specificity, so a catch-all ``"*"`` declared before a more-specific alias can
  shadow it (TypeScript prefers the longest/most-specific prefix match).
- Only wildcard patterns ending in ``*`` are handled; a pattern with a suffix
  after the ``*`` (e.g. ``"@x/*.js"``) is not matched.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from sumo_qa.repo_map_resolvers.base import LanguageConfig, RawImport, ScanContext, register
from sumo_qa.repo_map_treesitter import TSNode, parse

# TS/JS resolution extension order: TS source, then declarations, then JS
# (including the ESM/CJS `.mjs`/`.cjs` variants the scanner assigns `javascript`).
_PROBE_EXTENSIONS: tuple[str, ...] = (
    ".ts",
    ".tsx",
    ".d.ts",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
)
# Longest-first so a stem strip removes `.d.ts` before `.ts`.
_STRIP_EXTENSIONS: tuple[str, ...] = (".d.ts", ".tsx", ".jsx", ".ts", ".js")
_INDEX_BARRELS: tuple[str, ...] = (
    "index.ts",
    "index.tsx",
    "index.d.ts",
    "index.js",
    "index.jsx",
    "index.mjs",
    "index.cjs",
)

TYPESCRIPT_CONFIG = LanguageConfig(
    id="typescript", extensions=_PROBE_EXTENSIONS, barrels=_INDEX_BARRELS
)
JAVASCRIPT_CONFIG = LanguageConfig(
    id="javascript", extensions=_PROBE_EXTENSIONS, barrels=_INDEX_BARRELS
)

# Grammar kinds, pinned to tree-sitter-language-pack's typescript/tsx/javascript
# grammars (probed against the installed binding).
_IMPORT_STMT = "import_statement"  # `import … from '…'` / `import '…'`
_IMPORT_REQUIRE_CLAUSE = "import_require_clause"  # `import foo = require('…')`
_EXPORT_STMT = "export_statement"  # `export … from '…'` (re-export) or a wrapper
_CALL_EXPR = "call_expression"  # `require('…')` / `import('…')`
_STRING = "string"
_STRING_FRAGMENT = "string_fragment"
_FROM = "from"
_IDENTIFIER = "identifier"
_IMPORT = "import"  # the dynamic-import callee node kind
_ARGUMENTS = "arguments"

# Lexical function scopes — a require / dynamic import inside one is lazy.
_FUNCTION_KINDS = frozenset(
    {
        "function_declaration",
        "function_expression",
        "arrow_function",
        "method_definition",
        "generator_function",
        "generator_function_declaration",
    }
)


@dataclass(frozen=True)
class TsConfig:
    """Module-resolution slice of a ``tsconfig.json``, repo-relative.

    ``base_url`` is ``compilerOptions.baseUrl`` resolved to a repo-relative
    directory (``""`` = repo root, ``None`` = not configured, or an
    absolute/escaping baseUrl whose whole alias config was dropped). ``paths`` is
    the ``compilerOptions.paths`` map as an ordered tuple of
    ``(pattern, (target, …))`` pairs, every target already joined through
    ``base_url`` so it is repo-relative and every out-of-repo (absolute or
    escaping) target already dropped. Frozen: a parsed config is shared, not
    owned.
    """

    base_url: str | None = None
    paths: tuple[tuple[str, tuple[str, ...]], ...] = field(default_factory=tuple)


# Sentinel distinguishing "JSONC that will not decode" from a valid-but-empty
# config. ``parse_tsconfig`` is a pure best-effort parser and silently yields no
# aliases on a syntax error; scan-local preparation needs to TELL the two apart
# to emit a malformed-config warning (see :meth:`TypeScriptResolver.prepare`).
_MALFORMED_TSCONFIG = object()


def _load_tsconfig_json(text: str) -> object:
    """Parse ``text`` as JSONC, or return :data:`_MALFORMED_TSCONFIG` when it will not decode.

    Besides the ordinary ``json.JSONDecodeError`` (a ``ValueError`` subclass), a
    pathological but syntactically valid document can make the decoder raise
    ``RecursionError`` (deeply-nested arrays/objects) or a bare ``ValueError``
    (e.g. an integer exceeding the string-conversion limit). All are treated as a
    malformed config so the scan degrades to path-only, never aborting.
    """
    try:
        return json.loads(_strip_jsonc(text))
    except (RecursionError, ValueError):  # ValueError covers json.JSONDecodeError
        return _MALFORMED_TSCONFIG


def parse_tsconfig(text: str, *, config_dir: str = "") -> TsConfig:
    """Parse the ``baseUrl`` / ``paths`` of a ``tsconfig.json``.

    ``text`` is the raw file content (JSONC — line/block comments and trailing
    commas are tolerated, as real tsconfig files use them). ``config_dir`` is
    the repo-relative directory holding the tsconfig (``""`` = repo root) so the
    returned paths are repo-relative. ``baseUrl`` defaults to the tsconfig's own
    directory when ``paths`` is present without an explicit ``baseUrl`` (modern
    TS behaviour); targets are joined through that base. Windows backslash
    separators in ``baseUrl`` / ``paths`` targets are normalized to ``/`` so they
    match the ``/``-joined repo paths. A syntactically broken tsconfig yields an empty
    :class:`TsConfig` (no aliases), not a crash.

    A tsconfig's ``extends`` field is ignored (no base-config inheritance): only
    the config's OWN ``compilerOptions`` are read.
    """
    data = _load_tsconfig_json(text)
    if data is _MALFORMED_TSCONFIG:
        return TsConfig()
    return _build_tsconfig(data, config_dir)


def _normalize_seps(path: str) -> str:
    r"""Normalize Windows ``\`` path separators to ``/`` for repo-path matching.

    A tsconfig authored on Windows may spell a ``baseUrl`` / ``paths`` target with
    ``\`` (``src\app``); the repo-relative paths the resolver matches are always
    ``/``-joined, so a ``\``-separated value would never match. Converting ``\`` to
    ``/`` lets both spellings resolve identically.
    """
    return path.replace("\\", "/")


def _build_tsconfig(data: object, config_dir: str) -> TsConfig:
    """Build a :class:`TsConfig` from already-decoded JSONC ``data``.

    Split from :func:`parse_tsconfig` so scan-local preparation, which has
    already decoded the file (to detect a malformed config for its warning),
    can reuse the exact ``baseUrl`` / ``paths`` derivation without re-parsing.
    A non-object ``data`` (a valid JSON array, say) carries no compiler options.
    A tsconfig's ``extends`` field is ignored (no base-config inheritance): only
    the config's OWN ``compilerOptions`` are read.
    """
    options = data.get("compilerOptions", {}) if isinstance(data, dict) else {}
    if not isinstance(options, dict):
        options = {}

    raw_base = options.get("baseUrl")
    base_url: str | None = None
    if isinstance(raw_base, str):
        norm_base = _normalize_seps(raw_base)
        # A configured baseUrl that is absolute (`/src`, `C:\src`) or escapes the
        # repo root (`..` -> `_join_repo` None) points OUTSIDE the repo tree; every
        # paths/baseUrl target relative to it escapes too. Re-anchoring to the config
        # directory would fabricate phantom in-repo edges (a false dependency — the
        # worst repo-map failure), so the WHOLE alias config drops to an empty
        # TsConfig. A MISSING baseUrl (not a string) is unaffected: its paths stay
        # relative to the tsconfig directory.
        if _is_out_of_repo_target(config_dir, norm_base):
            return TsConfig()
        base_url = _join_repo(config_dir, norm_base)  # in-repo (not None)

    # Targets in `paths` are relative to the baseUrl when one is configured; without
    # any baseUrl they're relative to the tsconfig directory (TS >= 4.1). Windows
    # `\` separators are normalized to `/` so a target matches the `/`-joined repo
    # paths.
    target_base = base_url if base_url is not None else config_dir
    raw_paths = options.get("paths")
    pairs: list[tuple[str, tuple[str, ...]]] = []
    if isinstance(raw_paths, dict):
        for pattern, targets in raw_paths.items():
            if not isinstance(targets, list):  # a malformed entry is skipped, not fatal
                continue
            # A target that is out-of-repo — absolute (`/src`, `C:/x`) or escaping the
            # root via `..` — names no in-repo file, so it is dropped (not clamped to a
            # fake path); other valid targets in the same array still resolve.
            joined = tuple(
                jp
                for t in targets
                if isinstance(t, str)
                for jp in (_in_repo_target(target_base, _normalize_seps(t)),)
                if jp is not None
            )
            pairs.append((pattern, joined))

    return TsConfig(base_url=base_url, paths=tuple(pairs))


def _strip_jsonc(text: str) -> str:
    """Strip ``//`` / ``/* */`` comments and trailing commas, string-aware.

    Scans char by char so a ``//`` or ``/*`` inside a string literal is left
    intact, then removes a comma that immediately precedes a closing ``}``/``]``
    (ignoring whitespace) — the two ways a ``tsconfig.json`` departs from strict
    JSON.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:  # keep an escaped char verbatim
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return _drop_trailing_commas("".join(out))


def _drop_trailing_commas(text: str) -> str:
    """Remove a comma that only separates from a closing ``}``/``]``."""
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1  # drop the comma; keep the whitespace/closer
                continue
        out.append(ch)
        i += 1
    return "".join(out)


_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _is_absolute_base(raw: str) -> bool:
    """True when a ``baseUrl`` string is a filesystem-absolute path.

    A POSIX-absolute (``/src``), UNC/root-relative (``\\srv``), or Windows
    drive-absolute (``C:\\src`` / ``C:/src`` — a letter, ``:``, then a separator)
    ``baseUrl`` names a location OUTSIDE the repo tree. :func:`_join_repo` would
    silently strip the leading separator (``/src`` → ``src``) or fold the drive
    into a repo-relative segment (``C:/src`` → ``C:/src``), re-anchoring it
    repo-relative, so the caller must treat it like an escaping base and drop the
    alias config rather than fabricate a phantom in-repo edge. ``raw`` is the
    separator-normalized value, so both the backslash and forward-slash drive
    spellings arrive as ``C:/…`` here; the pattern matches either form defensively.
    """
    return raw.startswith(("/", "\\")) or _WINDOWS_DRIVE_RE.match(raw) is not None


def _join_repo(base: str, rel: str) -> str | None:
    """Join ``rel`` onto repo-relative ``base``, collapsing ``.`` / ``..``.

    Returns ``None`` when a ``..`` segment walks above the repo root: a target
    that escapes the project names no in-repo file, so it must yield no edge
    (mirrors :meth:`TypeScriptResolver._anchor` for relative specifiers). A ``*``
    glob segment is preserved (``_join_repo("src", "app/*")`` → ``"src/app/*"``);
    ``_join_repo("src", ".")`` → ``"src"``.
    """
    parts = [p for p in base.split("/") if p] if base else []
    for seg in rel.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                return None  # escaped above the repo root
            parts.pop()
        else:
            parts.append(seg)
    return "/".join(parts)


def _in_repo_target(base: str, rel: str) -> str | None:
    r"""Repo-relative join of an alias target / baseUrl ``rel`` onto ``base``, or
    ``None`` when ``rel`` names a location OUTSIDE the repo tree.

    The SINGLE choke point for the "absolute or escaping ⇒ no edge" rule, applied
    at every alias-resolution site (a config's own ``baseUrl``, each individual
    ``paths`` target, and the ``baseUrl`` fallback for a non-relative specifier).
    ``rel`` is out-of-repo when it is:

    - ABSOLUTE — a leading ``/`` or ``\``, or a Windows drive ``C:/`` / ``C:\``
      (:func:`_is_absolute_base`): ``_join_repo`` would silently strip the leading
      separator (``/src`` → ``src``) or fold the drive into a repo-relative segment,
      re-anchoring it repo-relative into a phantom in-repo path; or
    - ESCAPING — its ``..`` segments climb above the repo root, so ``_join_repo``
      returns ``None``.

    Either way it names no in-repo file and must yield no edge (re-anchoring it
    repo-relative would fabricate a false dependency, the worst repo-map failure).
    """
    if _is_absolute_base(rel):
        return None
    return _join_repo(base, rel)  # None here means the `..` escaped the repo root


def _is_out_of_repo_target(base: str, rel: str) -> bool:
    r"""Predicate face of :func:`_in_repo_target`: ``True`` when ``rel`` is absolute
    or escapes the repo root (relative to repo-relative ``base``), so it must emit
    no alias edge. Used where only the yes/no is needed (dropping a config's own
    ``baseUrl``); :func:`_in_repo_target` is used where the joined value is needed.
    """
    return _in_repo_target(base, rel) is None


# tsconfig discovery + degradation for the scan-local alias context (#484).
_TSCONFIG_NAME = "tsconfig.json"
_MALFORMED_TSCONFIG_MESSAGE = (
    "malformed tsconfig.json ignored by the typescript import resolver; "
    "paths/baseUrl aliases fall back to path-only resolution"
)
_UNREADABLE_TSCONFIG_MESSAGE = (
    "unreadable tsconfig.json ignored by the typescript import resolver; "
    "paths/baseUrl aliases fall back to path-only resolution"
)


@dataclass(frozen=True)
class _TsConfigIndex:
    """Scan-local tsconfig context for one repository scan (#484 TS/JS slice).

    ``configs_by_dir`` maps each repo-relative directory that holds a usable
    ``tsconfig.json`` to its parsed :class:`TsConfig` (alias targets already
    joined repo-relative through that directory). Built by
    :meth:`TypeScriptResolver.prepare` from the scan's bounded source reads and
    carried ONLY by the scan-local resolver instance — never attached to the
    registered singleton — so sequential and concurrent scans share nothing.
    Each importer resolves against its NEAREST entry
    (:meth:`TypeScriptResolver._nearest_tsconfig`), so unrelated workspaces'
    alias tables are never flattened into one.
    """

    configs_by_dir: Mapping[str, TsConfig]


class TypeScriptResolver:
    """Approach-C resolver for TypeScript / JavaScript.

    One class serves both languages; ``config`` (``typescript`` / ``javascript``
    id) and ``grammar`` (``tsx`` parses ``.ts``+``.tsx``; ``javascript`` parses
    ``.js``+``.jsx``) are set at construction. Alias / baseUrl resolution is
    driven by tsconfig context, supplied one of two ways: a single ``tsconfig``
    injected at construction (the #481 unit contract), or — during a real scan —
    a scan-local ``index`` of per-directory configs derived by :meth:`prepare`,
    selecting each importer's NEAREST tsconfig. The self-registered instances
    carry neither and resolve relative imports + barrels only (see the module
    docstring).
    """

    def __init__(
        self,
        config: LanguageConfig = TYPESCRIPT_CONFIG,
        *,
        grammar: str = "tsx",
        tsconfig: TsConfig | None = None,
        index: _TsConfigIndex | None = None,
    ) -> None:
        self.config = config
        self._grammar = grammar
        self._tsconfig = tsconfig
        self._index = index

    # ---------- extract ----------

    def extract(self, src: bytes) -> list[RawImport]:
        """Return the module specifiers in ``src`` as :class:`RawImport` records.

        Walks the parse tree, recording each ES ``import`` / re-``export … from``
        statement and each ``require('…')`` / dynamic ``import('…')`` call.
        ``function_local`` is set when the call sits inside a function body.
        """
        root = parse(self._grammar, src)
        out: list[RawImport] = []
        self._collect(root, function_depth=0, out=out)
        return out

    def _collect(self, node: TSNode, *, function_depth: int, out: list[RawImport]) -> None:
        kind = node.kind
        if kind == _IMPORT_STMT:
            spec = self._statement_specifier(node)
            if spec is not None:
                out.append(self._raw(spec, function_depth))
            return  # an import statement holds no nested imports
        if kind == _EXPORT_STMT:
            spec = self._statement_specifier(node)
            if spec is not None:
                out.append(self._raw(spec, function_depth))
            # fall through: `export const f = () => require('…')` nests a call
        elif kind == _CALL_EXPR:
            spec = self._call_specifier(node)
            if spec is not None:
                out.append(self._raw(spec, function_depth))
            # fall through: arguments may nest further calls
        next_depth = function_depth + 1 if kind in _FUNCTION_KINDS else function_depth
        for child in node.children:
            self._collect(child, function_depth=next_depth, out=out)

    @staticmethod
    def _raw(spec: str, function_depth: int) -> RawImport:
        return RawImport(module=spec, level=0, names=(), function_local=function_depth > 0)

    def _statement_specifier(self, node: TSNode) -> str | None:
        """The module string of an ``import`` / re-export statement, or ``None``.

        An ``import`` statement names its module via a ``string`` child (named /
        default / namespace / side-effect all carry it directly) OR — for the TS
        import-require form ``import foo = require('…')`` — via a ``string``
        nested one level down in an ``import_require_clause`` child, which the
        real grammar does not expose as a direct statement child. An ``export``
        statement names a module only when it is a re-export (has a ``from``
        keyword); a plain ``export const`` / ``export default 'literal'`` does
        not, so its ``string`` (if any) must not be mistaken for a module.
        """
        has_from = False
        fragment: str | None = None
        for child in node.children:
            if child.kind == _FROM:
                has_from = True
            elif child.kind == _STRING and fragment is None:
                fragment = self._string_text(child)
            elif child.kind == _IMPORT_REQUIRE_CLAUSE and fragment is None:
                fragment = self._require_clause_specifier(child)
        if node.kind == _IMPORT_STMT:
            return fragment
        return fragment if has_from else None

    def _require_clause_specifier(self, clause: TSNode) -> str | None:
        """The module string of an ``import_require_clause``, or ``None``.

        ``import foo = require('./foo')`` parses the specifier as a ``string``
        nested inside the ``import_require_clause`` (alongside the bound
        ``identifier`` and the ``require`` keyword). The grammar only forms this
        clause when the require argument is a string literal — a computed
        ``require(<expr>)`` parses to an ``ERROR`` node instead, never an
        ``import_require_clause`` — so a clause without a ``string`` child is
        unreachable via a real parse.
        """
        for child in clause.children:
            if child.kind == _STRING:
                return self._string_text(child)
        return None  # pragma: no cover -- defensive: an import_require_clause always carries a string literal

    def _call_specifier(self, node: TSNode) -> str | None:
        """The string argument of a ``require('…')`` / ``import('…')`` call.

        Returns ``None`` for any other call, or when the argument is not a plain
        string literal (a computed ``require(name)`` / ``import(expr)`` cannot be
        resolved statically).
        """
        children = list(node.children)
        if not children:  # pragma: no cover -- defensive: a call_expression always has a callee
            return None
        callee = children[0]
        is_require = callee.kind == _IDENTIFIER and callee.text == "require"
        is_dynamic_import = callee.kind == _IMPORT
        if not (is_require or is_dynamic_import):
            return None
        for child in children[1:]:
            if child.kind == _ARGUMENTS:
                for arg in child.children:
                    if arg.kind == _STRING:
                        return self._string_text(arg)
        return None

    @staticmethod
    def _string_text(node: TSNode) -> str:
        """The unquoted text of a ``string`` node (``''`` for an empty literal)."""
        for child in node.children:
            if child.kind == _STRING_FRAGMENT:
                return child.text
        return ""

    # ---------- resolve ----------

    def resolve(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        """Map one specifier to the repo-relative file path(s) it references.

        Relative specifiers (``./``, ``../``, bare ``.`` / ``..``) anchor at the
        importer's directory; non-relative specifiers go through the governing
        tsconfig's alias / baseUrl resolution (the importer's nearest scan-local
        config, or a single injected one; see :meth:`_applicable_tsconfig`), else
        they are external (empty list). Returns paths that exist in ``file_set``,
        de-duplicated preserving first-seen order; an empty list is the normal
        "external / not ours" outcome, never an error.
        """
        spec = imp.module
        if not spec:
            return []
        if spec in (".", "..") or spec.startswith("./") or spec.startswith("../"):
            importer_dir = importer.rsplit("/", 1)[0] if "/" in importer else ""
            base = self._anchor(importer_dir, spec)
            if base is None:
                return []  # walked past the repo root
            return self._probe(base, file_set)
        tsconfig = self._applicable_tsconfig(importer)
        if tsconfig is not None:
            return self._resolve_alias(spec, tsconfig, file_set)
        return []

    def _applicable_tsconfig(self, importer: str) -> TsConfig | None:
        """The tsconfig governing ``importer``'s non-relative specifiers.

        During a scan the resolver carries a per-directory ``index`` and picks
        the importer's NEAREST config; the #481 unit contract injects a single
        ``tsconfig`` used for every importer; the registered path-only singleton
        carries neither and returns ``None`` (a non-relative specifier is then
        external — the normal "not ours" drop).
        """
        if self._index is not None:
            return self._nearest_tsconfig(importer)
        return self._tsconfig

    def _nearest_tsconfig(self, importer: str) -> TsConfig | None:
        """The scan-local :class:`TsConfig` of ``importer``'s nearest ancestor
        directory that holds a usable ``tsconfig.json``; ``None`` when none
        governs it (the silent path-only fallback).

        Walks the importer's own directory up to the repo root, deepest first,
        so a nested workspace's tsconfig wins over an outer one — and a sibling
        workspace's config, on no ancestor path, is never consulted. That
        nearest-only walk is what keeps unrelated workspaces' alias tables from
        flattening together (#484).
        """
        assert self._index is not None  # guarded by _applicable_tsconfig
        dirs = importer.split("/")[:-1]  # drop the filename
        for i in range(len(dirs), -1, -1):
            tsconfig = self._index.configs_by_dir.get("/".join(dirs[:i]))
            if tsconfig is not None:
                return tsconfig
        return None

    @staticmethod
    def _anchor(importer_dir: str, spec: str) -> str | None:
        """Resolve a relative ``spec`` against ``importer_dir`` to a repo path.

        Returns ``None`` when the ``..`` segments walk above the repo root (which
        would otherwise fabricate an edge to a root-level file).
        """
        parts = [p for p in importer_dir.split("/") if p] if importer_dir else []
        for seg in spec.split("/"):
            if seg in ("", "."):
                continue
            if seg == "..":
                if not parts:
                    return None
                parts.pop()
            else:
                parts.append(seg)
        return "/".join(parts)

    def _resolve_alias(self, spec: str, tsconfig: TsConfig, file_set: set[str]) -> list[str]:
        """tsconfig ``paths`` then ``baseUrl`` resolution for a non-relative spec.

        ``tsconfig`` is the config governing this importer (see
        :meth:`_applicable_tsconfig`). For a ``paths`` array TS uses the FIRST
        target that resolves to a file, so probing stops at the first base that
        yields a hit; only when no pattern target resolves does it fall back to
        ``baseUrl``.
        """
        for pattern, targets in tsconfig.paths:
            for base in self._match_pattern(pattern, targets, spec):
                hits = self._probe(base, file_set)
                if hits:  # first resolving target wins (TS module resolution)
                    return hits
        base_url = tsconfig.base_url
        # No baseUrl root to fall back to: None means it was never configured (or its
        # whole alias config was dropped as out-of-repo).
        if base_url is None:
            return []
        # A spec that is itself absolute, or whose `..` segments escape above the
        # baseUrl root, names no in-repo file (`_in_repo_target` -> None).
        root_base = _in_repo_target(base_url, spec)
        return self._probe(root_base, file_set) if root_base is not None else []

    @staticmethod
    def _match_pattern(pattern: str, targets: tuple[str, ...], spec: str) -> list[str]:
        """Match ``spec`` against one ``paths`` pattern, yielding target bases.

        A wildcard pattern (``@app/*``) captures the tail after the prefix and
        substitutes it into each wildcard target (``src/*`` → ``src/<tail>``); a
        root-level wildcard target (``"*"``/``"./*"`` under a repo-root baseUrl,
        normalized to bare ``"*"``) substitutes the tail at the repo root; the
        bare catch-all ``*`` captures the whole specifier (``"*": ["src/*"]``
        maps ``foo`` → ``src/foo``); an exact pattern matches the whole specifier
        and uses each target verbatim.
        """
        if pattern.endswith("*"):
            prefix = pattern[:-1]  # "@app/*" -> "@app/"; bare "*" -> ""
            if not spec.startswith(prefix):
                return []
            tail = spec[len(prefix) :]
            bases: list[str] = []
            for target in targets:
                if target.endswith("/*"):
                    bases.append(target[:-1] + tail)  # "src/*" -> "src/" + tail
                elif target == "*":  # root wildcard: repo root + tail
                    bases.append(tail)
                else:
                    bases.append(target)
            return bases
        if spec == pattern:
            return [t[:-2] if t.endswith("/*") else t for t in targets]
        return []

    def _probe(self, base: str, file_set: set[str]) -> list[str]:
        """Module base → candidate file paths that exist in ``file_set``.

        Probes ``base`` verbatim first (a specifier written with an extension):
        when that exact file exists it IS the target and resolution stops there,
        so an explicit ``./util.js`` maps to ``util.js`` alone even when a
        sibling ``util.ts`` exists — the ``.js`` → ``.ts``/``.tsx`` rewrite is a
        fallback for a bare-emit import whose ``.js`` file is absent, not a
        second edge. Only when the verbatim probe misses does it try ``base`` +
        TS/JS extensions against the module stem, stopping at the FIRST that
        resolves — TS picks a single module by ``_PROBE_EXTENSIONS`` precedence,
        so when both ``util.ts`` and ``util.js`` exist ``./util`` emits only the
        higher-precedence ``util.ts``, not both. Only when nothing has matched (a
        same-named file shadows the directory) are the ``index.*`` barrels tried
        for a directory import, again stopping at the FIRST existing barrel by
        ``_INDEX_BARRELS`` precedence, so ``./pkg`` with both ``pkg/index.ts`` and
        ``pkg/index.js`` present emits only ``pkg/index.ts``. First-seen order is
        preserved for determinism.
        """
        out: list[str] = []

        def add(path: str) -> bool:
            if path and path in file_set and path not in out:
                out.append(path)
                return True
            return False

        if add(base):
            # An explicit-extension specifier that names an existing file resolves
            # to exactly that file; no `.js` -> `.ts`/`.tsx` rewrite is applied.
            return out
        stem = base
        for ext in _STRIP_EXTENSIONS:
            if base.endswith(ext):
                stem = base[: -len(ext)]
                break
        if stem:
            for ext in _PROBE_EXTENSIONS:
                if add(f"{stem}{ext}"):
                    break  # TS resolves to the first extension by precedence
        if not out:  # a same-named file shadows a directory's index barrel (TS)
            for barrel in self.config.barrels:
                if add(f"{stem}/{barrel}" if stem else barrel):
                    break  # TS resolves to the first barrel by precedence
        return out

    # ---------- scan-local preparation (#484 foundation, TS/JS slice) ----------

    def prepare(self, context: ScanContext) -> TypeScriptResolver:
        """Derive a scan-local resolver carrying per-config tsconfig context (#484).

        Discovers every ``tsconfig.json`` in the scan's file set and reads each
        through the context's bounded, memoized reads (no unbounded second
        repository read), parsing its ``paths`` / ``baseUrl`` with #481's parser
        keyed by its OWN directory. The returned resolver therefore selects each
        importer's NEAREST config (:meth:`_nearest_tsconfig`) instead of a
        flattened union of every workspace's aliases. A NEW instance is returned
        so the registered singleton never carries repository data; everything
        derived here dies with the scan. A tsconfig's ``extends`` field is ignored
        (no base-config inheritance): only its own ``baseUrl`` / ``paths`` are read.

        Reads no source and needs no tree-sitter (only JSON), so it is safe to
        call regardless of the ``[treesitter]`` extra. A missing config (no file)
        is the silent path-only fallback (no entry, no warning); a present-but-
        broken config (unreadable / non-UTF-8 / malformed, including a
        pathologically deep JSON that overflows the decoder) registers an EMPTY
        :class:`TsConfig` for its own directory so it SHADOWS any ancestor's
        aliases (:meth:`_nearest_tsconfig` stops there -> path-only, never an
        ancestor-alias leak), with one deterministic ``other`` warning each
        (deduped per path by the context), never aborting the scan.
        """
        configs_by_dir: dict[str, TsConfig] = {}
        tsconfigs = sorted(
            f for f in context.files if f == _TSCONFIG_NAME or f.endswith(f"/{_TSCONFIG_NAME}")
        )
        for path in tsconfigs:
            directory = path.rsplit("/", 1)[0] if "/" in path else ""
            # A present-but-broken config registers an EMPTY TsConfig so its own
            # directory still SHADOWS any ancestor tsconfig (`_nearest_tsconfig`
            # stops at this empty entry -> path-only for the workspace, no ancestor
            # alias leak). Mirrors the PHP adapter's empty-root shadowing. Only a
            # MISSING config (never in this loop) keeps the silent no-entry fallback.
            raw = context.read(path)
            if raw is None:
                context.warn_config(_UNREADABLE_TSCONFIG_MESSAGE, path)
                configs_by_dir[directory] = TsConfig()
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                context.warn_config(_MALFORMED_TSCONFIG_MESSAGE, path)
                configs_by_dir[directory] = TsConfig()
                continue
            data = _load_tsconfig_json(text)
            if data is _MALFORMED_TSCONFIG:
                context.warn_config(_MALFORMED_TSCONFIG_MESSAGE, path)
                configs_by_dir[directory] = TsConfig()
                continue
            configs_by_dir[directory] = _build_tsconfig(data, directory)
        return TypeScriptResolver(
            self.config,
            grammar=self._grammar,
            index=_TsConfigIndex(configs_by_dir=configs_by_dir),
        )


register(TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx"))
register(TypeScriptResolver(JAVASCRIPT_CONFIG, grammar="javascript"))
