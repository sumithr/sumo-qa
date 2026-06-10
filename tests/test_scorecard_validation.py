# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the scorecard load/validation envelope (issue #151).

``load_scorecard`` reuses the #144 / #149 loaders verbatim — their typed errors
must propagate unchanged — and validates only the scorecard-native coverage /
mutation signals with its own typed ``ScorecardValidationError``.
"""

from __future__ import annotations

import pytest

from sumo_qa.context_bundle_validation import ContextBundleValidationError
from sumo_qa.ledger_validation import LedgerValidationError
from sumo_qa.scorecard_models import QaScorecard
from sumo_qa.scorecard_validation import ScorecardValidationError, load_scorecard


def _row(**overrides) -> dict:
    base = {
        "risk_id": "R1",
        "risk": "Refund issued twice on retry.",
        "source_anchor": "refund.py:47",
        "test": "tests/test_refund.py::test_idempotent",
        "evidence_status": "passing",
        "residual": "open",
    }
    base.update(overrides)
    return base


def test_empty_payload_composes_insufficient_scorecard():
    card = load_scorecard()
    assert isinstance(card, QaScorecard)
    assert card.recommendation() == "insufficient_evidence"


def test_ledger_and_bundle_compose():
    card = load_scorecard(
        ledger_rows=[_row()],
        context_bundle={
            "test_evidence": {"result": "passing", "freshness": "fresh", "source": "manual"}
        },
    )
    assert card.ledger is not None and len(card.ledger.rows) == 1
    assert card.context_bundle is not None
    assert card.recommendation() == "ready"


def test_bad_ledger_vocab_propagates_ledger_error():
    with pytest.raises(LedgerValidationError) as exc:
        load_scorecard(ledger_rows=[_row(evidence_status="probably_fine")])
    assert exc.value.kind == "vocab_error"


def test_bad_bundle_propagates_context_bundle_error():
    with pytest.raises(ContextBundleValidationError):
        load_scorecard(
            context_bundle={
                "test_evidence": {"result": "passing", "freshness": "yesterday", "source": "manual"}
            }
        )


def test_coverage_out_of_range_raises_scorecard_value_error():
    with pytest.raises(ScorecardValidationError) as exc:
        load_scorecard(coverage={"line_percent": 150.0})
    assert exc.value.kind == "value_error"
    assert exc.value.path is not None and exc.value.path.startswith("coverage")


def test_unknown_coverage_field_raises_unknown_field():
    with pytest.raises(ScorecardValidationError) as exc:
        load_scorecard(coverage={"line_percent": 80.0, "branch_percent": 90.0})
    assert exc.value.kind == "unknown_field"


def test_negative_mutation_survivors_raises_scorecard_value_error():
    with pytest.raises(ScorecardValidationError) as exc:
        load_scorecard(mutation={"survivors": -2})
    assert exc.value.kind == "value_error"


def test_bad_coverage_freshness_raises_vocab_error():
    with pytest.raises(ScorecardValidationError) as exc:
        load_scorecard(coverage={"freshness": "yesterday"})
    assert exc.value.kind == "vocab_error"


def test_wrong_typed_mutation_count_raises_type_error():
    with pytest.raises(ScorecardValidationError) as exc:
        load_scorecard(mutation={"survivors": "lots"})
    assert exc.value.kind == "type_error"
