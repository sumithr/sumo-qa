# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the sumo_qa_record_coverage / sumo_qa_record_mutation MCP tools.

These are the persisted producers the QA report lacked (#147 follow-up): the
host runs the coverage/mutation tool and the LLM reads its output; these tools
only validate the collected summary and write the conventional artifact. Pinned
here: registration + writer-local annotation, validate-before-write (a bad
payload writes nothing and returns an error envelope), and the compact response
shape.
"""

from __future__ import annotations

import json

import pytest

from sumo_qa.server import build_mcp_server
from sumo_qa.server_schemas import RecordCoverageOutput, RecordMutationOutput


@pytest.fixture
def server():
    return build_mcp_server()


@pytest.fixture
def record_coverage(server):
    return server._tool_manager._tools["sumo_qa_record_coverage"].fn


@pytest.fixture
def record_mutation(server):
    return server._tool_manager._tools["sumo_qa_record_mutation"].fn


def test_tools_registered(server):
    assert "sumo_qa_record_coverage" in server._tool_manager._tools
    assert "sumo_qa_record_mutation" in server._tool_manager._tools


def test_record_tools_advertise_writer_local_annotation(server):
    for name in ("sumo_qa_record_coverage", "sumo_qa_record_mutation"):
        ann = server._tool_manager._tools[name].annotations
        assert ann.readOnlyHint is False
        assert ann.destructiveHint is False
        assert ann.openWorldHint is False


def test_record_coverage_writes_artifact(record_coverage, tmp_path):
    out = record_coverage(
        root=str(tmp_path),
        coverage={
            "source_tool": "pytest-cov",
            "generated_at": "2026-06-12T00:00:00Z",
            "line_percent": 100.0,
            "freshness": "fresh",
            "detail": "changed-file gaps: none",
        },
    )
    assert isinstance(out, RecordCoverageOutput)
    assert out.line_percent == 100.0
    assert out.freshness == "fresh"
    assert "100% lines" in out.compact_summary

    written = json.loads((tmp_path / ".sumo-qa" / "coverage.json").read_text(encoding="utf-8"))
    assert written["line_percent"] == 100.0
    assert written["schema_version"] == "1.0"
    assert written["source_tool"] == "pytest-cov"


def test_record_coverage_not_measured(record_coverage, tmp_path):
    out = record_coverage(
        root=str(tmp_path),
        coverage={"source_tool": "x", "generated_at": "x", "freshness": "fresh"},
    )
    assert isinstance(out, RecordCoverageOutput)
    assert out.line_percent is None
    assert "not measured" in out.compact_summary


def test_record_coverage_bad_input_returns_envelope_and_writes_nothing(record_coverage, tmp_path):
    out = record_coverage(
        root=str(tmp_path),
        coverage={
            "source_tool": "x",
            "generated_at": "x",
            "line_percent": 101.0,
            "freshness": "fresh",
        },
    )
    assert out["isError"] is True
    assert out["error"]["type"]
    assert not (tmp_path / ".sumo-qa" / "coverage.json").exists()


def test_record_coverage_missing_root_returns_envelope(record_coverage, tmp_path):
    out = record_coverage(
        root=str(tmp_path / "does-not-exist"),
        coverage={"source_tool": "x", "generated_at": "x", "freshness": "fresh"},
    )
    assert out["isError"] is True


def test_record_mutation_writes_artifact(record_mutation, tmp_path):
    out = record_mutation(
        root=str(tmp_path),
        mutation={
            "source_tool": "mutmut",
            "generated_at": "2026-06-12T00:00:00Z",
            "survivors": 2,
            "killed": 145,
            "freshness": "fresh",
        },
    )
    assert isinstance(out, RecordMutationOutput)
    assert (out.survivors, out.killed) == (2, 145)
    assert "2 survivor(s)" in out.compact_summary
    assert "145 killed" in out.compact_summary

    written = json.loads((tmp_path / ".sumo-qa" / "mutation.json").read_text(encoding="utf-8"))
    assert written["survivors"] == 2
    assert written["killed"] == 145


def test_record_mutation_bad_input_returns_envelope(record_mutation, tmp_path):
    out = record_mutation(
        root=str(tmp_path),
        mutation={"source_tool": "x", "generated_at": "x", "survivors": -1, "freshness": "fresh"},
    )
    assert out["isError"] is True
    assert not (tmp_path / ".sumo-qa" / "mutation.json").exists()


def test_record_coverage_relative_write_to_confined_to_root(record_coverage, tmp_path):
    out = record_coverage(
        root=str(tmp_path),
        coverage={"source_tool": "x", "generated_at": "x", "freshness": "fresh"},
        write_to="../escape.json",
    )
    assert out["isError"] is True
    assert not (tmp_path.parent / "escape.json").exists()
