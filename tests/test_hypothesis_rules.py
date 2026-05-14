# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from sumo_qa.rules import StandardsRulesEngine
from sumo_qa.tools import DEFAULT_RULES_PATH

# All classification keys present in standards/rules/change_rules.yaml.
KNOWN_CLASSIFICATIONS = [
    "api_contract_change",
    "business_logic_change",
    "state_transition_change",
    "ui_only_change",
    "configuration_change",
    "data_mapping_change",
    "error_handling_change",
    "async_flow_change",
    "security_change",
    "caching_change",
]

# Fixed keys that every evaluate() call must return.
_EXPECTED_RESULT_KEYS = frozenset(
    {
        "matched_rules",
        "must_consider",
        "suggested_test_types",
        "avoid_testing",
        "risk_templates",
        "test_design_techniques",
        "quality_characteristics",
        "templates_by_classification",
    }
)


def _engine() -> StandardsRulesEngine:
    return StandardsRulesEngine.from_file(DEFAULT_RULES_PATH)


# ---------------------------------------------------------------------------
# T1: empty input doesn't crash and returns a dict with the canonical keys.
# ---------------------------------------------------------------------------


def test_evaluate_empty_classifications_returns_dict() -> None:
    result = _engine().evaluate([])
    assert isinstance(result, dict)
    assert result.keys() == _EXPECTED_RESULT_KEYS


# ---------------------------------------------------------------------------
# T2: idempotence on duplicates.
# evaluate([X, X, Y]) and evaluate([X, Y]) must be equal because duplicate
# classifications carry no new information.
# NOTE: this property tests the *semantic* expectation; if it fails the
# production code does not deduplicate the input list before building
# matched_rules, which is a real defect — surface and do NOT suppress.
# ---------------------------------------------------------------------------


@given(classifications=st.lists(st.sampled_from(KNOWN_CLASSIFICATIONS), min_size=1, max_size=10))
@settings(max_examples=100)
def test_evaluate_idempotent_on_duplicates(classifications: list[str]) -> None:
    engine = _engine()
    deduped = list(dict.fromkeys(classifications))  # preserve first-seen order
    assert engine.evaluate(classifications) == engine.evaluate(deduped)


# ---------------------------------------------------------------------------
# T3: order independence.
# The QA guidance produced for a set of classifications must not depend on
# the order in which the caller lists them.
# NOTE: this property tests the *semantic* expectation; if it fails the
# production code iterates the input list in-order and builds ordered result
# lists — a real defect — surface and do NOT suppress.
# ---------------------------------------------------------------------------


@given(classifications=st.lists(st.sampled_from(KNOWN_CLASSIFICATIONS), min_size=1, max_size=10))
@settings(max_examples=100)
def test_evaluate_order_independent(classifications: list[str]) -> None:
    engine = _engine()
    assert engine.evaluate(classifications) == engine.evaluate(list(reversed(classifications)))


# ---------------------------------------------------------------------------
# T4: graceful on arbitrary / unknown classification strings.
# evaluate([arbitrary_string]) must not raise; result must be a dict with
# the canonical keys.
# ---------------------------------------------------------------------------


@given(classification=st.text(min_size=1, max_size=50))
@settings(max_examples=200)
def test_evaluate_graceful_on_arbitrary_classification(classification: str) -> None:
    result = _engine().evaluate([classification])
    assert isinstance(result, dict)
    assert result.keys() == _EXPECTED_RESULT_KEYS


# ---------------------------------------------------------------------------
# T5: result keys are always the canonical set, regardless of input.
# ---------------------------------------------------------------------------


@given(classifications=st.lists(st.sampled_from(KNOWN_CLASSIFICATIONS), min_size=0, max_size=10))
@settings(max_examples=100)
def test_evaluate_always_returns_canonical_keys(classifications: list[str]) -> None:
    result = _engine().evaluate(classifications)
    assert result.keys() == _EXPECTED_RESULT_KEYS
