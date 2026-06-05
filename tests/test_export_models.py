# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.export_models — the QA-test-case export schema (issue #148).

The export is a deterministic projection of already-structured QA state; this
module only locks the SHAPE of an exportable case. These tests pin the schema
contract: required fields, the distinct priority vocabulary, the reused
risk-ledger evidence-status vocabulary, the versioned-from-the-start
``schema_version``, stable-within-export ids, the ``extra="forbid"`` strictness,
and the flat-vs-nested predicate the CSV path depends on.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sumo_qa.export_models import (
    EXPORT_SCHEMA_VERSION,
    QaTestCase,
    QaTestCaseExport,
)
from sumo_qa.ledger_models import EvidenceStatus


def _case(**overrides) -> QaTestCase:
    base = dict(
        id="TC1",
        title="Refund is idempotent across a retried request.",
        preconditions=["A charge exists with a known idempotency key."],
        steps=["POST the refund twice with the same idempotency key."],
        expected_result="The charge is refunded exactly once; the second call is a no-op.",
        priority="high",
        evidence_status="planned",
    )
    base.update(overrides)
    return QaTestCase(**base)


def test_schema_version_constant_is_one_dot_zero():
    assert EXPORT_SCHEMA_VERSION == "1.0"


def test_minimal_case_round_trips():
    case = _case()
    assert case.id == "TC1"
    assert case.linked_risk_id is None
    assert case.priority == "high"
    assert case.evidence_status == "planned"


def test_empty_preconditions_and_steps_are_valid():
    case = _case(preconditions=[], steps=[])
    assert case.preconditions == []
    assert case.steps == []


def test_blank_id_is_rejected():
    with pytest.raises(ValidationError, match="non-blank"):
        _case(id="   ")


def test_blank_title_is_rejected():
    with pytest.raises(ValidationError, match="non-blank"):
        _case(title="")


def test_blank_expected_result_is_rejected():
    with pytest.raises(ValidationError, match="non-blank"):
        _case(expected_result="  ")


def test_unknown_priority_is_rejected():
    with pytest.raises(ValidationError):
        _case(priority="urgent")


def test_unknown_evidence_status_is_rejected():
    with pytest.raises(ValidationError):
        _case(evidence_status="probably_fine")


def test_extra_field_is_forbidden():
    with pytest.raises(ValidationError):
        QaTestCase(
            id="TC1",
            title="t",
            expected_result="r",
            priority="low",
            evidence_status="planned",
            owner="qa-team",  # not in the schema
        )


def test_evidence_status_vocabulary_matches_the_ledger():
    # The export reuses the ledger's EvidenceStatus verbatim (issue #144) so a
    # case and a ledger row mean the same by the same word. This pins that the
    # five states are exactly the ledger's, catching a silent divergence.
    import typing

    assert set(typing.get_args(EvidenceStatus)) == {
        "planned",
        "passing",
        "failing",
        "stale",
        "accepted_residual",
    }


def test_export_requires_explicit_schema_version():
    with pytest.raises(ValidationError):
        QaTestCaseExport(test_cases=[])  # schema_version omitted


def test_export_rejects_mismatched_schema_version():
    with pytest.raises(ValidationError):
        QaTestCaseExport(schema_version="2.0", test_cases=[])


def test_duplicate_case_ids_are_rejected():
    with pytest.raises(ValidationError, match="duplicate test case id"):
        QaTestCaseExport(
            schema_version=EXPORT_SCHEMA_VERSION,
            test_cases=[_case(id="TC1"), _case(id="TC1")],
        )


def test_distinct_ids_are_accepted():
    export = QaTestCaseExport(
        schema_version=EXPORT_SCHEMA_VERSION,
        test_cases=[_case(id="TC1"), _case(id="TC2")],
    )
    assert len(export.test_cases) == 2


def test_id_is_stripped_to_canonical_form():
    # Surrounding whitespace must not survive: the stored id is the canonical,
    # stripped value so it feeds the dedup check and every projection's row key
    # consistently.
    assert _case(id="  TC1  ").id == "TC1"


def test_whitespace_variant_ids_collide_under_the_duplicate_guard():
    # Because the id is normalised to its stripped form, " TC1 " and "TC1" are the
    # same canonical key — the duplicate-id guard (which stops two cases collapsing
    # onto one downstream key) must reject them as a duplicate.
    with pytest.raises(ValidationError, match="duplicate test case id"):
        QaTestCaseExport(
            schema_version=EXPORT_SCHEMA_VERSION,
            test_cases=[_case(id=" TC1 "), _case(id="TC1")],
        )


def test_case_is_flat_with_at_most_one_step_and_precondition():
    assert _case().is_flat() is True
    assert _case(preconditions=[], steps=[]).is_flat() is True


def test_case_is_not_flat_with_multiple_steps():
    assert _case(steps=["a", "b"]).is_flat() is False


def test_case_is_not_flat_with_multiple_preconditions():
    assert _case(preconditions=["a", "b"]).is_flat() is False


def test_export_is_flat_only_when_every_case_is_flat():
    flat = QaTestCaseExport(
        schema_version=EXPORT_SCHEMA_VERSION,
        test_cases=[_case(id="TC1"), _case(id="TC2")],
    )
    assert flat.is_flat() is True
    nested = QaTestCaseExport(
        schema_version=EXPORT_SCHEMA_VERSION,
        test_cases=[_case(id="TC1"), _case(id="TC2", steps=["a", "b"])],
    )
    assert nested.is_flat() is False


def test_empty_export_is_flat():
    export = QaTestCaseExport(schema_version=EXPORT_SCHEMA_VERSION, test_cases=[])
    assert export.is_flat() is True
