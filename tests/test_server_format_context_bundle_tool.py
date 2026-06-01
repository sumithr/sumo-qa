# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the sumo_qa_format_context_bundle MCP tool (#149).

The tool is file/format plumbing: it validates a host-supplied context bundle
and renders a host-neutral markdown brief + roll-up. It never inspects a repo or
makes a network call. These tests pin the registration, the read-only
annotation, the success shape, the stale/untrustworthy-evidence signal, the
bundle-vs-local conflict signal, partial-bundle tolerance, and the error
envelope.
"""

from __future__ import annotations

import pytest

from sumo_qa.context_bundle_models import CONTEXT_BUNDLE_SCHEMA_VERSION
from sumo_qa.server import build_mcp_server
from sumo_qa.server_schemas import FormatContextBundleOutput


@pytest.fixture
def server():
    return build_mcp_server()


@pytest.fixture
def tool(server):
    return server._tool_manager._tools["sumo_qa_format_context_bundle"].fn


def _bundle(**overrides) -> dict:
    base = {
        "schema_version": CONTEXT_BUNDLE_SCHEMA_VERSION,
        "issue_summary": "Refund double-charges on retry.",
        "pr_summary": "Add idempotency key.",
        "head_sha": "aaa",
        "changed_files": [{"path": "billing/refund.py", "change_kind": "modified"}],
        "test_evidence": {"result": "passing", "freshness": "fresh", "source": "local_git"},
        "ci_status": {"result": "passing", "freshness": "fresh", "source": "ci_provider"},
    }
    base.update(overrides)
    return base


def test_tool_is_registered(server):
    assert "sumo_qa_format_context_bundle" in server._tool_manager._tools


def test_tool_advertises_read_only_annotation(server):
    ann = server._tool_manager._tools["sumo_qa_format_context_bundle"].annotations
    assert ann.readOnlyHint is True
    assert ann.destructiveHint is False
    assert ann.openWorldHint is False


def test_tool_description_is_declarative(server):
    desc = (server._tool_manager._tools["sumo_qa_format_context_bundle"].description or "").lower()
    for forbidden in ("use this when", "use this before"):
        assert forbidden not in desc


def test_success_returns_structured_output(tool):
    out = tool(bundle=_bundle())
    assert isinstance(out, FormatContextBundleOutput)
    assert out.tool == "sumo_qa_format_context_bundle"
    assert out.changed_file_count == 1
    assert out.stale_evidence_fields == []
    assert out.untrustworthy_evidence_fields == []
    assert out.conflict is None
    assert "**Context bundle**" in out.markdown


def test_partial_bundle_is_accepted(tool):
    # Only the version + a single field — the absent-bundle path must not error.
    out = tool(bundle={"schema_version": CONTEXT_BUNDLE_SCHEMA_VERSION})
    assert isinstance(out, FormatContextBundleOutput)
    assert out.changed_file_count == 0
    assert out.untrustworthy_evidence_fields == []
    assert "Stale-evidence warning" not in out.markdown


def test_stale_ci_is_flagged(tool):
    out = tool(
        bundle=_bundle(
            ci_status={"result": "passing", "freshness": "stale", "source": "ci_provider"}
        )
    )
    assert out.stale_evidence_fields == ["ci_status"]
    assert out.untrustworthy_evidence_fields == ["ci_status"]
    assert "Stale-evidence warning" in out.markdown


def test_unknown_freshness_is_untrustworthy_but_not_stale(tool):
    out = tool(
        bundle=_bundle(
            test_evidence={"result": "passing", "freshness": "unknown", "source": "manual"}
        )
    )
    assert out.stale_evidence_fields == []
    assert out.untrustworthy_evidence_fields == ["test_evidence"]


def test_local_conflict_is_reported(tool):
    out = tool(bundle=_bundle(head_sha="aaa"), local_head_sha="bbb")
    assert out.conflict is not None
    assert "aaa" in out.conflict and "bbb" in out.conflict
    assert "Conflict" in out.markdown


def test_matching_local_head_no_conflict(tool):
    out = tool(bundle=_bundle(head_sha="aaa"), local_head_sha="aaa")
    assert out.conflict is None


def test_invalid_freshness_returns_error_envelope(tool):
    bad = _bundle()
    bad["ci_status"]["freshness"] = "probably_old"
    out = tool(bundle=bad)
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "vocab_error" in out["error"]["message"]
    assert out["error"]["actionable_hint"]


def test_missing_schema_version_returns_error_envelope(tool):
    out = tool(bundle={"issue_summary": "no version"})
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "missing_field" in out["error"]["message"]


def test_unknown_field_returns_error_envelope(tool):
    bad = _bundle()
    bad["rogue"] = True
    out = tool(bundle=bad)
    assert isinstance(out, dict)
    assert out["isError"] is True
    assert "unknown_field" in out["error"]["message"]
