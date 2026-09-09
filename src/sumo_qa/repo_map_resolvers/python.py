# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Python import resolver for the repo-map import-edge layer (#354).

The reference resolver of the Approach-C framework. ``extract`` reads imports
off a tree-sitter parse of Python source; ``resolve`` ports Understand-
Anything's path rules to map each raw import to the repo-relative file(s) it
references.

Resolution rules (ported from UA, then aligned with the import system):

- **Relative imports** are dot-anchored: ``level`` dots walk up from the
  importing file's package. ``from . import x`` (level 1) looks in the
  importer's own package; ``from .. import x`` (level 2) one package up. The
  anchored package's root is the parent of the topmost regular package above
  it (its own parent when there is none), and that root is the ONLY search
  prefix: the dots name the importer's own package, which is rooted in a
  single ``sys.path`` entry, so portions under shallower roots do not merge
  in. From there it runs the same component walk as an absolute import, over
  that one prefix rather than a whole ancestor chain.
- **Absolute imports** walk the importer's ancestors as candidate roots,
  **deepest first** (the effective ``sys.path`` order), so a monorepo /
  multi-root layout resolves against the nearest source root before a
  shallower one.
- **One component walk for both forms**: each dotted component is owned by
  the first search prefix holding a regular package (``comp/__init__.py``)
  or a module (``comp.py``). A regular package confines the rest of the
  lookup to its own directory, so a missing leaf beneath it never falls
  through to a shallower root. A plain module has no submodules, so it
  shadows a same-named directory and stops the walk (``import pkg.sub`` with
  ``pkg.py`` present resolves to ``pkg.py``, never ``pkg/sub.py``).
- **Regular package over same-named module** (#461): when both ``p.py`` and
  ``p/__init__.py`` exist at one import path, the runtime imports the regular
  package, so only ``p/__init__.py`` is retained and ``p.py`` never becomes an
  edge. A ``p.py`` beside a same-named *namespace* dir (no ``__init__.py``)
  is still the module and still shadows descent into the dir.
- **PEP 420 implicit namespace packages**: a directory need not contain
  ``__init__.py`` to be a package. A component with no owning prefix keeps
  every prefix as a namespace portion, merged in order, and a regular
  package or module at any later prefix still wins over nearer portions.
- **Specifier submodule probing**: ``from pkg import sub`` may name a
  submodule rather than a member, so each specifier is looked up beneath the
  resolved module as ``pkg/sub.py`` / ``pkg/sub/__init__.py`` (same
  precedence), never beneath a plain module.
- **Wildcard / qualified / attribute specifiers are skipped**: ``from x
  import *`` carries no specifier to probe, a dotted specifier (rare) isn't a
  plain submodule name, and a specifier naming an attribute every module
  object carries (``__init__``, ``__doc__``) binds that attribute rather
  than importing a submodule; all yield only the module-level resolution,
  never a fabricated path.

A node is tagged ``function_local`` (→ ``medium`` confidence downstream) when
its import statement sits inside a ``function_definition`` body; module-level
and class-body imports are not (→ ``high``).
"""

from __future__ import annotations

import types

from sumo_qa.repo_map_resolvers.base import LanguageConfig, RawImport, register
from sumo_qa.repo_map_treesitter import TSNode, parse

PYTHON_CONFIG = LanguageConfig(
    id="python",
    extensions=(".py", ".pyi"),
    barrels=("__init__.py",),
)

# Grammar kinds, pinned to tree-sitter-language-pack's Python grammar (probed
# against the installed binding; the binding-contract test re-asserts them).
_IMPORT_STMT = "import_statement"  # `import a.b`
_IMPORT_FROM_STMT = "import_from_statement"  # `from a.b import c`
_DOTTED_NAME = "dotted_name"  # `a.b`
_RELATIVE_IMPORT = "relative_import"  # `.pkg` / `..`
_IMPORT_PREFIX = "import_prefix"  # the leading dots of a relative import
_ALIASED_IMPORT = "aliased_import"  # `c as d`
_WILDCARD_IMPORT = "wildcard_import"  # `*`
_FUNCTION_DEF = "function_definition"

# A module INSTANCE (not the ``ModuleType`` class, whose ``hasattr`` would also
# answer for ``type``'s attributes such as ``mro``): the names it carries are
# bound by ``from pkg import <name>`` without ever importing a submodule. The
# loader adds a few more to a really imported module that a bare instance
# lacks; those are listed explicitly.
_MODULE_INSTANCE = types.ModuleType("_sumo_qa_module_probe")
_LOADER_ADDED_ATTRIBUTES = frozenset({"__file__", "__cached__", "__path__", "__builtins__"})


def _is_module_attribute(name: str) -> bool:
    """True when ``from pkg import <name>`` binds an attribute every imported
    module (or package) already has, so the import system never tries the
    submodule ``pkg/<name>.py``."""
    return name in _LOADER_ADDED_ATTRIBUTES or hasattr(_MODULE_INSTANCE, name)


class PythonResolver:
    """Approach-C resolver for Python (the framework's reference resolver)."""

    config = PYTHON_CONFIG

    def extract(self, src: bytes) -> list[RawImport]:
        """Return the imports in ``src`` as :class:`RawImport` records.

        Walks the parse tree, recording each ``import`` / ``from … import …``
        statement. ``function_local`` is set when the statement is lexically
        inside a function body (so the orchestrator can down-rank a lazy
        import to ``medium`` confidence).
        """
        root = parse("python", src)
        raws: list[RawImport] = []
        self._collect(root, function_depth=0, out=raws)
        return raws

    def _collect(self, node: TSNode, *, function_depth: int, out: list[RawImport]) -> None:
        kind = node.kind
        if kind == _IMPORT_STMT:
            out.extend(self._plain_imports(node, function_depth > 0))
            return
        if kind == _IMPORT_FROM_STMT:
            from_import = self._from_import(node, function_depth > 0)
            if from_import is not None:
                out.append(from_import)
            return
        next_depth = function_depth + 1 if kind == _FUNCTION_DEF else function_depth
        for child in node.children:
            self._collect(child, function_depth=next_depth, out=out)

    @staticmethod
    def _plain_imports(node: TSNode, function_local: bool) -> list[RawImport]:
        """`import a.b, c.d` -> one RawImport per dotted module (level 0)."""
        raws: list[RawImport] = []
        for child in node.children:
            module = PythonResolver._module_of(child)
            if module:
                raws.append(
                    RawImport(module=module, level=0, names=(), function_local=function_local)
                )
        return raws

    @staticmethod
    def _from_import(node: TSNode, function_local: bool) -> RawImport | None:
        """`from <module> import <names>` -> one RawImport.

        Handles the relative-import dot count (``level``) and collects each
        imported specifier into ``names`` (skipping the wildcard ``*`` and the
        alias tail of ``x as y``). The module token is the first ``dotted_name``
        / ``relative_import`` child; everything after the ``import`` keyword is a
        specifier.
        """
        level = 0
        module = ""
        names: list[str] = []
        seen_import_kw = False
        for child in node.children:
            kind = child.kind
            if kind == "import":
                seen_import_kw = True
                continue
            if not seen_import_kw:
                # Module side: either an absolute dotted name or a relative
                # import (which carries the dot count and an optional tail).
                if kind == _RELATIVE_IMPORT:
                    level, tail = PythonResolver._relative_parts(child)
                    module = tail
                elif kind == _DOTTED_NAME:
                    module = child.text
                continue
            # Specifier side (after `import`).
            if kind == _WILDCARD_IMPORT:
                continue  # `from x import *` -> no specifier to probe
            if kind == _ALIASED_IMPORT:
                spec = PythonResolver._aliased_target(child)
                if spec:
                    names.append(spec)
            elif kind == _DOTTED_NAME:
                names.append(child.text)
        if level == 0 and not module:  # pragma: no cover -- defensive: the grammar
            return None  # always gives a from-import a module side or a relative_import
        return RawImport(
            module=module,
            level=level,
            names=tuple(names),
            function_local=function_local,
        )

    @staticmethod
    def _relative_parts(node: TSNode) -> tuple[int, str]:
        """A ``relative_import`` node -> (dot count, dotted tail or '').

        ``from . import x`` -> (1, ''); ``from ..pkg.sub import x`` ->
        (2, 'pkg.sub'). The leading dots live in an ``import_prefix`` child
        (one ``.`` token per level); the optional module tail is a sibling
        ``dotted_name``.
        """
        level = 0
        tail = ""
        for child in node.children:
            if child.kind == _IMPORT_PREFIX:
                level = sum(1 for tok in child.children if tok.kind == ".")
            elif child.kind == _DOTTED_NAME:
                tail = child.text
        return level, tail

    @staticmethod
    def _aliased_target(node: TSNode) -> str:
        """`c as d` -> 'c' (the imported name, not the local alias)."""
        for child in node.children:
            if child.kind == _DOTTED_NAME:
                return child.text
        return ""  # pragma: no cover -- defensive: an aliased_import always has a dotted_name

    @staticmethod
    def _module_of(node: TSNode) -> str:
        """The dotted module string of a plain-import child, or ''.

        `import a.b` -> 'a.b'; `import a.b as c` (aliased) -> 'a.b'.
        """
        if node.kind == _DOTTED_NAME:
            return node.text
        if node.kind == _ALIASED_IMPORT:
            return PythonResolver._aliased_target(node)
        return ""

    def resolve(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        """Map one raw import to the repo-relative file path(s) it references.

        Returns repo-relative paths that exist in ``file_set``; an empty list
        means the import points outside the repo (external package, stdlib) or
        could not be resolved -- never an error. Deterministic: results are
        de-duplicated preserving first-seen order.

        Both import forms feed one component walk (``_walk``): a relative
        import anchors the walk at the importer's package with a single
        search prefix, an absolute import starts it from the importer's
        ancestor roots in ``sys.path`` order (deepest first).
        """
        if imp.level > 0:
            anchor = self._relative_anchor(importer, imp, file_set)
            if anchor is None:
                return []
            root, parts = anchor
            search = [root]  # exactly one prefix: see _relative_anchor
        else:
            search = self._ancestor_roots(importer)
            parts = imp.module.split(".")
        return self._walk(search, parts, imp.names, file_set)

    def _relative_anchor(
        self, importer: str, imp: RawImport, file_set: set[str]
    ) -> tuple[list[str], list[str]] | None:
        """Dot-anchored relative resolution: the ONE search prefix and the
        dotted components to walk from it, or ``None`` when the dots
        overshoot.

        Returning a single prefix rather than a list of them is deliberate:
        it makes the single-root rule below structural, so a later change
        cannot quietly reintroduce cross-root merging (and with it the false
        edge from ``app/pkg/m.py`` to a root-level ``pkg/x.py``) by appending
        to a list. ``resolve`` wraps it for ``_walk``.

        ``level`` dots walk up from the importer's package directory. The
        importer's own directory is level 1 (``from .``), one up is level 2,
        and so on. The module tail (``from ..pkg.sub``) extends the anchored
        package before the leaf.

        The anchored package's ROOT (the ``sys.path`` entry it is imported
        from) is the parent of the topmost regular package in the chain of
        ``__init__.py`` directories above it: ``pkg/sub/`` under
        ``pkg/__init__.py`` is ``pkg.sub`` rooted at the repo root, so the
        walked components start at ``pkg`` and the lookup can never escape
        ``pkg/``. With no regular ancestor the anchored package's own parent
        is taken as the root (the deepest-root convention absolute imports
        use), and the walk starts at the package itself, so ``from . import
        x`` keeps the containing barrel as a dependency.

        That root is the SINGLE search prefix -- unlike an absolute import,
        a relative one does not also search the root's ancestors. A dotted
        import names a package the runtime looks up across every
        ``sys.path`` entry, but the dots of a relative import name the
        importer's OWN package, which is rooted in exactly one of them.
        Merging portions from shallower roots would emit edges the runtime
        never loads: ``from . import x`` in ``app/pkg/m.py`` must not reach
        a root-level ``pkg/x.py``, because ``app/pkg`` and ``pkg`` are the
        same namespace package only when both ``app/`` and the repo root are
        on ``sys.path``. Nothing in a file set says that, so those portions
        stay unmerged -- an under-edge rather than a fabricated one, the
        same convention used for a namespace package whose real root is a
        shallower ancestor than its parent (``app/pkg/sub/deep/`` imported
        as ``pkg.sub.deep`` from ``app/``).

        A relative import whose dots consume the importer's whole directory
        path (``up >= len(package)``) is resolved as nothing: it has walked
        off the top of the repo, and anchoring at the repo root would
        fabricate a false edge to a root-level file. Note this counts
        DIRECTORY components, not package ones, so it only catches the
        overshoot when the package chain starts at the repo root. Dots that
        climb past the topmost ``__init__.py`` into a directory that is
        really a ``sys.path`` root still resolve, where the runtime raises
        "attempted relative import beyond top-level package" -- a known
        over-edge inherited from the previous resolver, not closed here.
        """
        package = importer.split("/")[:-1]  # the importer's package is its directory
        up = imp.level - 1  # `from .` (level 1) anchors at the importer's own package
        if up >= len(package):
            return None
        base = package[: len(package) - up] if up else list(package)
        tail = imp.module.split(".") if imp.module else []
        # Climb while the parent directory is a regular package: the chain of
        # __init__.py directories fixes the root at the topmost one's parent.
        top = len(base) - 1
        while top > 0 and any(
            barrel in file_set for barrel in self._barrels_of("/".join(base[:top]))
        ):
            top -= 1
        root = base[:top]
        return root, [*base[top:], *tail]

    @staticmethod
    def _ancestor_roots(importer: str) -> list[list[str]]:
        """Candidate source roots: the importer's directory and every ancestor
        down to the repo root, **deepest first** (the effective ``sys.path``
        order for an absolute import)."""
        parts = importer.split("/")[:-1]  # drop the filename
        roots: list[list[str]] = []
        for i in range(len(parts), -1, -1):
            roots.append(parts[:i])
        return roots

    def _walk(
        self,
        search: list[list[str]],
        parts: list[str],
        names: tuple[str, ...],
        file_set: set[str],
    ) -> list[str]:
        """Resolve dotted ``parts`` (then each specifier in ``names``) over the
        ordered ``search`` prefixes, the way the import system walks
        ``sys.path`` and then each package's ``__path__``.

        Per component, the FIRST prefix holding a regular package
        (``<comp>/__init__.py``) or a module (``<comp>.py``) owns it:

        - a regular package confines the rest of the lookup to its own
          directory, so a miss beneath it is final and a shallower prefix can
          never supply the leaf (a regular package also beats a same-named
          module in the same prefix, #461);
        - a plain module (no barrel beside it) has no submodules: the walk
          stops at that file, which shadows a same-named namespace dir and
          suppresses descent (``import pkg.sub`` / ``from pkg import sub`` with
          ``pkg.py`` present resolve to ``pkg.py``, never ``pkg/sub.py``);
        - no owner means the component is a PEP 420 namespace package whose
          portions merge across every prefix, in order, so the walk keeps all
          of them (a regular package at ANY later prefix still wins, since the
          owner search runs across all prefixes before merging).

        The leaf takes the same rule and contributes its file(s); specifiers
        are then looked up beneath the leaf (or its merged portions). A
        qualified (dotted) specifier is skipped -- it isn't a plain submodule
        name -- and so is a specifier naming an attribute every module object
        carries (``from pkg import __init__`` binds the attribute; no
        submodule import happens). Order is leaf first, then specifiers in
        source order, so first-seen de-dup is deterministic.
        """
        for comp in parts[:-1]:
            owner = self._owner(search, comp, file_set)
            if owner is None:
                search = [[*prefix, comp] for prefix in search]  # namespace portions
                continue
            path = "/".join([*owner, comp])
            if self._is_plain_module(path, file_set):
                return [f"{path}.py"]  # a module has no submodules: shadowed descent
            search = [[*owner, comp]]  # a regular package confines the lookup
        resolved: list[str] = []
        leaf = parts[-1]
        owner = self._owner(search, leaf, file_set)
        if owner is None:
            search = [[*prefix, leaf] for prefix in search]
        else:
            path = "/".join([*owner, leaf])
            resolved.extend(self._leaf_files(path, file_set))
            if self._is_plain_module(path, file_set):
                return resolved  # specifiers are members of the module, never submodules
            search = [[*owner, leaf]]
        for name in names:
            if "." in name or _is_module_attribute(name):
                # A qualified specifier is not a plain submodule name, and a
                # name every module object already carries (``__init__``,
                # ``__doc__``, ...) binds that attribute: the import system
                # only tries a submodule when the attribute lookup fails.
                continue
            owner = self._owner(search, name, file_set)
            if owner is None:
                continue
            for cand in self._leaf_files("/".join([*owner, name]), file_set):
                if cand not in resolved:
                    resolved.append(cand)
        return resolved

    def _owner(self, search: list[list[str]], comp: str, file_set: set[str]) -> list[str] | None:
        """The first search prefix under which ``comp`` is a regular package
        or a module, or ``None`` (``comp`` is at most a namespace package)."""
        for prefix in search:
            path = "/".join([*prefix, comp])
            if f"{path}.py" in file_set or any(
                barrel in file_set for barrel in self._barrels_of(path)
            ):
                return prefix
        return None

    def _barrels_of(self, path: str) -> list[str]:
        """The package-barrel candidate(s) for import path ``path``."""
        return [f"{path}/{barrel}" for barrel in self.config.barrels]

    def _is_plain_module(self, path: str, file_set: set[str]) -> bool:
        """``path.py`` exists and NO regular-package barrel sits beside it.

        Only a plain module shadows a same-named directory; when
        ``path/__init__.py`` also exists the runtime imports the package and
        the ``.py`` is the losing candidate (#461)."""
        if f"{path}.py" not in file_set:
            return False
        return not any(barrel in file_set for barrel in self._barrels_of(path))

    def _leaf_files(self, path: str, file_set: set[str]) -> list[str]:
        """The existing file(s) for an owned import path, in precedence order.

        Both ``path.py`` and ``path/__init__.py`` present -> only the regular
        package barrel (runtime precedence, #461). Otherwise whichever of the
        module or the barrel exists."""
        barrels = [barrel for barrel in self._barrels_of(path) if barrel in file_set]
        module = f"{path}.py"
        if module in file_set and barrels:
            return barrels
        # Past that guard `barrels` is empty whenever the module exists, so
        # there is no module-plus-barrel result to build: that combination is
        # precisely what #461 forbids.
        return [module] if module in file_set else barrels


register(PythonResolver())
