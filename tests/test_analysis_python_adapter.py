# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the stdlib-ast Python symbol adapter (issue #212)."""

from __future__ import annotations

import pytest

from sumo_qa.analysis.python_adapter import (
    PythonSymbolAdapter,
    extract_symbols,
    innermost_symbol,
    symbols_touching_lines,
)

# Line numbers are load-bearing (span assertions), so the fixture is built line
# by line and joined; the comments are the 1-based line each entry becomes.
_SRC = "\n".join(
    [
        "import os",  # 1
        "",  # 2
        "@deco",  # 3
        "def free(x):",  # 4
        "    def inner(y):",  # 5  nested function -> free.inner (function scope)
        "        return y",  # 6
        "    return inner(x)",  # 7
        "",  # 8
        "class Outer:",  # 9
        "    def meth(self):",  # 10  method Outer.meth
        "        return 1",  # 11
        "    if os.name:",  # 12  conditional in class body (non-def)
        "        def cond_meth(self):",  # 13  method Outer.cond_meth (scope preserved)
        "            return 2",  # 14
        "    class Inner:",  # 15  nested class Outer.Inner
        "        async def ameth(self):",  # 16  method Outer.Inner.ameth
        "            return 3",  # 17
    ]
).encode("utf-8")


def _by_qualname() -> dict[str, tuple[str, int, int]]:
    return {s.qualname: (s.kind, s.start_line, s.end_line) for s in extract_symbols(_SRC)}


def test_extract_covers_functions_methods_and_classes():
    got = _by_qualname()
    assert set(got) == {
        "free",
        "free.inner",
        "Outer",
        "Outer.meth",
        "Outer.cond_meth",
        "Outer.Inner",
        "Outer.Inner.ameth",
    }


def test_decorator_line_is_included_in_the_symbol_span():
    # `free` is decorated on line 3; its span must start at the decorator, not
    # the `def` on line 4, so a change to the decorator counts as a change.
    assert _by_qualname()["free"] == ("function", 3, 7)


def test_nested_function_is_a_function_not_a_method():
    assert _by_qualname()["free.inner"] == ("function", 5, 6)


def test_conditionally_defined_method_keeps_method_kind():
    # cond_meth sits under `if os.name:` inside the class body; the else-branch
    # descent must preserve class scope so it reads as a method.
    assert _by_qualname()["Outer.cond_meth"] == ("method", 13, 14)


def test_async_method_in_nested_class():
    assert _by_qualname()["Outer.Inner.ameth"] == ("method", 16, 17)


def test_innermost_symbol_prefers_the_smallest_span():
    symbols = extract_symbols(_SRC)
    inner = innermost_symbol(symbols, 6)
    assert inner is not None and inner.qualname == "free.inner"


def test_innermost_symbol_returns_none_outside_every_symbol():
    symbols = extract_symbols(_SRC)
    # Line 1 (`import os`) is outside every def/class span.
    assert innermost_symbol(symbols, 1) is None


def test_symbols_touching_lines_maps_to_innermost_each():
    symbols = extract_symbols(_SRC)
    touched = symbols_touching_lines(symbols, {11, 14})
    assert [s.qualname for s in touched] == ["Outer.meth", "Outer.cond_meth"]


def test_symbols_touching_lines_empty_input_is_empty():
    symbols = extract_symbols(_SRC)
    assert symbols_touching_lines(symbols, set()) == []


def test_symbols_touching_lines_outside_span_contributes_nothing():
    symbols = extract_symbols(_SRC)
    assert symbols_touching_lines(symbols, {1}) == []


def test_extract_symbols_raises_syntaxerror_on_broken_source():
    with pytest.raises(SyntaxError):
        extract_symbols(b"def (:\n")


def test_adapter_delegates_to_module_functions():
    adapter = PythonSymbolAdapter()
    assert adapter.language == "python"
    assert ".py" in adapter.extensions
    symbols = adapter.extract_symbols(_SRC)
    touched = adapter.symbols_touching_lines(symbols, {11})
    assert [s.qualname for s in touched] == ["Outer.meth"]
