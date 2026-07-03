# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the analysis composition (issue #212).

The headline test is the AC#4 end-to-end path: a real ``git diff`` plus the
changed source maps a changed symbol to its likely owning test. The rest cover
the clean-degradation branches (unsupported language, parse error, absent
tree-sitter extra) and the optional-signal passthrough.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from sumo_qa.analysis import analyzer
from sumo_qa.analysis.analyzer import analyze_changes
from sumo_qa.analysis.contracts import AnalysisFallback
from sumo_qa.analysis.diff import changed_lines_from_unified_diff
from sumo_qa.scorecard_models import CoverageSignal, MutationSignal


def _git(root, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=True,
        env=env,
        text=True,
    )
    return result.stdout


_V1 = b"def price(qty):\n    return qty * 2\n\n\ndef unrelated():\n    return 0\n"
_V2 = b"def price(qty):\n    subtotal = qty * 3\n    return subtotal\n\n\ndef unrelated():\n    return 0\n"


def test_git_diff_plus_source_maps_a_changed_symbol_to_its_likely_test(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Tester")
    mod = tmp_path / "pkg" / "mod.py"
    mod.parent.mkdir(parents=True)
    mod.write_bytes(_V1)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    mod.write_bytes(_V2)

    diff = _git(tmp_path, "diff")
    changed_lines = changed_lines_from_unified_diff(diff)
    assert "pkg/mod.py" in changed_lines  # the diff really pointed at the file

    test_sources = {
        "tests/test_price.py": b"from pkg.mod import price\n\n\ndef test_price():\n    assert price(2) == 6\n",
    }
    result = analyze_changes(
        changed_sources={"pkg/mod.py": mod.read_bytes()},
        changed_lines=changed_lines,
        test_sources=test_sources,
    )

    # The change touched `price` (not `unrelated`), so only `price` is changed.
    assert [c.symbol.qualname for c in result.changed_symbols] == ["price"]
    price_tests = [t for t in result.likely_tests if t.changed_symbol == "price"]
    assert len(price_tests) == 1
    assert price_tests[0].test_path == "tests/test_price.py"
    assert price_tests[0].test_symbol == "test_price"
    assert price_tests[0].confidence == "high"
    # The evidence cites the concrete symbol and the concrete test.
    assert "pkg/mod.py::price" in result.evidence.citations
    assert "tests/test_price.py::test_price" in result.evidence.test_focus


def test_unsupported_language_file_degrades_cleanly():
    result = analyze_changes(
        changed_sources={"app/Main.kt": b"fun main() {}\n"},
        changed_lines={"app/Main.kt": {1}},
    )
    assert result.changed_symbols == []
    assert "unsupported_language" in result.fallback_statuses()


def test_unparseable_python_source_records_a_parse_error_fallback():
    result = analyze_changes(
        changed_sources={"pkg/broken.py": b"def (:\n"},
        changed_lines={"pkg/broken.py": {1}},
    )
    assert result.changed_symbols == []
    assert "parse_error" in result.fallback_statuses()


def test_absent_treesitter_extra_records_missing_dependency_fallback(monkeypatch):
    monkeypatch.setattr(analyzer, "TREESITTER_AVAILABLE", False)
    result = analyze_changes(
        changed_sources={"pkg/mod.py": b"def run():\n    return 1\n"},
        changed_lines={"pkg/mod.py": {1}},
    )
    assert result.impacted_symbols == []
    assert "missing_optional_dependency" in result.fallback_statuses()


def test_present_treesitter_extra_without_a_graph_is_not_a_fallback(monkeypatch):
    # When the extra IS installed but no import graph was supplied, the absence
    # is the caller's choice, not a degradation -- no fallback is recorded.
    monkeypatch.setattr(analyzer, "TREESITTER_AVAILABLE", True)
    result = analyze_changes(
        changed_sources={"pkg/mod.py": b"def run():\n    return 1\n"},
        changed_lines={"pkg/mod.py": {1}},
    )
    assert "missing_optional_dependency" not in result.fallback_statuses()


def test_import_graph_drives_cross_file_impacted_symbols():
    result = analyze_changes(
        changed_sources={"pkg/core.py": b"def run():\n    return 1\n"},
        changed_lines={"pkg/core.py": {1}},
        importer_sources={
            "pkg/caller.py": b"from pkg.core import run\n\n\ndef use():\n    return run()\n"
        },
        importers_by_imported={"pkg/core.py": {"pkg/caller.py"}},
    )
    assert [(i.path, i.qualname) for i in result.impacted_symbols] == [("pkg/caller.py", "use")]
    # A supplied graph means the reach ran -- no missing-dependency fallback.
    assert "missing_optional_dependency" not in result.fallback_statuses()


def test_defaults_run_without_tests_and_without_crashing():
    result = analyze_changes(
        changed_sources={"pkg/mod.py": b"def run():\n    return 1\n"},
        changed_lines={"pkg/mod.py": {1}},
    )
    assert result.likely_tests == []


def test_changed_file_without_line_info_flags_no_symbols():
    # A changed source with no changed-line entry attributes to no symbol.
    result = analyze_changes(
        changed_sources={"pkg/mod.py": b"def run():\n    return 1\n"},
        changed_lines={},
    )
    assert result.changed_symbols == []


def test_optional_signals_and_extra_fallbacks_flow_through():
    extra = AnalysisFallback(
        status="invalid_artifact", subject=".sumo-qa/coverage.json", message="bad"
    )
    result = analyze_changes(
        changed_sources={"pkg/mod.py": b"def run():\n    return 1\n"},
        changed_lines={"pkg/mod.py": {1}},
        coverage=CoverageSignal(line_percent=90.0, freshness="fresh"),
        mutation=MutationSignal(survivors=1, freshness="fresh"),
        extra_fallbacks=[extra],
    )
    assert result.coverage is not None and result.coverage.line_percent == 90.0
    assert result.mutation is not None and result.mutation.survivors == 1
    assert "invalid_artifact" in result.fallback_statuses()
    assert any("line coverage 90% (fresh)" in n for n in result.evidence.risk_notes)


@pytest.mark.parametrize("bad_lines", [{1}, set()])
def test_analyze_changes_never_raises_on_edge_line_sets(bad_lines):
    # Empty and single-line change sets both resolve without error.
    result = analyze_changes(
        changed_sources={"pkg/mod.py": b"x = 1\n"},
        changed_lines={"pkg/mod.py": bad_lines},
    )
    assert result.changed_symbols == []
