# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the shared ast reference collector (issue #212)."""

from __future__ import annotations

from sumo_qa.analysis.references import Reference, collect_references

_SRC = b"\n".join(
    [
        b"import mod",
        b"",
        b"CONST = mod.value",  # module-level: Name 'mod', Attribute 'value', Name 'CONST'
        b"",
        b"def helper():",
        b"    obj.method()",  # call of attribute -> 'method' called; Name 'obj'
        b"    plain()",  # call of name -> 'plain' called
        b"    arr[0]()",  # call of subscript -> callee has no simple name
        b"    return CONST",  # Name 'CONST'
        b"",
        b"async def ahelper():",
        b"    return other()",  # call of name -> 'other' called, enclosing 'ahelper'
        b"",
    ]
)


def _refs() -> list[Reference]:
    refs = collect_references(_SRC)
    assert refs is not None
    return refs


def _find(refs: list[Reference], name: str, *, called: bool) -> Reference:
    matches = [r for r in refs if r.name == name and r.called == called]
    assert matches, f"no {'called' if called else 'named'} reference to {name}"
    return matches[0]


def test_call_of_a_plain_name_is_marked_called_with_enclosing_function():
    ref = _find(_refs(), "plain", called=True)
    assert ref.enclosing == "helper"


def test_call_of_an_attribute_uses_the_attribute_name():
    ref = _find(_refs(), "method", called=True)
    assert ref.enclosing == "helper"


def test_module_level_reference_has_no_enclosing_function():
    ref = _find(_refs(), "value", called=False)  # from `mod.value` at module scope
    assert ref.enclosing is None


def test_async_function_scopes_its_references():
    ref = _find(_refs(), "other", called=True)
    assert ref.enclosing == "ahelper"


def test_subscript_callee_contributes_no_called_name():
    # `arr[0]()` — the callee is a subscript, so no simple name is recorded as a
    # call; only the bare `arr` Name is present, never called.
    refs = _refs()
    assert not any(r.called and r.name == "arr" for r in refs)
    assert any(r.name == "arr" and not r.called for r in refs)


def test_unparseable_source_returns_none():
    assert collect_references(b"def (:\n") is None
