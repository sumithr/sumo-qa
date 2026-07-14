# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Rust import resolver for the repo-map import-edge layer (#358).

A follow-on resolver in the Approach-C framework the foundation (#354) shipped.
``extract`` reads ``mod`` / ``use`` items off a tree-sitter parse of Rust
source; ``resolve`` ports Understand-Anything's Rust rules to map each one to
the repo-relative file(s) it references by walking the crate module tree.

Resolution rules (ported from UA):

- **``mod name;``** declares a child module of the importing file's module. It
  resolves against the importer's *module directory* to ``<dir>/name.rs`` or
  ``<dir>/name/mod.rs``. An inline ``mod name { … }`` defines the module in
  place and maps to no file, so it is not emitted; its body is still walked for
  nested ``use`` items **and** its name is carried as a path prefix so a nested
  file-module ``mod outer { mod child; }`` resolves to ``<dir>/outer/child.rs``.
- **The module directory of a file** is where its child modules live: a crate
  root (``lib.rs`` / ``main.rs``) or a ``mod.rs`` owns its *own* directory; any
  other ``foo.rs`` owns the sibling directory ``foo/`` (so ``src/foo.rs``'s
  children live in ``src/foo/``). A single-file Cargo *target* root (a ``.rs``
  file directly under ``tests/`` / ``examples/`` / ``benches/`` or ``src/bin/``)
  is a crate root too, so it likewise owns its *own containing* directory: rustc
  reads a crate root's ``mod`` files from beside the root file, so ``mod helper;``
  in ``tests/api.rs`` resolves to ``tests/helper.rs`` (not ``tests/api/helper.rs``).
- **``use`` paths** are anchored by their leading segment:
  - ``crate::`` anchors at the crate root's directory — the nearest ancestor of
    the importer holding a ``lib.rs`` / ``main.rs``, or, for a Cargo bin/test/
    example/bench target (a file under ``src/bin/`` / ``tests/`` / ``examples/``
    / ``benches/``), that target's own root. ``crate::`` names the CALLER's OWN
    crate, so when the importer is itself a crate-root file the path resolves to
    THAT root: ``crate::`` from ``src/main.rs`` -> ``src/main.rs`` and from
    ``src/lib.rs`` -> ``src/lib.rs``, even in a mixed lib+bin package where both
    roots share ``src/``. A ``crate::`` from a *shared* ``src/`` module in a
    lib+bin package depends on which crate compiles that module: WITH scan-local
    context (below) provable membership picks the owning root and ambiguous
    membership offers no root at all; the bare path-only resolver (no context)
    keeps the library root (``src/lib.rs``) as its documented default;
  - ``self::`` anchors at the importer's own module directory — deepened by any
    enclosing inline ``mod`` names when the ``use`` is nested in an inline module;
  - ``super::`` walks one parent module up per ``super`` token (each ``super``
    first climbs out of an enclosing inline ``mod`` before leaving the file);
  - a BARE leading segment that the importer's own scope PROVABLY declares as a
    module (``mod foo;`` / ``mod foo { }`` in the same frame) is a Rust-2018+
    uniform path into the current scope: ``extract`` rewrites it self-anchored
    and marks it ``_LEVEL_BARE``, and ``resolve`` honours it only when the
    scan-local context proves the importer's crate uses a uniform-paths edition
    (2018/2021/2024 from the nearest ``Cargo.toml``) — 2015 bare paths are
    crate-root-relative, so without that proof the path is dropped (#358);
  - any other leading segment (``std``, an external crate name) is an external
    path and is **dropped** — modern-edition ``use`` reaches in-crate modules
    only through ``crate`` / ``self`` / ``super`` or a proven current-scope head.
- **Each path's leaf** may name a submodule *or* an item inside its parent
  module, so both are probed (mirroring the Python resolver's module +
  specifier-submodule duality): ``use crate::foo::Thing`` probes ``foo/Thing``
  as a submodule **and** ``foo`` as the module that holds the item ``Thing``.
- **Grouped / glob / aliased uses** decompose the same way:
  ``use a::b::{c, d}`` probes the module ``a::b`` and each of ``a::b::c`` /
  ``a::b::d``; ``use a::b::*`` probes the module ``a::b``; ``use a::b::c as d``
  drops the alias and probes the path ``a::b::c``. A group is expanded fully:
  a **nested** group member (``use a::{b::{c}}``) recurses under its own
  extended prefix, and an **aliased** member (``use a::{d as e}``) resolves its
  pre-``as`` path ``a::d`` — so every reached module is emitted, not just the
  direct identifier members.

A node is tagged ``function_local`` (→ ``medium`` confidence downstream) when
its ``mod`` / ``use`` item sits inside a ``function_item`` body; module-level
items are not (→ ``high``).

**Scan-local crate context (#484 Rust slice).** ``prepare(context)`` derives a
:class:`_CrateIndex` from the scan's bounded source reads and returns a NEW
resolver instance carrying it — the registered singleton stays path-only and
is never mutated with repository data, so scans share nothing. The index adds
three provable capabilities, each under-edging instead of guessing:

- per-file INLINE module declarations, so a use path whose tail lives inline in
  another file (``use crate::cfg::Item`` with ``mod cfg { … }`` in ``lib.rs``)
  resolves to the hosting file;
- crate membership from walking ``mod`` declarations out of every crate root,
  so a mixed lib+bin root-module probe resolves to the PROVABLE owning root and
  an ambiguous shared module (declared by both roots) gets no root edge at all;
- per-package edition verdicts from ``Cargo.toml`` (workspace-inherited
  editions included), gating bare current-scope resolution. A missing manifest
  is the normal path-only fallback; an unreadable/malformed manifest degrades
  the same way plus one deterministic ``other`` warning per affected file.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass

if sys.version_info >= (3, 11):  # pragma: no cover -- version-gated import: only one
    import tomllib  # branch runs per interpreter (same pattern as the scanner)
else:  # pragma: no cover -- 3.10 backport path
    import tomli as tomllib

from sumo_qa.repo_map_resolvers.base import LanguageConfig, RawImport, ScanContext, register
from sumo_qa.repo_map_treesitter import TSNode, parse

RUST_CONFIG = LanguageConfig(
    id="rust",
    extensions=(".rs",),
    # Rust's "barrel" is mod.rs, but it is never a directory-import target the
    # way __init__.py / index.ts are (a directory is reached as <dir>/mod.rs by
    # the module-file conventions, not by a bare directory name), so the
    # generic barrel slot stays empty and the .rs conventions live in resolve.
    barrels=(),
)

# Grammar kinds, pinned to tree-sitter-language-pack's Rust grammar (probed
# against the installed binding; the resolver's real-tree-sitter tests
# re-assert them so a grammar rename fails loudly rather than silently emitting
# nothing).
_MOD_ITEM = "mod_item"  # `mod foo;` / `mod foo { … }`
_USE_DECLARATION = "use_declaration"  # `use a::b::c;`
_FUNCTION_ITEM = "function_item"  # a `fn` body -> function-local
_DECLARATION_LIST = "declaration_list"  # the `{ … }` of an inline `mod foo { }`
_IDENTIFIER = "identifier"
_SCOPED_IDENTIFIER = "scoped_identifier"  # `a::b::c`
_SCOPED_USE_LIST = "scoped_use_list"  # `a::b::{c, d}`
_USE_LIST = "use_list"  # the `{c, d}` group
_USE_WILDCARD = "use_wildcard"  # `a::b::*`
_USE_AS_CLAUSE = "use_as_clause"  # `a::b::c as d`
# The path-head keyword kinds (each is its own leaf node, not an identifier).
_PATH_SEGMENT_KINDS = frozenset({_IDENTIFIER, "crate", "self", "super"})
# The keyword SEGMENT VALUES a use path may be anchored by; any other head is
# either a proven current-scope module (-> _LEVEL_BARE) or external (#358).
_PATH_HEAD_KEYWORDS = frozenset({"crate", "self", "super"})
# The node kinds that can head a `use` tree's path child: a multi-segment
# `scoped_identifier` (`crate::foo`) OR a single leaf segment. A BARE head
# keyword (`use crate::{a, b}`, `use crate::*`) emits the head as its own
# `crate` / `self` / `super` leaf with no wrapping `scoped_identifier`, so those
# leaf kinds must be accepted here too or the path reads as empty (#358).
_PATH_HEAD_KINDS = _PATH_SEGMENT_KINDS | {_SCOPED_IDENTIFIER}

# Rust source file suffixes that name a *module file*, by role.
_RS = ".rs"
_MOD_FILE = "mod.rs"
_CRATE_ROOTS = ("lib.rs", "main.rs")
# Stems whose file owns its OWN directory as its module directory (rather than a
# sibling directory named after the stem): a ``mod.rs`` always does; a ``lib.rs``
# / ``main.rs`` does ONLY at the crate's actual root — a same-named file nested
# deeper (a module reached via ``mod main;``) is a plain module that owns its
# sibling ``main/`` dir, so those stems are guarded by ``_is_crate_root`` (#358).
_MOD_STEM = "mod"
_CRATE_ROOT_STEMS = frozenset({"lib", "main"})
# Cargo package-root directories whose immediate ``.rs`` children are each their
# OWN crate root (an integration test / example / benchmark target). ``src/bin``
# is the binary-target analogue, handled separately since it lives UNDER ``src``.
_TARGET_ROOT_DIRS = frozenset({"tests", "examples", "benches"})
_SRC_DIR = "src"
_BIN_DIR = "bin"

# RawImport.level is reused as a Rust item-kind flag (the field is the
# foundation's, shared across languages): 0 = a `use` path, 1 = a `mod`
# declaration (resolved as a direct child of the importer, never an item),
# 2 = a bare use path PROVEN (by extraction) to name a current-scope module,
# already rewritten self-anchored, resolvable only with scan-local edition
# context (#358).
_LEVEL_USE = 0
_LEVEL_MOD = 1
_LEVEL_BARE = 2

# Cargo manifest handling for the scan-local edition verdicts (#484).
_CARGO_MANIFEST = "Cargo.toml"
# Editions whose `use` paths may start at the current scope (uniform paths).
# 2015 is deliberately absent: its bare paths are crate-root-relative, and a
# manifest without an edition key defaults to 2015, so both stay conservative.
_UNIFORM_PATH_EDITIONS = frozenset({"2018", "2021", "2024"})
_MALFORMED_MANIFEST_MESSAGE = (
    "malformed Cargo.toml ignored by the rust import resolver; "
    "bare current-scope imports fall back to path-only resolution"
)
_UNREADABLE_MANIFEST_MESSAGE = (
    "unreadable Cargo.toml ignored by the rust import resolver; "
    "bare current-scope imports fall back to path-only resolution"
)


@dataclass(frozen=True)
class _CrateIndex:
    """Scan-local crate/target context for one repository scan (#484).

    Built by :meth:`RustResolver.prepare` from the scan's bounded source
    reads, carried only by the scan-local resolver instance, and discarded
    with the scan — never attached to the registered singleton.

    - ``inline_by_file`` — for each file, the module paths (relative to the
      file's own module, nesting included) declared INLINE (``mod x { … }``),
      so a use path reaching into another file's inline module resolves to the
      hosting file.
    - ``sole_owner_by_file`` — files whose crate membership is PROVABLE: the
      file is reachable through ``mod`` declarations from exactly one crate
      root. Shared modules reachable from several roots, and unreachable
      files, are absent — their membership must not be guessed.
    - ``uniform_paths_by_dir`` — for each directory holding a ``Cargo.toml``,
      whether that package's edition provably enables uniform paths (bare
      current-scope ``use``). Unreadable/malformed manifests are ``False``.
    """

    inline_by_file: Mapping[str, frozenset[tuple[str, ...]]]
    sole_owner_by_file: Mapping[str, str]
    uniform_paths_by_dir: Mapping[str, bool]


class RustResolver:
    """Approach-C resolver for Rust (mod/use against the crate module tree).

    ``index`` is ``None`` for the registered path-only singleton; a prepared,
    scan-local instance (see :meth:`prepare`) carries the :class:`_CrateIndex`
    that unlocks the context-dependent capabilities (#484 Rust slice).
    """

    config = RUST_CONFIG

    def __init__(self, index: _CrateIndex | None = None) -> None:
        self._index = index

    # ---------- extract (tree-sitter) ----------

    def extract(self, src: bytes) -> list[RawImport]:
        """Return the ``mod`` / ``use`` items in ``src`` as :class:`RawImport`.

        Walks the parse tree, recording each file-backed ``mod name;`` (level 1)
        and each ``use`` path (level 0). A bare ``use`` head that the file's own
        scope declares as a module is rewritten self-anchored and emitted as
        level 2 (see :meth:`_classify_head`); the declaration pre-pass makes
        declaration ORDER irrelevant, matching Rust name resolution (#358).
        ``function_local`` is set when the item is lexically inside a ``fn``
        body (so the orchestrator can down-rank a deferred import to ``medium``
        confidence).
        """
        root = parse("rust", src)
        mods, inlines = self._declaration_paths(root)
        decls = frozenset(mods) | frozenset(inlines)
        raws: list[RawImport] = []
        self._collect(root, function_depth=0, inline_prefix=(), decls=decls, out=raws)
        return raws

    def _collect(
        self,
        node: TSNode,
        *,
        function_depth: int,
        inline_prefix: tuple[str, ...],
        decls: frozenset[tuple[str, ...]],
        out: list[RawImport],
    ) -> None:
        kind = node.kind
        if kind == _MOD_ITEM:
            self._mod_item(node, function_depth > 0, inline_prefix, decls, out)
            return
        if kind == _USE_DECLARATION:
            out.extend(self._use_imports(node, function_depth > 0, inline_prefix, decls))
            return
        next_depth = function_depth + 1 if kind == _FUNCTION_ITEM else function_depth
        for child in node.children:
            self._collect(
                child, function_depth=next_depth, inline_prefix=inline_prefix, decls=decls, out=out
            )

    def _mod_item(
        self,
        node: TSNode,
        function_local: bool,
        inline_prefix: tuple[str, ...],
        decls: frozenset[tuple[str, ...]],
        out: list[RawImport],
    ) -> None:
        """`mod name;` -> one level-1 RawImport; `mod name { … }` -> recurse.

        An inline module (one carrying a ``declaration_list`` body) defines the
        module in place and maps to no file; its body is still walked so a
        ``use`` nested inside it is captured, and its name is threaded onto
        ``inline_prefix`` so a nested file-module (``mod outer { mod child; }``)
        resolves under the enclosing module (``outer/child.rs``), not the file's
        own directory (#358).
        """
        name = ""
        decl_list: TSNode | None = None
        for child in node.children:
            ckind = child.kind
            if ckind == _IDENTIFIER and not name:
                name = child.text
            elif ckind == _DECLARATION_LIST:
                decl_list = child
        if decl_list is not None:
            child_prefix = (*inline_prefix, name) if name else inline_prefix
            for child in decl_list.children:
                self._collect(
                    child,
                    function_depth=1 if function_local else 0,
                    inline_prefix=child_prefix,
                    decls=decls,
                    out=out,
                )
            return
        if name:
            module = "::".join((*inline_prefix, name))
            out.append(
                RawImport(module=module, level=_LEVEL_MOD, names=(), function_local=function_local)
            )

    def _use_imports(
        self,
        node: TSNode,
        function_local: bool,
        inline_prefix: tuple[str, ...],
        decls: frozenset[tuple[str, ...]],
    ) -> list[RawImport]:
        """`use <tree>;` -> the RawImport(s) the use tree resolves to.

        Dispatches on the shape of the path child (skipping the ``use`` keyword,
        any ``visibility_modifier`` of a ``pub use`` re-export, and the ``;``):

        - a plain ``scoped_identifier`` / ``identifier`` -> one path RawImport;
        - a ``use_as_clause`` -> the inner path, alias dropped;
        - a ``use_wildcard`` -> the prefix module path;
        - a ``scoped_use_list`` -> the prefix module plus each grouped name.

        ``inline_prefix`` is the chain of enclosing inline ``mod`` names; every
        extracted head goes through :meth:`_classify_head`, which normalises a
        leading ``self`` / ``super`` for that inline frame (so ``resolve``,
        which works in the physical FILE's module frame, anchors correctly —
        e.g. a ``mod tests { use super::Foo; }`` in ``src/foo.rs`` targets the
        ``foo`` module's ``Foo``, not the crate root) and rewrites a bare head
        the current scope provably declares (``decls``) into a level-2
        self-anchored path (#358). At file top level the prefix is empty and
        the normalisation is a no-op.
        """
        for child in node.children:
            kind = child.kind
            if kind in (_SCOPED_IDENTIFIER, _IDENTIFIER):
                segs, level = self._classify_head(self._path_segments(child), inline_prefix, decls)
                return [self._path_import("::".join(segs), (), function_local, level)]
            if kind in (_USE_AS_CLAUSE, _USE_WILDCARD):
                path = self._first_path(child)
                raw = self._path_segments(path) if path is not None else []
                segs, level = self._classify_head(raw, inline_prefix, decls)
                return [self._path_import("::".join(segs), (), function_local, level)]
            if kind == _SCOPED_USE_LIST:
                return self._expand_group(child, (), function_local, inline_prefix, decls)
        return []  # pragma: no cover -- defensive: a use_declaration always has a path child

    def _classify_head(
        self,
        segments: list[str],
        inline_prefix: tuple[str, ...],
        decls: frozenset[tuple[str, ...]],
    ) -> tuple[list[str], int]:
        """Normalise a use path's head for its frame and classify bare heads.

        ``self`` / ``super`` heads are rebased for the enclosing inline ``mod``
        frame (:meth:`_normalize_head`). A BARE head (not ``crate`` / ``self``
        / ``super``) that the current scope PROVABLY declares as a module —
        ``decls`` holds the file's frame-qualified ``mod`` declarations,
        external and inline, excluding function-local ones — is a Rust-2018+
        uniform path into the current scope: it is rewritten self-anchored and
        marked ``_LEVEL_BARE`` so resolution stays gated on the scan-local
        edition proof. Any other bare head keeps ``_LEVEL_USE`` and resolves to
        nothing (external crate / ``std``), exactly as before (#358).
        """
        segs = self._normalize_head(segments, inline_prefix)
        if segs and segs[0] not in _PATH_HEAD_KEYWORDS and (*inline_prefix, segs[0]) in decls:
            return ["self", *inline_prefix, *segs], _LEVEL_BARE
        return segs, _LEVEL_USE

    def _expand_group(
        self,
        group: TSNode,
        prefix: tuple[str, ...],
        function_local: bool,
        inline_prefix: tuple[str, ...] = (),
        decls: frozenset[tuple[str, ...]] = frozenset(),
        level: int = _LEVEL_USE,
    ) -> list[RawImport]:
        """`prefix::{...}` -> the RawImport(s) the group expands to.

        Direct ``identifier`` members collapse into one group RawImport
        (``module=<prefix path>``, ``names=(...)``) preserving the
        container-plus-members probe. Every other member emits its own edge so
        the group is expanded fully (#358):

        - a **nested** ``scoped_use_list`` recurses under its own extended prefix
          (``use a::{b::{c, d}}`` -> the module ``a::b`` and each of
          ``a::b::c`` / ``a::b::d``);
        - an **aliased** ``use_as_clause`` or a plain ``scoped_identifier`` member
          resolves its (pre-``as``) path as a leaf (submodule + item-of-parent);
        - a ``use_wildcard`` member probes its prefix module.

        A bare ``self`` member (``use a::{self, b}`` -> import ``a`` itself) is
        covered by the container probe, so it contributes no separate edge.

        A TOP-LEVEL group head (``prefix`` empty) goes through
        :meth:`_classify_head`: ``self`` / ``super`` are normalised for the
        enclosing inline ``mod`` frame, and a provably-declared bare head
        (``mod g; use g::{a, b};``) is rewritten self-anchored with the whole
        group marked ``_LEVEL_BARE`` — every member RawImport inherits that
        ``level`` so nothing under an unproven head can resolve. Nested-group
        recursion passes its extended ``prefix`` and the inherited ``level``;
        the inner head is a continuation, never re-classified (#358).
        """
        head = self._first_path(group)
        raw_segs = self._path_segments(head) if head is not None else []
        if prefix:
            segs: tuple[str, ...] = (*prefix, *raw_segs)
        else:
            classified, level = self._classify_head(raw_segs, inline_prefix, decls)
            segs = tuple(classified)
        module = "::".join(segs)
        names: list[str] = []
        extra: list[RawImport] = []
        for child in group.children:
            if child.kind != _USE_LIST:
                continue
            for member in child.children:
                mkind = member.kind
                if mkind == _IDENTIFIER:
                    names.append(member.text)
                elif mkind == _SCOPED_USE_LIST:
                    extra.extend(self._expand_group(member, segs, function_local, level=level))
                elif mkind == _SCOPED_IDENTIFIER:
                    path = (*segs, *self._path_segments(member))
                    extra.append(self._path_import("::".join(path), (), function_local, level))
                elif mkind in (_USE_AS_CLAUSE, _USE_WILDCARD):
                    inner = self._first_path(member)
                    seg = self._path_segments(inner) if inner is not None else []
                    extra.append(
                        self._path_import("::".join((*segs, *seg)), (), function_local, level)
                    )
        results: list[RawImport] = []
        # Emit the prefix-module group for the direct members; also keep it when
        # the group has NO members at all (only `self`), so the prefix itself is
        # still probed. When the group is purely nested/aliased members, the
        # prefix is only a router and gets no spurious edge of its own.
        if names or not extra:
            results.append(self._path_import(module, tuple(names), function_local, level))
        results.extend(extra)
        return results

    @staticmethod
    def _path_import(
        module: str, names: tuple[str, ...], function_local: bool, level: int = _LEVEL_USE
    ) -> RawImport:
        return RawImport(module=module, level=level, names=names, function_local=function_local)

    @staticmethod
    def _first_path(node: TSNode) -> TSNode | None:
        """The first path child of a group / glob / alias wrapper.

        The path may be a multi-segment ``scoped_identifier`` (``crate::foo``) or
        a single leaf: a plain ``identifier`` (an external crate head) or a bare
        head keyword (``crate`` / ``self`` / ``super``) when the ``use`` reaches
        straight into a group or glob with no intermediate module segment
        (``use crate::{a, b}``, ``use self::*``). All of those leaf kinds head a
        real path, so any is returned; only a keyword-less ``::``/brace node is
        skipped.
        """
        for child in node.children:
            if child.kind in _PATH_HEAD_KINDS:
                return child
        return None  # pragma: no cover -- defensive: these wrappers always hold a path

    @staticmethod
    def _path_segments(node: TSNode) -> list[str]:
        """A path node -> its segment strings in source order.

        ``scoped_identifier`` nests left-associatively (the innermost is the
        leftmost), so a pre-order walk yields ``crate::foo::Thing`` as
        ``["crate", "foo", "Thing"]``. The path-head keywords (``crate`` /
        ``self`` / ``super``) are their own leaf kinds, captured alongside plain
        identifiers; the ``::`` separators are not.
        """
        return [n.text for n in node.descendants() if n.kind in _PATH_SEGMENT_KINDS]

    @staticmethod
    def _normalize_head(segments: list[str], inline_prefix: tuple[str, ...]) -> list[str]:
        """Rewrite a ``use`` path's leading ``self`` / ``super`` for its inline frame.

        A ``use`` written inside an inline ``mod`` block is authored in that
        inline module's frame, but ``resolve`` anchors everything in the physical
        FILE module's frame. Given ``inline_prefix`` = the chain of enclosing
        inline ``mod`` names (``P``, depth ``m`` below the file module), this
        rebases the head so the two frames agree — a no-op when the ``use`` is at
        file top level (``inline_prefix`` empty) or the head is neither ``self``
        nor ``super`` (``crate`` / external, which the inline nesting never moves):

        - ``self::rest`` -> ``self::<P>::rest`` (``self`` names the inline module,
          ``m`` levels below the file module);
        - a run of ``k`` leading ``super`` tokens climbs one module each: the
          first ``min(k, m)`` pop inline components off the END of ``P`` and stay
          within the file's subtree (``self::<P[:m-k]>::rest``); any ``super``
          beyond ``m`` climbs above the file module and is kept as a ``super``
          token for :meth:`_walk_super`'s crate-root-clamped walk (#358).
        """
        if not inline_prefix or not segments:
            return segments
        if segments[0] == "self":
            return ["self", *inline_prefix, *segments[1:]]
        if segments[0] == "super":
            k = 0
            while k < len(segments) and segments[k] == "super":
                k += 1
            m = len(inline_prefix)
            if k <= m:
                return ["self", *inline_prefix[: m - k], *segments[k:]]
            return ["super"] * (k - m) + list(segments[k:])
        return segments

    # ---------- resolve (pure path arithmetic) ----------

    def resolve(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        """Map one ``mod`` / ``use`` item to the repo-relative file(s) it names.

        Returns repo-relative paths that exist in ``file_set``; an empty list
        means the item points outside the crate (external crate, ``std``) or
        could not be resolved — never an error. Deterministic: results are
        de-duplicated preserving first-seen order.
        """
        if imp.level == _LEVEL_MOD:
            candidates = self._resolve_mod(importer, imp.module, file_set)
        elif imp.level == _LEVEL_BARE:
            candidates = self._resolve_bare(importer, imp, file_set)
        else:
            candidates = self._resolve_use(importer, imp, file_set)
        resolved: list[str] = []
        for cand in candidates:
            if cand in file_set and cand not in resolved:
                resolved.append(cand)
        return resolved

    def _resolve_mod(self, importer: str, name: str, file_set: set[str]) -> list[str]:
        """`mod name;` -> the child module file under the importer's module dir.

        ``name`` may be a ``::``-joined path when the ``mod`` was declared inside
        an inline module (``mod outer { mod child; }`` -> ``outer::child``), so
        the child resolves under the enclosing inline module (#358). A ``mod``
        DECLARES a file module, so only the conventional module-file candidates
        apply — never the inline-hosted probe (an inline module of the same
        name lives in the importer itself, which is no edge).
        """
        anchor = self._module_dir(importer, file_set)
        return self._conventional_module_files(anchor, name.split("::"), file_set)

    def _resolve_bare(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        """A proven current-scope bare path resolves only with scan context.

        Extraction proved the head names a module declared in the importer's
        own scope (level 2, already rewritten self-anchored); whether the use
        actually reaches it still depends on the crate's edition — a 2015 bare
        path is crate-root-relative, not current-scope. Without an index (the
        registered path-only singleton) or without a provable uniform-paths
        edition from the importer's nearest ``Cargo.toml``, the path is
        dropped: under-edge, never guess (#358).
        """
        index = self._index
        if index is None or not self._uniform_paths(index, importer):
            return []
        return self._resolve_use(importer, imp, file_set)

    @staticmethod
    def _uniform_paths(index: _CrateIndex, importer: str) -> bool:
        """Whether the importer's nearest ``Cargo.toml`` proves uniform paths."""
        dirs = importer.split("/")[:-1]
        for i in range(len(dirs), -1, -1):
            verdict = index.uniform_paths_by_dir.get("/".join(dirs[:i]))
            if verdict is not None:
                return verdict
        return False  # no manifest anywhere above: the normal path-only fallback

    def _resolve_use(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        """Resolve a ``use`` path to candidate module files.

        Strips the ``crate`` / ``self`` / ``super`` head to an anchor directory
        (external paths return ``[]``), then probes the leaf as a submodule and
        as an item of its parent module — and, for a group, each named member.

        The importer's own crate-root file is threaded through so a crate-root
        module probe anchors at the CALLER's own root: a ``crate::`` from
        ``src/main.rs`` in a lib+bin package targets ``src/main.rs``, not the
        sibling ``src/lib.rs`` (see :meth:`_own_root_file`). For a non-root
        importer with scan context, the PROVABLE owning root (crate membership
        walked from every root's ``mod`` graph) is threaded the same way so a
        shared two-root probe resolves to the right root or, when membership is
        ambiguous, to none (#358).
        """
        segments = imp.module.split("::") if imp.module else []
        anchored = self._anchor(importer, segments, file_set)
        if anchored is None:
            return []  # external crate / std / unanchorable super
        anchor, segs = anchored
        own_root = self._own_root_file(importer, file_set)
        sole_owner = self._sole_owner(importer) if own_root is None else None
        candidates: list[str] = []
        if imp.names:
            # `use prefix::{a, b}`: the prefix module (item container) plus each
            # member as a submodule of it.
            candidates += self._module_files(anchor, segs, file_set, own_root, sole_owner)
            for name in imp.names:
                candidates += self._module_files(
                    anchor, [*segs, name], file_set, own_root, sole_owner
                )
        else:
            # `use prefix::…::leaf`: leaf as a submodule, and leaf as an item of
            # the parent module (so the parent module file is also probed).
            candidates += self._module_files(anchor, segs, file_set, own_root, sole_owner)
            candidates += self._module_files(anchor, segs[:-1], file_set, own_root, sole_owner)
        return candidates

    def _sole_owner(self, importer: str) -> str | None:
        """The importer's PROVABLE crate-root file from the scan-local module
        graph; ``None`` without an index or when membership is ambiguous or
        unknown (so the caller never guesses a root)."""
        if self._index is None:
            return None
        return self._index.sole_owner_by_file.get(importer)

    def _anchor(
        self, importer: str, segments: list[str], file_set: set[str]
    ) -> tuple[str, list[str]] | None:
        """Resolve a path head to ``(anchor_dir, remaining_segments)`` or ``None``.

        ``crate`` anchors at the crate root dir; ``self`` at the importer's
        module dir; each ``super`` walks one parent module up. Any other head
        (an external crate, ``std``) returns ``None`` so the path is dropped.
        """
        if not segments:
            return None  # pragma: no cover -- defensive: a use always has >=1 segment
        head = segments[0]
        if head == "crate":
            crate_dir = self._crate_root_dir(importer, file_set)
            if crate_dir is None:
                return None
            return crate_dir, segments[1:]
        if head == "self":
            return self._module_dir(importer, file_set), segments[1:]
        if head == "super":
            return self._walk_super(importer, segments, file_set)
        return None  # external crate / std

    def _walk_super(
        self, importer: str, segments: list[str], file_set: set[str]
    ) -> tuple[str, list[str]] | None:
        """`super::…` -> the parent module dir reached by the leading supers.

        Each ``super`` strips one component off the importer's module dir. A
        ``super`` from a crate root, or one that walks above it, cannot resolve
        and returns ``None`` (no false edge to a root-level file): the walk is
        clamped so the anchor never rises shallower than the crate root dir.
        """
        depth = 0
        while depth < len(segments) and segments[depth] == "super":
            depth += 1
        parts = [p for p in self._module_dir(importer, file_set).split("/") if p]
        anchor_len = len(parts) - depth
        if anchor_len < 0:
            return None  # more supers than module depth
        crate_dir = self._crate_root_dir(importer, file_set)
        if crate_dir is not None:
            if anchor_len < len([p for p in crate_dir.split("/") if p]):
                return None  # walks above the crate root (its module has no parent)
        elif anchor_len == 0:
            return None  # no known crate root: don't anchor super at the repo root
        return "/".join(parts[:anchor_len]), segments[depth:]

    def _module_files(
        self,
        anchor_dir: str,
        segs: list[str],
        file_set: set[str],
        own_root: str | None = None,
        sole_owner: str | None = None,
    ) -> list[str]:
        """A module path rooted at ``anchor_dir`` -> its candidate file path(s).

        The conventional module-file candidates always apply (see
        :meth:`_conventional_module_files`). With scan-local context, the path
        may additionally live INLINE in a hosting file (#484): for every split
        of the path into a file-module prefix and a non-empty suffix, the
        prefix's hosting file is offered when its declaration index carries the
        suffix as an inline module chain — so ``use crate::cfg::Item`` with
        ``mod cfg { … }`` inline in ``lib.rs`` resolves to ``src/lib.rs``. A
        mixed chain whose inline module declares a file child needs no special
        case: an inline module contributes a directory component for nested
        external ``mod`` files, which the conventional candidates already
        cover.
        """
        candidates = self._conventional_module_files(
            anchor_dir, segs, file_set, own_root, sole_owner
        )
        if self._index is None or not segs:
            return candidates
        for split in range(len(segs)):
            suffix = tuple(segs[split:])
            hosts = self._conventional_module_files(
                anchor_dir, segs[:split], file_set, own_root, sole_owner
            )
            for host in hosts:
                if host not in file_set:
                    continue
                if suffix in self._index.inline_by_file.get(host, frozenset()):
                    candidates.append(host)
        return candidates

    def _conventional_module_files(
        self,
        anchor_dir: str,
        segs: list[str],
        file_set: set[str],
        own_root: str | None = None,
        sole_owner: str | None = None,
    ) -> list[str]:
        """The module-file convention candidates for a path at ``anchor_dir``.

        With no segments the path *is* the anchor module, whose file is found by
        :meth:`_dir_module_files` (which honours ``own_root`` — the importer's
        own crate-root file — and ``sole_owner`` — the importer's provable
        crate membership — when the anchor is a crate root). Otherwise the
        leaf module ``segs[-1]`` lives under ``anchor_dir/segs[:-1]`` as
        ``<leaf>.rs`` or ``<leaf>/mod.rs`` (its children, in turn, would live in
        ``<leaf>/``); the root hints only bear on a crate-root module, so they
        are irrelevant here and ignored.
        """
        if not segs:
            return self._dir_module_files(anchor_dir, file_set, own_root, sole_owner)
        parent = "/".join(p for p in (anchor_dir, *segs[:-1]) if p)
        leaf = segs[-1]
        base = f"{parent}/{leaf}" if parent else leaf
        return [f"{base}{_RS}", f"{base}/{_MOD_FILE}"]

    def _dir_module_files(
        self,
        anchor_dir: str,
        file_set: set[str],
        own_root: str | None = None,
        sole_owner: str | None = None,
    ) -> list[str]:
        """The candidate file(s) for the module whose module directory is ``anchor_dir``.

        That module is reached as the sibling ``<dir>.rs``, as ``<dir>/mod.rs``,
        or — when ``anchor_dir`` is a crate root dir — as ``<dir>/lib.rs`` /
        ``<dir>/main.rs``. ``file_set`` filtering in :meth:`resolve` keeps only
        the one that actually exists, so the over-broad candidate set never
        fabricates an edge.

        When BOTH ``lib.rs`` and ``main.rs`` exist at the crate root, only ONE
        may be offered — emitting the sibling too would fabricate a spurious
        second edge. Which one:

        - the CALLER's own crate root wins (``own_root``): a ``crate::`` from
          ``src/main.rs`` resolves to ``src/main.rs``, not the library sibling;
        - otherwise, WITH scan-local context, the importer's PROVABLE crate
          membership (``sole_owner``) picks the owning root, and ambiguous or
          unknown membership offers NO root at all — under-edging instead of
          fabricating a wrong high-confidence edge (#358);
        - without context (the registered path-only singleton) the library root
          (``lib.rs``, first in :data:`_CRATE_ROOTS`) stays the documented
          default.

        A single-file Cargo target root leaves no ``lib.rs`` / ``main.rs`` at its
        containing dir, so when ``own_root`` names the root file itself and no
        ``lib.rs`` / ``main.rs`` is present, that root file is offered as THE
        crate-root module: ``crate::Item`` from ``src/bin/tool.rs`` ->
        ``src/bin/tool.rs`` (#358).
        """
        parts = [p for p in anchor_dir.split("/") if p]
        candidates: list[str] = []
        if parts:
            parent = "/".join(parts[:-1])
            base = parts[-1]
            named = f"{parent}/{base}{_RS}" if parent else f"{base}{_RS}"
            candidates.append(named)
        prefix = f"{anchor_dir}/" if anchor_dir else ""
        present_roots = [
            f"{prefix}{root}" for root in _CRATE_ROOTS if f"{prefix}{root}" in file_set
        ]
        candidates.append(f"{prefix}{_MOD_FILE}")
        if present_roots:
            if own_root is not None and own_root in present_roots:
                # The importer's OWN crate root at this dir.
                candidates.append(own_root)
            elif len(present_roots) == 1 or self._index is None:
                # A single unambiguous root, or the path-only singleton's
                # documented lib.rs-preferred default.
                candidates.append(present_roots[0])
            elif sole_owner is not None and sole_owner in present_roots:
                # Two roots, but membership is provable: the owning root.
                candidates.append(sole_owner)
            # else: two roots and ambiguous/unknown membership -> no root
            # candidate at all (never guess a high-confidence edge, #358).
        elif own_root is not None:
            # A single-file target root: its own file IS the crate-root module,
            # and no lib.rs / main.rs sits beside it to stand in for the root.
            candidates.append(own_root)
        else:
            candidates.extend(f"{prefix}{root}" for root in _CRATE_ROOTS)
        return candidates

    def _crate_root_dir(self, importer: str, file_set: set[str]) -> str | None:
        """The crate root directory ``crate::`` anchors at for ``importer``.

        Cargo compiles more than the ``src/lib.rs`` / ``src/main.rs`` crate: each
        ``.rs`` file directly under ``src/bin/``, ``tests/``, ``examples/`` or
        ``benches/`` is its OWN crate root. Such a target is detected FIRST (it is
        the crate root even when a sibling library ``lib.rs`` also exists, since a
        binary's / integration test's ``crate::`` names its own crate, not the
        library) via :meth:`_special_crate_root_dir`.

        Otherwise this walks the importer's ancestors deepest-first and returns
        the first whose ``lib.rs`` / ``main.rs`` exists in ``file_set``; ``None``
        when no crate root is in the map (``crate::`` then resolves nothing rather
        than guessing a root).
        """
        special = self._special_crate_root_dir(importer)
        if special is not None:
            return special
        parts = importer.split("/")[:-1]  # drop the filename
        for i in range(len(parts), -1, -1):
            base = "/".join(parts[:i])
            prefix = f"{base}/" if base else ""
            if any(f"{prefix}{root}" in file_set for root in _CRATE_ROOTS):
                return base
        return None

    @staticmethod
    def _single_file_target_dir(importer: str) -> str | None:
        """The containing dir when ``importer`` *is* a single-file Cargo target root.

        Cargo compiles each ``.rs`` file directly under ``src/bin/``, ``tests/``,
        ``examples/`` or ``benches/`` as its own crate root. rustc reads a crate
        root's ``mod`` files from beside the root file, so such a target's child
        modules live in the root file's *own containing* directory: ``tests/api.rs``
        -> ``tests/``; ``src/bin/tool.rs`` -> ``src/bin/``. Returns that directory,
        or ``None`` when ``importer`` is not itself such a root (a directory-based
        target root such as ``tests/api/main.rs``, a file nested deeper, or a
        ``tests`` / ``examples`` / ``benches`` component under ``src`` — a normal
        module directory — all return ``None`` and fall through to the ordinary
        crate-root rules).
        """
        dir_parts = importer.split("/")[:-1]
        if not dir_parts:
            return None
        parent = dir_parts[-1]
        is_bin = parent == _BIN_DIR and len(dir_parts) >= 2 and dir_parts[-2] == _SRC_DIR
        is_target = parent in _TARGET_ROOT_DIRS and _SRC_DIR not in dir_parts
        if is_bin or is_target:
            return "/".join(dir_parts)
        return None

    @staticmethod
    def _special_crate_root_dir(importer: str) -> str | None:
        """Crate root dir when ``importer`` is (or is under) a Cargo bin/test target.

        Cargo compiles each ``.rs`` file directly under ``src/bin/``, ``tests/``,
        ``examples/`` or ``benches/`` as its own crate root. A ``tests`` /
        ``examples`` / ``benches`` component nested under ``src`` is a normal
        module directory (``src/foo/tests/…``), not a target root, and is skipped.

        A single-file target root (``tests/api.rs``, ``src/bin/tool.rs``) anchors
        ``crate::`` at its *own containing* directory, matching rustc — the crate
        root's ``mod`` files live beside the root file: ``crate::helpers`` from
        ``tests/api.rs`` -> ``tests/helpers.rs``; ``crate::Item`` from
        ``src/bin/tool.rs`` -> the root ``src/bin/tool.rs`` itself (found as this
        anchor dir's own crate-root module, see :meth:`_dir_module_files`).

        Returns that crate root dir, or ``None`` when ``importer`` is not part of
        such a target.

        Residual gap: a ``.rs`` file nested *below* a target dir but not the root
        file (``tests/api/helpers.rs``, ``src/bin/tool/config.rs``) is treated as a
        directory-target-style subtree anchored one level in (``tests/api``,
        ``src/bin/tool``). The path-only contract cannot tell such a layout from a
        directory target's own files, and keeping the anchor inside that subtree
        never fabricates a cross-target edge; this is the documented residual gap.
        """
        single = RustResolver._single_file_target_dir(importer)
        if single is not None:
            return single
        parts = importer.split("/")
        for i, comp in enumerate(parts[:-1]):
            is_bin = comp == _BIN_DIR and i >= 1 and parts[i - 1] == _SRC_DIR
            is_target = comp in _TARGET_ROOT_DIRS and _SRC_DIR not in parts[:i]
            if is_bin or is_target:
                root = parts[i + 1]
                stem = root[: -len(_RS)] if root.endswith(_RS) else root
                return "/".join([*parts[: i + 1], stem])
        return None

    def _module_dir(self, importer: str, file_set: set[str]) -> str:
        """The directory under which ``importer``'s child modules live.

        A crate root (``lib.rs`` / ``main.rs``) or a ``mod.rs`` owns its own
        directory; any other ``foo.rs`` owns the sibling ``foo/``. A ``lib.rs`` /
        ``main.rs`` counts as a crate root only when it *is* the actual crate
        root — a same-named file nested below one (a module reached via
        ``mod main;``) is a plain module that owns its sibling ``main/`` (#358).

        A single-file Cargo target root (``tests/api.rs``, ``src/bin/tool.rs``) is
        a crate root as well, so — matching rustc — its child modules live in its
        *own containing* directory, NOT a same-named sibling: ``mod helper;`` in
        ``tests/api.rs`` -> ``tests/helper.rs`` (#358).
        """
        single = self._single_file_target_dir(importer)
        if single is not None:
            return single
        parts = importer.split("/")
        directory = parts[:-1]
        stem = self._stem(importer)
        if stem == _MOD_STEM or (
            stem in _CRATE_ROOT_STEMS and self._is_crate_root(importer, file_set)
        ):
            return "/".join(directory)
        return "/".join([*directory, stem])

    @staticmethod
    def _is_crate_root(importer: str, file_set: set[str]) -> bool:
        """Whether a ``lib.rs`` / ``main.rs`` ``importer`` is the crate's root file.

        It is the root only when NO strictly-shallower ancestor directory holds a
        crate root; a same-named file nested deeper (reached via ``mod main;``)
        has such an ancestor and is a plain module, not the crate root (#358).
        """
        dir_parts = importer.split("/")[:-1]
        for i in range(len(dir_parts) - 1, -1, -1):
            base = "/".join(dir_parts[:i])
            prefix = f"{base}/" if base else ""
            if any(f"{prefix}{root}" in file_set for root in _CRATE_ROOTS):
                return False
        return True

    def _own_root_file(self, importer: str, file_set: set[str]) -> str | None:
        """The importer's OWN crate-root FILE, when the importer is itself one.

        ``crate::`` (and a crate-root ``self::`` item probe) anchors at the
        CALLER's own crate root, so when the importer IS the ``lib.rs`` /
        ``main.rs`` crate root its own file is THE crate-root module — even where
        a sibling ``src/lib.rs`` and ``src/main.rs`` coexist in a lib+bin
        package. Returned so :meth:`_dir_module_files` prefers it over the
        lib-first default (a ``crate::`` from ``src/main.rs`` -> ``src/main.rs``,
        from ``src/lib.rs`` -> ``src/lib.rs``).

        Returns ``None`` when the importer is not a crate-root file — including a
        shared ``src/`` module (``src/foo.rs``), whose crate membership the
        path-only contract cannot determine, so the lib-preferred default stands.

        A single-file Cargo target root (``tests/api.rs``, ``src/bin/tool.rs``) is
        its OWN crate-root module too, so it is returned here: its containing dir
        holds no ``lib.rs`` / ``main.rs``, so :meth:`_dir_module_files` needs this
        signal to offer the root file itself as the crate-root module (``crate::``
        from ``src/bin/tool.rs`` -> ``src/bin/tool.rs``) (#358).
        """
        if self._single_file_target_dir(importer) is not None:
            return importer
        stem = self._stem(importer)
        if stem in _CRATE_ROOT_STEMS and self._is_crate_root(importer, file_set):
            return importer
        return None

    @staticmethod
    def _stem(path: str) -> str:
        """The filename of ``path`` without its ``.rs`` suffix."""
        name = path.split("/")[-1]
        return name[: -len(_RS)] if name.endswith(_RS) else name

    # ---------- scan-local preparation (#484 foundation, Rust slice) ----------

    def prepare(self, context: ScanContext) -> RustResolver:
        """Derive a scan-local resolver carrying crate/target context (#484).

        Reads only Rust sources and Cargo manifests, always through the
        context's bounded, memoized reads — no unbounded second repository
        read. Returns a NEW resolver instance so the registered singleton never
        carries repository data; everything derived here dies with the scan.
        Unreadable sources contribute no context and malformed/unreadable
        manifests degrade with one deterministic ``other`` warning each — the
        scan itself is never aborted. Parses with tree-sitter, so callers reach
        preparation only behind the orchestrator's availability gate (the same
        contract as :meth:`extract`).
        """
        file_set = set(context.files)
        rust_files = sorted(f for f in context.files if f.endswith(_RS))
        mods_by_file: dict[str, list[tuple[str, ...]]] = {}
        inline_by_file: dict[str, frozenset[tuple[str, ...]]] = {}
        for path in rust_files:
            src = context.read(path)
            if src is None:
                continue  # unreadable source: no context from it, never an abort
            mods, inlines = self._declaration_paths(parse("rust", src))
            if mods:
                mods_by_file[path] = mods
            if inlines:
                inline_by_file[path] = frozenset(inlines)
        return RustResolver(
            index=_CrateIndex(
                inline_by_file=inline_by_file,
                sole_owner_by_file=self._sole_owners(rust_files, mods_by_file, file_set),
                uniform_paths_by_dir=self._uniform_paths_by_dir(context),
            )
        )

    def _declaration_paths(
        self, root: TSNode
    ) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]]]:
        """One parsed file -> its ``(external, inline)`` module declaration paths.

        Each path is relative to the file's own module and carries the inline
        nesting (``mod outer { mod child; }`` -> external ``("outer",
        "child")``). Function-local declarations are excluded: they are not in
        the file module's item scope, so neither bare-head classification nor
        the cross-file indexes may see them.
        """
        mods: list[tuple[str, ...]] = []
        inlines: list[tuple[str, ...]] = []
        self._collect_declarations(root, (), mods, inlines)
        return mods, inlines

    def _collect_declarations(
        self,
        node: TSNode,
        prefix: tuple[str, ...],
        mods: list[tuple[str, ...]],
        inlines: list[tuple[str, ...]],
    ) -> None:
        """Walk ``mod`` declarations only (a lighter sibling of :meth:`_collect`)."""
        kind = node.kind
        if kind == _FUNCTION_ITEM:
            return  # function-local declarations are not in the file module's scope
        if kind == _MOD_ITEM:
            name = ""
            decl_list: TSNode | None = None
            for child in node.children:
                ckind = child.kind
                if ckind == _IDENTIFIER and not name:
                    name = child.text
                elif ckind == _DECLARATION_LIST:
                    decl_list = child
            if not name:
                return  # pragma: no cover -- defensive: a mod_item always carries a name
            path = (*prefix, name)
            if decl_list is None:
                mods.append(path)
                return
            inlines.append(path)
            for child in decl_list.children:
                self._collect_declarations(child, path, mods, inlines)
            return
        for child in node.children:
            self._collect_declarations(child, prefix, mods, inlines)

    def _sole_owners(
        self,
        rust_files: list[str],
        mods_by_file: dict[str, list[tuple[str, ...]]],
        file_set: set[str],
    ) -> dict[str, str]:
        """file -> its PROVABLE crate-root file (reachable from exactly one root).

        Walks the ``mod`` graph out of every crate root (package roots and
        single-file Cargo targets alike), resolving each declaration by the
        module-file conventions — ``name.rs`` first, mirroring rustc's
        preference when both forms exist. Files reachable from several roots
        (a shared ``src/`` module declared by both ``lib.rs`` and ``main.rs``)
        or from none are omitted: their membership is not provable and must
        not be guessed (#358).
        """
        owners: dict[str, set[str]] = {}
        for root in rust_files:
            if not self._is_crate_root_file(root, file_set):
                continue
            visited = {root}
            queue = [root]
            while queue:
                current = queue.pop()
                owners.setdefault(current, set()).add(root)
                module_dir = self._module_dir(current, file_set)
                for decl in mods_by_file.get(current, []):
                    base = "/".join(p for p in (module_dir, *decl) if p)
                    for candidate in (f"{base}{_RS}", f"{base}/{_MOD_FILE}"):
                        if candidate in file_set:
                            if candidate not in visited:
                                visited.add(candidate)
                                queue.append(candidate)
                            break  # name.rs shadows name/mod.rs (rustc rejects both)
        return {path: next(iter(roots)) for path, roots in owners.items() if len(roots) == 1}

    def _is_crate_root_file(self, path: str, file_set: set[str]) -> bool:
        """Whether ``path`` is compiled as its own crate root.

        True for a package root (``lib.rs`` / ``main.rs`` with no shallower
        root above it) and for a single-file Cargo target (``src/bin/*.rs``,
        ``tests/*.rs``, ``examples/*.rs``, ``benches/*.rs``).
        """
        if self._single_file_target_dir(path) is not None:
            return True
        return self._stem(path) in _CRATE_ROOT_STEMS and self._is_crate_root(path, file_set)

    def _uniform_paths_by_dir(self, context: ScanContext) -> dict[str, bool]:
        """Package dir -> whether its edition provably enables uniform paths.

        Every ``Cargo.toml`` is read through the context's bounded reads. A
        missing manifest is simply no entry (the normal path-only fallback).
        An unreadable or malformed manifest gets one deterministic ``other``
        warning and a conservative ``False``. ``edition.workspace = true``
        resolves against the nearest enclosing manifest carrying a
        ``[workspace]`` table; an unresolvable inheritance stays ``False`` —
        Cargo's default edition is 2015, whose bare paths are crate-root
        relative, so only an explicit 2018+ edition may enable bare
        current-scope resolution (#358).
        """
        manifests = sorted(
            f for f in context.files if f == _CARGO_MANIFEST or f.endswith(f"/{_CARGO_MANIFEST}")
        )
        parsed: dict[str, dict[str, object] | None] = {}
        for manifest in manifests:
            directory = manifest.rsplit("/", 1)[0] if "/" in manifest else ""
            raw = context.read(manifest)
            if raw is None:
                context.warn_config(_UNREADABLE_MANIFEST_MESSAGE, manifest)
                parsed[directory] = None
                continue
            try:
                parsed[directory] = tomllib.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, tomllib.TOMLDecodeError):
                context.warn_config(_MALFORMED_MANIFEST_MESSAGE, manifest)
                parsed[directory] = None
        return {
            directory: self._edition_enables_uniform_paths(directory, data, parsed)
            for directory, data in parsed.items()
        }

    @staticmethod
    def _edition_enables_uniform_paths(
        directory: str,
        data: dict[str, object] | None,
        parsed: dict[str, dict[str, object] | None],
    ) -> bool:
        """Whether one parsed manifest proves a uniform-paths (2018+) edition.

        ``None`` (unusable manifest) and manifests without a ``[package]``
        table (virtual workspace roots) are ``False``. A literal edition string
        answers directly. ``edition.workspace = true`` walks ``parsed`` up the
        ancestor directories to the nearest manifest with a ``[workspace]``
        table and reads ``workspace.package.edition`` — the nearest workspace
        root decides, and one without an inheritable edition is ``False``.
        """
        if data is None:
            return False
        package = data.get("package")
        if not isinstance(package, dict):
            return False  # no [package]: a virtual workspace root or unrecognized shape
        edition = package.get("edition")
        if isinstance(edition, str):
            return edition in _UNIFORM_PATH_EDITIONS
        if isinstance(edition, dict) and edition.get("workspace") is True:
            parts = [p for p in directory.split("/") if p]
            for i in range(len(parts), -1, -1):
                candidate = parsed.get("/".join(parts[:i]))
                if not isinstance(candidate, dict):
                    continue  # no (usable) manifest at this ancestor: keep climbing
                workspace = candidate.get("workspace")
                if not isinstance(workspace, dict):
                    continue  # a plain package between member and workspace root
                ws_package = workspace.get("package")
                ws_edition = ws_package.get("edition") if isinstance(ws_package, dict) else None
                if isinstance(ws_edition, str):
                    return ws_edition in _UNIFORM_PATH_EDITIONS
                return False  # nearest workspace root lacks an inheritable edition
        return False  # edition absent (Cargo defaults to 2015) or unrecognized shape


register(RustResolver())
