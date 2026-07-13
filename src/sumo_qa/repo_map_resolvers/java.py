# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Java import resolver for the repo-map import-edge layer (#357).

A follow-on resolver of the Approach-C framework the foundation (#354) shipped.
``extract`` reads ``import`` declarations off a tree-sitter parse of Java
source; ``resolve`` ports Understand-Anything's Java path rules to map each raw
import to the repo-relative file(s) it references.

Resolution rules (ported from UA):

- **Fully-qualified type imports** map the dotted name to a source file under a
  source root: ``import a.b.C;`` -> ``<root>/a/b/C.java``. The source root is
  not known a priori (``src/main/java``, ``src/``, a multi-module prefix, or
  nothing), so resolution matches a file whose path ends with the package
  path ``a/b/C.java`` at a path-segment boundary AND whose prefix is a plausible
  source root - covering the Maven/Gradle ``src/main/java`` layout and flat
  layouts alike. The source-root check stops a short import (``import foo.Bar``)
  from matching a longer in-repo package (``com/acme/foo/Bar.java``, package
  ``com.acme.foo``) whose package path merely ends in ``foo/Bar.java``.
- **Nested-type imports resolve to the declaring top-level type's file.** A
  nested type has no file of its own: ``Inner`` in ``import a.b.Outer.Inner;``
  is declared inside the top-level type ``Outer``, whose file is
  ``a/b/Outer.java`` (there is no ``a/b/Outer/Inner.java``). Resolution truncates
  the type FQN to its top-level type - the path up to and including the FIRST
  uppercase-initial segment, package segments being lowercase - so
  ``import a.b.Outer.Inner``, ``import a.b.Outer`` and
  ``import static a.b.Outer.Inner.CONST`` all map to ``a/b/Outer.java``.
- **Wildcard package imports** fan out: ``import a.b.*;`` resolves to every
  ``.java`` file directly inside a package directory ``a/b`` (one edge per
  type in the package). Sub-packages are not part of ``a.b.*`` and are excluded.
- **Static imports** name a member of a type, so the importable *file* is the
  type: ``import static a.b.C.method;`` resolves to ``a/b/C.java`` (the trailing
  member is stripped in ``extract``); ``import static a.b.C.*;`` likewise targets
  the single type ``a.b.C``, NOT a package fan-out.
- **JDK and external packages are dropped**: ``java.*`` / ``javax.*`` /
  ``sun.*`` (JDK-internal) are dropped by an explicit guard, and any other
  package absent from the repo is dropped naturally (no file matches) - both
  yield ``[]``, never an edge.

Known limitation: uppercase-package layouts (``import A.B.C`` where package
segments are uppercase-initial) are mis-handled by the first-uppercase-segment
type-boundary heuristic (mapped to ``A.java``); this violates Java's
lowercase-package naming convention and is left unhandled.

Java imports are always top-level (no function-local / lazy form and no
relative imports), so every :class:`RawImport` carries ``level=0`` and
``function_local=False`` - the orchestrator tags every Java import edge
``high`` confidence.
"""

from __future__ import annotations

from sumo_qa.repo_map_resolvers.base import LanguageConfig, RawImport, register
from sumo_qa.repo_map_treesitter import TSNode, parse

JAVA_CONFIG = LanguageConfig(id="java", extensions=(".java",))

# Grammar kinds, pinned to tree-sitter-language-pack's Java grammar (probed
# against the installed binding). `import a.b.C;` parses to an
# `import_declaration` holding a `scoped_identifier` (the dotted name); a
# wildcard adds an `asterisk` sibling; a static import adds a `static` keyword.
_IMPORT_DECL = "import_declaration"  # `import a.b.C;`
_SCOPED_IDENTIFIER = "scoped_identifier"  # `a.b.C`
_IDENTIFIER = "identifier"  # a single-segment name (defensive)
_ASTERISK = "asterisk"  # the `*` of a wildcard import
_STATIC = "static"  # the `static` keyword of a static import

# The package-fan-out marker carried in RawImport.names: `import a.b.*` records
# names=("*",) so resolve() distinguishes a package wildcard (fan out) from a
# single-type import (one file). Mirrors the framework's use of `names` to carry
# resolve-time intent without widening the shared RawImport contract.
_WILDCARD = "*"

# JDK root packages: imports under these never resolve to a repo file. `java` /
# `javax` are the public JDK roots; `sun` is a JDK-internal root (`sun.misc.*`
# etc.). Dropped by an explicit guard (not merely by no-match) so the rule is
# stated, and so a pathological in-repo `java/...` (or `sun/...`) file can't
# fabricate a JDK edge.
_JDK_ROOTS = frozenset({"java", "javax", "sun"})

_JAVA_SUFFIX = ".java"

# The final path segment of a Maven/Gradle Java source set (`src/main/java`,
# `src/test/java`, `<module>/src/main/java`). A multi-segment prefix ending here
# is a source root: the segments AFTER it are the package. A prefix ending in an
# ordinary lowercase name (`com/acme`) is a package prefix, not a source root -
# recognising the difference is what stops a short import whose package path is a
# proper suffix of a longer in-repo package from fabricating an edge.
_SOURCE_LANG_DIR = "java"


class JavaResolver:
    """Approach-C resolver for Java."""

    config = JAVA_CONFIG

    def extract(self, src: bytes) -> list[RawImport]:
        """Return the ``import`` declarations in ``src`` as :class:`RawImport`.

        Walks the parse tree for ``import_declaration`` nodes (Java imports are
        top-level, so a flat scan suffices). Each yields one record: a single
        type import keeps its full dotted name; a wildcard keeps the package and
        is flagged with the ``"*"`` fan-out marker; a static member import drops
        the trailing member to leave the resolvable type name.
        """
        root = parse("java", src)
        raws: list[RawImport] = []
        for node in root.descendants():
            if node.kind == _IMPORT_DECL:
                raw = self._import(node)
                if raw is not None:
                    raws.append(raw)
        return raws

    @staticmethod
    def _import(node: TSNode) -> RawImport | None:
        """One ``import_declaration`` -> a :class:`RawImport`, or ``None``.

        Reads the dotted name (a ``scoped_identifier`` / ``identifier`` child),
        and whether the declaration is ``static`` and/or a ``*`` wildcard:

        - ``import a.b.*;`` -> module ``a.b``, names ``("*",)`` (package fan-out)
        - ``import static a.b.C.*;`` -> module ``a.b.C``, names ``()`` (the type)
        - ``import static a.b.C.m;`` -> module ``a.b.C``, names ``()`` (member
          ``m`` dropped)
        - ``import a.b.C;`` -> module ``a.b.C``, names ``()``
        """
        is_static = False
        is_wildcard = False
        dotted = ""
        for child in node.children:
            kind = child.kind
            if kind == _STATIC:
                is_static = True
            elif kind == _ASTERISK:
                is_wildcard = True
            elif kind in (_SCOPED_IDENTIFIER, _IDENTIFIER):
                dotted = child.text
        if not dotted:  # pragma: no cover -- defensive: a valid import always names a path
            return None
        if is_wildcard and not is_static:
            # `import a.b.*` -> package a.b, fan out across its files.
            return RawImport(module=dotted, level=0, names=(_WILDCARD,), function_local=False)
        if is_static and not is_wildcard:
            # `import static a.b.C.member` -> the type is a.b.C; drop the member.
            type_fqn = dotted.rsplit(".", 1)[0] if "." in dotted else dotted
            return RawImport(module=type_fqn, level=0, names=(), function_local=False)
        # `import a.b.C;` and `import static a.b.C.*;` both target one type file.
        return RawImport(module=dotted, level=0, names=(), function_local=False)

    def resolve(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        """Map one raw import to the repo-relative file path(s) it references.

        Returns repo-relative paths that exist in ``file_set``, sorted for
        determinism; an empty list means the import points outside the repo
        (JDK, external package, unresolved) - never an error. ``importer`` is
        unused: Java imports are fully qualified, so resolution is independent of
        the importing file's location (unlike Python's relative / walk-up rules).
        """
        if self._is_jdk(imp.module):
            return []
        package_path = imp.module.replace(".", "/")
        if imp.names == (_WILDCARD,):
            return self._resolve_package(package_path, file_set)
        return self._resolve_type(package_path, file_set)

    @staticmethod
    def _is_jdk(module: str) -> bool:
        """True when ``module``'s top-level package is a JDK root (``java`` /
        ``javax`` / ``sun`` JDK-internal) - those never resolve to a repo
        file."""
        top = module.split(".", 1)[0]
        return top in _JDK_ROOTS

    @staticmethod
    def _top_level_type_path(type_path: str) -> str:
        """Truncate a slash-joined type path to its declaring top-level type.

        A nested type and a static member both live in the enclosing top-level
        type's ``.java`` file, not in a file or directory of their own. Package
        segments are lowercase-initial and the top-level type is the FIRST
        uppercase-initial segment, so ``a/b/Outer/Inner`` (nested type ``Inner``)
        and ``a/b/Outer`` (the type itself) both truncate to ``a/b/Outer``. If no
        segment is uppercase-initial (an all-lowercase name, e.g. an unconventional
        lowercase class), the path is returned unchanged so it still resolves as a
        plain type path."""
        segments = type_path.split("/")
        for i, seg in enumerate(segments):
            if seg[:1].isupper():
                return "/".join(segments[: i + 1])
        return type_path

    @staticmethod
    def _is_source_root(root: str) -> bool:
        """True when a repo-relative prefix ``root`` is a plausible Java source root.

        A source root is where package directories begin, so a file under it,
        ``<root>/a/b/C.java``, genuinely declares package ``a.b``. Recognised roots
        are the repo root or a single top-level source directory (``""``, ``src``,
        ``gen``, ...) and a Maven/Gradle source set whose final segment is the
        language directory (``.../src/main/java``). A multi-segment prefix ending
        in an ordinary package segment (``com/acme``) is a package prefix, not a
        source root - so a short import ``foo.Bar`` whose package path is only a
        suffix of a longer in-repo package ``com.acme.foo.Bar`` cannot fabricate an
        edge to ``com/acme/foo/Bar.java``."""
        if "/" not in root:  # the repo root ("") or a single top-level source dir
            return True
        return root.rsplit("/", 1)[1] == _SOURCE_LANG_DIR

    @staticmethod
    def _resolve_type(package_path: str, file_set: set[str]) -> list[str]:
        """Files whose path is the top-level type path ``a/b/C`` + ``.java`` under a
        plausible source root.

        The type FQN is first truncated to its declaring top-level type
        (:meth:`_top_level_type_path`), so a nested-type import ``a.b.Outer.Inner``
        resolves to ``a/b/Outer.java`` rather than a non-existent
        ``a/b/Outer/Inner.java``. The truncated path then matches ``a/b/C.java``
        exactly (flat layout, empty root) or any path ending in ``/a/b/C.java``
        whose prefix is a plausible source root (:meth:`_is_source_root`). The
        leading-slash boundary keeps the match at a path-segment boundary
        (``b/C.java`` matches ``x/b/C.java`` but not ``lib/C.java``), and the
        source-root check keeps it honest across packages: ``foo.Bar`` does NOT
        match ``com/acme/foo/Bar.java`` (package ``com.acme.foo``), whose prefix
        ``com/acme`` is a package, not a source root. Multiple matches (the same
        type duplicated across source roots) are all returned, sorted."""
        type_path = JavaResolver._top_level_type_path(package_path)
        suffix = type_path + _JAVA_SUFFIX
        boundary = "/" + suffix
        hits: list[str] = []
        for f in file_set:
            if f == suffix:
                root = ""  # flat layout: the file IS the package path
            elif f.endswith(boundary):
                root = f[: -len(boundary)]  # the prefix ahead of the package path
            else:
                continue
            if JavaResolver._is_source_root(root):
                hits.append(f)
        return sorted(hits)

    @staticmethod
    def _resolve_package(package_path: str, file_set: set[str]) -> list[str]:
        """Every ``.java`` file directly inside the package directory
        ``package_path`` (``a/b``), sorted.

        A file belongs to package ``a/b`` when its parent directory is ``a/b``
        exactly (flat layout) or ends in ``/a/b`` (under a source root). Files in
        sub-packages (``a/b/sub/Deep.java``, parent ``.../a/b/sub``) and sibling
        packages are excluded by the same path-segment-boundary check used for
        type resolution."""
        boundary = "/" + package_path
        hits: list[str] = []
        for f in file_set:
            if not f.endswith(_JAVA_SUFFIX) or "/" not in f:
                continue
            parent = f.rsplit("/", 1)[0]
            if parent == package_path or parent.endswith(boundary):
                hits.append(f)
        return sorted(hits)


register(JavaResolver())
