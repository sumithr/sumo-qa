"""Tests for sumo_qa.knowledge_loaders.

These tools read markdown catalogues and return them verbatim. No inference,
no filtering beyond optional metadata-based subset selection. The tests
assert that known canonical entries are present in the returned text.
"""
from sumo_qa.knowledge_loaders import sumo_qa_load_classifications


def test_load_classifications_contains_ten_canonical_entries():
    text = sumo_qa_load_classifications()
    for entry in [
        "api_contract_change",
        "business_logic_change",
        "security_change",
        "performance_change",
        "frontend_change",
        "infrastructure_change",
        "test_change",
        "docs_change",
        "config_change",
        "data_migration",
    ]:
        assert entry in text, f"Missing canonical classification: {entry}"


def test_load_classifications_returns_non_empty_text():
    text = sumo_qa_load_classifications()
    assert isinstance(text, str)
    assert len(text) > 200
