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
  children live in ``src/foo/``).
- **``use`` paths** are anchored by their leading segment:
  - ``crate::`` anchors at the crate root's directory (the nearest ancestor of
    the importer holding a ``lib.rs`` / ``main.rs``);
  - ``self::`` anchors at the importer's own module directory;
  - ``super::`` walks one parent module up per ``super`` token;
  - any other leading segment (``std``, an external crate name) is an external
    path and is **dropped** — modern-edition ``use`` reaches in-crate modules
    only through ``crate`` / ``self`` / ``super``.
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
"""

from __future__ import annotations

from sumo_qa.repo_map_resolvers.base import LanguageConfig, RawImport, register
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

# RawImport.level is reused as a Rust item-kind flag (the field is the
# foundation's, shared across languages): 0 = a `use` path, 1 = a `mod`
# declaration (resolved as a direct child of the importer, never an item).
_LEVEL_USE = 0
_LEVEL_MOD = 1


class RustResolver:
    """Approach-C resolver for Rust (mod/use against the crate module tree)."""

    config = RUST_CONFIG

    # ---------- extract (tree-sitter) ----------

    def extract(self, src: bytes) -> list[RawImport]:
        """Return the ``mod`` / ``use`` items in ``src`` as :class:`RawImport`.

        Walks the parse tree, recording each file-backed ``mod name;`` (level 1)
        and each ``use`` path (level 0). ``function_local`` is set when the item
        is lexically inside a ``fn`` body (so the orchestrator can down-rank a
        deferred import to ``medium`` confidence).
        """
        root = parse("rust", src)
        raws: list[RawImport] = []
        self._collect(root, function_depth=0, inline_prefix=(), out=raws)
        return raws

    def _collect(
        self,
        node: TSNode,
        *,
        function_depth: int,
        inline_prefix: tuple[str, ...],
        out: list[RawImport],
    ) -> None:
        kind = node.kind
        if kind == _MOD_ITEM:
            self._mod_item(node, function_depth > 0, inline_prefix, out)
            return
        if kind == _USE_DECLARATION:
            out.extend(self._use_imports(node, function_depth > 0))
            return
        next_depth = function_depth + 1 if kind == _FUNCTION_ITEM else function_depth
        for child in node.children:
            self._collect(child, function_depth=next_depth, inline_prefix=inline_prefix, out=out)

    def _mod_item(
        self,
        node: TSNode,
        function_local: bool,
        inline_prefix: tuple[str, ...],
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
                    out=out,
                )
            return
        if name:
            module = "::".join((*inline_prefix, name))
            out.append(
                RawImport(module=module, level=_LEVEL_MOD, names=(), function_local=function_local)
            )

    def _use_imports(self, node: TSNode, function_local: bool) -> list[RawImport]:
        """`use <tree>;` -> the RawImport(s) the use tree resolves to.

        Dispatches on the shape of the path child (skipping the ``use`` keyword,
        any ``visibility_modifier`` of a ``pub use`` re-export, and the ``;``):

        - a plain ``scoped_identifier`` / ``identifier`` -> one path RawImport;
        - a ``use_as_clause`` -> the inner path, alias dropped;
        - a ``use_wildcard`` -> the prefix module path;
        - a ``scoped_use_list`` -> the prefix module plus each grouped name.
        """
        for child in node.children:
            kind = child.kind
            if kind in (_SCOPED_IDENTIFIER, _IDENTIFIER):
                module = "::".join(self._path_segments(child))
                return [self._path_import(module, (), function_local)]
            if kind == _USE_AS_CLAUSE:
                path = self._first_path(child)
                module = "::".join(self._path_segments(path)) if path is not None else ""
                return [self._path_import(module, (), function_local)]
            if kind == _USE_WILDCARD:
                path = self._first_path(child)
                module = "::".join(self._path_segments(path)) if path is not None else ""
                return [self._path_import(module, (), function_local)]
            if kind == _SCOPED_USE_LIST:
                return self._expand_group(child, (), function_local)
        return []  # pragma: no cover -- defensive: a use_declaration always has a path child

    def _expand_group(
        self, group: TSNode, prefix: tuple[str, ...], function_local: bool
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
        """
        head = self._first_path(group)
        segs = (*prefix, *self._path_segments(head)) if head is not None else prefix
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
                    extra.extend(self._expand_group(member, segs, function_local))
                elif mkind == _SCOPED_IDENTIFIER:
                    path = (*segs, *self._path_segments(member))
                    extra.append(self._path_import("::".join(path), (), function_local))
                elif mkind in (_USE_AS_CLAUSE, _USE_WILDCARD):
                    inner = self._first_path(member)
                    seg = self._path_segments(inner) if inner is not None else []
                    extra.append(self._path_import("::".join((*segs, *seg)), (), function_local))
        results: list[RawImport] = []
        # Emit the prefix-module group for the direct members; also keep it when
        # the group has NO members at all (only `self`), so the prefix itself is
        # still probed. When the group is purely nested/aliased members, the
        # prefix is only a router and gets no spurious edge of its own.
        if names or not extra:
            results.append(self._path_import(module, tuple(names), function_local))
        results.extend(extra)
        return results

    @staticmethod
    def _path_import(module: str, names: tuple[str, ...], function_local: bool) -> RawImport:
        return RawImport(
            module=module, level=_LEVEL_USE, names=names, function_local=function_local
        )

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
        the child resolves under the enclosing inline module (#358).
        """
        anchor = self._module_dir(importer, file_set)
        return self._module_files(anchor, name.split("::"), file_set)

    def _resolve_use(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        """Resolve a ``use`` path to candidate module files.

        Strips the ``crate`` / ``self`` / ``super`` head to an anchor directory
        (external paths return ``[]``), then probes the leaf as a submodule and
        as an item of its parent module — and, for a group, each named member.
        """
        segments = imp.module.split("::") if imp.module else []
        anchored = self._anchor(importer, segments, file_set)
        if anchored is None:
            return []  # external crate / std / unanchorable super
        anchor, segs = anchored
        candidates: list[str] = []
        if imp.names:
            # `use prefix::{a, b}`: the prefix module (item container) plus each
            # member as a submodule of it.
            candidates += self._module_files(anchor, segs, file_set)
            for name in imp.names:
                candidates += self._module_files(anchor, [*segs, name], file_set)
        else:
            # `use prefix::…::leaf`: leaf as a submodule, and leaf as an item of
            # the parent module (so the parent module file is also probed).
            candidates += self._module_files(anchor, segs, file_set)
            candidates += self._module_files(anchor, segs[:-1], file_set)
        return candidates

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

    def _module_files(self, anchor_dir: str, segs: list[str], file_set: set[str]) -> list[str]:
        """A module path rooted at ``anchor_dir`` -> its candidate file path(s).

        With no segments the path *is* the anchor module, whose file is found by
        :meth:`_dir_module_files`. Otherwise the leaf module ``segs[-1]`` lives
        under ``anchor_dir/segs[:-1]`` as ``<leaf>.rs`` or ``<leaf>/mod.rs``
        (its children, in turn, would live in ``<leaf>/``).
        """
        if not segs:
            return self._dir_module_files(anchor_dir, file_set)
        parent = "/".join(p for p in (anchor_dir, *segs[:-1]) if p)
        leaf = segs[-1]
        base = f"{parent}/{leaf}" if parent else leaf
        return [f"{base}{_RS}", f"{base}/{_MOD_FILE}"]

    @staticmethod
    def _dir_module_files(anchor_dir: str, file_set: set[str]) -> list[str]:
        """The candidate file(s) for the module whose module directory is ``anchor_dir``.

        That module is reached as the sibling ``<dir>.rs``, as ``<dir>/mod.rs``,
        or — when ``anchor_dir`` is a crate root dir — as ``<dir>/lib.rs`` /
        ``<dir>/main.rs``. ``file_set`` filtering in :meth:`resolve` keeps only
        the one that actually exists, so the over-broad candidate set never
        fabricates an edge.

        When BOTH ``lib.rs`` and ``main.rs`` exist at the crate root, the library
        root (``lib.rs``, first in :data:`_CRATE_ROOTS`) is the single canonical
        module file; emitting the sibling ``main.rs`` too would fabricate a
        spurious second edge, so only the preferred present root is offered (#358).
        """
        parts = [p for p in anchor_dir.split("/") if p]
        candidates: list[str] = []
        if parts:
            parent = "/".join(parts[:-1])
            base = parts[-1]
            named = f"{parent}/{base}{_RS}" if parent else f"{base}{_RS}"
            candidates.append(named)
        prefix = f"{anchor_dir}/" if anchor_dir else ""
        candidates.append(f"{prefix}{_MOD_FILE}")
        present_roots = [root for root in _CRATE_ROOTS if f"{prefix}{root}" in file_set]
        if present_roots:
            candidates.append(f"{prefix}{present_roots[0]}")  # prefer lib.rs
        else:
            candidates.extend(f"{prefix}{root}" for root in _CRATE_ROOTS)
        return candidates

    def _crate_root_dir(self, importer: str, file_set: set[str]) -> str | None:
        """The nearest ancestor directory of ``importer`` holding a crate root.

        Walks the importer's ancestors deepest-first and returns the first whose
        ``lib.rs`` / ``main.rs`` exists in ``file_set``; ``None`` when no crate
        root is in the map (``crate::`` then resolves nothing rather than
        guessing a root).
        """
        parts = importer.split("/")[:-1]  # drop the filename
        for i in range(len(parts), -1, -1):
            base = "/".join(parts[:i])
            prefix = f"{base}/" if base else ""
            if any(f"{prefix}{root}" in file_set for root in _CRATE_ROOTS):
                return base
        return None

    def _module_dir(self, importer: str, file_set: set[str]) -> str:
        """The directory under which ``importer``'s child modules live.

        A crate root (``lib.rs`` / ``main.rs``) or a ``mod.rs`` owns its own
        directory; any other ``foo.rs`` owns the sibling ``foo/``. A ``lib.rs`` /
        ``main.rs`` counts as a crate root only when it *is* the actual crate
        root — a same-named file nested below one (a module reached via
        ``mod main;``) is a plain module that owns its sibling ``main/`` (#358).
        """
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

    @staticmethod
    def _stem(path: str) -> str:
        """The filename of ``path`` without its ``.rs`` suffix."""
        name = path.split("/")[-1]
        return name[: -len(_RS)] if name.endswith(_RS) else name


register(RustResolver())
