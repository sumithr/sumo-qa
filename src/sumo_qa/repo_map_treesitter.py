# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""tree-sitter adapter for the repo-map import-edge layer (#354).

Wraps the ``tree-sitter-language-pack`` binding so resolvers never touch the
raw API. Two reasons this layer exists:

1. **Optional dependency.** tree-sitter is an opt-in extra
   (``pip install sumo-qa[treesitter]``); the core install stays pure-Python.
   This module guards the import at load: :data:`TREESITTER_AVAILABLE` is the
   single switch the orchestrator reads to decide between emitting import edges
   and recording the graceful-degradation warning.

2. **Non-mainstream binding API.** ``tree-sitter-language-pack``'s binding is
   method-style and differs from the upstream ``tree-sitter`` package:
   ``parse()`` takes a ``str`` (not ``bytes``); ``tree.root_node()`` is a
   method; and node accessors are methods too — ``kind()``, ``child(i)``,
   ``child_count()``, ``named_child(i)``, ``named_child_count()``,
   ``start_byte()``, ``end_byte()``. A node carries no ``.text`` attribute, so
   source text is recovered by byte-slicing the original source. All of that is
   absorbed here behind :class:`TSNode`; the version is pinned and the
   binding-contract test (``tests/test_repo_map_treesitter.py``) fails loudly
   if any of these shapes drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:  # pragma: no cover -- exercised by both CI paths (extra present / absent)
    import tree_sitter_language_pack as _language_pack

    TREESITTER_AVAILABLE = True
except ImportError:  # pragma: no cover -- the no-extra path; covered by a monkeypatched test
    _language_pack = None  # type: ignore[assignment]
    TREESITTER_AVAILABLE = False

if TYPE_CHECKING:  # pragma: no cover -- typing-only import, never executed
    from collections.abc import Iterator


class TreesitterUnavailableError(RuntimeError):
    """Raised when a parse is attempted without the ``[treesitter]`` extra.

    Callers gate on :data:`TREESITTER_AVAILABLE` first; reaching a parse with
    the extra absent is a programming error, not a degradation path, so it
    raises rather than returning empty.
    """


class TSNode:
    """A thin, attribute-style wrapper over one language-pack node.

    The raw binding exposes everything as zero-arg methods (``kind()``,
    ``child_count()``, …); this wrapper normalises them to properties /
    helpers and carries the source bytes so ``text`` works despite the binding
    having no ``.text`` of its own. Resolvers walk :class:`TSNode`, never the
    raw node, so a binding change is absorbed in one place.
    """

    __slots__ = ("_node", "_src")

    def __init__(self, node: Any, src: bytes) -> None:
        self._node = node
        self._src = src

    @property
    def kind(self) -> str:
        """The node's grammar kind (``import_statement``, ``dotted_name``, …)."""
        return str(self._node.kind())

    @property
    def child_count(self) -> int:
        return int(self._node.child_count())

    def child(self, index: int) -> TSNode:
        return TSNode(self._node.child(index), self._src)

    @property
    def children(self) -> Iterator[TSNode]:
        """Direct children in source order."""
        for i in range(self.child_count):
            yield self.child(i)

    @property
    def text(self) -> str:
        """The exact source slice this node spans, UTF-8 decoded.

        The binding carries no ``.text``; recover it from the original source
        bytes via the node's byte range.
        """
        return self._src[self._node.start_byte() : self._node.end_byte()].decode(
            "utf-8", errors="replace"
        )

    def descendants(self) -> Iterator[TSNode]:
        """Pre-order walk over self and every descendant."""
        yield self
        for child in self.children:
            yield from child.descendants()


def parse(language: str, src: bytes) -> TSNode:
    """Parse ``src`` for ``language`` and return the wrapped root node.

    ``src`` is bytes (resolvers read files as bytes); the language-pack
    ``parse`` wants ``str``, so decoding happens here. Raises
    :class:`TreesitterUnavailableError` when the extra is absent — callers must
    gate on :data:`TREESITTER_AVAILABLE` first.
    """
    if not TREESITTER_AVAILABLE:  # pragma: no cover -- defensive; gated by callers
        raise TreesitterUnavailableError(
            "tree-sitter is not installed; install the [treesitter] extra"
        )
    parser = _language_pack.get_parser(language)
    tree = parser.parse(src.decode("utf-8", errors="replace"))
    if tree is None:  # pragma: no cover -- defensive: parse() of decoded text always yields a tree
        raise TreesitterUnavailableError(f"tree-sitter returned no parse tree for {language}")
    return TSNode(tree.root_node(), src)
