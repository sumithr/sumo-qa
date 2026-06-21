# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Binding-contract tests for sumo_qa.repo_map_treesitter (#354).

These tests parse a REAL Python snippet through the installed
``tree-sitter-language-pack`` binding and assert the node kinds and accessor
shapes the resolver depends on. They are the loud-failure tripwire for binding
API drift: if a language-pack upgrade renames ``import_from_statement``, makes
``child_count`` a property, or changes ``parse`` to take bytes, these fail with
a precise message instead of the import-edge layer silently emitting nothing.

No fabricated fixtures (the #127 scar): the snippet is parsed by the real
binding and the kinds asserted are what that binding actually produces. The
whole module is skipped when the ``[treesitter]`` extra is absent, so the core
(pure-Python) install still has a green suite.
"""

from __future__ import annotations

import pytest

from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE, TSNode, parse

pytestmark = pytest.mark.skipif(
    not TREESITTER_AVAILABLE,
    reason="tree-sitter not installed (the [treesitter] extra is absent)",
)

# A snippet covering every Python import shape the resolver reads: plain,
# dotted, absolute-from, relative (level 1 and 2, with and without a tail),
# wildcard, aliased, and imports nested in a function body and a class body.
_SNIPPET = b"""import os
import os.path
from a.b import c, d
from . import sibling
from ..pkg import deep
from .local import thing as alias
from x import *
def fn():
    import json
class K:
    import sys
"""


def _kinds(node: TSNode) -> set[str]:
    return {n.kind for n in node.descendants()}


def test_parse_accepts_bytes_and_returns_module_root():
    # parse() takes bytes (resolvers read files as bytes) and the wrapped root
    # is the grammar's top-level `module` node.
    root = parse("python", _SNIPPET)
    assert isinstance(root, TSNode)
    assert root.kind == "module"


def test_top_level_import_statement_kinds_pinned():
    # The two statement kinds the resolver dispatches on. A rename here breaks
    # extraction silently in production, so pin them explicitly.
    root = parse("python", _SNIPPET)
    top = {child.kind for child in root.children}
    assert "import_statement" in top
    assert "import_from_statement" in top


def test_relative_import_structure_pinned():
    # The resolver reads the relative dot count from `import_prefix` (one `.`
    # token per level) inside a `relative_import`, and the module tail from a
    # sibling `dotted_name`. Pin both kinds.
    kinds = _kinds(parse("python", _SNIPPET))
    assert "relative_import" in kinds
    assert "import_prefix" in kinds
    assert "dotted_name" in kinds


def test_specifier_and_wildcard_kinds_pinned():
    # Aliased specifiers (`thing as alias`) and the wildcard (`*`) are the two
    # specifier shapes the resolver special-cases. Pin their kinds.
    kinds = _kinds(parse("python", _SNIPPET))
    assert "aliased_import" in kinds
    assert "wildcard_import" in kinds


def test_function_and_class_body_kinds_pinned():
    # Function-local vs class-body confidence keys off the `function_definition`
    # ancestor; the binding nests body statements under a `block`.
    kinds = _kinds(parse("python", _SNIPPET))
    assert "function_definition" in kinds
    assert "class_definition" in kinds
    assert "block" in kinds


def test_node_accessors_are_method_style():
    # The language-pack binding exposes node accessors as zero-arg METHODS,
    # not properties — the non-mainstream shape the adapter exists to absorb.
    # If an upgrade flips these to properties, the wrapper's int()/range() calls
    # break; assert the raw shape here so the failure is precise.
    root = parse("python", _SNIPPET)
    raw = root._node  # the underlying language-pack node
    assert callable(raw.kind)
    assert callable(raw.child_count)
    assert callable(raw.start_byte)
    assert callable(raw.end_byte)


def test_text_recovered_by_byte_slice():
    # The binding carries no `.text`; the wrapper recovers source text from the
    # node's byte range. Assert a known dotted name round-trips.
    root = parse("python", _SNIPPET)
    dotted = [n for n in root.descendants() if n.kind == "dotted_name"]
    texts = {n.text for n in dotted}
    assert "os.path" in texts
    assert "a.b" in texts


def test_text_aligned_after_invalid_utf8_byte():
    # An invalid UTF-8 byte before an import: `parse` decodes with
    # errors="replace", which rewrites the bad byte to U+FFFD (3 bytes), shifting
    # every later parser byte offset. `text` must slice the bytes the parser
    # actually saw (the decoded source's UTF-8 encoding), not the original source
    # bytes, or a node's text drifts and a real import is silently dropped (#458).
    # The bad byte sits before the import so the offsets are shifted at the point
    # the import name is sliced; the import target must still round-trip exactly.
    root = parse("python", b"# bad \xff byte\nimport target\n")
    dotted = {n.text for n in root.descendants() if n.kind == "dotted_name"}
    assert "target" in dotted


def test_children_iterates_in_source_order():
    # The resolver relies on children being yielded in source order (module
    # token before specifiers in a from-import). Assert ordering on a dotted
    # name: identifier, '.', identifier.
    root = parse("python", _SNIPPET)
    os_path = next(n for n in root.descendants() if n.kind == "dotted_name" and n.text == "os.path")
    child_kinds = [c.kind for c in os_path.children]
    assert child_kinds == ["identifier", ".", "identifier"]
