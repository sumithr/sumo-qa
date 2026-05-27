# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from sumo_qa.tdm_catalogue import TestDataCatalogue
from sumo_qa.tdm_models import (
    TDMConfidenceLevel,
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
        results = [
            _search_result(entry, self.validator, scenario_tags or [], known_valid_for or [])
            for entry in entries
        ]
        results.sort(key=lambda result: result.rank_score, reverse=True)
        total_count = len(results)
        safe_offset = max(offset, 0)
        page_size = max(limit, 1)
        limited_results = results[safe_offset : safe_offset + page_size]
        end_index = safe_offset + len(limited_results)
        has_more = total_count > end_index
        next_offset = end_index if has_more else None
        response_confidence = _aggregate_confidence(
            [result.validation.confidence.level for result in limited_results]
        )
        freshness = (
            limited_results[0].validation.freshness
            if limited_results
            else not_applicable_freshness("No catalogue entry matched the query.")
        )
        missing_information = _find_missing_information(
            environment, domain, scenario_tags, known_valid_for, product_id, sku
        )
        if not limited_results:
            missing_information.extend(
                _empty_result_hints(
                    environment, domain, scenario_tags, known_valid_for, product_id, sku
                )
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
            confidence=TestDataConfidence(
                level=response_confidence, reason=_find_confidence_reason(limited_results)
            ),
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
    universally across domains: stable identifiers, known starting state,
    named edge cases, explicit 'what NOT to use'. Domain-specific
    specialisation (whatever the actual domain is — auth, billing, ML
    inference, retail fulfilment, infrastructure, etc.) is the AI's job —
    the AI is grounded in ISTQB risk-based testing and reads the question
    verbatim via MCP sampling.

    A lightweight, *deterministic* scenario-signal pass (see
    ``_SCENARIO_RULES``) enriches the existing list fields when obvious
    keywords appear in the question — e.g. ``locked``, ``refund``,
    ``discontinued``, ``due-date``, ``stale``. The enrichment is purely
    additive (the universal skeleton stays) and never widens the schema.
    It does NOT re-introduce phrase-based domain guessing — ``_detect_domain()``
    still returns ``"general"`` when the caller omits ``domain``. Issue #78
    motivated this; the rules are local, keyword-based, and free of network
    calls or live validation.
    """
    entity_characteristics = [
        "stable identifier for the entity under test",
        "entity exists and is in the expected state in the target environment",
    ]
    resource_state_conditions = ["known starting state of the resource before test execution"]
    scenario_preconditions = [
        "all prerequisite conditions for the scenario are satisfied in the target environment",
    ]
    dependencies = [
        "any upstream system the entity depends on",
        "any downstream system the test exercises",
    ]
    edges = [
        "boundary values for the inputs the test exercises",
        "unavailable or degraded dependency",
        "invalid or out-of-policy input",
    ]
    what_not = [
        "records discovered ad-hoc with no validation history",
        "data with unknown owner",
        "entries not validated against the target environment",
    ]

    # Scenario-aware enrichment. Each matched rule contributes items to
    # whichever existing list field is the natural home for its scenario;
    # _dedupe() collapses any overlap between rule families and the
    # universal skeleton.
    for rule in _scenario_rules(question):
        entity_characteristics.extend(rule.get("required_entity_characteristics", []))
        resource_state_conditions.extend(rule.get("resource_state_conditions", []))
        scenario_preconditions.extend(rule.get("scenario_preconditions", []))
        dependencies.extend(rule.get("downstream_dependencies", []))
        edges.extend(rule.get("edge_case_recommendations", []))
        what_not.extend(rule.get("what_not_to_use", []))

    return TestDataRequirements(
        summary=(
            f"Use owned, recently validated {domain} data in "
            f"{environment or 'the target integration environment'}; "
            "avoid ad-hoc records with no validation history."
        ),
        domain=domain,
        environment=environment,
        required_entity_characteristics=_dedupe(entity_characteristics),
        resource_state_conditions=_dedupe(resource_state_conditions),
        scenario_preconditions=_dedupe(scenario_preconditions),
        downstream_dependencies=_dedupe(dependencies),
        edge_case_recommendations=_dedupe(edges),
        what_not_to_use=_dedupe(what_not),
        assumptions=[
            "No live downstream validation is configured yet.",
            "Catalogue entries are local YAML until provider integrations are added.",
        ],
        confidence=TestDataConfidence(
            level="medium",
            reason="Requirement reasoning is deterministic and rule-based, but not backed by live downstream validation.",
        ),
        freshness=not_applicable_freshness(
            "Requirements reasoning does not validate a specific catalogue entry."
        ),
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
    return TestDataSearchResult(
        entry=entry, validation=validation, suitability_reason=reason, rank_score=score
    )


def _rank_score(
    entry: TestDataEntry,
    confidence: str,
    scenario_tags: list[str],
    known_valid_for: list[str],
) -> int:
    score = {"high": 60, "medium": 35, "low": 10}[confidence]
    score += 10 * len(
        {item.lower() for item in scenario_tags}.intersection(
            {item.lower() for item in entry.scenario_tags}
        )
    )
    score += 12 * len(
        {item.lower() for item in known_valid_for}.intersection(
            {item.lower() for item in entry.known_valid_for}
        )
    )
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
        matched_tags = sorted(
            {item.lower() for item in scenario_tags}.intersection(
                {item.lower() for item in entry.scenario_tags}
            )
        )
        if matched_tags:
            matches.append(f"matches scenario tag(s): {', '.join(matched_tags)}")
    if known_valid_for:
        matched_uses = sorted(
            {item.lower() for item in known_valid_for}.intersection(
                {item.lower() for item in entry.known_valid_for}
            )
        )
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


def _aggregate_confidence(levels: list[str]) -> TDMConfidenceLevel:
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
    produces generic requirements; pass `domain=...` to scope to whichever
    domain folder the catalogue uses (e.g. 'auth', 'billing', 'payments',
    'inventory' — whatever the team's `knowledge/test_data/` layout
    declares).

    Note: _SCENARIO_RULES enriches the requirement *lists* with scenario-
    specific items when the question contains an obvious keyword, but it
    deliberately does NOT touch `domain` — phrase-based domain inference
    was removed for a reason (PR history; issue #78 keeps it out)."""
    return "general"


# Scenario-signal rules consumed by `_requirements_for()` via
# `_scenario_rules()`. Each rule is a `keywords` tuple + items keyed by
# the matching field on `TestDataRequirements`; matching is lightweight
# case-insensitive substring detection on the question text. Add a rule
# by appending a dict — no schema change, no LLM, no network. Rule
# families intentionally cover the issue-#78 scenarios (auth/account,
# billing/payments, inventory/product, boundary/degraded-state).
_SCENARIO_RULES: tuple[dict[str, Any], ...] = (
    # --- Auth / account state ------------------------------------------------
    {
        "keywords": ("locked", "lockout", "lock out"),
        "required_entity_characteristics": [
            "user-account record with a stable identifier and a 'locked' status field",
        ],
        "resource_state_conditions": [
            "account is in the locked state in the target environment per the auth provider's policy",
        ],
        "scenario_preconditions": [
            "account has been locked by the configured policy (consecutive failed logins, manual lock, or admin action)",
        ],
        "what_not_to_use": [
            "active accounts repurposed as 'locked' via ad-hoc flag flips — state reverts and breaks the next run",
        ],
    },
    {
        "keywords": ("mfa", "two-factor", "two factor"),
        "required_entity_characteristics": [
            "user account with a known MFA enrolment state and the configured second-factor channel",
        ],
        "resource_state_conditions": [
            "MFA enrolment record matches the scenario (enrolled / not enrolled / partially enrolled)",
        ],
        "scenario_preconditions": [
            "second-factor delivery channel is reachable in the target environment",
        ],
    },
    {
        "keywords": ("token replay", "expired token", "replay attack"),
        "required_entity_characteristics": [
            "auth token with a known issued-at and expiry, and the replay-detection state at that point in time",
        ],
        "resource_state_conditions": [
            "replay-detection cache reflects the expected prior-use state for the token",
        ],
        "edge_case_recommendations": [
            "token presented at, immediately before, and immediately after its expiry boundary",
        ],
    },
    # --- Billing / payments --------------------------------------------------
    {
        "keywords": ("refund",),
        "required_entity_characteristics": [
            "invoice or payment record with a stable id, a paid state, and a known issue date",
        ],
        "resource_state_conditions": [
            "invoice is in paid state and within the refund-eligibility window",
        ],
        "scenario_preconditions": [
            "refund window for the invoice has not expired per the configured policy",
        ],
    },
    {
        "keywords": ("paid invoice",),
        "resource_state_conditions": [
            "invoice is in paid state in the target environment with the original payment record intact",
        ],
    },
    {
        "keywords": ("duplicate payment",),
        "edge_case_recommendations": [
            "second payment submitted within the duplicate-detection window for the same invoice",
        ],
    },
    {
        "keywords": ("currency", "rounding"),
        "edge_case_recommendations": [
            "amounts at the minor-unit rounding boundary in the configured currency",
        ],
    },
    # --- Inventory / product -------------------------------------------------
    {
        "keywords": ("sku",),
        "required_entity_characteristics": [
            "product record with a stable SKU and a known stock state",
        ],
    },
    {
        "keywords": ("stock",),
        "resource_state_conditions": [
            "stock level for the SKU is in the expected state (in stock / low / zero) in the target environment",
        ],
    },
    {
        "keywords": ("discontinued",),
        "required_entity_characteristics": [
            "product record flagged as discontinued, with the documented replacement SKU when one exists",
        ],
        "what_not_to_use": [
            "discontinued SKUs without a documented replacement — the fallback path becomes ambiguous",
        ],
    },
    {
        "keywords": ("backorder", "back order"),
        "resource_state_conditions": [
            "SKU is in backorder state with a known expected-restock date",
        ],
    },
    {
        "keywords": ("product id",),
        "required_entity_characteristics": [
            "stable product id distinct from the SKU, persisted in the target environment",
        ],
    },
    # --- Boundary / degraded-state ------------------------------------------
    {
        "keywords": ("due-date", "due date"),
        "edge_case_recommendations": [
            "due-date value at, immediately before, and immediately after the boundary",
        ],
    },
    {
        "keywords": ("stale",),
        "edge_case_recommendations": [
            "upstream returns a stale record older than the configured freshness window",
        ],
    },
)


def _scenario_rules(question: str) -> list[dict[str, Any]]:
    """Return scenario enrichment rules whose keywords appear in the
    question text. Case-insensitive WORD-BOUNDARY match — deterministic,
    no LLM, no network. Multiple rules can match a single question; each
    contributes items to whichever existing list field on
    :class:`TestDataRequirements` is the natural home for its scenario.

    Word-boundary anchoring (``\\b``) prevents short keywords from
    misfiring on incidental substrings: ``locked`` no longer matches
    ``unlocked``; ``currency`` no longer matches ``concurrency``;
    ``stock`` no longer matches ``stockholm``. Multi-word keywords
    (``token replay``, ``paid invoice``) still match exactly because
    ``re.escape`` escapes the space and ``\\b`` straddles the
    non-word characters at each end."""
    text = question.lower()
    return [
        rule
        for rule in _SCENARIO_RULES
        if any(re.search(rf"\b{re.escape(kw)}\b", text) for kw in rule["keywords"])
    ]


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
