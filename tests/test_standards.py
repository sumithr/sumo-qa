# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from pathlib import Path

import pytest
import yaml

from sumo_qa.standards import StandardsEngine
from sumo_qa.tools import DEFAULT_STANDARDS_PATH

ROOT = Path(__file__).resolve().parents[1]


def test_loads_versioned_standards_pack() -> None:
    engine = StandardsEngine.from_directory(ROOT / "standards" / "packs")
    evaluation = engine.evaluate("prepare")

    assert "qa-shift-left-core@1.0.0" in evaluation.pack_versions
    assert any(check["id"] == "work.testability" for check in evaluation.checks)


def test_istqb_pack_is_loaded_alongside_core() -> None:
    """The ISTQB-aligned pack ships with the package and loads automatically.

    Senior-QA framing (early testing principle, risk-based testing,
    deliberate technique choice, confirmation vs regression) should be
    available to every workflow without extra configuration.
    """
    engine = StandardsEngine.from_directory(ROOT / "standards" / "packs")
    evaluation = engine.evaluate("prepare")

    assert "istqb-aligned@1.0.0" in evaluation.pack_versions

    check_ids = {check["id"] for check in evaluation.checks}
    # Foundation principles surface in `prepare` workflow
    assert "principles.early_testing" in check_ids
    # Advanced Test Manager risk framing
    assert "risk_based.product_vs_project" in check_ids
    # Deliberate technique choice
    assert "techniques.choose_deliberately" in check_ids


def test_istqb_pack_offers_review_specific_checks() -> None:
    engine = StandardsEngine.from_directory(ROOT / "standards" / "packs")
    evaluation = engine.evaluate("review")

    check_ids = {check["id"] for check in evaluation.checks}
    assert "testing.confirmation_vs_regression" in check_ids
    assert "structural.coverage" in check_ids


def test_filters_standards_by_workflow() -> None:
    engine = StandardsEngine.from_directory(ROOT / "standards" / "packs")
    evaluation = engine.evaluate("question")

    assert all("question" == evaluation.workflow for _ in evaluation.checks)
    assert any(check["id"] == "question.qa_answer" for check in evaluation.checks)


def test_check_missing_pass_criteria_raises_value_error(tmp_path: Path) -> None:
    pack = {
        "id": "test-pack",
        "version": "0.0.1",
        "name": "Test Pack",
        "checks": [
            {
                "id": "custom.workflow",
                "title": "Custom workflow check",
                "applies_to": ["custom-workflow"],
                "severity": "low",
                "qa_focus": "Verify custom workflow.",
            }
        ],
    }
    pack_path = tmp_path / "test-pack.yaml"
    pack_path.write_text(yaml.safe_dump(pack, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        StandardsEngine.from_directory(tmp_path)

    assert "pass_criteria" in str(excinfo.value)


def test_unknown_severity_raises_value_error(tmp_path: Path) -> None:
    pack = {
        "id": "test-pack",
        "version": "0.0.1",
        "name": "Test Pack",
        "checks": [
            {
                "id": "custom.workflow",
                "title": "Custom workflow check",
                "applies_to": ["custom-workflow"],
                "severity": "catastrophic",
                "qa_focus": "Verify custom workflow.",
                "pass_criteria": ["Has explicit verification."],
            }
        ],
    }
    pack_path = tmp_path / "test-pack.yaml"
    pack_path.write_text(yaml.safe_dump(pack, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        StandardsEngine.from_directory(tmp_path)

    assert "severity" in str(excinfo.value)
    assert str(pack_path) in str(excinfo.value)


def test_unknown_field_at_pack_level_raises_value_error(tmp_path: Path) -> None:
    pack = {
        "id": "test-pack",
        "version": "0.0.1",
        "name": "Test Pack",
        "unexpected_pack_field": "value",
        "checks": [
            {
                "id": "custom.workflow",
                "title": "Custom workflow check",
                "applies_to": ["custom-workflow"],
                "severity": "low",
                "qa_focus": "Verify custom workflow.",
                "pass_criteria": ["Has explicit verification."],
            }
        ],
    }
    pack_path = tmp_path / "test-pack.yaml"
    pack_path.write_text(yaml.safe_dump(pack, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        StandardsEngine.from_directory(tmp_path)

    assert str(pack_path) in str(excinfo.value)


def test_unknown_field_at_check_level_raises_value_error(tmp_path: Path) -> None:
    pack = {
        "id": "test-pack",
        "version": "0.0.1",
        "name": "Test Pack",
        "checks": [
            {
                "id": "custom.workflow",
                "title": "Custom workflow check",
                "applies_to": ["custom-workflow"],
                "severity": "low",
                "qa_focus": "Verify custom workflow.",
                "pass_criteria": ["Has explicit verification."],
                "unexpected_check_field": True,
            }
        ],
    }
    pack_path = tmp_path / "test-pack.yaml"
    pack_path.write_text(yaml.safe_dump(pack, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        StandardsEngine.from_directory(tmp_path)

    assert str(pack_path) in str(excinfo.value)


def test_pack_with_optional_description_and_domain_loads(tmp_path: Path) -> None:
    pack = {
        "id": "test-pack",
        "version": "0.0.1",
        "name": "Test Pack",
        "description": "A pack with optional metadata.",
        "domain": "qa",
        "checks": [
            {
                "id": "custom.workflow",
                "title": "Custom workflow check",
                "applies_to": ["custom-workflow"],
                "severity": "low",
                "qa_focus": "Verify custom workflow.",
                "pass_criteria": ["Has explicit verification."],
            }
        ],
    }
    pack_path = tmp_path / "test-pack.yaml"
    pack_path.write_text(yaml.safe_dump(pack, sort_keys=False), encoding="utf-8")

    engine = StandardsEngine.from_directory(tmp_path)

    assert "test-pack@0.0.1" in engine.evaluate("custom-workflow").pack_versions


def test_from_directory_raises_when_dir_does_not_exist(tmp_path: Path) -> None:
    """StandardsEngine.from_directory() raises FileNotFoundError on a missing path (line 69)."""
    with pytest.raises(FileNotFoundError, match="Standards directory not found"):
        StandardsEngine.from_directory(tmp_path / "does_not_exist")


def test_from_directory_raises_when_no_yaml_packs_found(tmp_path: Path) -> None:
    """StandardsEngine.from_directory() raises ValueError when the dir has no *.yaml (line 73)."""
    # tmp_path exists but contains no YAML files.
    with pytest.raises(ValueError, match="No standards YAML packs found"):
        StandardsEngine.from_directory(tmp_path)


def test_unknown_workflow_in_applies_to_is_allowed(tmp_path: Path) -> None:
    pack = {
        "id": "test-pack",
        "version": "0.0.1",
        "name": "Test Pack",
        "checks": [
            {
                "id": "custom.workflow",
                "title": "Custom workflow check",
                "applies_to": ["custom-workflow"],
                "severity": "low",
                "qa_focus": "Verify custom workflow.",
                "pass_criteria": ["custom-workflow has explicit verification."],
            }
        ],
    }
    pack_path = tmp_path / "test-pack.yaml"
    pack_path.write_text(yaml.safe_dump(pack, sort_keys=False), encoding="utf-8")

    engine = StandardsEngine.from_directory(tmp_path)
    evaluation = engine.evaluate("custom-workflow")

    assert any(check["id"] == "custom.workflow" for check in evaluation.checks)


# ---------------------------------------------------------------------------
# Mutation-strengthening tests (Phase 3) — see docs/qa/runs/2026-05-14-phase3-*
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["id", "title", "severity", "qa_focus", "pass_criteria"])
def test_evaluation_check_dict_has_canonical_keys(key: str) -> None:
    """Kill mutmut survivors `xǁStandardsEngineǁevaluate__mutmut_7..14` (8 mutants).

    Each mutant changes a dict-key string in the per-check output dict
    (`"title"` → `"XXtitleXX"` or `"TITLE"`, etc.). The keys are part of the
    public StandardsEvaluation contract — downstream consumers index into
    `evaluation.checks[i]["title"]`. This parametrised test asserts each
    canonical key is present; any spelling mutation breaks the assertion.
    """
    engine = StandardsEngine.from_directory(DEFAULT_STANDARDS_PATH)
    evaluation = engine.evaluate("review")
    assert evaluation.checks, "review workflow should have ≥ 1 applicable check"
    assert key in evaluation.checks[0], (
        f"Missing canonical key {key!r}; got {list(evaluation.checks[0])}"
    )


def test_evaluation_prompts_contain_check_title_and_focus() -> None:
    """Kill mutmut survivors `xǁStandardsEngineǁevaluate__mutmut_16` and `_20`.

    M16: `prompts.append(f"{check.title}: {check.qa_focus}")` → `prompts.append(None)`.
    M20: `prompts=prompts` in the returned StandardsEvaluation → `prompts=None`.

    Both leave evaluation.prompts non-functional from the caller's view. This
    test asserts the field exists, is non-empty, and the formatted strings
    contain the expected `:` separator — kills both mutations.
    """
    engine = StandardsEngine.from_directory(DEFAULT_STANDARDS_PATH)
    evaluation = engine.evaluate("review")
    assert evaluation.prompts is not None
    assert evaluation.prompts, "review workflow should produce ≥ 1 prompt"
    assert ":" in evaluation.prompts[0], (
        f"Expected `title: qa_focus` format; got {evaluation.prompts[0]!r}"
    )
