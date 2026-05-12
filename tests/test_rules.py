# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from pathlib import Path

import pytest
import yaml

from sumo_qa.rules import StandardsRulesEngine

ROOT = Path(__file__).resolve().parents[1]


def test_rules_map_classification_to_qa_expectations() -> None:
    engine = StandardsRulesEngine.from_file(ROOT / "standards" / "rules" / "change_rules.yaml")

    evaluation = engine.evaluate(["async_flow_change"])

    assert "async_flow_change" in evaluation["matched_rules"]
    assert "idempotency" in evaluation["must_consider"]
    assert "nonfunctional" in evaluation["suggested_test_types"]


def test_missing_rules_file_returns_empty_engine(tmp_path: Path) -> None:
    engine = StandardsRulesEngine.from_file(tmp_path / "does_not_exist.yaml")

    evaluation = engine.evaluate([])

    assert evaluation == {
        "matched_rules": [],
        "must_consider": [],
        "suggested_test_types": [],
        "avoid_testing": [],
        "risk_templates": [],
        "test_design_techniques": [],
        "quality_characteristics": [],
        "templates_by_classification": {},
    }


def test_evaluate_surfaces_istqb_test_design_techniques() -> None:
    """ISTQB Foundation/Advanced test design techniques (boundary value analysis,
    decision tables, state transition testing, pairwise, equivalence partitioning)
    must be available per classification, so the QA brain reasons in named
    techniques rather than generic bullets.
    """
    engine = StandardsRulesEngine.from_file(ROOT / "standards" / "rules" / "change_rules.yaml")

    api = engine.evaluate(["api_contract_change"])
    assert api["test_design_techniques"], "api_contract_change should have ISTQB techniques"
    techniques_text = " ".join(api["test_design_techniques"]).lower()
    assert "boundary value" in techniques_text or "equivalence" in techniques_text
    assert "decision table" in techniques_text or "pairwise" in techniques_text

    state = engine.evaluate(["state_transition_change"])
    state_text = " ".join(state["test_design_techniques"]).lower()
    assert "state transition" in state_text


def test_evaluate_surfaces_iso25010_quality_characteristics() -> None:
    """ISO/IEC 25010 quality characteristics (functional suitability, performance
    efficiency, reliability, security, etc.) per classification."""
    engine = StandardsRulesEngine.from_file(ROOT / "standards" / "rules" / "change_rules.yaml")

    caching = engine.evaluate(["caching_change"])
    chars = [item.lower() for item in caching["quality_characteristics"]]
    # caching directly affects performance efficiency and reliability
    assert any("performance" in c for c in chars)
    assert any("reliability" in c for c in chars)

    api = engine.evaluate(["api_contract_change"])
    api_chars = [item.lower() for item in api["quality_characteristics"]]
    assert any("compatibility" in c or "functional" in c for c in api_chars)


def test_evaluate_returns_per_classification_template_map() -> None:
    engine = StandardsRulesEngine.from_file(ROOT / "standards" / "rules" / "change_rules.yaml")

    evaluation = engine.evaluate(["api_contract_change", "data_mapping_change"])

    by_classification = evaluation["templates_by_classification"]
    assert "api_contract_change" in by_classification
    assert "data_mapping_change" in by_classification
    # api template should be under api, not data_mapping
    api_marker = "payload shape or validation changes silently"
    assert any(api_marker in template for template in by_classification["api_contract_change"])
    assert all(api_marker not in template for template in by_classification["data_mapping_change"])


def test_unknown_suggested_test_type_raises_value_error(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        yaml.safe_dump(
            {
                "made_up_change": {
                    "suggested_test_types": ["chaos"],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as excinfo:
        StandardsRulesEngine.from_file(rules_path)

    message = str(excinfo.value)
    assert "made_up_change" in message
    assert str(rules_path) in message
    assert "chaos" in message


def test_unknown_field_under_classification_raises_value_error(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        yaml.safe_dump(
            {
                "made_up_change": {
                    "must_consider": ["something"],
                    "unexpected_key": ["nope"],
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as excinfo:
        StandardsRulesEngine.from_file(rules_path)

    assert "made_up_change" in str(excinfo.value)
    assert str(rules_path) in str(excinfo.value)
