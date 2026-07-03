# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Ruby import resolver for the repo-map import-edge layer (#360).

An Approach-C resolver in the framework the foundation (#354) shipped.
``extract`` reads ``require`` / ``require_relative`` calls off a tree-sitter
parse of Ruby source; ``resolve`` ports Understand-Anything's Ruby path rules to
map each one to the repo-relative file it references.

Resolution rules (ported from UA):

- **``require_relative``** is anchored to the *requiring file's directory*. A
  leading ``./`` is that same directory; each ``../`` segment walks one
  directory up. A path that walks past the repo root resolves to nothing
  (Ruby would raise ``LoadError`` at runtime).
- **``require``** is resolved against the *load path*: the repo root and
  ``lib/`` (the conventional ``$LOAD_PATH`` entries for a project). The first
  load-path root that yields an existing file wins, mirroring Ruby's
  first-match-on-``$LOAD_PATH`` semantics — so ``require "lib/bar"`` lands on
  ``lib/bar.rb`` via the root, and ``require "bar"`` lands on ``lib/bar.rb`` via
  the ``lib/`` entry.
- **Extension probe**: a path without a suffix is probed as ``<path>.rb``; an
  explicit ``.rb`` suffix is probed verbatim.
- **Gems / stdlib dropped**: a ``require`` of a gem or the standard library
  (``json``, ``set``, …) matches no repo file, so ``resolve`` returns ``[]`` and
  the orchestrator emits no edge — the same "external / not-ours" outcome as
  Python's third-party imports.
- **Dynamic arguments dropped at ``extract``**: a ``require`` whose argument is
  not a single plain string literal (string interpolation, ``File.join(...)``,
  a constant) carries no static path and yields no :class:`RawImport`.

A node is tagged ``function_local`` (→ ``medium`` confidence downstream) when
its ``require`` sits inside a method body (``def`` / ``def self.``); top-level
requires and requires inside a block are not (→ ``high``).
"""

from __future__ import annotations

from sumo_qa.repo_map_resolvers.base import LanguageConfig, RawImport, register
from sumo_qa.repo_map_treesitter import TSNode, parse

# Ruby has no package-barrel (``__init__.py`` / ``index.ts``) convention, so
# ``barrels`` is empty: a directory never stands in for a file.
RUBY_CONFIG = LanguageConfig(
    id="ruby",
    extensions=(".rb",),
    barrels=(),
)

# Conventional load-path roots, probed in order; the first that resolves wins
# (Ruby loads the first match on ``$LOAD_PATH``). "" is the repo root.
_LOAD_PATHS = ("", "lib")

# Grammar kinds, pinned to tree-sitter-language-pack's Ruby grammar (probed
# against the installed binding).
_CALL = "call"  # `require "x"` / `obj.require`
_IDENTIFIER = "identifier"  # the bare method name `require` / `require_relative`
_ARGUMENT_LIST = "argument_list"  # `("x")` / `"x"`
_STRING = "string"  # a string literal
_STRING_CONTENT = "string_content"  # the literal text inside the quotes
_METHOD = "method"  # `def name ... end`
_SINGLETON_METHOD = "singleton_method"  # `def self.name ... end`
_STRING_DELIMS = ('"', "'")  # the quote tokens bounding a string literal
_ARG_PUNCT = (",", "(", ")")  # separators/brackets inside an argument_list (not args)

_REQUIRE = "require"
_REQUIRE_RELATIVE = "require_relative"


class RubyResolver:
    """Approach-C resolver for Ruby (``require`` / ``require_relative``)."""

    config = RUBY_CONFIG

    def extract(self, src: bytes) -> list[RawImport]:
        """Return the ``require`` / ``require_relative`` calls in ``src``.

        Walks the parse tree, recording each bare ``require``/``require_relative``
        call whose argument is a single plain string literal. ``level`` is ``1``
        for ``require_relative`` (file-relative) and ``0`` for ``require``
        (load-path); ``function_local`` is set when the call is lexically inside
        a method body (so the orchestrator down-ranks a lazy require to
        ``medium`` confidence).
        """
        root = parse("ruby", src)
        raws: list[RawImport] = []
        self._collect(root, method_depth=0, out=raws)
        return raws

    def _collect(self, node: TSNode, *, method_depth: int, out: list[RawImport]) -> None:
        if node.kind == _CALL:
            raw = self._require_call(node, method_depth > 0)
            if raw is not None:
                out.append(raw)
            # Fall through and still recurse: a require nested in a block lives
            # under an outer (non-require) call node.
        next_depth = method_depth + 1 if node.kind in (_METHOD, _SINGLETON_METHOD) else method_depth
        for child in node.children:
            self._collect(child, method_depth=next_depth, out=out)

    @staticmethod
    def _require_call(node: TSNode, function_local: bool) -> RawImport | None:
        """A ``call`` node -> a :class:`RawImport`, or ``None`` if not a require.

        Matches only a *bare* ``require`` / ``require_relative`` (the call's
        first child is the method-name ``identifier``); a receiver-qualified
        call (``Kernel.require``) leads with a constant/identifier receiver and
        is skipped. The argument must be a single plain string literal.
        """
        children = list(node.children)
        if not children or children[0].kind != _IDENTIFIER:
            return None
        name = children[0].text
        if name not in (_REQUIRE, _REQUIRE_RELATIVE):
            return None
        arg = next((c for c in children if c.kind == _ARGUMENT_LIST), None)
        if arg is None:  # pragma: no cover -- a require call always carries an argument_list
            return None
        module = RubyResolver._string_arg(arg)
        if not module:
            return None
        level = 1 if name == _REQUIRE_RELATIVE else 0
        return RawImport(module=module, level=level, names=(), function_local=function_local)

    @staticmethod
    def _string_arg(arg: TSNode) -> str:
        """The text of a single plain string literal in ``arg``, or ``''``.

        Returns ``''`` when the argument list does not hold *exactly one*
        argument that is a string literal, or when that string carries anything
        other than quote delimiters and plain content (interpolation, an escape)
        — i.e. a dynamic path with no statically-resolvable target. Punctuation
        (commas, parentheses) is not an argument, so ``require("foo")`` still
        counts as one; a second argument (``require "foo", bar``) does count, so
        the mixed-arg form is skipped rather than yielding a false ``"foo"``
        edge.
        """
        args = [c for c in arg.children if c.kind not in _ARG_PUNCT]
        if len(args) != 1 or args[0].kind != _STRING:
            return ""
        content = ""
        for part in args[0].children:
            kind = part.kind
            if kind == _STRING_CONTENT:
                content += part.text
            elif kind in _STRING_DELIMS:
                continue
            else:
                return ""  # interpolation / escape -> dynamic, not a literal path
        return content

    def resolve(self, importer: str, imp: RawImport, file_set: set[str]) -> list[str]:
        """Map one require to the repo-relative file path(s) it references.

        Returns repo-relative paths that exist in ``file_set``; an empty list
        means the require points outside the repo (gem, stdlib) or could not be
        resolved — never an error. ``require_relative`` (``level > 0``) anchors
        to the importer's directory; ``require`` (``level == 0``) walks the load
        path and takes the first root that resolves.
        """
        if not imp.module:
            return []
        if imp.level > 0:
            target = self._join(importer.split("/")[:-1], imp.module)
            if target is None:
                return []
            return self._hits(target, file_set)
        for root in _LOAD_PATHS:
            target = self._join([root] if root else [], imp.module)
            if target is None:
                continue
            hits = self._hits(target, file_set)
            if hits:
                return hits
        return []

    @staticmethod
    def _join(base: list[str], module: str) -> str | None:
        """Join ``base`` directory parts with a ``/``-delimited module path.

        Collapses ``.`` (current dir) and ``..`` (parent) segments; returns
        ``None`` when a ``..`` walks above ``base`` (past the repo root), when
        nothing remains, or when ``module`` is a leading-``/`` absolute path. An
        absolute path (``require "/foo"`` / ``require_relative "/foo"``) names a
        filesystem location, not a repo-relative file, so it never joins onto a
        repo path -- without this guard the empty leading segment is silently
        dropped and ``/foo`` fabricates a repo edge to ``foo.rb``.
        """
        if module.startswith("/"):
            return None
        parts = list(base)
        for seg in module.split("/"):
            if seg in ("", "."):
                continue
            if seg == "..":
                if not parts:
                    return None
                parts.pop()
            else:
                parts.append(seg)
        if not parts:
            return None
        return "/".join(parts)

    @staticmethod
    def _hits(target: str, file_set: set[str]) -> list[str]:
        """The ``.rb`` candidate(s) for ``target`` that exist in ``file_set``.

        A path that already carries a ``.rb`` suffix is probed verbatim;
        otherwise ``<target>.rb`` is probed.
        """
        candidate = target if target.endswith(".rb") else f"{target}.rb"
        return [candidate] if candidate in file_set else []


register(RubyResolver())
