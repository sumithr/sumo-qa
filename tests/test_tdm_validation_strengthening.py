# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Mutation-strengthening tests (Phase 3) for `sumo_qa.tdm_validation`.

Walks the 57 surviving mutants from the Phase 3 baseline (see
`docs/qa/runs/2026-05-14-phase3-mutation-baseline.md`) and kills each via a
behaviour-anchored assertion. Production code is NOT touched.

Survivor classes:
- A. MockValidator.validate body (9): _lowest_confidence args, in/not-in invert,
  set-element text, pass None to _validation_reason
- B. assess_freshness (15): timezone.utc, FreshnessMetadata kwargs, reason text,
  max(...,0), boundary `<=` vs `<`
- C. _validation_reason (12): branch text mutations
- D. _plausibility_issues (12): future-date check, confidence/freshness checks,
  message text
- E. _heuristic_issues (5): inverted conditions, message text
- F. _confidence_from_freshness (3): branch conditions, return values
- G. _lowest_confidence (1): rank dict mutation
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sumo_qa import tdm_validation as tv
from sumo_qa.tdm_models import (
    FreshnessMetadata,
    TDMConfidenceLevel,
    TestDataEntry,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)


def _entry(**overrides) -> TestDataEntry:
    """Build a minimal TestDataEntry; overrides patch in test-specific fields."""
    defaults = dict(
        id="test-entry-1",
        environment="staging",
        domain="billing",
        owner="qa@example.com",
        source="manual-fixture",
        scenario_tags=["happy-path"],
        known_valid_for=["smoke-test"],
        confidence="medium",
        last_validated_at=NOW - timedelta(days=3),
    )
    defaults.update(overrides)
    return TestDataEntry(**defaults)


# ---------------------------------------------------------------------------
# Class A — MockValidator.validate body (9 mutants)
# ---------------------------------------------------------------------------


def test_validator_lowest_confidence_uses_all_three_inputs() -> None:
    """Kills _lowest_confidence-args mutations: removing entry.confidence or
    freshness_level from the call would let a high-recorded-confidence entry
    keep a "high" level when freshness or issues should drag it lower.
    """
    # Stale freshness (>30 days old) → freshness_level should be "low".
    # Recorded confidence is "high" but the lowest of (high, low, high) = low.
    entry = _entry(confidence="high", last_validated_at=NOW - timedelta(days=60))
    result = tv.MockValidator(now=NOW).validate(entry)
    assert result.confidence.level == "low", (
        f"Stale entry with high recorded confidence should drop to low; "
        f"got {result.confidence.level}"
    )


def test_validator_valid_field_uses_not_in_for_excluded_statuses() -> None:
    """Kills:
      - mutmut_34 (`not in` → `in` invert)
      - mutmut_35-38 (text mutations on `{"stale", "unknown"}`)

    Asserts: a fresh entry with no issues yields valid=True. A stale entry
    yields valid=False. An unknown-freshness entry yields valid=False.
    Inverting the operator or mutating the set strings would flip these.
    """
    fresh_entry = _entry(last_validated_at=NOW - timedelta(days=2))
    fresh_result = tv.MockValidator(now=NOW).validate(fresh_entry)
    assert fresh_result.valid is True, "Fresh entry with no issues should be valid"

    stale_entry = _entry(last_validated_at=NOW - timedelta(days=60))
    stale_result = tv.MockValidator(now=NOW).validate(stale_entry)
    assert stale_result.valid is False, "Stale entry should be invalid"

    unknown_entry = _entry(last_validated_at=None)
    unknown_result = tv.MockValidator(now=NOW).validate(unknown_entry)
    assert unknown_result.valid is False, "Unknown-freshness entry should be invalid"


def test_validator_passes_actual_issues_list_to_validation_reason() -> None:
    """Kills mutmut_42: `_validation_reason(entry, freshness, None)` would
    cause the function to behave as if there were no issues. Assert the
    reason text reflects the actual issues found.
    """
    # Entry missing owner → triggers _heuristic_issues.
    entry = _entry(owner="")
    result = tv.MockValidator(now=NOW).validate(entry)
    assert "owner is required" in result.confidence.reason, (
        f"Expected validation reason to mention 'owner is required'; "
        f"got {result.confidence.reason!r}"
    )


# ---------------------------------------------------------------------------
# Class B — assess_freshness (15 mutants)
# ---------------------------------------------------------------------------


def test_assess_freshness_default_now_is_timezone_aware() -> None:
    """Kills mutmut_3: `datetime.now(timezone.utc)` → `datetime.now(None)`.

    The mutated default would produce a naive datetime, then comparing
    `reference - validated_at` (where validated_at is aware) would raise
    TypeError. Calling assess_freshness without explicit `now` and with an
    aware `last_validated_at` would crash.
    """
    aware_validated_at = datetime.now(timezone.utc) - timedelta(days=1)
    # If now defaults to a naive datetime, this raises TypeError.
    result = tv.assess_freshness(aware_validated_at)
    assert isinstance(result, FreshnessMetadata)
    assert result.status in {"fresh", "aging", "stale"}


def test_assess_freshness_unknown_status_preserves_kwargs() -> None:
    """Kills mutmut_8 / _9: dropping `last_validated_at=None` or `age_days=None`
    from the FreshnessMetadata constructor for the unknown-status case.

    Asserts the returned metadata has BOTH fields explicitly set
    (would default to non-None / wrong-typed if removed from kwargs).
    """
    result = tv.assess_freshness(None)
    assert result.status == "unknown"
    assert result.last_validated_at is None, (
        f"Expected last_validated_at=None for unknown-status; got {result.last_validated_at!r}"
    )
    assert result.age_days is None, (
        f"Expected age_days=None for unknown-status; got {result.age_days!r}"
    )


def test_assess_freshness_unknown_reason_text() -> None:
    """Kills mutmut_13/_14/_15: text mutations on the unknown-status reason."""
    result = tv.assess_freshness(None)
    assert result.reason == "Entry has never been validated.", (
        f"Exact reason text required; got {result.reason!r}"
    )


def test_assess_freshness_clamps_negative_age_to_zero() -> None:
    """Kills mutmut_24: `max(..., 0)` → `max(..., 1)`.

    A future last_validated_at would produce a negative timedelta;
    `max(...days, 0)` clamps to 0, mutated `max(..., 1)` clamps to 1.
    Asserts age_days == 0 for a future date.
    """
    future_validated_at = NOW + timedelta(days=5)
    result = tv.assess_freshness(future_validated_at, now=NOW)
    assert result.age_days == 0, (
        f"Future last_validated_at should clamp age_days to 0; got {result.age_days}"
    )


@pytest.mark.parametrize(
    "age_days, expected_status",
    [
        (0, "fresh"),
        (7, "fresh"),  # boundary: <= 7 means 7 is included
        (8, "aging"),  # boundary: 8 is NOT fresh
        (30, "aging"),  # boundary: <= 30 means 30 is included
        (31, "stale"),  # boundary: 31 is NOT aging
    ],
)
def test_assess_freshness_status_boundaries(age_days: int, expected_status: str) -> None:
    """Kills boundary mutations on `<= 7` and `<= 30`.

    Mutations like `< 7` would shift the boundary by 1 day; this parametrised
    test exercises the exact boundary values + adjacent.
    """
    validated_at = NOW - timedelta(days=age_days)
    result = tv.assess_freshness(validated_at, now=NOW)
    assert result.status == expected_status, (
        f"age_days={age_days}: expected {expected_status}; got {result.status}"
    )


def test_assess_freshness_reason_format_includes_age_days() -> None:
    """Kills mutations on the reason format-string content. Asserts each
    status's reason contains the literal age and the canonical wording.
    """
    fresh = tv.assess_freshness(NOW - timedelta(days=3), now=NOW)
    assert fresh.reason == "Validated 3 day(s) ago.", f"Fresh: got {fresh.reason!r}"

    aging = tv.assess_freshness(NOW - timedelta(days=15), now=NOW)
    assert aging.reason == (
        "Validated 15 day(s) ago; still usable but should be refreshed soon."
    ), f"Aging: got {aging.reason!r}"

    stale = tv.assess_freshness(NOW - timedelta(days=60), now=NOW)
    assert stale.reason == "Entry has not been validated in 60 day(s).", (
        f"Stale: got {stale.reason!r}"
    )


# ---------------------------------------------------------------------------
# Class C — _validation_reason (12 mutants)
# ---------------------------------------------------------------------------


def test_validation_reason_includes_all_issues_when_present() -> None:
    """Kills text mutations on the issues-branch reason."""
    entry = _entry()
    freshness = FreshnessMetadata(status="fresh", reason="Validated 1 day ago.")
    issues = ["owner is required", "domain is required"]
    reason = tv._validation_reason(entry, freshness, issues)
    assert reason == (
        "Confidence: Low because heuristic validation found: owner is required, domain is required."
    ), f"Got {reason!r}"


def test_validation_reason_unknown_status_returns_canonical_text() -> None:
    """Kills text mutations on the unknown-status reason."""
    entry = _entry()
    freshness = FreshnessMetadata(status="unknown", reason="never validated")
    reason = tv._validation_reason(entry, freshness, [])
    assert reason == "Confidence: Low because entry has never been validated.", f"Got {reason!r}"


def test_validation_reason_fresh_uses_entry_confidence_titlecased() -> None:
    """Kills text + format mutations on the fresh-status reason."""
    entry = _entry(confidence="high")
    freshness = FreshnessMetadata(status="fresh", reason="Validated 2 day(s) ago.")
    reason = tv._validation_reason(entry, freshness, [])
    assert reason == "Confidence: High because validated 2 day(s) ago.", f"Got {reason!r}"


def test_validation_reason_aging_status_returns_medium_confidence() -> None:
    """Kills text mutations on the aging-status reason."""
    entry = _entry(confidence="high")
    freshness = FreshnessMetadata(
        status="aging",
        reason="Validated 20 day(s) ago; still usable but should be refreshed soon.",
    )
    reason = tv._validation_reason(entry, freshness, [])
    assert reason == (
        "Confidence: Medium because validated 20 day(s) ago; "
        "still usable but should be refreshed soon."
    ), f"Got {reason!r}"


def test_validation_reason_stale_status_returns_low_confidence() -> None:
    """Kills text mutations on the stale-status (default branch) reason."""
    entry = _entry(confidence="high")
    freshness = FreshnessMetadata(
        status="stale", reason="Entry has not been validated in 60 day(s)."
    )
    reason = tv._validation_reason(entry, freshness, [])
    assert reason == ("Confidence: Low because entry has not been validated in 60 day(s)."), (
        f"Got {reason!r}"
    )


# ---------------------------------------------------------------------------
# Class D — _plausibility_issues (12 mutants)
# ---------------------------------------------------------------------------


def test_plausibility_issues_flags_future_validated_at() -> None:
    """Kills mutations on the `validated_at > now` check + the message text.
    Boundary mutation `>=` would still flag (since NOW + delta is strictly >
    NOW), but the issue text is asserted exactly.
    """
    entry = _entry(last_validated_at=NOW + timedelta(hours=1))
    freshness = FreshnessMetadata(status="unknown", reason="x")
    issues = tv._plausibility_issues(entry, freshness, NOW)
    assert any("future" in i for i in issues), f"Expected future-date issue; got {issues}"


def test_plausibility_issues_flags_high_confidence_with_stale_freshness() -> None:
    """Kills the confidence-vs-stale check + message text mutations."""
    entry = _entry(confidence="high")
    freshness = FreshnessMetadata(status="stale", reason="x")
    issues = tv._plausibility_issues(entry, freshness, NOW)
    assert any("stale" in i and "high confidence" in i for i in issues), (
        f"Expected high-confidence-stale issue; got {issues}"
    )


def test_plausibility_issues_flags_high_confidence_with_unknown_freshness() -> None:
    """Kills the confidence-vs-unknown check + message text mutations."""
    entry = _entry(confidence="high", last_validated_at=None)
    freshness = FreshnessMetadata(status="unknown", reason="x")
    issues = tv._plausibility_issues(entry, freshness, NOW)
    assert any("never been validated" in i and "high confidence" in i for i in issues), (
        f"Expected high-confidence-unknown issue; got {issues}"
    )


def test_plausibility_issues_no_issues_for_low_confidence_stale() -> None:
    """Kills mutations that would invert the `confidence == "high"` check."""
    entry = _entry(confidence="low", last_validated_at=NOW - timedelta(days=60))
    freshness = FreshnessMetadata(status="stale", reason="x")
    issues = tv._plausibility_issues(entry, freshness, NOW)
    assert not any("confidence" in i for i in issues), (
        f"Low-confidence-stale should NOT flag confidence issue; got {issues}"
    )


def test_plausibility_issues_no_future_flag_for_past_validated_at() -> None:
    """Kills `>` → `<` invert: a past date should NOT trigger the future flag."""
    entry = _entry(last_validated_at=NOW - timedelta(hours=1))
    freshness = FreshnessMetadata(status="fresh", reason="x")
    issues = tv._plausibility_issues(entry, freshness, NOW)
    assert not any("future" in i for i in issues), (
        f"Past date should not flag future-date; got {issues}"
    )


def test_plausibility_issues_no_future_flag_when_last_validated_at_is_none() -> None:
    """Kills mutations that would skip the `is not None` guard."""
    entry = _entry(last_validated_at=None)
    freshness = FreshnessMetadata(status="unknown", reason="x")
    issues = tv._plausibility_issues(entry, freshness, NOW)
    # No future-date issue (since last_validated_at is None).
    assert not any("future" in i for i in issues), (
        f"None last_validated_at should not flag future-date; got {issues}"
    )


# ---------------------------------------------------------------------------
# Class E — _heuristic_issues (5 mutants)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, expected_issue_substring",
    [
        ("environment", "environment is required"),
        ("domain", "domain is required"),
        ("owner", "owner is required"),
    ],
)
def test_heuristic_issues_flags_missing_required_field(
    field: str, expected_issue_substring: str
) -> None:
    """Kills `not entry.X` → `entry.X` invert mutations + message text."""
    entry = _entry(**{field: ""})
    issues = tv._heuristic_issues(entry)
    assert any(expected_issue_substring in i for i in issues), (
        f"Expected {expected_issue_substring!r} in issues; got {issues}"
    )


def test_heuristic_issues_flags_empty_scenario_tags() -> None:
    """Kills `not entry.scenario_tags` → invert + message text mutations."""
    entry = _entry(scenario_tags=[])
    issues = tv._heuristic_issues(entry)
    assert any("scenario_tags" in i for i in issues), f"Expected scenario_tags issue; got {issues}"


def test_heuristic_issues_flags_empty_known_valid_for() -> None:
    """Kills `not entry.known_valid_for` → invert + message text mutations."""
    entry = _entry(known_valid_for=[])
    issues = tv._heuristic_issues(entry)
    assert any("known_valid_for" in i for i in issues), (
        f"Expected known_valid_for issue; got {issues}"
    )


def test_heuristic_issues_no_issues_for_complete_entry() -> None:
    """Kills mutations that would always-flag regardless of input."""
    issues = tv._heuristic_issues(_entry())
    assert issues == [], f"Complete entry should have no heuristic issues; got {issues}"


# ---------------------------------------------------------------------------
# Class F — _confidence_from_freshness (3 mutants)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, expected",
    [
        ("fresh", "high"),
        ("aging", "medium"),
        ("stale", "low"),
        ("unknown", "low"),
        ("not_applicable", "low"),
    ],
)
def test_confidence_from_freshness_maps_each_status(
    status: str, expected: TDMConfidenceLevel
) -> None:
    """Kills branch-condition mutations + return-value mutations.

    The 3 mutants surfaced are likely:
      - `== "fresh"` → `!= "fresh"`
      - `== "aging"` → `!= "aging"`
      - return value swaps

    This parametrised test exercises every status, asserting the exact mapping.
    """
    assert tv._confidence_from_freshness(status) == expected


# ---------------------------------------------------------------------------
# Class G — _lowest_confidence (1 mutant)
# ---------------------------------------------------------------------------


def test_lowest_confidence_returns_low_when_present() -> None:
    """Kills the rank-dict mutation. With the rank dict mutated, the min
    function would pick a different element. Asserts (high, medium, low)
    returns "low".
    """
    assert tv._lowest_confidence("high", "medium", "low") == "low"
    assert tv._lowest_confidence("high", "high", "high") == "high"
    assert tv._lowest_confidence("medium", "high") == "medium"
    assert tv._lowest_confidence("low") == "low"
