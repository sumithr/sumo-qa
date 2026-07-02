# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Go import resolver for the repo-map import-edge layer (#356).

A follow-on slice of the Approach-C framework the foundation (#354) shipped.
``extract`` reads import paths off a tree-sitter parse of Go source; ``resolve``
ports Understand-Anything's Go path rules to map each import path to the
repo-relative ``.go`` file(s) it references.

Resolution rules (ported from UA):

- **go.mod discovery.** Go packages live under a module rooted at the nearest
  enclosing ``go.mod``. ``resolve`` walks the importer's ancestor directories
  **deepest first** and takes the first that holds a ``go.mod`` as the module
  root. In a multi-module monorepo (nested ``go.mod`` files) the nearest
  enclosing module governs, so a package is always resolved against its own
  module, never a parent's. A nested ``go.mod`` is also a boundary in the other
  direction: resolution never reaches *into* a subdirectory that has its own
  ``go.mod`` (a distinct module), so a root-relative import path cannot forge a
  false edge across a module boundary.
- **Module-prefix stripping.** A Go import path is ``<module-path>/<dir>`` — the
  module's declared path followed by the package directory relative to the
  module root. The declared module path is not derivable from the directory
  tree (it is an arbitrary string in ``go.mod``), and the Approach-C
  ``resolve(importer, imp, file_set)`` contract intentionally exposes only paths
  (no file contents), so the prefix is stripped *structurally*: the package
  directory is the **longest import-path suffix that is a real package
  directory** (holds at least one ``.go`` file) within the importer's module —
  down to the empty suffix, i.e. the module-root package itself, so an import
  whose path equals the module path maps to the root ``.go`` files. The
  remaining head is the stripped module prefix. Longest-suffix-first avoids
  over-stripping to a coincidental shallow directory. A candidate directory that
  can only be reached by crossing a nested ``go.mod`` belongs to a different
  module and is not a valid match (see the go.mod-boundary rule above).
- **Package-level fan-out.** Go imports are package-level, not file-level: one
  import path names a directory, and every ``.go`` file in that directory is
  part of the package. So a resolved import fans out to an edge for **every**
  ``.go`` file in the package directory, returned sorted for determinism.
- **External / stdlib drop.** A standard-library import (``fmt``) or a
  third-party dependency (``github.com/x/y``) usually has no package directory
  under the module root, so no suffix matches and resolution returns ``[]`` —
  the normal "not ours" outcome, never an error. Caveat: because the declared
  module path is not exposed to ``resolve`` (only file paths are), an external
  import whose trailing segment(s) happen to collide with a real local package
  directory is indistinguishable from a local import and yields a (false) edge;
  disambiguating it needs the ``go.mod`` ``module`` directive and is out of
  scope for this path-only contract.

Go has no relative imports and no function-local imports (import declarations
are file-level only), so every :class:`RawImport` carries ``level=0``,
``names=()`` and ``function_local=False`` — the orchestrator tags every Go
import edge ``high`` confidence.
"""

from __future__ import annotations

from sumo_qa.repo_map_resolvers.base import LanguageConfig, RawImport, register
from sumo_qa.repo_map_treesitter import TSNode, parse

GO_CONFIG = LanguageConfig(
    id="go",
    extensions=(".go",),
    barrels=(),  # Go has no package-index barrel file (imports name the dir).
)

# Grammar kinds, pinned to tree-sitter-language-pack's Go grammar (probed
# against the installed binding; the extract tests re-assert them on real
# parse output).
_IMPORT_SPEC = "import_spec"  # one import: optional alias/`_`/`.` then the path
_INTERPRETED_STRING = "interpreted_string_literal"  # "example.com/x"
_RAW_STRING = "raw_string_literal"  # `example.com/x` (back-quoted; also legal)
_STRING_CONTENT_SUFFIX = "_content"  # the *_content child holds the unquoted text

_GO_MOD = "go.mod"
_GO_SUFFIX = ".go"


class GoResolver:
    """Approach-C resolver for Go."""

    config = GO_CONFIG

    def extract(self, src: bytes) -> list[RawImport]:
        """Return the imports in ``src`` as :class:`RawImport` records.

        Walks the parse tree for each ``import_spec`` (both the single-line
        ``import "x"`` form and the parenthesised group) and records its import
        path. Go imports are file-level only, so every record is ``level=0``,
        ``names=()``, ``function_local=False``.
        """
        root = parse("go", src)
        raws: list[RawImport] = []
        for node in root.descendants():
            if node.kind == _IMPORT_SPEC:
                path = self._import_path(node)
                if path:
                    raws.append(RawImport(module=path, level=0, names=(), function_local=False))
        return raws

    @staticmethod
    def _import_path(spec: TSNode) -> str:
        """The unquoted import-path string of an ``import_spec``, or ''.

        The path is the ``import_spec``'s string-literal child (interpreted or
        raw); any alias / blank (``_``) / dot (``.``) token is a separate
        sibling, so the path is independent of it.
        """
        for child in spec.children:
            if child.kind in (_INTERPRETED_STRING, _RAW_STRING):
                return GoResolver._string_content(child)
        return ""  # pragma: no cover -- defensive: an import_spec always has a string path

    @staticmethod
    def _string_content(literal: TSNode) -> str:
        """The unquoted text of a string literal node.

        Both interpreted and raw string literals expose their inner text as a
        ``*_content`` child (``interpreted_string_literal_content`` /
        ``raw_string_literal_content``), so the quote/back-quote delimiters are
        excluded without slicing.
        """
        for child in literal.children:
            if child.kind.endswith(_STRING_CONTENT_SUFFIX):
                return child.text
        return ""  # pragma: no cover -- defensive: a non-empty literal has a content child

    def resolve(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        """Map one import path to the repo-relative ``.go`` file(s) it references.

        Resolves against the importer's nearest enclosing ``go.mod`` module
        root, strips the module prefix by longest-suffix matching (the empty
        suffix maps to the module-root package), skips any candidate that lies
        beyond a nested ``go.mod`` boundary, and fans the resolved package
        directory out to every ``.go`` file it contains. Returns ``[]`` for an
        empty path, an importer with no enclosing ``go.mod``, or an import that
        matches no package directory within the module (external package /
        stdlib).
        """
        if not imp.module:
            return []
        module_root = self._module_root(importer, file_set)
        if module_root is None:
            return []
        segments = [seg for seg in imp.module.split("/") if seg]
        # Strip the module prefix by taking the LONGEST import-path suffix that
        # is a real package directory under the module root: drop 0 leading
        # segments first (whole path), then 1, then 2, … down to dropping ALL
        # segments (the empty suffix -> the module-root package itself, so an
        # import whose path equals the module path resolves the root `.go`
        # files), and stop at the first suffix whose directory holds a `.go`
        # file. The remaining head is the module prefix. A candidate reached by
        # crossing an intervening (nested) `go.mod` is a DIFFERENT module and is
        # skipped. A path that matches nothing is external/stdlib -> [].
        for strip in range(len(segments) + 1):
            package_dir = self._join(module_root, segments[strip:])
            if self._crosses_nested_module(module_root, package_dir, file_set):
                continue
            files = self._go_files_in_dir(package_dir, file_set)
            if files:
                return files
        return []

    @staticmethod
    def _module_root(importer: str, file_set: set[str]) -> str | None:
        """The repo-relative dir of the importer's nearest enclosing ``go.mod``.

        Walks the importer's ancestor directories **deepest first** so a nested
        module (``service/go.mod``) wins over an outer one (``go.mod``) — the
        multi-module-monorepo governance rule. Returns ``None`` when no ancestor
        holds a ``go.mod`` (resolution then drops; GOPATH-mode is out of scope).
        """
        dir_parts = importer.split("/")[:-1]  # drop the filename
        for depth in range(len(dir_parts), -1, -1):
            base = dir_parts[:depth]
            candidate = "/".join([*base, _GO_MOD]) if base else _GO_MOD
            if candidate in file_set:
                return "/".join(base)
        return None

    @staticmethod
    def _crosses_nested_module(module_root: str, package_dir: str, file_set: set[str]) -> bool:
        """True if ``package_dir`` lies beyond a nested ``go.mod`` boundary.

        The importer's module spans ``module_root`` down to (but not across) any
        deeper ``go.mod``. A candidate package directory reached by passing
        through an intervening ``go.mod`` — one sitting strictly below
        ``module_root`` and at or above ``package_dir`` — belongs to a distinct
        nested module, so an edge to it would be a false cross-module link.
        Walks the candidate's ancestors below the module root (``package_dir``
        itself included) and reports the first such boundary ``go.mod``.
        """
        if package_dir == module_root:
            return False  # the root package of the importer's own module
        root_depth = len(module_root.split("/")) if module_root else 0
        pkg_parts = package_dir.split("/")
        for depth in range(root_depth + 1, len(pkg_parts) + 1):
            if "/".join([*pkg_parts[:depth], _GO_MOD]) in file_set:
                return True
        return False

    @staticmethod
    def _join(module_root: str, rel: list[str]) -> str:
        """Join the module root and the package's module-relative segments."""
        parts = [module_root, *rel] if module_root else rel
        return "/".join(parts)

    @staticmethod
    def _go_files_in_dir(package_dir: str, file_set: set[str]) -> list[str]:
        """Every ``.go`` file directly inside ``package_dir`` (sorted).

        Go packages are flat — only files in the directory itself, not nested
        sub-packages — so a file matches when its parent directory equals
        ``package_dir`` exactly.
        """
        hits: list[str] = []
        for path in file_set:
            if not path.endswith(_GO_SUFFIX):
                continue
            parent = path.rsplit("/", 1)[0] if "/" in path else ""
            if parent == package_dir:
                hits.append(path)
        return sorted(hits)


register(GoResolver())
