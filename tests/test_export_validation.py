# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.export_validation — the load/validate envelope for a
QA-test-case export payload (issue #148).

Mirrors the risk-ledger / context-bundle validation envelopes: every failure
mode raises ``ExportValidationError`` with a stable ``kind`` so the MCP wrapper
can branch on the category rather than parsing free-form messages.
"""

from __future__ import annotations

import pytest

from sumo_qa.export_models import EXPORT_SCHEMA_VERSION
from sumo_qa.export_validation import ExportValidationError, load_test_case_export


def _payload(**overrides) -> dict:
    base = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "title": "Billing",
        "test_cases": [
            {
                "id": "TC1",
                "title": "Refund is idempotent.",
                "preconditions": [],
                "steps": [],
                "expected_result": "Refunded once.",
                "priority": "high",
                "evidence_status": "planned",
            }
        ],
    }
    base.update(overrides)
    return base


def test_load_valid_dict_returns_model():
    export = load_test_case_export(_payload())
    assert export.test_cases[0].id == "TC1"
    assert export.schema_version == "1.0"


def test_schema_version_mismatch_has_dedicated_kind():
    with pytest.raises(ExportValidationError) as excinfo:
        load_test_case_export(_payload(schema_version="2.0"))
    assert excinfo.value.kind == "schema_version_mismatch"
    assert "2.0" in excinfo.value.message


def test_missing_field_categorised():
    bad = _payload()
    del bad["test_cases"][0]["expected_result"]
    with pytest.raises(ExportValidationError) as excinfo:
        load_test_case_export(bad)
    assert excinfo.value.kind == "missing_field"


def test_unknown_field_categorised():
    bad = _payload()
    bad["test_cases"][0]["owner"] = "qa"
    with pytest.raises(ExportValidationError) as excinfo:
        load_test_case_export(bad)
    assert excinfo.value.kind == "unknown_field"


def test_out_of_vocab_priority_categorised_as_vocab_error():
    bad = _payload()
    bad["test_cases"][0]["priority"] = "urgent"
    with pytest.raises(ExportValidationError) as excinfo:
        load_test_case_export(bad)
    assert excinfo.value.kind == "vocab_error"


def test_out_of_vocab_evidence_status_categorised_as_vocab_error():
    bad = _payload()
    bad["test_cases"][0]["evidence_status"] = "probably_fine"
    with pytest.raises(ExportValidationError) as excinfo:
        load_test_case_export(bad)
    assert excinfo.value.kind == "vocab_error"


def test_duplicate_id_categorised_as_value_error():
    bad = _payload()
    bad["test_cases"].append(dict(bad["test_cases"][0]))
    with pytest.raises(ExportValidationError) as excinfo:
        load_test_case_export(bad)
    assert excinfo.value.kind == "value_error"
    assert "duplicate" in excinfo.value.message


def test_blank_id_categorised_as_value_error():
    bad = _payload()
    bad["test_cases"][0]["id"] = "  "
    with pytest.raises(ExportValidationError) as excinfo:
        load_test_case_export(bad)
    assert excinfo.value.kind == "value_error"


def test_null_schema_version_falls_through_to_pydantic():
    # A null (missing) schema_version is NOT the friendly "your artifact says
    # 2.0" case — it falls through to Pydantic's literal handler (vocab_error).
    with pytest.raises(ExportValidationError) as excinfo:
        load_test_case_export(_payload(schema_version=None))
    assert excinfo.value.kind == "vocab_error"


def test_non_string_mismatched_schema_version_is_version_mismatch():
    with pytest.raises(ExportValidationError) as excinfo:
        load_test_case_export({"schema_version": 2, "test_cases": []})
    assert excinfo.value.kind == "schema_version_mismatch"
    assert "2" in excinfo.value.message


def test_error_str_includes_kind_and_path():
    bad = _payload()
    del bad["test_cases"][0]["title"]
    with pytest.raises(ExportValidationError) as excinfo:
        load_test_case_export(bad)
    text = str(excinfo.value)
    assert "[missing_field]" in text
    assert "test_cases/0/title" in text


def test_wrong_type_for_test_cases_categorised_as_type_error():
    with pytest.raises(ExportValidationError) as excinfo:
        load_test_case_export({"schema_version": "1.0", "test_cases": "not a list"})
    assert excinfo.value.kind == "type_error"
