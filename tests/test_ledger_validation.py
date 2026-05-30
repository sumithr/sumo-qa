# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.ledger_validation — the load/validate envelope for a
risk-to-test ledger payload (issue #144).

Mirrors the repo-map validation envelope: every failure mode raises
``LedgerValidationError`` with a stable ``kind`` so the MCP wrapper can branch on
the category rather than parsing free-form messages.
"""

from __future__ import annotations

import pytest

from sumo_qa.ledger_models import LEDGER_SCHEMA_VERSION
from sumo_qa.ledger_validation import LedgerValidationError, load_ledger


def _payload(**overrides) -> dict:
    base = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "rows": [
            {
                "risk_id": "R1",
                "risk": "Refund issued twice on retry.",
                "source_anchor": "refund.py:47",
                "test": "tests/test_refund.py::test_idempotent",
                "evidence_status": "passing",
                "residual": "accepted",
            }
        ],
    }
    base.update(overrides)
    return base


def test_load_valid_dict_returns_model():
    led = load_ledger(_payload())
    assert led.rows[0].risk_id == "R1"
    assert led.schema_version == "1.0"


def test_schema_version_mismatch_has_dedicated_kind():
    with pytest.raises(LedgerValidationError) as excinfo:
        load_ledger(_payload(schema_version="2.0"))
    assert excinfo.value.kind == "schema_version_mismatch"
    assert "2.0" in excinfo.value.message


def test_missing_field_categorised():
    bad = _payload()
    del bad["rows"][0]["evidence_status"]
    with pytest.raises(LedgerValidationError) as excinfo:
        load_ledger(bad)
    assert excinfo.value.kind == "missing_field"


def test_unknown_field_categorised():
    bad = _payload()
    bad["rows"][0]["rogue"] = True
    with pytest.raises(LedgerValidationError) as excinfo:
        load_ledger(bad)
    assert excinfo.value.kind == "unknown_field"


def test_out_of_vocab_evidence_status_categorised_as_vocab_error():
    bad = _payload()
    bad["rows"][0]["evidence_status"] = "probably_fine"
    with pytest.raises(LedgerValidationError) as excinfo:
        load_ledger(bad)
    assert excinfo.value.kind == "vocab_error"


def test_duplicate_risk_id_categorised():
    bad = _payload()
    bad["rows"].append(dict(bad["rows"][0]))
    with pytest.raises(LedgerValidationError) as excinfo:
        load_ledger(bad)
    # duplicate-id is a model_validator failure → value_error category.
    assert excinfo.value.kind == "value_error"
    assert "duplicate" in excinfo.value.message


def test_non_string_schema_version_falls_through_to_pydantic():
    # A null/number schema_version is NOT the friendly "your artifact says 2.0"
    # case — it falls through to Pydantic's literal handler (vocab_error).
    with pytest.raises(LedgerValidationError) as excinfo:
        load_ledger(_payload(schema_version=None))
    assert excinfo.value.kind == "vocab_error"


def test_error_str_includes_kind_and_path():
    bad = _payload()
    del bad["rows"][0]["risk"]
    with pytest.raises(LedgerValidationError) as excinfo:
        load_ledger(bad)
    text = str(excinfo.value)
    assert "[missing_field]" in text
    assert "rows/0/risk" in text


def test_wrong_type_for_rows_categorised_as_type_error():
    with pytest.raises(LedgerValidationError) as excinfo:
        load_ledger({"schema_version": "1.0", "rows": "not a list"})
    assert excinfo.value.kind == "type_error"
