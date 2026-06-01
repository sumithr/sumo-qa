# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.context_bundle_validation — the load/validate envelope for
a host-neutral context-bundle payload (issue #149).

Mirrors the risk-ledger validation envelope: every failure mode raises
``ContextBundleValidationError`` with a stable ``kind`` so the MCP wrapper can
branch on the category. Crucially, an ABSENT or PARTIAL bundle is NOT a failure
— the contract must degrade cleanly when the host has little context.
"""

from __future__ import annotations

import pytest

from sumo_qa.context_bundle_models import CONTEXT_BUNDLE_SCHEMA_VERSION
from sumo_qa.context_bundle_validation import (
    ContextBundleValidationError,
    load_context_bundle,
)


def _payload(**overrides) -> dict:
    base = {
        "schema_version": CONTEXT_BUNDLE_SCHEMA_VERSION,
        "issue_summary": "Refund endpoint double-charges on retry.",
        "pr_summary": "Add idempotency key to refund path.",
        "head_sha": "abc123",
        "changed_files": [{"path": "billing/refund.py", "change_kind": "modified"}],
        "test_evidence": {"result": "passing", "freshness": "fresh", "source": "local_git"},
        "ci_status": {"result": "passing", "freshness": "stale", "source": "ci_provider"},
        "user_constraints": ["No schema changes."],
    }
    base.update(overrides)
    return base


# --- absent / partial bundle is first-class (not an error) -------------------


def test_empty_but_stamped_bundle_loads():
    # The "absent bundle" path: only the version is supplied. Must NOT raise —
    # the consuming skill falls back to direct inspection on a thin bundle.
    bundle = load_context_bundle({"schema_version": CONTEXT_BUNDLE_SCHEMA_VERSION})
    assert bundle.issue_summary is None
    assert bundle.changed_files == []
    assert bundle.test_evidence is None
    assert bundle.ci_status is None


def test_unstamped_empty_bundle_loads_and_defaults_version():
    # The first-class-partial contract: a wholly empty ``{}`` bundle (no version
    # stamp at all) MUST load — schema_version defaults to "1.0" rather than
    # raising missing_field. This test fails if schema_version is made required.
    bundle = load_context_bundle({})
    assert bundle.schema_version == CONTEXT_BUNDLE_SCHEMA_VERSION
    assert bundle.issue_summary is None
    assert bundle.changed_files == []


def test_partial_bundle_loads():
    # A partial bundle (issue text + one file, no CI/test evidence) is valid.
    bundle = load_context_bundle(
        {
            "schema_version": CONTEXT_BUNDLE_SCHEMA_VERSION,
            "issue_summary": "Just the ticket text.",
            "changed_files": [{"path": "a.py"}],
        }
    )
    assert bundle.issue_summary == "Just the ticket text."
    assert bundle.changed_files[0].change_kind == "modified"  # defaulted
    assert bundle.ci_status is None


def test_full_bundle_loads():
    bundle = load_context_bundle(_payload())
    assert bundle.head_sha == "abc123"
    assert bundle.test_evidence.freshness == "fresh"
    assert bundle.ci_status.freshness == "stale"


# --- genuine shape failures get stable kinds ---------------------------------


def test_schema_version_mismatch_has_dedicated_kind():
    with pytest.raises(ContextBundleValidationError) as excinfo:
        load_context_bundle(_payload(schema_version="2.0"))
    assert excinfo.value.kind == "schema_version_mismatch"
    assert "2.0" in excinfo.value.message


def test_missing_schema_version_defaults_not_an_error():
    # A missing schema_version is NO LONGER a missing_field error — it defaults
    # to the current version so an unstamped partial bundle still loads. Other
    # fields supplied alongside it are preserved.
    bundle = load_context_bundle({"issue_summary": "no version stamp"})
    assert bundle.schema_version == CONTEXT_BUNDLE_SCHEMA_VERSION
    assert bundle.issue_summary == "no version stamp"


def test_present_mismatched_schema_version_still_rejected():
    # The explicit-mismatch rejection is kept: a PRESENT but wrong version raises
    # schema_version_mismatch even though a missing one now defaults.
    with pytest.raises(ContextBundleValidationError) as excinfo:
        load_context_bundle({"schema_version": "2.0"})
    assert excinfo.value.kind == "schema_version_mismatch"
    assert "2.0" in excinfo.value.message


def test_missing_required_subfield_categorised_as_missing_field():
    # A required sub-field that IS still mandatory (a changed_files entry's
    # ``path``) raises missing_field — the stable kind survives even though the
    # top-level schema_version now defaults.
    with pytest.raises(ContextBundleValidationError) as excinfo:
        load_context_bundle(_payload(changed_files=[{"change_kind": "added"}]))
    assert excinfo.value.kind == "missing_field"
    assert excinfo.value.path == "changed_files/0/path"


def test_unknown_field_on_unstamped_bundle_still_rejected():
    # The default doesn't loosen extra-field forbidding: an unknown field still
    # raises unknown_field even when schema_version is omitted.
    with pytest.raises(ContextBundleValidationError) as excinfo:
        load_context_bundle({"rogue": True})
    assert excinfo.value.kind == "unknown_field"


def test_unknown_field_categorised():
    bad = _payload()
    bad["rogue"] = True
    with pytest.raises(ContextBundleValidationError) as excinfo:
        load_context_bundle(bad)
    assert excinfo.value.kind == "unknown_field"


def test_out_of_vocab_freshness_categorised_as_vocab_error():
    bad = _payload()
    bad["ci_status"]["freshness"] = "probably_old"
    with pytest.raises(ContextBundleValidationError) as excinfo:
        load_context_bundle(bad)
    assert excinfo.value.kind == "vocab_error"


def test_out_of_vocab_source_categorised_as_vocab_error():
    bad = _payload()
    bad["test_evidence"]["source"] = "telepathy"
    with pytest.raises(ContextBundleValidationError) as excinfo:
        load_context_bundle(bad)
    assert excinfo.value.kind == "vocab_error"


def test_blank_changed_file_path_categorised_as_value_error():
    bad = _payload()
    bad["changed_files"] = [{"path": "   "}]
    with pytest.raises(ContextBundleValidationError) as excinfo:
        load_context_bundle(bad)
    assert excinfo.value.kind == "value_error"
    assert "non-blank" in excinfo.value.message


def test_non_string_mismatched_schema_version_is_version_mismatch():
    with pytest.raises(ContextBundleValidationError) as excinfo:
        load_context_bundle({"schema_version": 2})
    assert excinfo.value.kind == "schema_version_mismatch"
    assert "2" in excinfo.value.message


def test_wrong_type_for_changed_files_categorised_as_type_error():
    with pytest.raises(ContextBundleValidationError) as excinfo:
        load_context_bundle(_payload(changed_files="not a list"))
    assert excinfo.value.kind == "type_error"


def test_error_str_includes_kind_and_path():
    bad = _payload()
    bad["ci_status"]["freshness"] = "nope"
    with pytest.raises(ContextBundleValidationError) as excinfo:
        load_context_bundle(bad)
    text = str(excinfo.value)
    assert "[vocab_error]" in text
    assert "ci_status/freshness" in text
