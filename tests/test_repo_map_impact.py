# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the slice-4 diff-impact core (issue #156)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from sumo_qa.repo_map_impact import analyze_diff_impact, changed_files_from_git
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
    assert d.probable_mapping_gap is False


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


def test_mapped_tests_is_tristate_only_source_files_carry_a_verdict():
    """``has_mapped_tests`` answers a question that is only meaningful for
    source_file nodes. Every other node type carries None — a docs or fixture
    node must never read as a vacuous coverage 'no' alongside a meaningful
    'no' on a source file (that inflates ~1 real gap into ~22 apparent ones)."""
    docs = RepoMapNode(id="file:README.md", type="docs", path="README.md")
    fixture = RepoMapNode(
        id="file:tests/fixtures/x.json", type="fixture", path="tests/fixtures/x.json"
    )
    rm = _map(
        [_src("src/a.py"), _src("src/lonely.py"), _test("tests/test_a.py"), docs, fixture],
        [_likely("tests/test_a.py", "src/a.py")],
    )
    out = analyze_diff_impact(
        rm,
        ["src/a.py", "src/lonely.py", "README.md", "tests/fixtures/x.json", "tests/test_a.py"],
    )
    verdicts = {n.path: n.has_mapped_tests for n in out.changed_nodes}
    assert verdicts == {
        "src/a.py": True,
        "src/lonely.py": False,
        "README.md": None,
        "tests/fixtures/x.json": None,
        "tests/test_a.py": None,
    }
    # risk_surface semantics are untouched: changed source files with no
    # mapped test, and ONLY those.
    assert out.risk_surface == ["src/lonely.py"]


def test_affected_nodes_obey_the_same_tristate():
    rm = _map(
        [_src("src/a.py"), _test("tests/test_a.py")], [_likely("tests/test_a.py", "src/a.py")]
    )
    # Changed source -> affected test_file row carries None, not a vacuous bool.
    out = analyze_diff_impact(rm, ["src/a.py"])
    assert [(n.path, n.has_mapped_tests) for n in out.affected_nodes] == [("tests/test_a.py", None)]
    # Changed test -> affected source_file row keeps its real verdict.
    out = analyze_diff_impact(rm, ["tests/test_a.py"])
    assert [(n.path, n.has_mapped_tests) for n in out.affected_nodes] == [("src/a.py", True)]


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


# ---------- Probable mapping gap vs true zero coverage (#266) ----------


def test_probable_mapping_gap_when_tests_exist_but_no_edges():
    # decision table — gap signal = test_files_present (T) AND zero likely_tests
    # edges (T) AND risk_surface non-empty (T). This is the Kotlin false-positive:
    # FooTest.kt exists but the (pre-fix) mapper produced no edges, so every
    # source reads as risk surface. Must be flagged as a probable mapping gap,
    # not true zero coverage.
    rm = _map(
        [_src("src/Foo.kt"), _src("src/Bar.kt"), _test("src/test/FooTest.kt")],
        [],
    )
    out = analyze_diff_impact(rm, ["src/Foo.kt", "src/Bar.kt"])
    assert out.risk_surface == ["src/Bar.kt", "src/Foo.kt"]
    assert out.probable_mapping_gap is True
    assert any(w.kind == "other" and "mapping gap" in w.message.lower() for w in out.warnings)


def test_no_mapping_gap_when_some_edges_exist():
    # Edges exist and tests map; a single uncovered file is real partial
    # coverage, NOT a wholesale mapping gap.
    rm = _map(
        [_src("src/a.py"), _src("src/b.py"), _test("tests/test_a.py")],
        [_likely("tests/test_a.py", "src/a.py")],
    )
    out = analyze_diff_impact(rm, ["src/b.py"])
    assert out.risk_surface == ["src/b.py"]
    assert out.probable_mapping_gap is False
    assert not any("mapping gap" in w.message.lower() for w in out.warnings)


def test_mapping_gap_ignores_dangling_likely_edge():
    # A dangling likely_tests edge (target node absent) is not a usable mapping,
    # so it must not suppress the probable_mapping_gap signal — the gap check
    # uses the same both-endpoints-resolvable filter as the rest of the analysis.
    rm = _map(
        [_src("src/a.py"), _test("tests/t.py")],
        [_likely("tests/t.py", "src/gone.py")],  # target node missing
    )
    out = analyze_diff_impact(rm, ["src/a.py"])
    assert out.probable_mapping_gap is True


def test_no_mapping_gap_when_no_test_files_present():
    # No test files anywhere -> honest zero coverage, not a mapping gap.
    rm = _map([_src("src/a.py")], [])
    out = analyze_diff_impact(rm, ["src/a.py"])
    assert out.risk_surface == ["src/a.py"]
    assert out.probable_mapping_gap is False
    assert not any("mapping gap" in w.message.lower() for w in out.warnings)


def _clean_git_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def _git(args, cwd):
    subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, env=_clean_git_env()
    )


def _init_repo(root: Path):
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "t"], root)
    _git(["config", "core.hooksPath", "/dev/null"], root)


def test_changed_files_from_git_lists_diff_against_base(tmp_path: Path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "base", "--no-verify"], tmp_path)
    base = (
        subprocess.run(
            ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            env=_clean_git_env(),
        )
        .stdout.decode()
        .strip()
    )
    (tmp_path / "a.py").write_text("x = 2\n")
    (tmp_path / "b.py").write_text("y = 1\n")
    _git(["add", "-A"], tmp_path)
    changed = changed_files_from_git(tmp_path, base)
    assert changed == ["a.py", "b.py"]


def test_changed_files_from_git_rejects_non_toplevel(tmp_path: Path):
    _init_repo(tmp_path)
    sub = tmp_path / "sub"
    sub.mkdir()
    with pytest.raises(ValueError, match="not a git repository toplevel"):
        changed_files_from_git(sub, "HEAD")


def test_changed_files_from_git_uses_merge_base_not_base_tip(tmp_path: Path):
    # A base branch that advanced after the fork point must NOT leak its own
    # changes into this branch's diff — diffing the merge-base, not base tip.
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "y.py").write_text("y = 1\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "A", "--no-verify"], tmp_path)
    # 'base' advances with a change to y.py the working tree never sees.
    _git(["checkout", "-q", "-b", "base"], tmp_path)
    (tmp_path / "y.py").write_text("y = 2\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "B", "--no-verify"], tmp_path)
    # Back at the fork point; make an uncommitted change to a.py only.
    _git(["checkout", "-q", "-"], tmp_path)
    (tmp_path / "a.py").write_text("x = 2\n")
    changed = changed_files_from_git(tmp_path, "base")
    assert changed == ["a.py"]
