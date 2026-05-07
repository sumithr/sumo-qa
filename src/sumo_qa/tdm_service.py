from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from sumo_qa.tdm_catalogue import TestDataCatalogue
from sumo_qa.tdm_models import (
    TestDataConfidence,
    TestDataEntry,
    TestDataFindResponse,
    TestDataRegisterResponse,
    TestDataRequirements,
    TestDataSearchResult,
    TestDataValidateResponse,
)
from sumo_qa.tdm_validation import MockValidator, TestDataValidator, not_applicable_freshness


class TestDataAssistant:
    def __init__(
        self,
        catalogue: TestDataCatalogue,
        validator: TestDataValidator | None = None,
    ) -> None:
        self.catalogue = catalogue
        self.validator = validator or MockValidator()

    def explain_requirements(
        self,
        question: str,
        environment: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        detected_domain = domain or _detect_domain(question)
        requirements = _requirements_for(question, detected_domain, environment)
        return requirements.model_dump(mode="json")

    def find_test_data(
        self,
        environment: str | None = None,
        domain: str | None = None,
        scenario_tags: list[str] | None = None,
        known_valid_for: list[str] | None = None,
        product_id: str | None = None,
        sku: str | None = None,
        limit: int = 5,
        offset: int = 0,
    ) -> dict[str, Any]:
        entries = self.catalogue.find(
            environment=_clean(environment),
            domain=_clean(domain),
            scenario_tags=scenario_tags,
            known_valid_for=known_valid_for,
            product_id=_clean(product_id),
            sku=_clean(sku),
        )
        results = [_search_result(entry, self.validator, scenario_tags or [], known_valid_for or []) for entry in entries]
        results.sort(key=lambda result: result.rank_score, reverse=True)
        total_count = len(results)
        safe_offset = max(offset, 0)
        page_size = max(limit, 1)
        limited_results = results[safe_offset : safe_offset + page_size]
        end_index = safe_offset + len(limited_results)
        has_more = total_count > end_index
        next_offset = end_index if has_more else None
        response_confidence = _aggregate_confidence([result.validation.confidence.level for result in limited_results])
        freshness = limited_results[0].validation.freshness if limited_results else not_applicable_freshness("No catalogue entry matched the query.")
        missing_information = _find_missing_information(
            environment, domain, scenario_tags, known_valid_for, product_id, sku
        )
        if not limited_results:
            missing_information.extend(
                _empty_result_hints(environment, domain, scenario_tags, known_valid_for, product_id, sku)
            )
        response = TestDataFindResponse(
            query={
                "environment": environment,
                "domain": domain,
                "scenario_tags": scenario_tags or [],
                "known_valid_for": known_valid_for or [],
                "product_id": product_id,
                "sku": sku,
                "limit": limit,
                "offset": safe_offset,
            },
            results=limited_results,
            total_count=total_count,
            has_more=has_more,
            next_offset=next_offset,
            missing_information=missing_information,
            confidence=TestDataConfidence(level=response_confidence, reason=_find_confidence_reason(limited_results)),
            freshness=freshness,
            validation_source=self.validator.validation_source,
        )
        return response.model_dump(mode="json")

    def validate_test_data(
        self,
        entry_id: str | None = None,
        entry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_entry = _resolve_entry(self.catalogue, entry_id, entry)
        validation = self.validator.validate(resolved_entry)
        response = TestDataValidateResponse(entry=resolved_entry, validation=validation)
        return response.model_dump(mode="json")

    def register_known_good_test_data(self, entry: dict[str, Any]) -> dict[str, Any]:
        try:
            candidate = TestDataEntry(**entry)
        except ValidationError as exc:
            raise ValueError(f"Invalid test data entry: {exc}") from exc
        pre_validation = self.validator.validate(candidate)
        if pre_validation.issues:
            raise ValueError(f"Invalid test data entry: {', '.join(pre_validation.issues)}")

        action, registered_entry, path, duplicate_of = self.catalogue.register(candidate)
        validation = self.validator.validate(registered_entry)
        response = TestDataRegisterResponse(
            action=action,
            entry=registered_entry,
            validation=validation,
            catalogue_path=path,
            duplicate_of=duplicate_of,
        )
        return response.model_dump(mode="json")


def _requirements_for(question: str, domain: str, environment: str | None) -> TestDataRequirements:
    """Generic test-data requirements skeleton. Senior-QA discipline applies
    universally: stable identifiers, known starting state, named edge cases,
    explicit 'what NOT to use'. Domain-specific specialisation (out-of-area
    addresses, pricing bands, slot booking, stock boundaries) is the AI's
    job — the AI is grounded in ISTQB risk-based testing in the system
    prompt and reads the question verbatim via MCP sampling.
    """
    product_characteristics = ["stable product identifier and SKU", "active product in the target environment"]
    stock_conditions = ["known stock state before test execution"]
    fulfilment_conditions = ["clear fulfilment eligibility for the requested location or channel"]
    dependencies = ["product catalogue", "pricing service", "stock or availability source", "fulfilment eligibility service"]
    edges = ["invalid postcode or location", "zero stock", "disabled fulfilment option"]
    what_not = ["random products found manually", "data with unknown owner", "entries not validated in the target environment"]

    return TestDataRequirements(
        summary=f"Use owned, recently validated {domain} data in {environment or 'the target integration environment'}; avoid manually discovered stale products.",
        domain=domain,
        environment=environment,
        required_product_characteristics=_dedupe(product_characteristics),
        stock_conditions=_dedupe(stock_conditions),
        fulfilment_conditions=_dedupe(fulfilment_conditions),
        downstream_dependencies=_dedupe(dependencies),
        edge_case_recommendations=_dedupe(edges),
        what_not_to_use=_dedupe(what_not),
        assumptions=["No live downstream validation is configured yet.", "Catalogue entries are local YAML until provider integrations are added."],
        confidence=TestDataConfidence(level="medium", reason="Requirement reasoning is deterministic and rule-based, but not backed by live downstream validation."),
        freshness=not_applicable_freshness("Requirements reasoning does not validate a specific catalogue entry."),
        validation_source="requirements-heuristic",
    )


def _search_result(
    entry: TestDataEntry,
    validator: TestDataValidator,
    scenario_tags: list[str],
    known_valid_for: list[str],
) -> TestDataSearchResult:
    validation = validator.validate(entry)
    score = _rank_score(entry, validation.confidence.level, scenario_tags, known_valid_for)
    reason = _suitability_reason(entry, validation.confidence.level, scenario_tags, known_valid_for)
    return TestDataSearchResult(entry=entry, validation=validation, suitability_reason=reason, rank_score=score)


def _rank_score(
    entry: TestDataEntry,
    confidence: str,
    scenario_tags: list[str],
    known_valid_for: list[str],
) -> int:
    score = {"high": 60, "medium": 35, "low": 10}[confidence]
    score += 10 * len({item.lower() for item in scenario_tags}.intersection({item.lower() for item in entry.scenario_tags}))
    score += 12 * len({item.lower() for item in known_valid_for}.intersection({item.lower() for item in entry.known_valid_for}))
    if entry.owner:
        score += 5
    return score


def _suitability_reason(
    entry: TestDataEntry,
    confidence: str,
    scenario_tags: list[str],
    known_valid_for: list[str],
) -> str:
    matches = []
    if scenario_tags:
        matched_tags = sorted({item.lower() for item in scenario_tags}.intersection({item.lower() for item in entry.scenario_tags}))
        if matched_tags:
            matches.append(f"matches scenario tag(s): {', '.join(matched_tags)}")
    if known_valid_for:
        matched_uses = sorted({item.lower() for item in known_valid_for}.intersection({item.lower() for item in entry.known_valid_for}))
        if matched_uses:
            matches.append(f"known valid for: {', '.join(matched_uses)}")
    matches.append(f"{confidence} confidence")
    matches.append(f"owned by {entry.owner}")
    return "; ".join(matches)


def _resolve_entry(
    catalogue: TestDataCatalogue,
    entry_id: str | None,
    entry: dict[str, Any] | None,
) -> TestDataEntry:
    if entry:
        return TestDataEntry(**entry)
    if entry_id:
        found = catalogue.get(entry_id)
        if found:
            return found
        raise ValueError(f"Test data entry not found: {entry_id}")
    raise ValueError("entry_id or entry is required")


def _empty_result_hints(
    environment: str | None,
    domain: str | None,
    scenario_tags: list[str] | None,
    known_valid_for: list[str] | None,
    product_id: str | None,
    sku: str | None,
) -> list[str]:
    hints: list[str] = []
    applied: list[str] = []
    if environment:
        applied.append(f"environment={environment}")
    if domain:
        applied.append(f"domain={domain}")
    if scenario_tags:
        applied.append(f"scenario_tags={scenario_tags}")
    if known_valid_for:
        applied.append(f"known_valid_for={known_valid_for}")
    if product_id:
        applied.append(f"product_id={product_id}")
    if sku:
        applied.append(f"sku={sku}")
    if applied:
        hints.append(
            "no catalogue entries matched the filters: "
            + ", ".join(applied)
            + ". Try relaxing scenario_tags or known_valid_for first."
        )
    else:
        hints.append(
            "the catalogue is empty for this query - register a known-good entry "
            "with sumo_qa_register_known_good_test_data."
        )
    return hints


def _find_missing_information(
    environment: str | None,
    domain: str | None,
    scenario_tags: list[str] | None,
    known_valid_for: list[str] | None,
    product_id: str | None,
    sku: str | None,
) -> list[str]:
    missing = []
    if not environment:
        missing.append("environment")
    if not domain:
        missing.append("domain")
    if not scenario_tags and not known_valid_for and not product_id and not sku:
        missing.append("scenario_tags, known_valid_for, product_id, or sku")
    return missing


def _find_confidence_reason(results: list[TestDataSearchResult]) -> str:
    if not results:
        return "Confidence: Low because no matching catalogue entries were found."
    best = results[0]
    return f"Confidence: {best.validation.confidence.level.title()} because top match {best.validation.validation_reason}"


def _aggregate_confidence(levels: list[str]) -> str:
    if not levels:
        return "low"
    if "high" in levels:
        return "high"
    if "medium" in levels:
        return "medium"
    return "low"


def _detect_domain(question: str) -> str:
    """Domain auto-detection used to phrase-match the question. That's the
    AI's job now — `qa_explain_test_data_requirements` callers should pass
    `domain` explicitly if they know it. Returns 'general' so the tool
    produces generic requirements; pass `domain=...` for catalogued
    domains like 'stock', 'fulfilment', or 'pricing'."""
    return "general"


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
