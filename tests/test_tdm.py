# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from sumo_qa.tdm_catalogue import TestDataCatalogue as Catalogue
from sumo_qa.tdm_models import TestDataEntry as Entry
from sumo_qa.tdm_service import TestDataAssistant as Assistant
from sumo_qa.tdm_validation import MockValidator
from sumo_qa.tools import QAShiftLeftService

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)


def service() -> QAShiftLeftService:
    assistant = Assistant(
        Catalogue(ROOT / "tests" / "fixtures" / "test_data"),
        MockValidator(now=NOW),
    )
    return QAShiftLeftService(test_data_assistant=assistant)


def test_explain_test_data_requirements_is_senior_qa_focused() -> None:
    """Phrase-based domain auto-detection has been removed — callers pass
    `domain` explicitly (the AI path also reasons about the domain). The
    deterministic skeleton still returns the universal QA bones (stable
    identifiers, edge cases, what-not-to-use) for any domain."""
    result = service().qa_explain_test_data_requirements(
        "What data do I need to test the locked-account rejection flow?",
        environment="integration",
        domain="auth",
    )

    assert result["tool"] == "sumo_qa_explain_test_data_requirements"
    assert result["domain"] == "auth"
    assert result["scenario_preconditions"], "must surface scenario-preconditions skeleton"
    assert result["resource_state_conditions"], "must surface resource-state skeleton"
    assert result["required_entity_characteristics"], "must surface entity-characteristics skeleton"
    assert result["what_not_to_use"], "must surface what-not-to-use skeleton"
    assert result["confidence"]["level"] == "medium"
    assert result["validation_source"] == "requirements-heuristic"


def test_explain_test_data_requirements_falls_back_to_general_when_domain_omitted() -> None:
    """Without an explicit domain, the tool stays generic — no phrase-matching
    to guess at the user's domain."""
    result = service().qa_explain_test_data_requirements(
        "What data do I need to test boundary-value handling on the due-date input?",
        environment="integration",
    )
    assert result["domain"] == "general"


def test_find_test_data_explains_when_no_results() -> None:
    result = service().qa_find_test_data(
        environment="integration",
        domain="auth",
        scenario_tags=["this_tag_does_not_exist_anywhere_in_the_catalogue"],
    )

    assert result["results"] == []
    # Headline / freshness / confidence should make the empty state obvious and useful.
    assert result["confidence"]["level"] == "low"
    reason = result["confidence"]["reason"].lower()
    assert "no matching catalogue entries" in reason
    # Helpful guidance about which filters narrowed too much.
    assert "this_tag_does_not_exist" in str(result.get("missing_information", "")) or any(
        "scenario_tag" in item for item in result.get("missing_information", [])
    )


def test_find_test_data_filters_and_explains_suitability() -> None:
    result = service().qa_find_test_data(
        environment="integration",
        domain="auth",
        scenario_tags=["account_locked"],
        known_valid_for=["locked account rejection"],
    )

    assert result["tool"] == "sumo_qa_find_test_data"
    assert result["results"]
    assert result["results"][0]["entry"]["id"] == "auth-locked-account-001"
    assert "known valid for" in result["results"][0]["suitability_reason"]
    assert result["results"][0]["validation"]["freshness"]["status"] == "fresh"


def test_find_test_data_pagination_metadata_present() -> None:
    """Pagination fields are always populated so callers can decide whether more
    results exist beyond the limit. Even single-page responses carry the totals."""
    result = service().qa_find_test_data(
        environment="integration",
        domain="auth",
        scenario_tags=["account_locked"],
        known_valid_for=["locked account rejection"],
        limit=5,
    )

    assert "total_count" in result
    assert "has_more" in result
    assert "next_offset" in result
    assert isinstance(result["total_count"], int)
    # When limit covers everything, has_more is false and next_offset is None.
    assert result["total_count"] == len(result["results"])
    assert result["has_more"] is False
    assert result["next_offset"] is None


def test_find_test_data_pagination_truncates_and_signals_more(tmp_path: Path) -> None:
    """When more entries match than the limit, has_more is true and next_offset
    points at the next page."""
    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")
    assistant = Assistant(catalogue, MockValidator(now=NOW))
    for index in range(7):
        assistant.register_known_good_test_data(
            {
                "id": f"auth-pagination-{index:03d}",
                "environment": "integration",
                "domain": "auth",
                "scenario_tags": ["pagination_smoke"],
                # Distinct known_valid_for per entry so duplicate detection
                # (env + domain + identifier + overlapping known_valid_for)
                # does NOT collapse them into one.
                "known_valid_for": [f"pagination smoke index {index}"],
                "owner": "qa",
                "confidence": "medium",
                "source": "qa-curated",
            }
        )

    page_one = assistant.find_test_data(
        environment="integration",
        domain="auth",
        scenario_tags=["pagination_smoke"],
        limit=3,
    )

    assert page_one["total_count"] == 7
    assert len(page_one["results"]) == 3
    assert page_one["has_more"] is True
    assert page_one["next_offset"] == 3

    page_two = assistant.find_test_data(
        environment="integration",
        domain="auth",
        scenario_tags=["pagination_smoke"],
        limit=3,
        offset=3,
    )

    assert page_two["total_count"] == 7
    assert len(page_two["results"]) == 3
    assert page_two["has_more"] is True
    assert page_two["next_offset"] == 6

    page_three = assistant.find_test_data(
        environment="integration",
        domain="auth",
        scenario_tags=["pagination_smoke"],
        limit=3,
        offset=6,
    )

    assert page_three["total_count"] == 7
    assert len(page_three["results"]) == 1
    assert page_three["has_more"] is False
    assert page_three["next_offset"] is None


def test_mock_validator_flags_future_validated_at() -> None:
    from datetime import timedelta as _td

    from sumo_qa.tdm_models import TestDataEntry as DEntry

    entry = DEntry(
        id="future-001",
        environment="integration",
        domain="auth",
        scenario_tags=["mfa_required"],
        known_valid_for=["mfa enforcement testing"],
        owner="qa",
        confidence="medium",
        source="qa-curated",
        last_validated_at=NOW + _td(days=10),
    )

    validator = MockValidator(now=NOW)
    result = validator.validate(entry)

    assert result.valid is False
    assert any("future" in issue.lower() for issue in result.issues)


def test_mock_validator_flags_high_confidence_with_stale_freshness() -> None:
    from datetime import timedelta as _td

    from sumo_qa.tdm_models import TestDataEntry as DEntry

    entry = DEntry(
        id="inconsistent-001",
        environment="integration",
        domain="auth",
        scenario_tags=["mfa_required"],
        known_valid_for=["mfa enforcement testing"],
        owner="qa",
        confidence="high",
        source="qa-curated",
        last_validated_at=NOW - _td(days=120),
    )

    validator = MockValidator(now=NOW)
    result = validator.validate(entry)

    assert result.valid is False
    assert any(
        "high confidence" in issue.lower() and "stale" in issue.lower() for issue in result.issues
    )


def test_validate_test_data_reports_freshness_and_confidence() -> None:
    result = service().qa_validate_test_data(entry_id="billing-pending-due-boundary-001")

    assert result["tool"] == "sumo_qa_validate_test_data"
    assert result["validation"]["validation_source"] == "mock-heuristic-validator"
    assert result["validation"]["freshness"]["status"] == "aging"
    assert result["validation"]["confidence"]["level"] == "medium"


def test_register_known_good_test_data_creates_updates_and_detects_duplicate(
    tmp_path: Path,
) -> None:
    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")
    assistant = Assistant(catalogue, MockValidator(now=NOW))
    entry = {
        "id": "auth-mfa-boundary-001",
        "environment": "integration",
        "domain": "auth",
        "scenario_tags": ["mfa_required", "boundary_token_age"],
        "known_valid_for": ["mfa enforcement testing"],
        "constraints": ["Reset MFA state after test execution."],
        "owner": "identity-platform",
        "confidence": "medium",
        "source": "qa-curated",
        "notes": "Boundary token-age example.",
    }

    created = assistant.register_known_good_test_data(entry)
    updated = assistant.register_known_good_test_data({**entry, "notes": "Updated note."})
    duplicate = assistant.register_known_good_test_data({**entry, "id": "different-id"})

    assert created["action"] == "created"
    assert created["entry"]["last_validated_at"]
    assert updated["action"] == "updated"
    assert duplicate["action"] == "duplicate"
    assert duplicate["duplicate_of"] == "auth-mfa-boundary-001"


def test_register_rejects_high_confidence_without_validation(tmp_path: Path) -> None:
    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")
    assistant = Assistant(catalogue, MockValidator(now=NOW))
    entry = {
        "id": "auth-overclaimed-001",
        "environment": "integration",
        "domain": "auth",
        "scenario_tags": ["mfa_required"],
        "known_valid_for": ["mfa enforcement testing"],
        "owner": "identity-platform",
        "confidence": "high",
        "source": "qa-curated",
    }

    with pytest.raises(ValueError) as excinfo:
        assistant.register_known_good_test_data(entry)

    message = str(excinfo.value).lower()
    assert "high confidence" in message
    assert "validate" in message or "downgrade" in message


def test_catalogue_caches_entries_until_invalidated(tmp_path: Path) -> None:
    root = tmp_path / "knowledge" / "test_data"
    domain_dir = root / "auth"
    domain_dir.mkdir(parents=True)
    yaml_path = domain_dir / "sample.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "entries": [
                    {
                        "id": "first",
                        "environment": "integration",
                        "domain": "auth",
                        "scenario_tags": ["active_account"],
                        "known_valid_for": ["active account login"],
                        "owner": "qa",
                        "confidence": "medium",
                        "source": "test",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    catalogue = Catalogue(root)
    first_call = catalogue.list_entries()
    assert [entry.id for entry in first_call] == ["first"]

    yaml_path.write_text(
        yaml.safe_dump(
            {
                "entries": [
                    {
                        "id": "second",
                        "environment": "integration",
                        "domain": "auth",
                        "scenario_tags": ["active_account"],
                        "known_valid_for": ["active account login"],
                        "owner": "qa",
                        "confidence": "medium",
                        "source": "test",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    cached = catalogue.list_entries()
    assert [entry.id for entry in cached] == ["first"], (
        "cache should return prior result until invalidated"
    )

    catalogue._invalidate_cache()
    refreshed = catalogue.list_entries()
    assert [entry.id for entry in refreshed] == ["second"]


def test_catalogue_register_invalidates_cache(tmp_path: Path) -> None:
    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")
    assistant = Assistant(catalogue, MockValidator(now=NOW))

    assert catalogue.list_entries() == []

    entry = {
        "id": "auth-cache-invalidate-001",
        "environment": "integration",
        "domain": "auth",
        "scenario_tags": ["active_account"],
        "known_valid_for": ["active account login"],
        "owner": "qa",
        "confidence": "medium",
        "source": "qa-curated",
    }
    assistant.register_known_good_test_data(entry)

    refreshed = catalogue.list_entries()
    assert [entry_obj.id for entry_obj in refreshed] == ["auth-cache-invalidate-001"]


def test_catalogue_reports_file_path_on_malformed_yaml(tmp_path: Path) -> None:
    domain_dir = tmp_path / "knowledge" / "test_data" / "auth"
    domain_dir.mkdir(parents=True)
    yaml_path = domain_dir / "broken.yaml"
    yaml_path.write_text("entries: [unclosed\n", encoding="utf-8")

    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")

    with pytest.raises(ValueError) as excinfo:
        catalogue.list_entries()

    assert str(yaml_path) in str(excinfo.value)


def test_catalogue_reports_file_path_on_invalid_entry(tmp_path: Path) -> None:
    domain_dir = tmp_path / "knowledge" / "test_data" / "auth"
    domain_dir.mkdir(parents=True)
    yaml_path = domain_dir / "bad_entry.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "entries": [
                    {
                        "id": "missing-fields-001",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")

    with pytest.raises(ValueError) as excinfo:
        catalogue.list_entries()

    message = str(excinfo.value)
    assert str(yaml_path) in message
    assert "missing-fields-001" in message


def test_catalogue_reports_file_path_when_entries_is_not_a_list(tmp_path: Path) -> None:
    domain_dir = tmp_path / "knowledge" / "test_data" / "auth"
    domain_dir.mkdir(parents=True)
    yaml_path = domain_dir / "wrong_shape.yaml"
    yaml_path.write_text(
        yaml.safe_dump({"entries": "not-a-list"}, sort_keys=False),
        encoding="utf-8",
    )

    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")

    with pytest.raises(ValueError) as excinfo:
        catalogue.list_entries()

    assert str(yaml_path) in str(excinfo.value)


def test_catalogue_get_returns_none_when_id_not_found(tmp_path: Path) -> None:
    """TestDataCatalogue.get() returns None when no entry matches (line 50)."""
    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")
    result = catalogue.get("nonexistent-id")
    assert result is None


def test_catalogue_raises_on_non_dict_entry(tmp_path: Path) -> None:
    """TestDataCatalogue.list_entries() raises ValueError when an entry is not a dict (line 32)."""
    domain_dir = tmp_path / "knowledge" / "test_data" / "auth"
    domain_dir.mkdir(parents=True)
    (domain_dir / "bad.yaml").write_text(
        yaml.safe_dump({"entries": ["not_a_dict"]}), encoding="utf-8"
    )
    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")
    with pytest.raises(ValueError, match="expected mapping"):
        catalogue.list_entries()


def test_catalogue_register_updates_existing_entry_by_id(tmp_path: Path) -> None:
    """TestDataCatalogue.register() updates an existing entry when the id matches (lines 70-72)."""
    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")
    base_entry = {
        "id": "auth-update-001",
        "environment": "integration",
        "domain": "auth",
        "scenario_tags": ["active_account"],
        "known_valid_for": ["login flow"],
        "owner": "qa",
        "confidence": "medium",
        "source": "qa-curated",
    }
    # Create first.
    action1, _, _, _ = catalogue.register(Entry(**base_entry))
    assert action1 == "created"
    # Update with same id.
    action2, updated, _, _ = catalogue.register(Entry(**{**base_entry, "notes": "updated note"}))
    assert action2 == "updated"
    assert updated.id == "auth-update-001"


def test_catalogue_register_returns_duplicate_when_different_id_but_same_identity(
    tmp_path: Path,
) -> None:
    """TestDataCatalogue.register() returns 'duplicate' when entry has different id but
    overlapping identity (lines 66)."""
    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")
    base = {
        "id": "auth-dup-original",
        "environment": "integration",
        "domain": "auth",
        "scenario_tags": ["account_locked"],
        "known_valid_for": ["locked account rejection"],
        "owner": "qa",
        "confidence": "medium",
        "source": "qa-curated",
    }
    catalogue.register(Entry(**base))
    # Register a new entry with the same identity but a different id.
    action, existing, _, existing_id = catalogue.register(
        Entry(**{**base, "id": "auth-dup-different-id"})
    )
    assert action == "duplicate"
    assert existing_id == "auth-dup-original"


def test_catalogue_find_duplicate_returns_none_when_no_match(tmp_path: Path) -> None:
    """TestDataCatalogue._find_duplicate() returns None when no overlapping entry
    exists in the catalogue (line 78)."""
    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")
    entry = Entry(
        id="auth-no-dup",
        environment="integration",
        domain="auth",
        scenario_tags=["unique_tag_xyz"],
        known_valid_for=["unique use case xyz"],
        owner="qa",
        confidence="medium",
        source="qa-curated",
    )
    result = catalogue._find_duplicate(entry)
    assert result is None


def test_catalogue_load_file_handles_empty_yaml(tmp_path: Path) -> None:
    """_load_file() returns empty entries dict when the YAML file contains null (line 152)."""
    from sumo_qa.tdm_catalogue import _load_file

    empty_yaml = tmp_path / "empty.yaml"
    empty_yaml.write_text("", encoding="utf-8")  # empty file → yaml.safe_load returns None
    result = _load_file(empty_yaml)
    assert result == {"entries": []}


def test_catalogue_load_file_raises_on_non_dict_top_level(tmp_path: Path) -> None:
    """_load_file() raises ValueError when the top-level YAML is not a mapping (line 154)."""
    from sumo_qa.tdm_catalogue import _load_file

    list_yaml = tmp_path / "list.yaml"
    list_yaml.write_text(yaml.safe_dump(["item1", "item2"]), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        _load_file(list_yaml)


# ---------------------------------------------------------------------------
# tdm_service.py branch coverage
# ---------------------------------------------------------------------------


def test_resolve_entry_returns_entry_from_dict(tmp_path: Path) -> None:
    """_resolve_entry() returns a TestDataEntry when `entry` dict is given (line 274)."""
    from sumo_qa.tdm_catalogue import TestDataCatalogue
    from sumo_qa.tdm_service import _resolve_entry

    catalogue = TestDataCatalogue(tmp_path / "test_data")
    result = _resolve_entry(
        catalogue,
        entry_id=None,
        entry={
            "id": "test-001",
            "environment": "integration",
            "domain": "auth",
            "scenario_tags": ["active"],
            "known_valid_for": ["login"],
            "owner": "qa",
            "confidence": "medium",
            "source": "test",
        },
    )
    assert result.id == "test-001"


def test_resolve_entry_raises_when_both_none(tmp_path: Path) -> None:
    """_resolve_entry() raises ValueError when both entry and entry_id are None (line 280)."""
    from sumo_qa.tdm_catalogue import TestDataCatalogue
    from sumo_qa.tdm_service import _resolve_entry

    catalogue = TestDataCatalogue(tmp_path / "test_data")
    with pytest.raises(ValueError, match="entry_id or entry is required"):
        _resolve_entry(catalogue, entry_id=None, entry=None)


def test_empty_result_hints_with_all_filters(tmp_path: Path) -> None:
    """_empty_result_hints() mentions known_valid_for, product_id, and sku (lines 300, 302, 304)."""
    from sumo_qa.tdm_service import _empty_result_hints

    hints = _empty_result_hints(
        environment="integration",
        domain="auth",
        scenario_tags=["tag1"],
        known_valid_for=["use1"],
        product_id="prod-001",
        sku="sku-001",
    )
    hint = hints[0]
    assert "known_valid_for" in hint
    assert "product_id" in hint
    assert "sku" in hint


def test_empty_result_hints_with_no_filters(tmp_path: Path) -> None:
    """_empty_result_hints() uses the 'catalogue is empty' message when no filters set (line 312)."""
    from sumo_qa.tdm_service import _empty_result_hints

    hints = _empty_result_hints(
        environment=None,
        domain=None,
        scenario_tags=None,
        known_valid_for=None,
        product_id=None,
        sku=None,
    )
    assert "catalogue is empty" in hints[0]


def test_find_missing_information_all_fields_missing() -> None:
    """_find_missing_information() reports environment, domain, and search params (lines 329, 331, 333)."""
    from sumo_qa.tdm_service import _find_missing_information

    missing = _find_missing_information(
        environment=None,
        domain=None,
        scenario_tags=None,
        known_valid_for=None,
        product_id=None,
        sku=None,
    )
    assert "environment" in missing
    assert "domain" in missing
    assert any("scenario_tags" in m for m in missing)


def test_aggregate_confidence_returns_medium_when_medium_present() -> None:
    """_aggregate_confidence() returns 'medium' when no high level present (line 350)."""
    from sumo_qa.tdm_service import _aggregate_confidence

    result = _aggregate_confidence(["medium", "low"])
    assert result == "medium"


def test_validate_test_data_raises_when_entry_id_not_found(tmp_path: Path) -> None:
    """validate_test_data() raises ValueError when entry_id doesn't exist in catalogue (line 279)."""
    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")
    assistant = Assistant(catalogue, MockValidator(now=NOW))
    with pytest.raises(ValueError, match="not found"):
        assistant.validate_test_data(entry_id="nonexistent-id-xyz")


def test_find_test_data_no_filters_returns_missing_info() -> None:
    """find_test_data() with no env/domain reports them in missing_information (lines 329, 331)."""
    result = service().qa_find_test_data()
    missing = result.get("missing_information", [])
    assert "environment" in missing
    assert "domain" in missing


def test_find_test_data_empty_with_product_id_and_sku(tmp_path: Path) -> None:
    """find_test_data() with product_id and sku filters exercices those hint branches (302, 304)."""
    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")
    assistant = Assistant(catalogue, MockValidator(now=NOW))
    result = assistant.find_test_data(
        environment="integration",
        domain="auth",
        product_id="prod-001",
        sku="sku-001",
    )
    assert result["results"] == []


# ---------------------------------------------------------------------------
# tdm_validation.py branch coverage
# ---------------------------------------------------------------------------


def _minimal_entry(**overrides):
    """Build a minimal TestDataEntry for validation tests."""
    from sumo_qa.tdm_models import TestDataEntry

    defaults = {
        "id": "val-test-001",
        "environment": "integration",
        "domain": "auth",
        "scenario_tags": ["active"],
        "known_valid_for": ["login"],
        "owner": "qa",
        "confidence": "medium",
        "source": "test",
    }
    return TestDataEntry(**{**defaults, **overrides})


def test_heuristic_issues_flags_missing_environment() -> None:
    """_heuristic_issues() appends 'environment is required' when empty (line 84)."""
    from sumo_qa.tdm_validation import _heuristic_issues

    entry = _minimal_entry(environment="")
    issues = _heuristic_issues(entry)
    assert any("environment" in i for i in issues)


def test_heuristic_issues_flags_missing_domain() -> None:
    """_heuristic_issues() appends 'domain is required' when empty (line 86)."""
    from sumo_qa.tdm_validation import _heuristic_issues

    entry = _minimal_entry(domain="")
    issues = _heuristic_issues(entry)
    assert any("domain" in i for i in issues)


def test_heuristic_issues_flags_missing_owner() -> None:
    """_heuristic_issues() appends 'owner is required' when empty (line 88)."""
    from sumo_qa.tdm_validation import _heuristic_issues

    entry = _minimal_entry(owner="")
    issues = _heuristic_issues(entry)
    assert any("owner" in i for i in issues)


def test_heuristic_issues_flags_missing_scenario_tags() -> None:
    """_heuristic_issues() appends scenario_tags hint when list is empty (line 90)."""
    from sumo_qa.tdm_validation import _heuristic_issues

    entry = _minimal_entry(scenario_tags=[])
    issues = _heuristic_issues(entry)
    assert any("scenario_tags" in i for i in issues)


def test_heuristic_issues_flags_missing_known_valid_for() -> None:
    """_heuristic_issues() appends known_valid_for hint when list is empty (line 92)."""
    from sumo_qa.tdm_validation import _heuristic_issues

    entry = _minimal_entry(known_valid_for=[])
    issues = _heuristic_issues(entry)
    assert any("known_valid_for" in i for i in issues)


def test_validation_reason_for_stale_freshness() -> None:
    """_validation_reason() returns the stale-specific message (line 146)."""
    from datetime import timedelta

    from sumo_qa.tdm_validation import _validation_reason, assess_freshness

    stale_date = NOW - timedelta(days=60)
    entry = _minimal_entry(last_validated_at=stale_date)
    freshness = assess_freshness(stale_date, NOW)
    reason = _validation_reason(entry, freshness, [])
    assert "Confidence: Low" in reason
    assert "day(s)" in reason


def test_ensure_aware_adds_utc_to_naive_datetime() -> None:
    """_ensure_aware() attaches UTC timezone to a naive datetime (line 151)."""
    from datetime import datetime

    from sumo_qa.tdm_validation import _ensure_aware

    naive = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo
    aware = _ensure_aware(naive)
    assert aware.tzinfo is not None


# ---------------------------------------------------------------------------
# tdm_catalogue.find() filter branch coverage (lines 66, 70, 72, 78)
# ---------------------------------------------------------------------------


def _make_catalogue_with_entries(tmp_path: Path, *entries) -> Catalogue:
    """Create a catalogue pre-populated with entries for filter tests."""
    cat = Catalogue(tmp_path / "knowledge" / "test_data")
    for e in entries:
        cat.register(e)
    cat._invalidate_cache()
    return cat


def test_catalogue_find_filters_by_environment(tmp_path: Path) -> None:
    """find() skips entries whose environment doesn't match (line 66: continue)."""
    entry = Entry(
        id="env-filter-001",
        environment="staging",
        domain="auth",
        scenario_tags=["active"],
        known_valid_for=["login"],
        owner="qa",
        confidence="medium",
        source="test",
    )
    cat = _make_catalogue_with_entries(tmp_path, entry)
    # Filter by 'integration' — 'staging' entry must be excluded.
    results = cat.find(environment="integration")
    assert all(e.environment.lower() == "integration" for e in results)
    assert not any(e.id == "env-filter-001" for e in results)


def test_catalogue_find_filters_by_product_id(tmp_path: Path) -> None:
    """find() skips entries whose product_id doesn't match (line 70: continue)."""
    entry = Entry(
        id="prod-filter-001",
        environment="integration",
        domain="auth",
        scenario_tags=["active"],
        known_valid_for=["login"],
        owner="qa",
        confidence="medium",
        source="test",
        product_id="PRODUCT-A",
    )
    cat = _make_catalogue_with_entries(tmp_path, entry)
    results = cat.find(product_id="PRODUCT-B")
    assert not any(e.id == "prod-filter-001" for e in results)


def test_catalogue_find_filters_by_sku(tmp_path: Path) -> None:
    """find() skips entries whose sku doesn't match (line 72: continue)."""
    entry = Entry(
        id="sku-filter-001",
        environment="integration",
        domain="auth",
        scenario_tags=["active"],
        known_valid_for=["login"],
        owner="qa",
        confidence="medium",
        source="test",
        sku="SKU-XYZ",
    )
    cat = _make_catalogue_with_entries(tmp_path, entry)
    results = cat.find(sku="SKU-ABC")
    assert not any(e.id == "sku-filter-001" for e in results)


def test_catalogue_find_filters_by_known_valid_for_no_intersection(tmp_path: Path) -> None:
    """find() skips entries with no known_valid_for intersection (line 78: continue)."""
    entry = Entry(
        id="valid-filter-001",
        environment="integration",
        domain="auth",
        scenario_tags=["active"],
        known_valid_for=["login"],
        owner="qa",
        confidence="medium",
        source="test",
    )
    cat = _make_catalogue_with_entries(tmp_path, entry)
    results = cat.find(known_valid_for=["completely_different_use_case"])
    assert not any(e.id == "valid-filter-001" for e in results)


def test_catalogue_loads_yaml_entries(tmp_path: Path) -> None:
    path = tmp_path / "knowledge" / "test_data" / "auth"
    path.mkdir(parents=True)
    (path / "sample.yaml").write_text(
        yaml.safe_dump(
            {
                "entries": [
                    {
                        "id": "sample-auth",
                        "environment": "integration",
                        "domain": "auth",
                        "scenario_tags": ["active_account"],
                        "known_valid_for": ["active account login"],
                        "owner": "qa",
                        "confidence": "medium",
                        "source": "test",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    entries = Catalogue(tmp_path / "knowledge" / "test_data").list_entries()

    assert entries == [
        Entry(
            id="sample-auth",
            environment="integration",
            domain="auth",
            scenario_tags=["active_account"],
            known_valid_for=["active account login"],
            owner="qa",
            confidence="medium",
            source="test",
        )
    ]
