# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Unit tests for sumo_qa.server_schemas.

These tests pin the Pydantic output models against the live return shapes of
the four test-data MCP tools. The models exist so FastMCP can emit a real
``outputSchema`` for each tool; if a tool starts returning a key the model
doesn't declare, ``extra="forbid"`` makes the model reject the dict and the
test here fails — surfacing the drift in this file rather than silently
hiding it behind ``dict[str, Any]``.

For ``TestDataFindOutput`` we go a step further and round-trip the live
service output through the model. That catches schema drift in the field
that's hardest to hand-mock (nested results / validation / confidence).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from sumo_qa.server_schemas import (
    TestDataFindOutput,
    TestDataRegisterOutput,
    TestDataRequirementsOutput,
    TestDataValidateOutput,
)
from sumo_qa.tdm_catalogue import TestDataCatalogue
from sumo_qa.tdm_service import TestDataAssistant
from sumo_qa.tdm_validation import MockValidator

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)


def _assistant(tmp_path: Path | None = None) -> TestDataAssistant:
    """Build a TestDataAssistant against the test fixture catalogue.

    Pass ``tmp_path`` to use an isolated copy of the catalogue (for the
    register test, which writes to disk).
    """
    catalogue_root = ROOT / "tests" / "fixtures" / "test_data"
    if tmp_path is not None:
        # Copy the fixture catalogue into tmp_path so the register test does
        # not mutate the shared fixture directory.
        import shutil

        dest = tmp_path / "test_data"
        shutil.copytree(catalogue_root, dest)
        catalogue_root = dest
    return TestDataAssistant(TestDataCatalogue(catalogue_root), MockValidator(now=NOW))


# ---------------------------------------------------------------------------
# TestDataRequirementsOutput
# ---------------------------------------------------------------------------


def test_requirements_output_accepts_live_service_payload() -> None:
    payload = _assistant().explain_requirements(
        "What data do I need to test the locked-account rejection flow?",
        environment="integration",
        domain="auth",
    )

    model = TestDataRequirementsOutput.model_validate(payload)

    assert model.tool == "sumo_qa_explain_test_data_requirements"
    assert model.summary
    assert model.domain == "auth"
    assert model.environment == "integration"
    assert model.required_entity_characteristics
    assert model.resource_state_conditions
    assert model.scenario_preconditions
    assert model.downstream_dependencies
    assert model.edge_case_recommendations
    assert model.what_not_to_use
    assert model.assumptions
    assert model.confidence.level == "medium"
    assert model.confidence.reason
    assert model.freshness.status == "not_applicable"
    assert model.freshness.reason
    assert model.freshness.last_validated_at is None
    assert model.freshness.age_days is None
    assert model.validation_source == "requirements-heuristic"


def test_requirements_output_rejects_unknown_field() -> None:
    payload = _assistant().explain_requirements("any question", domain="auth")
    payload["unexpected_field"] = "boom"
    with pytest.raises(ValidationError):
        TestDataRequirementsOutput.model_validate(payload)


# ---------------------------------------------------------------------------
# TestDataFindOutput
# ---------------------------------------------------------------------------


def test_find_output_accepts_live_service_payload() -> None:
    payload = _assistant().find_test_data(
        environment="integration",
        domain="auth",
        scenario_tags=["account_locked"],
        known_valid_for=["locked account rejection"],
    )

    model = TestDataFindOutput.model_validate(payload)

    assert model.tool == "sumo_qa_find_test_data"
    assert model.query["environment"] == "integration"
    assert model.results, "fixture should have at least one matching auth entry"
    first = model.results[0]
    assert first.entry.id
    assert first.entry.environment == "integration"
    assert first.entry.domain == "auth"
    assert first.entry.owner
    assert first.entry.source
    assert first.entry.scenario_tags
    assert first.entry.known_valid_for
    assert first.entry.constraints
    assert first.entry.confidence in {"low", "medium", "high"}
    assert first.entry.validation_source
    assert first.entry.notes is not None  # may be empty string
    assert first.validation.entry_id == first.entry.id
    assert isinstance(first.validation.valid, bool)
    assert first.validation.confidence.level in {"low", "medium", "high"}
    assert first.validation.confidence.reason
    assert first.validation.freshness.status in {
        "fresh",
        "aging",
        "stale",
        "unknown",
        "not_applicable",
    }
    assert first.validation.freshness.reason
    assert first.validation.validation_source
    assert first.validation.validation_reason
    assert first.validation.checked_at
    assert isinstance(first.validation.issues, list)
    assert first.suitability_reason
    assert isinstance(first.rank_score, int)
    assert model.total_count >= 1
    assert isinstance(model.has_more, bool)
    # next_offset is None when has_more is False; either is allowed by the model.
    assert model.next_offset is None or isinstance(model.next_offset, int)
    assert isinstance(model.missing_information, list)
    assert model.confidence.level in {"low", "medium", "high"}
    assert model.confidence.reason
    assert model.freshness.status
    assert model.freshness.reason
    assert model.validation_source


def test_find_output_rejects_unknown_field() -> None:
    payload = _assistant().find_test_data(environment="integration", domain="auth")
    payload["surprise_field"] = 1
    with pytest.raises(ValidationError):
        TestDataFindOutput.model_validate(payload)


# ---------------------------------------------------------------------------
# TestDataValidateOutput
# ---------------------------------------------------------------------------


def test_validate_output_accepts_live_service_payload() -> None:
    payload = _assistant().validate_test_data(entry_id="auth-locked-account-001")

    model = TestDataValidateOutput.model_validate(payload)

    assert model.tool == "sumo_qa_validate_test_data"
    assert model.entry.id == "auth-locked-account-001"
    assert model.entry.domain == "auth"
    assert model.entry.environment == "integration"
    assert model.entry.owner
    assert model.entry.source
    assert model.entry.scenario_tags
    assert model.entry.known_valid_for
    assert model.entry.constraints
    assert model.entry.confidence in {"low", "medium", "high"}
    assert model.entry.validation_source
    assert model.entry.notes is not None
    assert model.validation.entry_id == "auth-locked-account-001"
    assert isinstance(model.validation.valid, bool)
    assert model.validation.confidence.level
    assert model.validation.confidence.reason
    assert model.validation.freshness.status
    assert model.validation.freshness.reason
    assert model.validation.validation_source
    assert model.validation.validation_reason
    assert model.validation.checked_at
    assert isinstance(model.validation.issues, list)


def test_validate_output_rejects_unknown_field() -> None:
    payload = _assistant().validate_test_data(entry_id="auth-locked-account-001")
    payload["stray"] = True
    with pytest.raises(ValidationError):
        TestDataValidateOutput.model_validate(payload)


# ---------------------------------------------------------------------------
# TestDataRegisterOutput
# ---------------------------------------------------------------------------


def test_register_output_accepts_live_service_payload(tmp_path: Path) -> None:
    payload = _assistant(tmp_path=tmp_path).register_known_good_test_data(
        {
            "id": "billing-overdue-invoice-schema-001",
            "environment": "staging",
            "domain": "billing",
            "scenario_tags": ["overdue_invoice", "dunning_eligible"],
            "known_valid_for": ["dunning workflow testing"],
            "constraints": ["Reset overdue flag after test."],
            "owner": "billing-platform",
            "last_validated_at": "2026-05-05T09:00:00Z",
            "confidence": "high",
            "source": "qa-curated",
            "notes": "Overdue invoice usable for dunning-flow testing.",
        }
    )

    model = TestDataRegisterOutput.model_validate(payload)

    assert model.tool == "sumo_qa_register_known_good_test_data"
    assert model.action in {"created", "updated", "duplicate"}
    assert model.entry.id == "billing-overdue-invoice-schema-001"
    assert model.entry.domain == "billing"
    assert model.entry.environment == "staging"
    assert model.entry.owner == "billing-platform"
    assert model.entry.source == "qa-curated"
    assert model.entry.scenario_tags
    assert model.entry.known_valid_for
    assert model.entry.constraints
    assert model.entry.confidence == "high"
    assert model.entry.validation_source
    assert model.entry.notes
    assert model.validation.entry_id == "billing-overdue-invoice-schema-001"
    assert model.validation.confidence.level
    assert model.validation.freshness.status
    assert model.validation.validation_source
    assert model.validation.validation_reason
    assert model.validation.checked_at
    assert isinstance(model.validation.issues, list)
    assert model.catalogue_path
    # duplicate_of is None for a fresh insert; the model must still accept it.
    assert model.duplicate_of is None or isinstance(model.duplicate_of, str)


def test_register_output_rejects_unknown_field(tmp_path: Path) -> None:
    payload = _assistant(tmp_path=tmp_path).register_known_good_test_data(
        {
            "id": "billing-reject-unknown-001",
            "environment": "staging",
            "domain": "billing",
            "scenario_tags": ["overdue_invoice"],
            "known_valid_for": ["dunning workflow testing"],
            "constraints": ["Reset overdue flag after test."],
            "owner": "billing-platform",
            "last_validated_at": "2026-05-05T09:00:00Z",
            "confidence": "high",
            "source": "qa-curated",
            "notes": "Overdue invoice usable for dunning-flow testing.",
        }
    )
    payload["bonus_key"] = "nope"
    with pytest.raises(ValidationError):
        TestDataRegisterOutput.model_validate(payload)
