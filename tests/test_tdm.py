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
        Catalogue(ROOT / "knowledge" / "test_data"),
        MockValidator(now=NOW),
    )
    return QAShiftLeftService(test_data_assistant=assistant)


def test_explain_test_data_requirements_is_senior_qa_focused() -> None:
    """Phrase-based domain auto-detection has been removed — callers pass
    `domain` explicitly (the AI path also reasons about the domain). The
    deterministic skeleton still returns the universal QA bones (stable
    identifiers, edge cases, what-not-to-use) for any domain."""
    result = service().qa_explain_test_data_requirements(
        "What data do I need to test out-of-area fulfilment pricing?",
        environment="integration",
        domain="fulfilment",
    )

    assert result["tool"] == "sumo_qa_explain_test_data_requirements"
    assert result["domain"] == "fulfilment"
    assert result["fulfilment_conditions"], "must surface fulfilment-condition skeleton"
    assert result["what_not_to_use"], "must surface what-not-to-use skeleton"
    assert result["confidence"]["level"] == "medium"
    assert result["validation_source"] == "requirements-heuristic"


def test_explain_test_data_requirements_falls_back_to_general_when_domain_omitted() -> None:
    """Without an explicit domain, the tool stays generic — no phrase-matching
    'fulfilment' or 'pricing' to guess."""
    result = service().qa_explain_test_data_requirements(
        "What data do I need to test out-of-area fulfilment pricing?",
        environment="integration",
    )
    assert result["domain"] == "general"


def test_find_test_data_explains_when_no_results() -> None:
    result = service().qa_find_test_data(
        environment="integration",
        domain="stock",
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
        domain="fulfilment",
        scenario_tags=["out_of_area"],
        known_valid_for=["out-of-area fulfilment pricing"],
    )

    assert result["tool"] == "sumo_qa_find_test_data"
    assert result["results"]
    assert result["results"][0]["entry"]["id"] == "fulfilment-out-of-area-001"
    assert "known valid for" in result["results"][0]["suitability_reason"]
    assert result["results"][0]["validation"]["freshness"]["status"] == "fresh"


def test_find_test_data_pagination_metadata_present() -> None:
    """Pagination fields are always populated so callers can decide whether more
    results exist beyond the limit. Even single-page responses carry the totals."""
    result = service().qa_find_test_data(
        environment="integration",
        domain="fulfilment",
        scenario_tags=["out_of_area"],
        known_valid_for=["out-of-area fulfilment pricing"],
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
                "id": f"stock-pagination-{index:03d}",
                "environment": "integration",
                "domain": "stock",
                "product_id": f"{1000 + index}",
                "sku": f"{1000 + index}",
                "scenario_tags": ["pagination_smoke"],
                "known_valid_for": ["pagination smoke"],
                "owner": "qa",
                "confidence": "medium",
                "source": "qa-curated",
            }
        )

    page_one = assistant.find_test_data(
        environment="integration",
        domain="stock",
        scenario_tags=["pagination_smoke"],
        limit=3,
    )

    assert page_one["total_count"] == 7
    assert len(page_one["results"]) == 3
    assert page_one["has_more"] is True
    assert page_one["next_offset"] == 3

    page_two = assistant.find_test_data(
        environment="integration",
        domain="stock",
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
        domain="stock",
        scenario_tags=["pagination_smoke"],
        limit=3,
        offset=6,
    )

    assert page_three["total_count"] == 7
    assert len(page_three["results"]) == 1
    assert page_three["has_more"] is False
    assert page_three["next_offset"] is None


def test_mock_validator_flags_future_validated_at() -> None:
    from sumo_qa.tdm_models import TestDataEntry as DEntry
    from datetime import timedelta as _td
    entry = DEntry(
        id="future-001",
        environment="integration",
        domain="stock",
        sku="1",
        scenario_tags=["availability"],
        known_valid_for=["availability check"],
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
    from sumo_qa.tdm_models import TestDataEntry as DEntry
    from datetime import timedelta as _td
    entry = DEntry(
        id="inconsistent-001",
        environment="integration",
        domain="stock",
        sku="1",
        scenario_tags=["availability"],
        known_valid_for=["availability check"],
        owner="qa",
        confidence="high",
        source="qa-curated",
        last_validated_at=NOW - _td(days=120),
    )

    validator = MockValidator(now=NOW)
    result = validator.validate(entry)

    assert result.valid is False
    assert any(
        "high confidence" in issue.lower() and "stale" in issue.lower()
        for issue in result.issues
    )


def test_validate_test_data_reports_freshness_and_confidence() -> None:
    result = service().qa_validate_test_data(entry_id="stock-pricing-validation-001")

    assert result["tool"] == "sumo_qa_validate_test_data"
    assert result["validation"]["validation_source"] == "mock-heuristic-validator"
    assert result["validation"]["freshness"]["status"] == "aging"
    assert result["validation"]["confidence"]["level"] == "medium"


def test_register_known_good_test_data_creates_updates_and_detects_duplicate(tmp_path: Path) -> None:
    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")
    assistant = Assistant(catalogue, MockValidator(now=NOW))
    entry = {
        "id": "stock-low-stock-001",
        "environment": "integration",
        "domain": "stock",
        "product_id": "10001",
        "sku": "10001",
        "scenario_tags": ["low_stock", "stock_reservation"],
        "known_valid_for": ["stock reservation"],
        "constraints": ["Do not consume final unit in shared tests."],
        "owner": "stock-platform",
        "confidence": "medium",
        "source": "qa-curated",
        "notes": "Low stock boundary example.",
    }

    created = assistant.register_known_good_test_data(entry)
    updated = assistant.register_known_good_test_data({**entry, "notes": "Updated note."})
    duplicate = assistant.register_known_good_test_data({**entry, "id": "different-id"})

    assert created["action"] == "created"
    assert created["entry"]["last_validated_at"]
    assert updated["action"] == "updated"
    assert duplicate["action"] == "duplicate"
    assert duplicate["duplicate_of"] == "stock-low-stock-001"


def test_register_rejects_high_confidence_without_validation(tmp_path: Path) -> None:
    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")
    assistant = Assistant(catalogue, MockValidator(now=NOW))
    entry = {
        "id": "stock-overclaimed-001",
        "environment": "integration",
        "domain": "stock",
        "product_id": "10001",
        "sku": "10001",
        "scenario_tags": ["low_stock"],
        "known_valid_for": ["stock reservation"],
        "owner": "stock-platform",
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
    domain_dir = root / "stock"
    domain_dir.mkdir(parents=True)
    yaml_path = domain_dir / "sample.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "entries": [
                    {
                        "id": "first",
                        "environment": "integration",
                        "domain": "stock",
                        "sku": "1",
                        "scenario_tags": ["availability"],
                        "known_valid_for": ["availability check"],
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
                        "domain": "stock",
                        "sku": "2",
                        "scenario_tags": ["availability"],
                        "known_valid_for": ["availability check"],
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
    assert [entry.id for entry in cached] == ["first"], "cache should return prior result until invalidated"

    catalogue._invalidate_cache()
    refreshed = catalogue.list_entries()
    assert [entry.id for entry in refreshed] == ["second"]


def test_catalogue_register_invalidates_cache(tmp_path: Path) -> None:
    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")
    assistant = Assistant(catalogue, MockValidator(now=NOW))

    assert catalogue.list_entries() == []

    entry = {
        "id": "stock-cache-invalidate-001",
        "environment": "integration",
        "domain": "stock",
        "product_id": "1",
        "sku": "1",
        "scenario_tags": ["availability"],
        "known_valid_for": ["availability check"],
        "owner": "qa",
        "confidence": "medium",
        "source": "qa-curated",
    }
    assistant.register_known_good_test_data(entry)

    refreshed = catalogue.list_entries()
    assert [entry_obj.id for entry_obj in refreshed] == ["stock-cache-invalidate-001"]


def test_catalogue_reports_file_path_on_malformed_yaml(tmp_path: Path) -> None:
    domain_dir = tmp_path / "knowledge" / "test_data" / "stock"
    domain_dir.mkdir(parents=True)
    yaml_path = domain_dir / "broken.yaml"
    yaml_path.write_text("entries: [unclosed\n", encoding="utf-8")

    catalogue = Catalogue(tmp_path / "knowledge" / "test_data")

    with pytest.raises(ValueError) as excinfo:
        catalogue.list_entries()

    assert str(yaml_path) in str(excinfo.value)


def test_catalogue_reports_file_path_on_invalid_entry(tmp_path: Path) -> None:
    domain_dir = tmp_path / "knowledge" / "test_data" / "stock"
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
    domain_dir = tmp_path / "knowledge" / "test_data" / "stock"
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


def test_catalogue_loads_yaml_entries(tmp_path: Path) -> None:
    path = tmp_path / "knowledge" / "test_data" / "stock"
    path.mkdir(parents=True)
    (path / "sample.yaml").write_text(
        yaml.safe_dump(
            {
                "entries": [
                    {
                        "id": "sample-stock",
                        "environment": "integration",
                        "domain": "stock",
                        "sku": "1",
                        "scenario_tags": ["availability"],
                        "known_valid_for": ["availability check"],
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
            id="sample-stock",
            environment="integration",
            domain="stock",
            sku="1",
            scenario_tags=["availability"],
            known_valid_for=["availability check"],
            owner="qa",
            confidence="medium",
            source="test",
        )
    ]
