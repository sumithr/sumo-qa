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


from sumo_qa.knowledge_loaders import sumo_qa_load_approaches


def test_load_approaches_contains_eight_canonical_entries():
    text = sumo_qa_load_approaches()
    for entry in [
        "strategy-orchestration",
        "tdd-scaffold",
        "regression-first",
        "coverage-first-then-refactor",
        "strengthen-test-coverage",
        "verify-existing",
        "no-tests-recommended",
        "spike-first-then-tests",
    ]:
        assert entry in text, f"Missing canonical approach: {entry}"


from sumo_qa.knowledge_loaders import sumo_qa_load_principles


def test_load_principles_contains_istqb_and_iso():
    text = sumo_qa_load_principles()
    assert "ISTQB Foundation" in text
    assert "ISO/IEC 25010" in text
    assert "Pesticide paradox" in text
    assert "Defects cluster" in text
    assert "shift left" in text.lower() or "shift-left" in text.lower()


from sumo_qa.knowledge_loaders import sumo_qa_load_techniques


def test_load_techniques_contains_canonical_techniques():
    text = sumo_qa_load_techniques()
    for entry in [
        "boundary value analysis",
        "equivalence partitioning",
        "decision tables",
        "state transition testing",
        "MC-DC",
        "exploratory testing",
        "property-based testing",
        "mutation testing",
    ]:
        assert entry in text, f"Missing canonical technique: {entry}"


from sumo_qa.knowledge_loaders import sumo_qa_load_specialty_tools


def test_load_specialty_tools_contains_canonical_pairings():
    text = sumo_qa_load_specialty_tools()
    for entry in [
        "OWASP ZAP",
        "Pact",
        "k6",
        "Pitest",
        "Stryker",
        "Hypothesis",
        "axe-core",
        "Cypress",
        "Promptfoo",
        "JJWT",
    ]:
        assert entry in text, f"Missing canonical specialty tool: {entry}"


from sumo_qa.knowledge_loaders import sumo_qa_load_standards


def test_load_standards_returns_text_when_no_filter():
    text = sumo_qa_load_standards()
    assert isinstance(text, str)
    assert len(text) > 0


def test_load_standards_filter_returns_only_matching_packs():
    """The classification filter is metadata-based — only packs whose
    frontmatter declares the classification are returned."""
    full = sumo_qa_load_standards()
    filtered = sumo_qa_load_standards(classification="security_change")
    assert len(filtered) <= len(full)
    assert isinstance(filtered, str)


from sumo_qa.knowledge_loaders import sumo_qa_load_rules


def test_load_rules_returns_text_when_no_filter():
    text = sumo_qa_load_rules()
    assert isinstance(text, str)
    assert len(text) > 0


def test_load_rules_filter_by_classification_is_smaller():
    full = sumo_qa_load_rules()
    filtered = sumo_qa_load_rules(classification="security_change")
    assert len(filtered) <= len(full)
