# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""tree-sitter adapter for the repo-map import-edge layer (#354).

Wraps the ``tree-sitter-language-pack`` binding so resolvers never touch the
raw API. Two reasons this layer exists:

1. **Optional dependency.** tree-sitter is an opt-in extra
   (``pip install sumo-qa[treesitter]``); the core install stays pure-Python.
   This module guards the import at load: :data:`TREESITTER_AVAILABLE` is the
   single switch the orchestrator reads to decide between emitting import edges
   and recording the graceful-degradation warning.

2. **Binding API absorption.** Since 1.12.5 the language-pack's
   ``get_parser()`` returns the upstream ``tree_sitter.Parser``: ``parse()``
   takes ``bytes`` (a ``str`` raises ``TypeError``); ``tree.root_node`` and the
   node accessors — ``type``, ``child_count``, ``start_byte``, ``end_byte`` —
   are properties (``child(i)`` stays a method), and the kind accessor is named
   ``type``, not ``kind``. Earlier language-pack releases bundled a str-only
   method-style binding with the opposite shapes (#491), so the extra is
   floored at 1.12.5 in pyproject. All of it is absorbed here behind
   :class:`TSNode` — resolvers never touch the raw API — and the
   binding-contract test (``tests/test_repo_map_treesitter.py``) fails loudly
   if any of these shapes drift again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# The binding is an optional extra and is used only dynamically behind
# TSNode/parse(), so it is typed as ``Any``. Binding it through this
# Any-annotated name rather than directly as the import target keeps the type
# check identical whether or not the extra is installed: with the module absent
# the import resolves to ``Any`` via the [tool.mypy] override, and with it
# present the real module assigns cleanly to an ``Any`` target -- so no inline
# ``# type: ignore`` is needed (one would be flagged unused in whichever
# environment has the opposite import state, which ``warn_unused_ignores`` flags).
_language_pack: Any = None
TREESITTER_AVAILABLE = False
try:  # pragma: no cover -- exercised by both CI paths (extra present / absent)
    import tree_sitter_language_pack as _imported_language_pack
except ImportError:  # pragma: no cover -- the no-extra path; covered by a monkeypatched test
    pass
else:  # pragma: no cover -- the extra-present path; covered by a binding-contract test
    _language_pack = _imported_language_pack
    TREESITTER_AVAILABLE = True

if TYPE_CHECKING:  # pragma: no cover -- typing-only import, never executed
    from collections.abc import Iterator


class TreesitterUnavailableError(RuntimeError):
    """Raised when a parse is attempted without the ``[treesitter]`` extra.

    Callers gate on :data:`TREESITTER_AVAILABLE` first; reaching a parse with
    the extra absent is a programming error, not a degradation path, so it
    raises rather than returning empty.
    """


class TSNode:
    """A thin, attribute-style wrapper over one binding node.

    Presents the accessors under the names the resolvers use (``kind`` for the
    binding's ``type``) and carries the source bytes so ``text`` slices the
    exact bytes the parser saw (see :func:`parse`). Resolvers walk
    :class:`TSNode`, never the raw node, so a binding change is absorbed in
    one place.
    """

    __slots__ = ("_node", "_src")

    def __init__(self, node: Any, src: bytes) -> None:
        self._node = node
        self._src = src

    @property
    def kind(self) -> str:
        """The node's grammar kind (``import_statement``, ``dotted_name``, …)."""
        return str(self._node.type)

    @property
    def child_count(self) -> int:
        return int(self._node.child_count)

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

        Recovered from the parser's source bytes (the normalized bytes the
        parser saw, supplied by :func:`parse`) via the node's byte range.
        Keying off those bytes rather than the original ``src`` keeps the slice
        aligned when an invalid byte was rewritten to U+FFFD (see
        :func:`parse`).
        """
        return self._src[self._node.start_byte : self._node.end_byte].decode(
            "utf-8", errors="replace"
        )

    def descendants(self) -> Iterator[TSNode]:
        """Pre-order walk over self and every descendant."""
        yield self
        for child in self.children:
            yield from child.descendants()


def parse(language: str, src: bytes) -> TSNode:
    """Parse ``src`` for ``language`` and return the wrapped root node.

    ``src`` is bytes (resolvers read files as bytes); the binding's ``parse``
    wants ``bytes`` too, but the input is normalized first (see below). Raises
    :class:`TreesitterUnavailableError` when the extra is absent — callers must
    gate on :data:`TREESITTER_AVAILABLE` first.
    """
    if not TREESITTER_AVAILABLE:  # pragma: no cover -- defensive; gated by callers
        raise TreesitterUnavailableError(
            "tree-sitter is not installed; install the [treesitter] extra"
        )
    parser = _language_pack.get_parser(language)
    # Normalize through decode/encode BEFORE parsing so an invalid byte becomes
    # U+FFFD in the bytes the parser sees, and hand TSNode those same bytes:
    # the parser reports byte offsets into its input, so a node's text slice
    # stays aligned even though U+FFFD is 3 bytes and shifts every later offset
    # - against the ORIGINAL ``src`` the slice would drift and silently drop a
    # real import (#458). For valid UTF-8 the round-trip is identity, so this
    # is a no-op there.
    normalized = src.decode("utf-8", errors="replace").encode("utf-8")
    tree = parser.parse(normalized)
    if (
        tree is None
    ):  # pragma: no cover -- defensive: parse() of normalized bytes always yields a tree
        raise TreesitterUnavailableError(f"tree-sitter returned no parse tree for {language}")
    return TSNode(tree.root_node, normalized)
