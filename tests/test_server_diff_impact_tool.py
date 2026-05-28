# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the slice-4 sumo_qa_analyze_diff_impact MCP tool (#156)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from sumo_qa.server import build_mcp_server
from sumo_qa.server_schemas import DiffImpactOutput


@pytest.fixture
def server():
    return build_mcp_server()


@pytest.fixture
def tool(server):
    return server._tool_manager._tools["sumo_qa_analyze_diff_impact"].fn


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
    assert "sumo_qa_analyze_diff_impact" in server._tool_manager._tools


def test_tool_advertises_writer_annotation(server):
    ann = server._tool_manager._tools["sumo_qa_analyze_diff_impact"].annotations
    assert ann.readOnlyHint is False
    assert ann.destructiveHint is False
    assert ann.openWorldHint is False


def test_tool_description_is_declarative(server):
    desc = (server._tool_manager._tools["sumo_qa_analyze_diff_impact"].description or "").lower()
    for forbidden in ("use this when", "use this before", "you should", "you must"):
        assert forbidden not in desc


def test_explicit_changed_files_live_scan_fallback(tool, tmp_path):
    _seed_repo(tmp_path)
    out = tool(root=str(tmp_path), changed_files=["src/a.py", "src/lonely.py"])
    assert isinstance(out, DiffImpactOutput)
    assert out.used_live_scan is True
    assert out.changed_file_count == 2
    assert "tests/test_a.py" in out.related_tests
    assert "src/lonely.py" in out.risk_surface
    assert out.warning_count >= 1


def test_loads_persisted_artifact_when_present(tool, tmp_path):
    _seed_repo(tmp_path)
    from sumo_qa.repo_map_scanner import scan_repo

    rm = scan_repo(tmp_path, generator_version="t")
    artifact = tmp_path / ".sumo-qa" / "repo-map.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(rm.model_dump(mode="json")), encoding="utf-8")
    out = tool(root=str(tmp_path), changed_files=["src/a.py"])
    assert out.used_live_scan is False
    assert out.artifact_path == str(artifact.resolve())


def test_ignores_foreign_artifact_and_scans_live(tool, tmp_path):
    _seed_repo(tmp_path)
    from sumo_qa.repo_map_scanner import scan_repo

    rm = scan_repo(tmp_path, generator_version="t")
    data = rm.model_dump(mode="json")
    data["project"]["root"] = "/some/other/repo"
    artifact = tmp_path / ".sumo-qa" / "repo-map.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(data), encoding="utf-8")
    out = tool(root=str(tmp_path), changed_files=["src/a.py"])
    assert out.used_live_scan is True
    assert out.artifact_path is None
    assert out.warning_count >= 1


def test_base_ref_derives_changed_files(tool, tmp_path):
    _init_repo(tmp_path)
    _seed_repo(tmp_path)
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
    (tmp_path / "src" / "a.py").write_text("x = 2\n")
    _git(["add", "-A"], tmp_path)
    out = tool(root=str(tmp_path), base_ref=base)
    assert out.base_ref == base
    assert "src/a.py" in [n.path for n in out.changed_nodes]


def test_writes_overlay_when_requested(tool, tmp_path):
    _seed_repo(tmp_path)
    out = tool(root=str(tmp_path), changed_files=["src/a.py"], write_overlay=True)
    overlay = tmp_path / ".sumo-qa" / "diff-impact.json"
    assert out.overlay_path == str(overlay.resolve())
    assert out.overlay_bytes is not None and out.overlay_bytes > 0
    assert overlay.is_file()
    json.loads(overlay.read_text(encoding="utf-8"))


def test_error_envelope_on_missing_root(tool, tmp_path):
    out = tool(root=str(tmp_path / "nope"), changed_files=[])
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert out["error"]["type"] == "ValueError"
    assert out["error"]["actionable_hint"]


def test_error_envelope_when_no_changed_source(tool, tmp_path):
    _seed_repo(tmp_path)
    out = tool(root=str(tmp_path))
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "changed_files or base_ref" in out["error"]["message"]


def test_stale_flag_when_commit_differs(tool, tmp_path):
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
    out = tool(root=str(tmp_path), changed_files=["src/a.py"])
    assert out.is_stale is True
