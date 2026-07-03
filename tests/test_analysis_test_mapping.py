# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for changed-symbol -> likely-owning-test mapping (issue #212 AC#4)."""

from __future__ import annotations

from sumo_qa.analysis.contracts import ChangedSymbol, Symbol
from sumo_qa.analysis.test_mapping import map_changed_symbols_to_tests


def _changed(qualname: str, path: str = "pkg/mod.py") -> ChangedSymbol:
    return ChangedSymbol(
        path=path, symbol=Symbol(qualname=qualname, kind="function", start_line=1, end_line=2)
    )


def test_calling_test_is_high_confidence_and_names_the_enclosing_test():
    changed = [_changed("Order.total")]
    tests = {"tests/test_order.py": b"def test_total():\n    assert Order().total() == 1\n"}
    result = map_changed_symbols_to_tests(changed, tests)
    assert len(result) == 1
    row = result[0]
    assert row.confidence == "high"
    assert row.test_symbol == "test_total"
    assert row.changed_symbol == "Order.total"
    assert "calls total" in row.reason


def test_naming_without_calling_is_medium_confidence():
    changed = [_changed("helper")]
    tests = {"tests/test_h.py": b"def test_ref():\n    fn = helper\n    return fn\n"}
    result = map_changed_symbols_to_tests(changed, tests)
    assert len(result) == 1
    assert result[0].confidence == "medium"
    assert "references helper" in result[0].reason


def test_module_level_reference_yields_a_row_with_no_test_symbol():
    changed = [_changed("boot")]
    tests = {"tests/mod_level.py": b"boot()\n"}
    result = map_changed_symbols_to_tests(changed, tests)
    assert len(result) == 1
    assert result[0].test_symbol is None
    assert result[0].confidence == "high"


def test_one_leaf_maps_to_every_changed_symbol_sharing_it():
    # Two changed symbols share the leaf `run`; a test naming `run` maps to both.
    changed = [_changed("run", path="pkg/a.py"), _changed("Runner.run", path="pkg/b.py")]
    tests = {"tests/test_run.py": b"def test_it():\n    run()\n"}
    result = map_changed_symbols_to_tests(changed, tests)
    mapped = {r.changed_symbol for r in result}
    assert mapped == {"run", "Runner.run"}


def test_unparseable_test_file_is_skipped_cleanly():
    changed = [_changed("thing")]
    tests = {
        "tests/broken.py": b"def (:\n",
        "tests/ok.py": b"def test_it():\n    thing()\n",
    }
    result = map_changed_symbols_to_tests(changed, tests)
    assert [r.test_path for r in result] == ["tests/ok.py"]


def test_no_matching_references_yields_no_rows():
    changed = [_changed("unreferenced")]
    tests = {"tests/test_other.py": b"def test_x():\n    something_else()\n"}
    assert map_changed_symbols_to_tests(changed, tests) == []
