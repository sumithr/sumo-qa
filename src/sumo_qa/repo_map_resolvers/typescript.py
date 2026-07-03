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
  config is supplied at construction via :func:`parse_tsconfig`.
- **Bare specifiers** with no alias/baseUrl hit (``react``, ``lodash``,
  ``@scope/pkg``) are external → an empty list, the normal "not ours" outcome.

**Note on alias resolution end-to-end.** The :class:`~sumo_qa.repo_map_resolvers.base.Resolver`
``resolve(importer, imp, file_set)`` contract passes neither the repo root nor
file contents, so the resolver cannot itself read ``tsconfig.json`` during a
scan. The two resolvers self-registered here therefore carry **no** tsconfig and
resolve relative imports + barrels only — the bulk of intra-repo TS/JS edges.
Alias/baseUrl resolution is a fully-implemented, fully-tested capability that
activates once a ``TsConfig`` is supplied; wiring the orchestrator to discover
and thread the project's ``tsconfig.json`` into the resolver is a foundation
follow-up (it would change ``infer_imports_edges`` / the ``Resolver`` protocol,
out of scope for this slice — see #354).

**Known limitations (tsconfig alias path, not yet scan-active).** Because the
alias path is dormant at scan time (no tsconfig is threaded through the
foundation ``resolve()`` contract), its precision refinements belong to the
future tsconfig-threading slice rather than this one:

- Matched ``paths`` patterns are tried in JSON declaration order, not by
  specificity, so a catch-all ``"*"`` declared before a more-specific alias can
  shadow it (TypeScript prefers the longest/most-specific prefix match).
- Only wildcard patterns ending in ``*`` are handled; a pattern with a suffix
  after the ``*`` (e.g. ``"@x/*.js"``) is not matched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sumo_qa.repo_map_resolvers.base import LanguageConfig, RawImport, register
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
    directory (``""`` = repo root, ``None`` = not configured). ``paths`` is the
    ``compilerOptions.paths`` map as an ordered tuple of
    ``(pattern, (target, …))`` pairs, every target already joined through
    ``base_url`` so it is repo-relative. Frozen: a parsed config is shared, not
    owned.
    """

    base_url: str | None = None
    paths: tuple[tuple[str, tuple[str, ...]], ...] = field(default_factory=tuple)


def parse_tsconfig(text: str, *, config_dir: str = "") -> TsConfig:
    """Parse the ``baseUrl`` / ``paths`` of a ``tsconfig.json``.

    ``text`` is the raw file content (JSONC — line/block comments and trailing
    commas are tolerated, as real tsconfig files use them). ``config_dir`` is
    the repo-relative directory holding the tsconfig (``""`` = repo root) so the
    returned paths are repo-relative. ``baseUrl`` defaults to the tsconfig's own
    directory when ``paths`` is present without an explicit ``baseUrl`` (modern
    TS behaviour); targets are joined through that base.
    """
    try:
        data = json.loads(_strip_jsonc(text))
    except json.JSONDecodeError:
        return TsConfig()  # a syntactically broken tsconfig yields no aliases, not a crash
    options = data.get("compilerOptions", {}) if isinstance(data, dict) else {}
    if not isinstance(options, dict):
        options = {}

    raw_base = options.get("baseUrl")
    base_url = _join_repo(config_dir, raw_base) if isinstance(raw_base, str) else None

    # Targets in `paths` are relative to baseUrl; without a baseUrl they're
    # relative to the tsconfig directory (TS >= 4.1).
    target_base = base_url if base_url is not None else config_dir
    raw_paths = options.get("paths", {})
    pairs: list[tuple[str, tuple[str, ...]]] = []
    if isinstance(raw_paths, dict):
        for pattern, targets in raw_paths.items():
            if not isinstance(targets, list):  # a malformed entry is skipped, not fatal
                continue
            # A target escaping the repo root via `..` (`_join_repo` -> None) names
            # no in-repo file, so it is dropped rather than clamped to a fake path.
            joined = tuple(
                j
                for t in targets
                if isinstance(t, str)
                for j in (_join_repo(target_base, t),)
                if j is not None
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


class TypeScriptResolver:
    """Approach-C resolver for TypeScript / JavaScript.

    One class serves both languages; ``config`` (``typescript`` / ``javascript``
    id) and ``grammar`` (``tsx`` parses ``.ts``+``.tsx``; ``javascript`` parses
    ``.js``+``.jsx``) are set at construction. ``tsconfig`` enables alias /
    baseUrl resolution when supplied (the self-registered instances omit it; see
    the module docstring).
    """

    def __init__(
        self,
        config: LanguageConfig = TYPESCRIPT_CONFIG,
        *,
        grammar: str = "tsx",
        tsconfig: TsConfig | None = None,
    ) -> None:
        self.config = config
        self._grammar = grammar
        self._tsconfig = tsconfig

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
        importer's directory; non-relative specifiers go through tsconfig
        alias / baseUrl resolution when a :class:`TsConfig` is configured, else
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
        if self._tsconfig is not None:
            return self._resolve_alias(spec, file_set)
        return []

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

    def _resolve_alias(self, spec: str, file_set: set[str]) -> list[str]:
        """tsconfig ``paths`` then ``baseUrl`` resolution for a non-relative spec.

        For a ``paths`` array TS uses the FIRST target that resolves to a file, so
        probing stops at the first base that yields a hit; only when no pattern
        target resolves does it fall back to ``baseUrl``.
        """
        assert self._tsconfig is not None  # guarded by the caller
        for pattern, targets in self._tsconfig.paths:
            for base in self._match_pattern(pattern, targets, spec):
                hits = self._probe(base, file_set)
                if hits:  # first resolving target wins (TS module resolution)
                    return hits
        base_url = self._tsconfig.base_url
        if base_url is None:
            return []
        root_base = _join_repo(base_url, spec)
        # A spec whose `..` segments escape above the baseUrl root names no file.
        return self._probe(root_base, file_set) if root_base is not None else []

    @staticmethod
    def _match_pattern(pattern: str, targets: tuple[str, ...], spec: str) -> list[str]:
        """Match ``spec`` against one ``paths`` pattern, yielding target bases.

        A wildcard pattern (``@app/*``) captures the tail after the prefix and
        substitutes it into each wildcard target (``src/*`` → ``src/<tail>``); the
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


register(TypeScriptResolver(TYPESCRIPT_CONFIG, grammar="tsx"))
register(TypeScriptResolver(JAVASCRIPT_CONFIG, grammar="javascript"))
