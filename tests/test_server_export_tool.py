# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the sumo_qa_export_test_cases MCP tool (#148).

The tool is deterministic file/format plumbing: it validates host-supplied test
cases and renders them into json / markdown / csv. It never infers a case and is
side-effect free BY DEFAULT (returns text, writes nothing) — it persists a file
ONLY when the caller explicitly passes ``output_path`` (#148's carve-out),
confined to the project export root. These tests pin the tool
registration, the writer-local annotation, the success shapes per format, the
markdown default, the schema-version stamp, and the error envelopes for an
unsupported format, a non-flat CSV request, and an invalid case.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from sumo_qa.server import build_mcp_server
from sumo_qa.server_schemas import ExportTestCasesOutput


@pytest.fixture
def server():
    return build_mcp_server()


@pytest.fixture
def tool(server):
    return server._tool_manager._tools["sumo_qa_export_test_cases"].fn


def _case(**overrides) -> dict:
    base = {
        "id": "TC1",
        "title": "Refund is idempotent across a retried request.",
        "preconditions": ["A charge exists with a known idempotency key."],
        "steps": ["POST the refund twice with the same idempotency key."],
        "expected_result": "The charge is refunded exactly once.",
        "priority": "high",
        "evidence_status": "planned",
    }
    base.update(overrides)
    return base


def test_tool_is_registered(server):
    assert "sumo_qa_export_test_cases" in server._tool_manager._tools


def test_export_title_param_survives_schema_title_slimming(server):
    # Regression for #148: the export-level title arg must be named
    # `export_title`, NOT `title`. The served-schema slimming pass drops every
    # dict key named `title` (Pydantic field-name echoes), so a param literally
    # named `title` would be stripped from the published inputSchema and a host
    # model could never see or fill it. Assert the real served schema exposes
    # `export_title` and carries no top-level `title` property (the bug shape).
    tools = asyncio.run(server.list_tools())
    export = next(t for t in tools if t.name == "sumo_qa_export_test_cases")
    props = (export.inputSchema or {}).get("properties", {})
    assert "export_title" in props, f"export_title missing from served schema: {sorted(props)}"
    assert "title" not in props


def test_tool_advertises_writer_local_annotation(server):
    # The tool writes ONLY when output_path is explicitly supplied (default None
    # stays side-effect-free), mirroring scan_repo's writer-local precedent
    # (write_to defaults None). readOnlyHint is therefore False.
    ann = server._tool_manager._tools["sumo_qa_export_test_cases"].annotations
    assert ann.readOnlyHint is False
    assert ann.destructiveHint is False
    assert ann.openWorldHint is False


def test_tool_description_is_declarative(server):
    desc = (server._tool_manager._tools["sumo_qa_export_test_cases"].description or "").lower()
    for forbidden in ("use this when", "use this before"):
        assert forbidden not in desc


def test_default_format_is_markdown(tool):
    out = tool(test_cases=[_case()])
    assert isinstance(out, ExportTestCasesOutput)
    assert out.tool == "sumo_qa_export_test_cases"
    assert out.format == "markdown"
    assert out.schema_version == "1.0"
    assert out.test_case_count == 1
    assert "**QA test cases**" in out.content


def test_json_export_returns_parseable_versioned_document(tool):
    out = tool(test_cases=[_case()], format="json", export_title="Billing")
    assert out.format == "json"
    parsed = json.loads(out.content)
    assert parsed["schema_version"] == "1.0"
    assert parsed["title"] == "Billing"
    assert parsed["test_cases"][0]["id"] == "TC1"


def test_csv_export_for_flat_outline(tool):
    out = tool(test_cases=[_case(preconditions=[], steps=[])], format="csv")
    assert out.format == "csv"
    assert out.content.startswith('"id","title",')


def test_unsupported_format_returns_error_envelope(tool):
    out = tool(test_cases=[_case()], format="xml")
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "unsupported export format" in out["error"]["message"]
    assert out["error"]["actionable_hint"]


def test_csv_for_nested_export_returns_error_envelope(tool):
    out = tool(
        test_cases=[_case(steps=["a", "b"])],
        format="csv",
    )
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "flat test-case outlines" in out["error"]["message"]


def test_invalid_priority_returns_error_envelope(tool):
    out = tool(test_cases=[_case(priority="urgent")])
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "vocab_error" in out["error"]["message"]


def test_duplicate_id_returns_error_envelope(tool):
    out = tool(test_cases=[_case(id="TC1"), _case(id="TC1")])
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "duplicate" in out["error"]["message"]


def test_missing_required_field_returns_error_envelope(tool):
    bad = _case()
    del bad["expected_result"]
    out = tool(test_cases=[bad])
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "missing_field" in out["error"]["message"]


def test_empty_export_renders_placeholder(tool):
    out = tool(test_cases=[])
    assert out.test_case_count == 0
    assert "none recorded" in out.content.lower()


# ---------------------------------------------------------------------------
# output_path write carve-out (#148 explicit file-write).
# Default (no output_path) stays side-effect-free; writing happens ONLY when an
# explicit path is supplied, confined to <cwd>/.sumo-qa/exports.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["markdown", "json", "csv"])
def test_default_no_output_path_writes_nothing(tool, tmp_path, monkeypatch, fmt):
    # NON-NEGOTIABLE: the default path is byte-identical to today and touches no
    # disk. csv needs a flat outline.
    monkeypatch.chdir(tmp_path)
    cases = [_case(preconditions=[], steps=[])] if fmt == "csv" else [_case()]
    out = tool(test_cases=cases, format=fmt)
    assert isinstance(out, ExportTestCasesOutput)
    assert out.format == fmt
    assert out.written_path is None
    assert not (tmp_path / ".sumo-qa" / "exports").exists()
    assert not (tmp_path / ".sumo-qa").exists()


def test_write_on_output_path_round_trip_json(tool, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tool(test_cases=[_case()], format="json", output_path="cases.json")
    assert isinstance(out, ExportTestCasesOutput)
    target = tmp_path / ".sumo-qa" / "exports" / "cases.json"
    assert out.written_path == str(target.resolve())
    assert target.exists()
    # the on-disk bytes EQUAL the returned content (write == render).
    assert target.read_text(encoding="utf-8") == out.content


def test_write_on_output_path_round_trip_markdown(tool, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tool(test_cases=[_case()], format="markdown", output_path="cases.md")
    target = tmp_path / ".sumo-qa" / "exports" / "cases.md"
    assert out.written_path == str(target.resolve())
    assert target.read_text(encoding="utf-8") == out.content


def test_written_bytes_equal_default_render(tool, tmp_path, monkeypatch):
    # The write path reuses the exact renderer: on-disk bytes == the no-write
    # call's content for the same input/format.
    monkeypatch.chdir(tmp_path)
    no_write = tool(test_cases=[_case()], format="json")
    written = tool(test_cases=[_case()], format="json", output_path="cases.json")
    target = tmp_path / ".sumo-qa" / "exports" / "cases.json"
    assert target.read_text(encoding="utf-8") == no_write.content
    assert written.content == no_write.content


def test_refuse_absolute_path_outside_root(tool, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    evil = tmp_path.parent / "evil.json"
    out = tool(test_cases=[_case()], format="json", output_path=str(evil))
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert out["error"]["type"] == "ExportValidationError"
    assert "export root" in out["error"]["message"]
    assert not evil.exists()


def test_refuse_traversal_escape(tool, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tool(test_cases=[_case()], format="json", output_path="../../escape.json")
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert out["error"]["type"] == "ExportValidationError"
    assert not (tmp_path.parent.parent / "escape.json").exists()
    assert not (tmp_path / ".." / "escape.json").resolve().exists()


def test_refuse_overwrite_existing(tool, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exports = tmp_path / ".sumo-qa" / "exports"
    exports.mkdir(parents=True)
    target = exports / "cases.json"
    original = "PRE-EXISTING DO NOT CLOBBER\n"
    target.write_text(original, encoding="utf-8")
    out = tool(test_cases=[_case()], format="json", output_path="cases.json")
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert out["error"]["type"] == "FileExistsError"
    assert "overwrite" in out["error"]["message"]
    # the original file is byte-for-byte UNCHANGED (no silent clobber/partial).
    assert target.read_text(encoding="utf-8") == original


def test_validation_failure_writes_no_file(tool, tmp_path, monkeypatch):
    # A bad export (duplicate id) with an output_path must NOT create a file —
    # validation precedes the write.
    monkeypatch.chdir(tmp_path)
    out = tool(
        test_cases=[_case(id="TC1"), _case(id="TC1")],
        format="json",
        output_path="cases.json",
    )
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert not (tmp_path / ".sumo-qa" / "exports" / "cases.json").exists()


def test_refuse_symlink_escape(tool, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exports = tmp_path / ".sumo-qa" / "exports"
    exports.mkdir(parents=True)
    outside = tmp_path.parent / "outside_dir"
    outside.mkdir(exist_ok=True)
    link = exports / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover -- no symlink support
        pytest.skip("platform does not support symlinks")
    out = tool(test_cases=[_case()], format="json", output_path="link/x.json")
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert out["error"]["type"] == "ExportValidationError"
    assert not (outside / "x.json").exists()


def test_refuse_parent_symlink_swapped_after_validation(tool, tmp_path, monkeypatch):
    # TOCTOU regression: _resolve_export_target validates a benign in-root path,
    # but an attacker then swaps the dest's PARENT for a symlink pointing outside
    # the root before the bytes are written. The atomic O_NOFOLLOW openat/renameat
    # write must refuse to follow the swapped-in parent symlink, so nothing lands
    # outside the export root. We simulate winning that race by performing the
    # swap inside a wrapper around the real _write_atomic (invoked AFTER
    # _resolve_export_target has already returned a validated target).
    import sumo_qa.server as server_mod

    monkeypatch.chdir(tmp_path)
    exports = tmp_path / ".sumo-qa" / "exports"
    exports.mkdir(parents=True)
    outside = tmp_path.parent / "toctou_outside"
    outside.mkdir(exist_ok=True)
    # The benign validated target is exports/subdir/x.json; the attacker turns
    # `subdir` into a symlink -> outside in the check->write gap.
    subdir = exports / "subdir"
    real_write = server_mod._write_atomic

    def racing_write(dest, text):
        # Recreate the parent as a symlink to outside, mimicking the attacker
        # winning the race after validation but before the open.
        if subdir.exists() or subdir.is_symlink():
            subdir.rmdir() if subdir.is_dir() and not subdir.is_symlink() else subdir.unlink()
        try:
            subdir.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):  # pragma: no cover -- no symlink support
            pytest.skip("platform does not support symlinks")
        return real_write(dest, text)

    monkeypatch.setattr(server_mod, "_write_atomic", racing_write)
    out = tool(test_cases=[_case()], format="json", output_path="subdir/x.json")
    # The write must fail (O_NOFOLLOW on the parent dir refuses the symlink) and
    # NOTHING must be written through the symlink into the outside dir.
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert not (outside / "x.json").exists()
