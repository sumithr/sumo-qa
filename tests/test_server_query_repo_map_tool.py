# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the sumo_qa_query_repo_map MCP tool (#156 query tool)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from sumo_qa.server import build_mcp_server
from sumo_qa.server_schemas import RepoMapQueryOutput


@pytest.fixture
def server():
    return build_mcp_server()


@pytest.fixture
def tool(server):
    return server._tool_manager._tools["sumo_qa_query_repo_map"].fn


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
    _git(["config", "user.email", "t@e.com"], root)
    _git(["config", "user.name", "t"], root)
    _git(["config", "core.hooksPath", "/dev/null"], root)


def _seed_repo(root: Path):
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "a.py").write_text("x = 1\n")
    (root / "tests" / "test_a.py").write_text("def test_x():\n    pass\n")
    (root / "src" / "lonely.py").write_text("y = 1\n")


def test_tool_is_registered(server):
    assert "sumo_qa_query_repo_map" in server._tool_manager._tools


def test_tool_advertises_read_only_annotation(server):
    ann = server._tool_manager._tools["sumo_qa_query_repo_map"].annotations
    assert ann.readOnlyHint is True
    assert ann.destructiveHint is False
    assert ann.openWorldHint is False


def test_tool_description_is_declarative(server):
    desc = (server._tool_manager._tools["sumo_qa_query_repo_map"].description or "").lower()
    for forbidden in ("use this when", "use this before", "you should", "you must"):
        assert forbidden not in desc


def test_query_by_path_live_scan_fallback(tool, tmp_path):
    _seed_repo(tmp_path)
    out = tool(root=str(tmp_path), query="src/a.py")
    assert isinstance(out, RepoMapQueryOutput)
    assert out.used_live_scan is True
    assert "src/a.py" in {m.path for m in out.matches}
    assert out.warning_count >= 1  # live-scan fallback warning


def test_query_by_evidence_type(tool, tmp_path):
    _seed_repo(tmp_path)
    out = tool(root=str(tmp_path), query="test_file")
    assert "tests/test_a.py" in {m.path for m in out.matches}
    assert all(m.type == "test_file" for m in out.matches if m.kind == "node")


def test_query_loads_persisted_artifact_when_present(tool, tmp_path):
    _seed_repo(tmp_path)
    from sumo_qa.repo_map_scanner import scan_repo

    rm = scan_repo(tmp_path, generator_version="t")
    artifact = tmp_path / ".sumo-qa" / "repo-map.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(rm.model_dump(mode="json")), encoding="utf-8")
    out = tool(root=str(tmp_path), query="a.py")
    assert out.used_live_scan is False
    assert out.artifact_path == str(artifact.resolve())


def test_query_ignores_foreign_artifact_and_scans_live(tool, tmp_path):
    _seed_repo(tmp_path)
    from sumo_qa.repo_map_scanner import scan_repo

    rm = scan_repo(tmp_path, generator_version="t")
    data = rm.model_dump(mode="json")
    data["project"]["root"] = "/some/other/repo"
    artifact = tmp_path / ".sumo-qa" / "repo-map.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(data), encoding="utf-8")
    out = tool(root=str(tmp_path), query="a.py")
    assert out.used_live_scan is True
    assert out.artifact_path is None
    assert out.warning_count == 1  # foreign-artifact rejection only


def test_query_limit_truncates_and_reports_total(tool, tmp_path):
    _seed_repo(tmp_path)
    out = tool(root=str(tmp_path), query=".py", limit=1)
    assert len(out.matches) == 1
    assert out.total_matches >= 2
    assert out.truncated is True


def test_query_types_filter(tool, tmp_path):
    _seed_repo(tmp_path)
    out = tool(root=str(tmp_path), query="a.py", types=["test_file"])
    assert out.types_filter == ["test_file"]
    assert {m.path for m in out.matches} == {"tests/test_a.py"}


def test_query_stale_flag_when_commit_differs(tool, tmp_path):
    _init_repo(tmp_path)
    _seed_repo(tmp_path)
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "c1", "--no-verify"], tmp_path)
    from sumo_qa.repo_map_scanner import scan_repo

    rm = scan_repo(tmp_path, generator_version="t")
    data = rm.model_dump(mode="json")
    data["project"]["git_commit"] = "0" * 40
    artifact = tmp_path / ".sumo-qa" / "repo-map.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(data), encoding="utf-8")
    out = tool(root=str(tmp_path), query="a.py")
    assert out.is_stale is True
    assert out.warnings_by_kind.get("stale", 0) >= 1


def test_query_freshness_summary_present(tool, tmp_path):
    _seed_repo(tmp_path)
    out = tool(root=str(tmp_path), query="a.py")
    assert out.schema_version == "1.0"
    assert out.generator_version
    assert out.generated_at is not None


def test_error_envelope_on_missing_root(tool, tmp_path):
    out = tool(root=str(tmp_path / "nope"), query="a.py")
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert out["error"]["type"] == "ValueError"
    assert out["error"]["actionable_hint"]


def test_error_envelope_on_blank_query(tool, tmp_path):
    _seed_repo(tmp_path)
    out = tool(root=str(tmp_path), query="   ")
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "blank" in out["error"]["message"]


def test_error_envelope_on_unknown_types(tool, tmp_path):
    _seed_repo(tmp_path)
    out = tool(root=str(tmp_path), query="a.py", types=["testfile"])
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "unknown types" in out["error"]["message"]
