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
  directory is the **longest non-empty import-path suffix that is a real package
  directory** (holds at least one non-test ``.go`` file) within the module. The
  remaining head is the stripped module prefix. Only suffixes of length >= 1 are
  tried: an import that matches no local package directory resolves to ``[]``
  (external/stdlib, or a bare module-path import — see Known limitations). The
  module-root package (the empty suffix) is deliberately never a fallback,
  because it cannot be told from an external import that simply matches nothing,
  so using it would make every unresolved import falsely edge to the root
  ``.go`` files. Longest-suffix-first avoids over-stripping to a coincidental
  shallow directory. When that longest real match lies beyond a nested
  ``go.mod`` it belongs to a *different* module: the import targets that nested
  module (external to this contract) and is **dropped outright** — resolution
  does not then fall through to a shorter same-module suffix, which could
  otherwise forge a false edge to a coincidental decoy dir sharing the trailing
  segment (see the go.mod-boundary rule above).
- **Package-level fan-out.** Go imports are package-level, not file-level: one
  import path names a directory, and every non-test ``.go`` file in that
  directory is part of the package. So a resolved import fans out to an edge for
  **every** non-test ``.go`` file in the package directory, returned sorted for
  determinism. ``*_test.go`` files are excluded — they are not compiled into the
  imported package for a production import, so fanning out to them would forge a
  false source->test edge.
- **External / stdlib drop.** A standard-library import is dropped *before*
  suffix matching by a first-path-segment guard: its leading segment is a Go
  stdlib top-level package name (``fmt``, ``net`` in ``net/http``), which a
  local module import — rooted at the module's own declared path — never is.
  This makes the drop robust even when a multi-segment stdlib path's trailing
  segment collides with a real local package dir (``net/http`` vs a local
  ``http/``); without the guard such a path would be suffix-matched onto that
  dir and forge a false edge (see Known limitations). A third-party dependency
  (``github.com/x/y``) has no package directory under the module root, so no
  suffix matches and resolution returns ``[]`` — the normal "not ours"
  outcome, never an error.

Go has no relative imports and no function-local imports (import declarations
are file-level only), so every :class:`RawImport` carries ``level=0``,
``names=()`` and ``function_local=False`` — the orchestrator tags every Go
import edge ``high`` confidence.

Known limitations
-----------------

The first two below share one root cause: the path-only ``resolve`` contract
does not expose the ``go.mod`` ``module`` directive, so a genuinely local import
and an external one that happens to line up with the directory tree cannot be
told apart. Each is a *safe* outcome (a pinned false edge or a missing edge),
tracked here so a future fix is a deliberate, reviewed change.

- **External-name collision (false edge, pinned).** A *third-party* import
  whose trailing segment(s) collide with a real local package directory (e.g.
  ``github.com/ext/widget`` with a local ``widget/`` dir) is indistinguishable
  from a local import and yields a (false) edge. Disambiguating it needs the
  module path. (The *standard-library* sub-case — e.g. ``net/http`` colliding
  with a local ``http/`` — is no longer a limitation: it is dropped by the
  first-path-segment stdlib guard described under "External / stdlib drop",
  since a stdlib import's leading segment is a fixed, well-known name.)
- **Bare module-root import (missing edge).** An import whose path equals the
  module path (the module-root package itself) is NOT resolved: the resolver
  cannot tell it from an external import that simply matches no local package,
  so resolving it (via an empty stripped suffix) would make every unresolved
  stdlib/external import falsely edge to the module-root ``.go`` files. Such an
  import returns ``[]`` — the safe missing edge is preferred over a systematic
  false one.
- **Vendored imports (missing edge).** Imports satisfied by a ``vendor/`` tree
  (``vendor/<import-path>/*.go``) are not resolved: candidate package dirs are
  built only as ``<module-root>/<stripped suffix>``, never under ``vendor/``.
  This is a safe false-negative, not implemented in this slice.
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
_TEST_GO_SUFFIX = "_test.go"  # `*_test.go`: not part of the imported package

# Go standard-library top-level import roots -- the FIRST path segment of a
# stdlib import. Basis: the Go 1.24 standard library's top-level `src/`
# package directories. A LOCAL module import is rooted at the module's own
# declared path (an arbitrary string from `go.mod`, e.g. `example.com/...`),
# whose first segment is never one of these; an EXTERNAL import
# (`github.com/...`) likewise never leads with a stdlib segment. So a raw
# import whose first segment is in this set is standard-library and is dropped
# BEFORE structural suffix matching -- otherwise a multi-segment stdlib import
# (`net/http`, `encoding/json`) whose trailing segment collides with a real
# local package dir (`http/`, `json/`) would be suffix-matched onto that dir
# and forge a false stdlib->local edge. (The external-name collision below is
# a separate, still-documented limitation: its first segment is not a stdlib
# name, so this guard does not -- and must not -- cover it.)
_GO_STDLIB_ROOTS = frozenset(
    {
        "bufio",
        "bytes",
        "cmp",
        "compress",
        "container",
        "context",
        "crypto",
        "database",
        "debug",
        "embed",
        "encoding",
        "errors",
        "expvar",
        "flag",
        "fmt",
        "go",
        "hash",
        "html",
        "image",
        "index",
        "io",
        "iter",
        "log",
        "maps",
        "math",
        "mime",
        "net",
        "os",
        "path",
        "plugin",
        "reflect",
        "regexp",
        "runtime",
        "slices",
        "sort",
        "strconv",
        "strings",
        "structs",
        "sync",
        "syscall",
        "testing",
        "text",
        "time",
        "unicode",
        "unique",
        "unsafe",
        "weak",
    }
)


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
        root, strips the module prefix by longest non-empty-suffix matching, and
        fans the resolved package directory out to every non-test ``.go`` file it
        contains. When the longest real package-dir match lies beyond a nested
        ``go.mod`` the import belongs to that distinct module and is dropped
        outright (no fall-through to a shorter same-module decoy). Returns ``[]``
        for an empty path, an importer with no enclosing ``go.mod``, an import
        whose target lives in a nested module, or an import that matches no
        package directory within the module (external package / stdlib, or a bare
        module-root import — see the module Known limitations).
        """
        if not imp.module:
            return []
        segments = [seg for seg in imp.module.split("/") if seg]
        if segments and segments[0] in _GO_STDLIB_ROOTS:
            # Standard-library import: its FIRST path segment is a Go stdlib
            # top-level package, which a local module import (rooted at the
            # module's own declared path) never is. Reject it on the RAW import
            # path, BEFORE any module-prefix stripping / suffix matching, so a
            # multi-segment stdlib import (`net/http`, `encoding/json`) cannot
            # be suffix-matched onto a local package dir whose name collides
            # with its trailing segment (`http/`, `json/`) -- see the
            # `_GO_STDLIB_ROOTS` note. External-name collisions remain a
            # documented limitation (their first segment is not a stdlib name).
            return []
        module_root = self._module_root(importer, file_set)
        if module_root is None:
            return []
        # Strip the module prefix by taking the LONGEST import-path suffix that
        # is a real package directory under the module root: drop 0 leading
        # segments first (whole path), then 1, then 2, … down to dropping all but
        # the last segment (suffix length 1), and stop at the first suffix whose
        # directory holds a non-test `.go` file. Only NON-EMPTY suffixes are
        # tried: the module-root package (the empty suffix) is deliberately NOT a
        # fallback, because the path-only contract cannot distinguish a genuine
        # module-path import from an external import that simply matches no local
        # package, so resolving the empty suffix would make EVERY unresolved
        # stdlib/external import falsely edge to the module-root `.go` files (see
        # the module docstring's Known limitations). The remaining head is the
        # module prefix. If that first real match is reached by crossing an
        # intervening (nested) `go.mod` it is a DIFFERENT module, so the import is
        # dropped outright (NOT retried at a shorter suffix, which could hit a
        # decoy). A path that matches nothing is external/stdlib -> [].
        for strip in range(len(segments)):
            package_dir = self._join(module_root, segments[strip:])
            files = self._go_files_in_dir(package_dir, file_set)
            if not files:
                continue
            if self._crosses_nested_module(module_root, package_dir, file_set):
                # This suffix is the LONGEST that maps onto a real package dir,
                # but that dir lives beyond a nested `go.mod` (a distinct
                # module): the import targets that nested module, which the
                # path-only contract treats as external. Drop the import — do
                # NOT fall through to a SHORTER same-module suffix that happens
                # to share the trailing segment, which would forge a false edge
                # to a decoy dir (e.g. import `.../service/core` with a nested
                # `service/go.mod` must not resolve to a root-level `core/`).
                return []
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

        Only ever called with a ``package_dir`` strictly below ``module_root``
        (a non-empty stripped suffix), so ``package_dir == module_root`` cannot
        arise: the module-root package is not a resolution target.
        """
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
        """Every non-test ``.go`` file directly inside ``package_dir`` (sorted).

        Go packages are flat — only files in the directory itself, not nested
        sub-packages — so a file matches when its parent directory equals
        ``package_dir`` exactly. ``*_test.go`` files are excluded: they are not
        compiled into the imported package for a production import, so fanning a
        source import out to them would fabricate a false source->test edge.
        """
        hits: list[str] = []
        for path in file_set:
            if not path.endswith(_GO_SUFFIX):
                continue
            if path.endswith(_TEST_GO_SUFFIX):
                continue
            parent = path.rsplit("/", 1)[0] if "/" in path else ""
            if parent == package_dir:
                hits.append(path)
        return sorted(hits)


register(GoResolver())
