"""Specialty routing — which extra testing capabilities does this change pull in?

The AI-sampling path is the brain that picks specialties from the static
`SPECIALTY_REGISTRY`. The deterministic harness only fires off the team-
classification → specialty mapping (classifications are explicit facts
about the change, not pattern guesses). Pattern detection (extensions,
path substrings, free-text keywords) has been removed.
"""
from sumo_qa.specialty_routing import SPECIALTY_REGISTRY, detect_specialty_needs


def test_classification_drives_specialty_routing_in_the_deterministic_path() -> None:
    """When a caller supplies classifications (explicit facts), the matching
    specialties surface. No pattern matching."""
    needs = detect_specialty_needs(
        classifications=["ui_only_change"],
        touched_files=["src/components/CheckoutButton.tsx"],
        free_text="anything",
    )

    ids = {n["id"] for n in needs}
    assert "frontend_e2e" in ids
    # accessibility_testing is also tied to ui_only_change.
    assert "accessibility_testing" in ids


def test_api_contract_classification_recommends_contract_testing() -> None:
    needs = detect_specialty_needs(
        classifications=["api_contract_change"],
        touched_files=["src/orders/api.py"],
        free_text="anything",
    )

    ids = {n["id"] for n in needs}
    assert "contract_testing" in ids


def test_caching_or_async_classification_recommends_performance_testing() -> None:
    needs = detect_specialty_needs(
        classifications=["caching_change"],
        touched_files=["src/stock/cache/availability_cache.py"],
        free_text="anything",
    )

    ids = {n["id"] for n in needs}
    assert "performance_testing" in ids


def test_no_classifications_returns_empty_list() -> None:
    """The deterministic harness no longer pattern-matches paths or free
    text. Without classifications, nothing surfaces — the AI is what picks
    specialties from intent + paths."""
    needs = detect_specialty_needs(
        classifications=[],
        touched_files=["ios/AppDelegate.swift", "src/auth/login.py"],
        free_text="Added JWT validation and updated mobile launch screen",
    )

    assert needs == []


def test_specialty_registry_exposes_full_catalog_for_ai_grounding() -> None:
    """The AI is grounded against `SPECIALTY_REGISTRY`. Every entry has the
    fields the AI needs to reason about which specialty to pull in."""
    assert len(SPECIALTY_REGISTRY) >= 7
    for rule in SPECIALTY_REGISTRY:
        assert rule.id
        assert rule.approach
        assert rule.well_known_tools
        assert rule.mcp_hint
        assert rule.when_to_use


def test_each_specialty_has_required_fields_in_detector_output() -> None:
    needs = detect_specialty_needs(
        classifications=["api_contract_change", "ui_only_change", "caching_change"],
        touched_files=["src/orders/api.py", "src/components/Foo.tsx", "src/cache/x.py"],
        free_text="anything",
    )
    assert len(needs) >= 3
    for entry in needs:
        assert "id" in entry
        assert "approach" in entry
        assert "well_known_tools" in entry
        assert "mcp_hint" in entry
        assert "when_to_use" in entry
        assert isinstance(entry["well_known_tools"], list)
