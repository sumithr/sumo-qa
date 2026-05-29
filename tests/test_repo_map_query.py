# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the pure repo-map query function (#156 query tool).

Technique: equivalence partitioning over the match dimensions (exact node id,
exact path, evidence type, category, tag, file name, substring, command name,
command kind, no-match) — one representative per class. Plus boundary value
analysis on the ``limit`` bound (0, at-limit, over-limit -> truncated).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sumo_qa.repo_map_models import (
    RepoMap,
    RepoMapCommand,
    RepoMapNode,
    RepoMapProject,
)
from sumo_qa.repo_map_query import query_repo_map


def _project() -> RepoMapProject:
    return RepoMapProject(
        root="/repo",
        name="example",
        git_commit="abc123",
        generated_at=datetime(2026, 5, 29, tzinfo=timezone.utc),
        generator_version="sumo-qa test",
    )


@pytest.fixture
def repo_map() -> RepoMap:
    nodes = [
        RepoMapNode(
            id="file:src/sumo_qa/server.py",
            type="source_file",
            path="src/sumo_qa/server.py",
            language="python",
            category="app",
            tags=["mcp", "entrypoint"],
        ),
        RepoMapNode(
            id="file:tests/test_server.py",
            type="test_file",
            path="tests/test_server.py",
            language="python",
            tags=["mcp"],
        ),
        RepoMapNode(
            id="file:.github/workflows/ci.yml",
            type="ci_workflow",
            path=".github/workflows/ci.yml",
            language="yaml",
        ),
        RepoMapNode(
            id="file:src/sumo_qa/installer.py",
            type="source_file",
            path="src/sumo_qa/installer.py",
            language="python",
            category="cli",
        ),
    ]
    commands = [
        RepoMapCommand(name="pytest", kind="test", source="pyproject.toml", raw="pytest -q"),
        RepoMapCommand(name="ruff", kind="lint", source="pyproject.toml", raw="ruff check"),
    ]
    return RepoMap(schema_version="1.0", project=_project(), nodes=nodes, commands=commands)


# --- equivalence partitioning: one representative per match class ---------


def test_exact_node_id_ranks_first(repo_map):
    res = query_repo_map(repo_map, "file:src/sumo_qa/server.py")
    assert res.matches, "expected a match for an exact node id"
    top = res.matches[0]
    assert top.kind == "node"
    assert top.id == "file:src/sumo_qa/server.py"
    assert "id" in top.match_reason.lower()


def test_exact_path_match(repo_map):
    res = query_repo_map(repo_map, "src/sumo_qa/server.py")
    assert res.matches[0].path == "src/sumo_qa/server.py"
    assert res.matches[0].kind == "node"


def test_evidence_type_match_returns_all_of_that_type(repo_map):
    res = query_repo_map(repo_map, "ci_workflow")
    paths = {m.path for m in res.matches}
    assert ".github/workflows/ci.yml" in paths
    assert all(m.type == "ci_workflow" for m in res.matches if m.kind == "node")


def test_category_match(repo_map):
    res = query_repo_map(repo_map, "cli")
    assert "src/sumo_qa/installer.py" in {m.path for m in res.matches}


def test_tag_match(repo_map):
    res = query_repo_map(repo_map, "entrypoint")
    assert {m.path for m in res.matches} == {"src/sumo_qa/server.py"}
    assert "entrypoint" in res.matches[0].match_reason


def test_filename_match(repo_map):
    res = query_repo_map(repo_map, "installer.py")
    assert "src/sumo_qa/installer.py" in {m.path for m in res.matches}


def test_substring_path_match(repo_map):
    res = query_repo_map(repo_map, "sumo_qa")
    paths = {m.path for m in res.matches}
    assert "src/sumo_qa/server.py" in paths
    assert "src/sumo_qa/installer.py" in paths


def test_command_name_match(repo_map):
    res = query_repo_map(repo_map, "pytest")
    cmd = [m for m in res.matches if m.kind == "command"]
    assert cmd, "expected a command match for 'pytest'"
    assert cmd[0].id == "command:pytest"
    assert cmd[0].type == "test"
    assert cmd[0].path == "pyproject.toml"


def test_command_kind_match(repo_map):
    res = query_repo_map(repo_map, "lint")
    assert any(m.kind == "command" and m.id == "command:ruff" for m in res.matches)


def test_id_substring_match(repo_map):
    # "file:" is in every node id but in no path — forces the id-substring branch.
    res = query_repo_map(repo_map, "file:")
    assert {m.path for m in res.matches if m.kind == "node"} == {
        "src/sumo_qa/server.py",
        "tests/test_server.py",
        ".github/workflows/ci.yml",
        "src/sumo_qa/installer.py",
    }
    assert all("node id contains" in m.match_reason for m in res.matches if m.kind == "node")


def test_tag_substring_match(repo_map):
    # "entry" is a substring of the "entrypoint" tag but not an exact tag/path/id.
    res = query_repo_map(repo_map, "entry")
    assert {m.path for m in res.matches} == {"src/sumo_qa/server.py"}
    assert "tag contains" in res.matches[0].match_reason


def test_command_name_substring_match(repo_map):
    # "ytest" is inside "pytest" but is not the exact name or kind.
    res = query_repo_map(repo_map, "ytest")
    assert [m.id for m in res.matches] == ["command:pytest"]
    assert "command name contains" in res.matches[0].match_reason


def test_command_raw_substring_match(repo_map):
    # "check" is only in ruff's raw ("ruff check"), not its name or kind.
    res = query_repo_map(repo_map, "check")
    assert [m.id for m in res.matches] == ["command:ruff"]
    assert "command contains" in res.matches[0].match_reason


def test_no_match_returns_empty(repo_map):
    res = query_repo_map(repo_map, "nonexistent-xyzzy")
    assert res.matches == []
    assert res.total_matches == 0
    assert res.truncated is False


def test_case_insensitive(repo_map):
    res = query_repo_map(repo_map, "SERVER.PY")
    assert "src/sumo_qa/server.py" in {m.path for m in res.matches}


def test_matches_sorted_by_score_descending(repo_map):
    res = query_repo_map(repo_map, "mcp")
    scores = [m.score for m in res.matches]
    assert scores == sorted(scores, reverse=True)


# --- types filter ---------------------------------------------------------


def test_types_filter_restricts_to_node_type(repo_map):
    # "server" matches both server.py (source_file) and test_server.py
    # (test_file); the filter keeps only the test_file.
    res = query_repo_map(repo_map, "server", types=["test_file"])
    assert res.types_filter == ["test_file"]
    assert {m.path for m in res.matches} == {"tests/test_server.py"}


def test_types_filter_excludes_commands_when_node_type_given(repo_map):
    res = query_repo_map(repo_map, "pytest", types=["source_file"])
    assert all(m.kind == "node" for m in res.matches)
    assert not any(m.kind == "command" for m in res.matches)


def test_command_type_in_filter_includes_commands(repo_map):
    res = query_repo_map(repo_map, "ruff", types=["command"])
    assert any(m.kind == "command" and m.id == "command:ruff" for m in res.matches)
    assert all(m.kind == "command" for m in res.matches)


# --- boundary value analysis on the limit bound --------------------------


def test_limit_bounds_returned_matches(repo_map):
    # ".py" substring matches the 3 python file paths (server, test_server,
    # installer); ci.yml does not.
    res = query_repo_map(repo_map, ".py", limit=2)
    assert len(res.matches) == 2
    assert res.total_matches == 3
    assert res.truncated is True


def test_limit_at_total_is_not_truncated(repo_map):
    res_all = query_repo_map(repo_map, ".py", limit=100)
    total = res_all.total_matches
    res = query_repo_map(repo_map, ".py", limit=total)
    assert len(res.matches) == total
    assert res.truncated is False


def test_limit_zero_returns_no_matches_but_reports_total(repo_map):
    res = query_repo_map(repo_map, ".py", limit=0)
    assert res.matches == []
    assert res.total_matches == 3
    assert res.truncated is True


def test_negative_limit_rejected(repo_map):
    with pytest.raises(ValueError):
        query_repo_map(repo_map, "sumo_qa", limit=-1)


def test_blank_query_rejected(repo_map):
    with pytest.raises(ValueError):
        query_repo_map(repo_map, "   ")


def test_unknown_types_value_rejected(repo_map):
    # A typo'd node type must fail loudly, not silently return zero matches.
    with pytest.raises(ValueError, match="unknown types"):
        query_repo_map(repo_map, "server", types=["testfile"])


def test_command_in_types_is_valid(repo_map):
    # "command" is a valid filter value alongside node types.
    res = query_repo_map(repo_map, "ruff", types=["command", "source_file"])
    assert res.types_filter == ["command", "source_file"]
    assert any(m.id == "command:ruff" for m in res.matches)


def test_limit_clamped_to_hard_max(repo_map):
    from sumo_qa.repo_map_query import _MAX_LIMIT

    res = query_repo_map(repo_map, ".py", limit=10_000)
    assert res.limit == _MAX_LIMIT
    # The fixture has fewer than _MAX_LIMIT matches, so nothing is truncated.
    assert res.truncated is False


def test_effective_limit_echoed_when_under_max(repo_map):
    res = query_repo_map(repo_map, ".py", limit=2)
    assert res.limit == 2


def test_duplicate_command_names_sort_deterministically():
    project = _project()
    commands = [
        RepoMapCommand(name="build", kind="build", source="b/package.json", raw="b"),
        RepoMapCommand(name="build", kind="build", source="a/package.json", raw="a"),
    ]
    rm = RepoMap(schema_version="1.0", project=project, nodes=[], commands=commands)
    res = query_repo_map(rm, "build")
    # Both match on exact command name (same id "command:build"); the (id, path)
    # tiebreak orders them by source path deterministically.
    assert [m.path for m in res.matches] == ["a/package.json", "b/package.json"]
