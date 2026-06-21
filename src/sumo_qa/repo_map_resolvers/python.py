# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Python import resolver for the repo-map import-edge layer (#354).

The reference resolver of the Approach-C framework. ``extract`` reads imports
off a tree-sitter parse of Python source; ``resolve`` ports Understand-
Anything's path rules to map each raw import to the repo-relative file(s) it
references.

Resolution rules (ported from UA):

- **Relative imports** are dot-anchored: ``level`` dots walk up from the
  importing file's package. ``from . import x`` (level 1) looks in the
  importer's own package; ``from .. import x`` (level 2) one package up.
- **PEP-328 implicit namespace packages**: a directory need not contain
  ``__init__.py`` to be a package. Resolution probes both ``pkg/mod.py`` and
  ``pkg/__init__.py`` and accepts whichever exists, without requiring the
  ``__init__.py`` to gate the directory.
- **Absolute imports** walk the importer's ancestors as candidate roots,
  **deepest first**, so a monorepo / multi-root layout resolves against the
  nearest source root before a shallower one.
- **Specifier submodule probing**: ``from pkg import sub`` may name a submodule
  rather than a member, so each specifier is also probed as ``pkg/sub.py`` /
  ``pkg/sub/__init__.py``.
- **Wildcard / qualified specifiers are skipped**: ``from x import *`` carries
  no specifier to probe, and a dotted specifier (rare) isn't a plain submodule
  name; both yield only the module-level resolution, never a fabricated path.

A node is tagged ``function_local`` (→ ``medium`` confidence downstream) when
its import statement sits inside a ``function_definition`` body; module-level
and class-body imports are not (→ ``high``).
"""

from __future__ import annotations

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
        could not be resolved — never an error. Deterministic: results are
        de-duplicated preserving first-seen order.

        Relative imports anchor unambiguously to the importer's package, so
        their candidates are simply filtered against ``file_set``. Absolute
        imports walk candidate roots and stop at the first that has any match,
        so the file set is consulted during the walk (see ``_resolve_absolute``).
        """
        if imp.level > 0:
            candidates = self._resolve_relative(importer, imp)
            resolved: list[str] = []
            for cand in candidates:
                if cand in file_set and cand not in resolved:
                    resolved.append(cand)
            return resolved
        return self._resolve_absolute(importer, imp, file_set)

    def _resolve_relative(self, importer: str, imp: RawImport) -> list[str]:
        """Dot-anchored relative resolution.

        ``level`` dots walk up from the importer's package directory. The
        importer's own directory is level 1 (``from .``), one up is level 2,
        and so on. The module tail (``from ..pkg.sub``) extends the anchored
        base before probing.
        """
        parts = importer.split("/")
        # The importer's package is its directory; the file itself is parts[-1].
        package = parts[:-1]
        # `from .` (level 1) anchors at the importer's own package; each extra
        # dot strips one more directory.
        up = imp.level - 1
        # A relative import that consumes ALL package components (up == len) or
        # more walks past the top-level package - Python rejects this ("attempted
        # relative import beyond top-level package"). Anchoring at the repo root
        # would fabricate a false edge to a root-level file, so resolve nothing.
        if up >= len(package):
            return []
        base = package[: len(package) - up] if up else list(package)
        tail = imp.module.split(".") if imp.module else []
        anchored = "/".join(base + tail) if (base or tail) else ""
        return self._probe(anchored, imp.names)

    def _resolve_absolute(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        """``sys.path`` walk-up: try each importer ancestor as a candidate root,
        deepest first, and take the FIRST root that resolves.

        Exactly one source root is on the effective ``sys.path`` for a given
        absolute import, so the nearest (deepest) ancestor that produces any
        match wins; shallower roots that happen to hold a same-named module are
        not the imported one and must not fabricate a second edge. Returns the
        probe paths that exist under that winning root."""
        module_parts = imp.module.split(".")
        for root in self._ancestor_roots(importer):
            base = "/".join([*root, *module_parts]) if root else "/".join(module_parts)
            hits: list[str] = []
            for cand in self._probe(base, imp.names, module_parts, root, file_set):
                if cand in file_set and cand not in hits:
                    hits.append(cand)
            if hits:
                return hits
        return []

    def _shadowing_module(
        self, module_parts: list[str], root: list[str], file_set: set[str]
    ) -> str | None:
        """The path of an INTERMEDIATE dotted-module component that resolves to a
        ``.py`` module, shadowing a same-named package dir, or ``None``.

        ``import pkg.sub`` requires ``pkg`` to be a package: a ``.py`` file
        shadows a same-named dir, and a plain module has no submodules. So if
        ``pkg.py`` exists, ``pkg`` is a module and ``pkg.sub`` cannot descend into
        ``pkg/``: the import resolves to ``pkg.py`` and ``pkg/sub.py`` is a false
        edge. Walks the module components (excluding the final one, which is the
        leaf the caller probes normally) and returns the first whose ``.py``
        sibling exists. Single-component modules never shadow (no intermediate)."""
        for depth in range(1, len(module_parts)):
            prefix = [*root, *module_parts[:depth]]
            module_file = "/".join(prefix) + ".py"
            if module_file in file_set:
                return module_file
        return None

    @staticmethod
    def _ancestor_roots(importer: str) -> list[list[str]]:
        """Candidate source roots: the importer's directory and every ancestor
        down to the repo root, **deepest first**."""
        parts = importer.split("/")[:-1]  # drop the filename
        roots: list[list[str]] = []
        for i in range(len(parts), -1, -1):
            roots.append(parts[:i])
        return roots

    def _probe(
        self,
        base: str,
        names: tuple[str, ...],
        module_parts: list[str] | None = None,
        root: list[str] | None = None,
        file_set: set[str] | None = None,
    ) -> list[str]:
        """Module-path -> candidate file paths.

        Probes ``base.py`` and (PEP-328 implicit namespace package) the
        package barrel ``base/__init__.py``; then probes each specifier as a
        submodule ``base/<name>.py`` / ``base/<name>/__init__.py``. A
        qualified (dotted) specifier is skipped — it isn't a plain submodule
        name. Order is module first, then specifiers in source order, so
        ``resolve``'s first-seen de-dup is deterministic.

        When ``module_parts``/``root``/``file_set`` are supplied (the absolute
        path), an intermediate dotted-module component shadowed by a ``.py``
        module collapses resolution to that shadowing file: ``import pkg.sub``
        with ``pkg.py`` present resolves to ``pkg.py``, never ``pkg/sub.py`` (a
        module has no submodules)."""
        if module_parts is not None and root is not None and file_set is not None:
            shadow = self._shadowing_module(module_parts, root, file_set)
            if shadow is not None:
                return [shadow]
        candidates: list[str] = []
        if base:
            candidates.append(f"{base}.py")
            for barrel in self.config.barrels:
                candidates.append(f"{base}/{barrel}")
        for name in names:
            if "." in name:
                continue  # qualified specifier: not a plain submodule
            sub = f"{base}/{name}" if base else name
            candidates.append(f"{sub}.py")
            for barrel in self.config.barrels:
                candidates.append(f"{sub}/{barrel}")
        return candidates


register(PythonResolver())
