# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the slice-3 sumo_qa_scan_repo MCP tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sumo_qa.server import build_mcp_server
from sumo_qa.server_schemas import RepoMapScanOutput


@pytest.fixture
def server():
    return build_mcp_server()


@pytest.fixture
def tool(server):
    return server._tool_manager._tools["sumo_qa_scan_repo"].fn


def _make_file(root: Path, rel: str, content: str = "x") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---------- Registration ----------


def test_scan_repo_tool_is_registered(server) -> None:
    tool_names = set(server._tool_manager._tools.keys())
    assert "sumo_qa_scan_repo" in tool_names


def test_scan_repo_tool_advertises_writer_annotation(server) -> None:
    # The tool can write the artifact to an arbitrary path via ``write_to``,
    # so it must NOT advertise ``read_only_hint`` — a host that trusts that hint
    # could auto-run the tool or skip write confirmation and silently overwrite
    # a local file. Register as a (non-destructive, local) writer instead.
    info = server._tool_manager._tools["sumo_qa_scan_repo"]
    ann = info.annotations
    assert ann.read_only_hint is False
    assert ann.destructive_hint is False
    assert ann.open_world_hint is False


def test_scan_repo_tool_description_is_declarative(server) -> None:
    desc = (server._tool_manager._tools["sumo_qa_scan_repo"].description or "").lower()
    # Existing host-neutrality lint (in test_server.py) forbids directive
    # phrases; mirror it locally so the new tool can't accidentally
    # reintroduce them.
    for forbidden in ("use this when", "use this before", "you should", "you must"):
        assert forbidden not in desc, f"description contains directive phrase: {forbidden}"


# ---------- Happy path ----------


def test_scan_repo_returns_compact_summary(tool, tmp_path: Path):
    _make_file(tmp_path, "README.md", "# x\n")
    _make_file(tmp_path, "src/app.py", "x = 1\n")
    _make_file(tmp_path, "tests/test_app.py", "def test_x():\n    pass\n")
    _make_file(tmp_path, "pyproject.toml", '[project]\nname = "x"\nversion = "1"\n')

    output = tool(root=str(tmp_path))

    assert isinstance(output, RepoMapScanOutput)
    assert output.tool == "sumo_qa_scan_repo"
    assert output.schema_version == "1.0"
    assert output.node_count >= 4
    assert output.nodes_by_type["source_file"] >= 1
    assert output.nodes_by_type["test_file"] >= 1
    assert output.nodes_by_type["docs"] >= 1
    assert output.nodes_by_type["manifest"] >= 1
    assert output.edge_count >= 1
    assert output.edges_by_type["likely_tests"] >= 1
    assert "high" in output.edges_by_confidence
    # Compact-by-design: the schema explicitly does NOT carry node/edge arrays.
    serialized = output.model_dump()
    assert "nodes" not in serialized
    assert "edges" not in serialized


def test_scan_repo_writes_artifact_when_write_to_provided(tool, tmp_path: Path):
    _make_file(tmp_path, "src/app.py", "x = 1\n")
    artifact = tmp_path / "out" / "repo-map.json"

    output = tool(root=str(tmp_path), write_to=str(artifact))

    assert output.artifact_path == str(artifact.resolve())
    assert output.artifact_bytes is not None
    assert output.artifact_bytes > 0
    assert artifact.is_file()
    written = json.loads(artifact.read_text(encoding="utf-8"))
    assert written["schema_version"] == "1.0"
    assert written["project"]["root"] == str(tmp_path.resolve())
    # Round-trip back through the slice-1 validator to confirm the on-disk
    # artifact is conformant, not just a JSON dump that happens to look right.
    from sumo_qa.repo_map_validation import load_repo_map

    load_repo_map(artifact)


def test_scan_repo_relative_write_to_resolves_under_root(tool, tmp_path: Path, monkeypatch):
    # A relative write_to (the conventional ".sumo-qa/repo-map.json") must land
    # under the SCANNED root, not the server cwd — even when cwd is elsewhere.
    _make_file(tmp_path, "src/app.py", "x = 1\n")
    elsewhere = tmp_path / "server_cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    output = tool(root=str(tmp_path), write_to=".sumo-qa/repo-map.json")

    expected = tmp_path / ".sumo-qa" / "repo-map.json"
    assert output.artifact_path == str(expected.resolve())
    assert expected.is_file()
    # NOT under the server cwd
    assert not (elsewhere / ".sumo-qa" / "repo-map.json").exists()


def test_scan_repo_skips_disk_write_when_write_to_omitted(tool, tmp_path: Path):
    _make_file(tmp_path, "src/app.py", "x = 1\n")
    output = tool(root=str(tmp_path))
    assert output.artifact_path is None
    assert output.artifact_bytes is None


def test_scan_repo_default_generator_version_is_package_version(tool, tmp_path: Path):
    _make_file(tmp_path, "src/app.py", "x = 1\n")
    output = tool(root=str(tmp_path))
    assert output.generator_version.startswith("sumo-qa ")


def test_scan_repo_explicit_generator_version_is_honoured(tool, tmp_path: Path):
    _make_file(tmp_path, "src/app.py", "x = 1\n")
    output = tool(root=str(tmp_path), generator_version="custom-1.2.3")
    assert output.generator_version == "custom-1.2.3"


# ---------- Error envelope ----------


def test_scan_repo_returns_error_envelope_on_missing_root(tool, tmp_path: Path):
    output = tool(root=str(tmp_path / "does-not-exist"))
    assert isinstance(output, dict)
    assert output.get("isError") is True
    err = output["error"]
    assert err["type"] == "ValueError"
    assert "must be a directory" in err["message"]
    assert err["actionable_hint"]


def test_scan_repo_returns_error_envelope_on_file_root(tool, tmp_path: Path):
    f = tmp_path / "not-a-dir"
    f.write_text("x")
    output = tool(root=str(f))
    assert isinstance(output, dict)
    assert output.get("isError") is True
    assert output["error"]["type"] == "ValueError"
