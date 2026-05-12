# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

SUPPORTED_TEST_TYPES = {"unit", "integration", "contract", "functional", "nonfunctional"}


class _RawChangeRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    must_consider: list[str] = Field(default_factory=list)
    suggested_test_types: list[str] = Field(default_factory=list)
    avoid_testing: list[str] = Field(default_factory=list)
    risk_templates: list[str] = Field(default_factory=list)
    # ISTQB Foundation + Advanced (TA / TTA) test design techniques. Free-form
    # strings; the engine just surfaces them. Examples:
    #   "boundary value analysis on payload size and field length"
    #   "decision table for validation rule combinations"
    #   "state transition testing including invalid transitions"
    #   "pairwise / orthogonal-array combinations of optional flags"
    #   "equivalence partitioning of valid and invalid input classes"
    test_design_techniques: list[str] = Field(default_factory=list)
    # ISO/IEC 25010 quality characteristics most directly affected by this
    # change type. Examples:
    #   "functional_correctness"
    #   "compatibility_co_existence"
    #   "performance_efficiency_time_behaviour"
    #   "reliability_recoverability"
    #   "security_integrity"
    quality_characteristics: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ChangeRule:
    classification: str
    must_consider: list[str]
    suggested_test_types: list[str]
    avoid_testing: list[str]
    risk_templates: list[str]
    test_design_techniques: list[str]
    quality_characteristics: list[str]


class StandardsRulesEngine:
    def __init__(self, rules: dict[str, ChangeRule]) -> None:
        self._rules = rules

    @classmethod
    def from_file(cls, path: str | Path) -> StandardsRulesEngine:
        rules_path = Path(path)
        if not rules_path.exists():
            return cls({})

        with rules_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}

        rules: dict[str, ChangeRule] = {}
        for classification, body in raw.items():
            classification_name = str(classification)
            try:
                parsed = _RawChangeRule.model_validate(body or {})
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid change rule '{classification_name}' in {rules_path}: {exc}"
                ) from exc
            unknown_test_types = [
                test_type
                for test_type in parsed.suggested_test_types
                if test_type not in SUPPORTED_TEST_TYPES
            ]
            if unknown_test_types:
                raise ValueError(
                    f"Invalid change rule '{classification_name}' in {rules_path}: "
                    f"unsupported suggested_test_types {unknown_test_types}; "
                    f"allowed values are {sorted(SUPPORTED_TEST_TYPES)}"
                )
            rules[classification_name] = ChangeRule(
                classification=classification_name,
                must_consider=list(parsed.must_consider),
                suggested_test_types=list(parsed.suggested_test_types),
                avoid_testing=list(parsed.avoid_testing),
                risk_templates=list(parsed.risk_templates),
                test_design_techniques=list(parsed.test_design_techniques),
                quality_characteristics=list(parsed.quality_characteristics),
            )
        return cls(rules)

    def evaluate(self, classifications: list[str]) -> dict[str, Any]:
        matched = [self._rules[name] for name in classifications if name in self._rules]
        must_consider = _dedupe(item for rule in matched for item in rule.must_consider)
        suggested_test_types = _dedupe(
            item for rule in matched for item in rule.suggested_test_types
        )
        avoid_testing = _dedupe(item for rule in matched for item in rule.avoid_testing)
        risk_templates = _dedupe(item for rule in matched for item in rule.risk_templates)
        test_design_techniques = _dedupe(
            item for rule in matched for item in rule.test_design_techniques
        )
        quality_characteristics = _dedupe(
            item for rule in matched for item in rule.quality_characteristics
        )
        templates_by_classification = {
            rule.classification: list(rule.risk_templates) for rule in matched
        }

        return {
            "matched_rules": [rule.classification for rule in matched],
            "must_consider": must_consider,
            "suggested_test_types": suggested_test_types,
            "avoid_testing": avoid_testing,
            "risk_templates": risk_templates,
            "test_design_techniques": test_design_techniques,
            "quality_characteristics": quality_characteristics,
            "templates_by_classification": templates_by_classification,
        }


def _dedupe(items: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
