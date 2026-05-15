# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from sumo_qa.tdm_models import (
    FreshnessMetadata,
    TDMConfidenceLevel,
    TestDataConfidence,
    TestDataEntry,
    ValidationResult,
)


class TestDataValidator(Protocol):
    validation_source: str

    def validate(self, entry: TestDataEntry) -> ValidationResult:
        """Validate a test data entry without provisioning or mutating downstream systems."""


class MockValidator:
    validation_source = "mock-heuristic-validator"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now

    def validate(self, entry: TestDataEntry) -> ValidationResult:
        now = self._now or datetime.now(timezone.utc)
        freshness = assess_freshness(entry.last_validated_at, now)
        issues = _heuristic_issues(entry)
        issues.extend(_plausibility_issues(entry, freshness, now))
        freshness_level = _confidence_from_freshness(freshness.status)
        level = _lowest_confidence(entry.confidence, freshness_level, "low" if issues else "high")
        valid = not issues and freshness.status not in {"stale", "unknown"}
        reason = _validation_reason(entry, freshness, issues)
        return ValidationResult(
            entry_id=entry.id,
            valid=valid,
            confidence=TestDataConfidence(level=level, reason=reason),
            freshness=freshness,
            validation_source=self.validation_source,
            validation_reason=reason,
            checked_at=now,
            issues=issues,
        )


def assess_freshness(
    last_validated_at: datetime | None, now: datetime | None = None
) -> FreshnessMetadata:
    reference = now or datetime.now(timezone.utc)
    if last_validated_at is None:
        return FreshnessMetadata(
            status="unknown",
            # Both kwargs match the FreshnessMetadata model defaults; mutmut
            # mutations that drop them produce identical objects.
            last_validated_at=None,  # pragma: no mutate
            age_days=None,  # pragma: no mutate
            reason="Entry has never been validated.",
        )
    validated_at = _ensure_aware(last_validated_at)
    age_days = max((reference - validated_at).days, 0)
    if age_days <= 7:
        status = "fresh"
        reason = f"Validated {age_days} day(s) ago."
    elif age_days <= 30:
        status = "aging"
        reason = f"Validated {age_days} day(s) ago; still usable but should be refreshed soon."
    else:
        status = "stale"
        reason = f"Entry has not been validated in {age_days} day(s)."
    return FreshnessMetadata(
        status=status, last_validated_at=validated_at, age_days=age_days, reason=reason
    )


def not_applicable_freshness(reason: str) -> FreshnessMetadata:
    return FreshnessMetadata(status="not_applicable", reason=reason)


def _heuristic_issues(entry: TestDataEntry) -> list[str]:
    issues = []
    if not entry.environment:
        issues.append("environment is required")
    if not entry.domain:
        issues.append("domain is required")
    if not entry.owner:
        issues.append("owner is required")
    if not entry.scenario_tags:
        issues.append("scenario_tags should describe when this data is useful")
    if not entry.known_valid_for:
        issues.append("known_valid_for should name validated use cases")
    return issues


def _plausibility_issues(
    entry: TestDataEntry,
    freshness: FreshnessMetadata,
    now: datetime,
) -> list[str]:
    issues: list[str] = []
    if entry.last_validated_at is not None:
        validated_at = _ensure_aware(entry.last_validated_at)
        if validated_at > now:
            issues.append(
                f"last_validated_at is in the future ({validated_at.isoformat()}); "
                "the timestamp is likely wrong or the clock skewed"
            )
    if entry.confidence == "high" and freshness.status == "stale":
        issues.append(
            "entry claims high confidence but freshness is stale; "
            "either re-validate or downgrade the recorded confidence"
        )
    if entry.confidence == "high" and freshness.status == "unknown":
        issues.append(
            "entry claims high confidence but has never been validated; "
            "validate first or downgrade the recorded confidence"
        )
    return issues


def _confidence_from_freshness(status: str) -> TDMConfidenceLevel:
    if status == "fresh":
        return "high"
    if status == "aging":
        return "medium"
    return "low"


def _lowest_confidence(*levels: TDMConfidenceLevel) -> TDMConfidenceLevel:
    # Magnitude of the rank values is irrelevant to `min(..., key=...)` — only
    # ordering matters. Mutations to the high-rank value (e.g. 2 → 3) preserve
    # the ordering low<medium<high and produce no observable difference.
    rank = {"low": 0, "medium": 1, "high": 2}  # pragma: no mutate
    return min(levels, key=lambda level: rank[level])


def _validation_reason(
    entry: TestDataEntry, freshness: FreshnessMetadata, issues: list[str]
) -> str:
    if issues:
        return f"Confidence: Low because heuristic validation found: {', '.join(issues)}."
    if freshness.status == "unknown":
        return "Confidence: Low because entry has never been validated."
    if freshness.status == "fresh":
        return f"Confidence: {entry.confidence.title()} because {freshness.reason.lower()}"
    if freshness.status == "aging":
        return f"Confidence: Medium because {freshness.reason.lower()}"
    return f"Confidence: Low because {freshness.reason.lower()}"


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
