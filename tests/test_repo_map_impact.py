# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the slice-4 diff-impact core (issue #156)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sumo_qa.repo_map_impact import analyze_diff_impact
from sumo_qa.repo_map_models import (
    SCHEMA_VERSION,
    DiffImpact,
    ImpactNode,
    RepoMap,
    RepoMapEdge,
    RepoMapNode,
    RepoMapProject,
)


def test_impact_node_minimal_shape():
    n = ImpactNode(id="file:src/a.py", type="source_file", path="src/a.py", has_mapped_tests=True)
    assert n.has_mapped_tests is True
    assert n.path == "src/a.py"


def test_impact_node_forbids_extra():
    with pytest.raises(ValidationError):
        ImpactNode(id="x", type="source_file", path="x", has_mapped_tests=False, bogus=1)


def test_diff_impact_defaults_are_empty_lists():
    d = DiffImpact()
    assert d.changed_nodes == []
    assert d.affected_nodes == []
    assert d.related_tests == []
    assert d.unmapped_files == []
    assert d.risk_surface == []
    assert d.suggested_inspections == []
    assert d.warnings == []


def _project():
    return RepoMapProject(
        root="/repo",
        name="repo",
        git_commit="abc123",
        generated_at="2026-05-29T00:00:00Z",
        generator_version="t",
    )


def _map(nodes, edges):
    return RepoMap(schema_version=SCHEMA_VERSION, project=_project(), nodes=nodes, edges=edges)


def _src(path):
    return RepoMapNode(id=f"file:{path}", type="source_file", path=path)


def _test(path):
    return RepoMapNode(id=f"file:{path}", type="test_file", path=path)


def _likely(test_path, src_path, conf="high"):
    return RepoMapEdge(
        source=f"file:{test_path}",
        target=f"file:{src_path}",
        type="likely_tests",
        confidence=conf,
        reason="name convention",
    )


def test_changed_source_with_test_lists_related_test_and_not_risk():
    rm = _map(
        [_src("src/a.py"), _test("tests/test_a.py")], [_likely("tests/test_a.py", "src/a.py")]
    )
    out = analyze_diff_impact(rm, ["src/a.py"])
    assert [n.path for n in out.changed_nodes] == ["src/a.py"]
    assert out.changed_nodes[0].has_mapped_tests is True
    assert out.related_tests == ["tests/test_a.py"]
    assert out.risk_surface == []
    assert [n.path for n in out.affected_nodes] == ["tests/test_a.py"]


def test_changed_source_without_test_is_risk_surface():
    rm = _map([_src("src/lonely.py")], [])
    out = analyze_diff_impact(rm, ["src/lonely.py"])
    assert out.changed_nodes[0].has_mapped_tests is False
    assert out.risk_surface == ["src/lonely.py"]
    assert out.related_tests == []


def test_changed_test_file_marks_source_as_affected():
    rm = _map(
        [_src("src/a.py"), _test("tests/test_a.py")], [_likely("tests/test_a.py", "src/a.py")]
    )
    out = analyze_diff_impact(rm, ["tests/test_a.py"])
    assert [n.path for n in out.changed_nodes] == ["tests/test_a.py"]
    assert [n.path for n in out.affected_nodes] == ["src/a.py"]


def test_unmapped_changed_file_is_reported():
    rm = _map([_src("src/a.py")], [])
    out = analyze_diff_impact(rm, ["src/ghost.py", "src/a.py"])
    assert out.unmapped_files == ["src/ghost.py"]
    assert "src/ghost.py" in out.suggested_inspections


def test_dangling_edge_endpoint_is_ignored():
    # An edge whose target node is absent must not crash or invent a node.
    rm = _map([_test("tests/test_a.py")], [_likely("tests/test_a.py", "src/gone.py")])
    out = analyze_diff_impact(rm, ["tests/test_a.py"])
    assert out.affected_nodes == []


def test_empty_changeset_returns_empty_result():
    rm = _map([_src("src/a.py")], [])
    out = analyze_diff_impact(rm, [])
    assert out.changed_nodes == []
    assert out.unmapped_files == []


def test_result_is_deterministic_and_sorted():
    rm = _map(
        [_src("src/b.py"), _src("src/a.py"), _test("tests/test_a.py")],
        [_likely("tests/test_a.py", "src/a.py")],
    )
    first = analyze_diff_impact(rm, ["src/b.py", "src/a.py"])
    second = analyze_diff_impact(rm, ["src/a.py", "src/b.py"])
    assert first.model_dump() == second.model_dump()
    assert [n.path for n in first.changed_nodes] == ["src/a.py", "src/b.py"]
