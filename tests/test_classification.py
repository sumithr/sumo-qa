"""ChangeClassificationEngine — deterministic-fallback classifier only.

The AI-sampling path is the brain. The deterministic harness deliberately
does NOT pattern-match paths or text to classify a change. It accepts
explicit classifications from a caller (e.g. an upstream AI classifier)
and otherwise returns an empty result with a note pointing at AI sampling.
"""
from sumo_qa.classification import (
    CHANGE_CLASSIFICATIONS,
    ChangeClassificationEngine,
)


def test_no_classification_without_explicit_input() -> None:
    """No pattern matching — no classification."""
    result = ChangeClassificationEngine().classify(
        change_summary="Change API payload field mapping",
        changed_file_paths=["src/fulfilment/api/options_controller.py"],
        diff_snippet="+ response['twoPerson'] = source.fulfilmentService",
    )

    assert result.classifications == []
    assert result.primary is None


def test_explicit_classifications_are_honoured() -> None:
    """Callers (or an AI classifier upstream) can supply classifications
    directly. The harness honours them and returns high confidence."""
    result = ChangeClassificationEngine().classify(
        change_summary="anything",
        changed_file_paths=["src/whatever.py"],
        explicit_classifications=["api_contract_change", "data_mapping_change"],
    )

    names = result.names()
    assert "api_contract_change" in names
    assert "data_mapping_change" in names
    for c in result.classifications:
        assert c.confidence == "high"


def test_explicit_classifications_outside_canonical_set_are_dropped() -> None:
    """Only canonical classification names are accepted, so the team's
    standards/rules YAML packs always have something to dispatch on."""
    result = ChangeClassificationEngine().classify(
        explicit_classifications=["api_contract_change", "made_up_thing"],
    )

    assert result.names() == ["api_contract_change"]


def test_canonical_classification_set_is_the_team_vocabulary() -> None:
    """The canonical set is the vocabulary the team's standards/rules
    YAML packs are keyed on. This test pins the names so packs don't
    accidentally drift."""
    assert CHANGE_CLASSIFICATIONS == {
        "api_contract_change",
        "business_logic_change",
        "state_transition_change",
        "ui_only_change",
        "configuration_change",
        "data_mapping_change",
        "error_handling_change",
        "async_flow_change",
        "caching_change",
        "security_change",
    }


def test_to_dict_includes_helpful_confidence_note_when_unclassified() -> None:
    """No classifications -> dump should tell the caller what to do
    (enable AI sampling or pass explicit_classifications)."""
    result = ChangeClassificationEngine().classify(
        change_summary="something",
    )

    dump = result.to_dict()
    assert "confidence_note" in dump
    note = dump["confidence_note"].lower()
    assert "unsure" in note or "sampling" in note or "explicit" in note
