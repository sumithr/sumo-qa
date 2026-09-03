# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
import codecs
import locale
import sys
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


def test_load_pack_carries_every_declared_field_through(tmp_path: Path) -> None:
    """Every field declared in a pack YAML reaches the loaded pack and its
    evaluated checks unchanged.

    Kills the kwarg→None mutants mutmut >=3.7 generates on the StandardCheck /
    StandardsPack constructors in _load_pack (title, severity, qa_focus, name,
    source). Check-level fields are observable through evaluate(); the pack's
    name and source path have no public reader yet, so they are asserted on
    the loaded pack itself (the same access the hypothesis suite uses).
    """
    pack = {
        "id": "field-pack",
        "version": "9.9.9",
        "name": "Field Round-Trip Pack",
        "checks": [
            {
                "id": "roundtrip.check",
                "title": "Round-trip title",
                "applies_to": ["roundtrip"],
                "severity": "high",
                "qa_focus": "Every declared field survives loading.",
                "pass_criteria": ["title, severity and qa_focus match the YAML"],
            }
        ],
    }
    pack_path = tmp_path / "field-pack.yaml"
    pack_path.write_text(yaml.safe_dump(pack, sort_keys=False), encoding="utf-8")

    engine = StandardsEngine.from_directory(tmp_path)
    evaluation = engine.evaluate("roundtrip")

    assert evaluation.checks == [
        {
            "id": "roundtrip.check",
            "title": "Round-trip title",
            "severity": "high",
            "qa_focus": "Every declared field survives loading.",
            "pass_criteria": ["title, severity and qa_focus match the YAML"],
        }
    ]
    assert evaluation.prompts == ["Round-trip title: Every declared field survives loading."]
    assert evaluation.pack_versions == ["field-pack@9.9.9"]

    (loaded,) = engine._packs
    assert loaded.name == "Field Round-Trip Pack"
    assert loaded.source == pack_path


@pytest.mark.skipif(
    sys.flags.utf8_mode == 1,
    reason="UTF-8 mode pins the locale default to UTF-8; the contract is vacuous here",
)
def test_load_pack_decodes_utf8_regardless_of_host_locale(tmp_path: Path) -> None:
    """A standards pack is decoded as UTF-8 whatever the host locale says.

    Kills the `encoding="utf-8"` dropped / `encoding=None` mutants in
    _load_pack. The pack is written as raw UTF-8 bytes (allow_unicode). Under
    a "C" locale the mutant decodes with the host default instead: ASCII on
    POSIX (UnicodeDecodeError) or the ANSI code page on Windows (mojibake);
    either way the equality below fails, while the original loads the text
    verbatim. The pragma on the `with` line keeps mutmut from scoring these,
    so this test is the guard; it restores the locale on every exit path.
    """
    pack = {
        "id": "utf8-pack",
        "version": "0.0.1",
        "name": "UTF-8 Pack",
        "checks": [
            {
                "id": "utf8.check",
                "title": "Décodage",
                "applies_to": ["utf8"],
                "severity": "low",
                "qa_focus": "Vérifie l'encodage → UTF-8.",
                "pass_criteria": ["non-ASCII text round-trips"],
            }
        ],
    }
    (tmp_path / "utf8-pack.yaml").write_text(
        yaml.safe_dump(pack, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    original_locale = locale.setlocale(locale.LC_CTYPE)
    try:
        locale.setlocale(locale.LC_CTYPE, "C")
        # getpreferredencoding(False) exists on 3.10 (getencoding is 3.11+);
        # codecs.lookup normalises aliases such as "UTF8" or Windows "cp65001".
        if codecs.lookup(locale.getpreferredencoding(False)).name == "utf-8":
            pytest.skip("this host's C locale still defaults to UTF-8; contract is vacuous here")
        engine = StandardsEngine.from_directory(tmp_path)
    finally:
        locale.setlocale(locale.LC_CTYPE, original_locale)

    evaluation = engine.evaluate("utf8")
    assert evaluation.prompts == ["Décodage: Vérifie l'encodage → UTF-8."]


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
