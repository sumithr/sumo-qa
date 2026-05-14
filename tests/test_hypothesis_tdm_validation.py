# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Hypothesis property tests for sumo_qa.tdm_validation.

Covers invariants that happy-path unit tests cannot pin:
  - assess_freshness is monotonic with age (older => worse-or-equal status).
  - _heuristic_issues always returns a list, never None.
  - _lowest_confidence is commutative.
  - _lowest_confidence is associative.
  - _confidence_from_freshness is total over all known freshness statuses.
  - _ensure_aware always produces a tz-aware datetime.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from sumo_qa import tdm_validation as tv
from sumo_qa.tdm_models import TestDataEntry

# ---------------------------------------------------------------------------
# Known constants, read directly from the production module / models.
# ---------------------------------------------------------------------------

KNOWN_CONFIDENCE_LEVELS = ["low", "medium", "high"]

# Statuses produced by assess_freshness (excludes "not_applicable", which is
# produced only by not_applicable_freshness and never fed into
# _confidence_from_freshness in production).
FRESHNESS_STATUSES = ["fresh", "aging", "stale", "unknown"]

# Severity order for monotonicity: higher number = worse freshness.
# "unknown" sits at 1 (worse than fresh but below stale) because it means
# never-validated, not necessarily old.  The real ordering tested below only
# covers dates that *produce* fresh/aging/stale — unknown is excluded by the
# assume() guard (both sides get concrete datetimes).
FRESHNESS_SEVERITY = {"fresh": 0, "aging": 1, "stale": 2}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _aware(dt: datetime) -> datetime:
    """Return dt with UTC attached if it was naive."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _minimal_entry(**overrides) -> TestDataEntry:
    """Build a minimal valid TestDataEntry, accepting field overrides."""
    defaults = dict(
        id="test-id",
        environment="test",
        domain="orders",
        owner="team-qa",
        source="catalogue",
        scenario_tags=["checkout"],
        known_valid_for=["place-order"],
        confidence="low",
    )
    defaults.update(overrides)
    return TestDataEntry(**defaults)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

NAIVE_DTS = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 1, 1),
)

CONFIDENCE_LEVELS = st.sampled_from(KNOWN_CONFIDENCE_LEVELS)


# ---------------------------------------------------------------------------
# Property 1 — assess_freshness is monotonic with age
#
# Given two last_validated_at times where older < newer (both before `now`),
# the older timestamp should produce a freshness status that is worse-or-equal
# to the newer timestamp (because older means more days have elapsed).
# ---------------------------------------------------------------------------


@given(t1=NAIVE_DTS, t2=NAIVE_DTS)
@settings(max_examples=200)
def test_assess_freshness_monotonic_with_age(t1: datetime, t2: datetime) -> None:
    """Older last_validated_at must yield freshness worse-or-equal to newer."""
    assume(t1 != t2)
    older, newer = (_aware(min(t1, t2)), _aware(max(t1, t2)))
    # `now` is strictly after newer so both timestamps produce concrete statuses
    # (fresh/aging/stale), never "unknown" (which requires None input).
    now = _aware(newer + timedelta(days=1))

    older_result = tv.assess_freshness(older, now)
    newer_result = tv.assess_freshness(newer, now)

    older_severity = FRESHNESS_SEVERITY[older_result.status]
    newer_severity = FRESHNESS_SEVERITY[newer_result.status]
    assert older_severity >= newer_severity, (
        f"older ({older}) => {older_result.status!r} severity={older_severity}, "
        f"newer ({newer}) => {newer_result.status!r} severity={newer_severity}; "
        "expected older to be worse-or-equal"
    )


# ---------------------------------------------------------------------------
# Property 2 — _heuristic_issues always returns a list (never None)
# ---------------------------------------------------------------------------


@given(
    environment=st.text(min_size=0, max_size=20),
    domain=st.text(min_size=0, max_size=20),
    owner=st.text(min_size=0, max_size=20),
    scenario_tags=st.lists(st.text(min_size=1, max_size=10), max_size=5),
    known_valid_for=st.lists(st.text(min_size=1, max_size=10), max_size=5),
)
@settings(max_examples=200)
def test_heuristic_issues_always_returns_list(
    environment: str,
    domain: str,
    owner: str,
    scenario_tags: list[str],
    known_valid_for: list[str],
) -> None:
    """_heuristic_issues must return a list for any combination of field values."""
    entry = _minimal_entry(
        environment=environment,
        domain=domain,
        owner=owner,
        scenario_tags=scenario_tags,
        known_valid_for=known_valid_for,
    )
    result = tv._heuristic_issues(entry)
    assert isinstance(result, list), f"Expected list, got {type(result)}"


# ---------------------------------------------------------------------------
# Property 3 — _lowest_confidence is commutative
# ---------------------------------------------------------------------------


@given(a=CONFIDENCE_LEVELS, b=CONFIDENCE_LEVELS)
@settings(max_examples=50)
def test_lowest_confidence_commutative(a: str, b: str) -> None:
    """_lowest_confidence(a, b) == _lowest_confidence(b, a) for all inputs."""
    assert tv._lowest_confidence(a, b) == tv._lowest_confidence(b, a)


# ---------------------------------------------------------------------------
# Property 4 — _lowest_confidence is associative
# ---------------------------------------------------------------------------


@given(a=CONFIDENCE_LEVELS, b=CONFIDENCE_LEVELS, c=CONFIDENCE_LEVELS)
@settings(max_examples=50)
def test_lowest_confidence_associative(a: str, b: str, c: str) -> None:
    """_lowest_confidence must be associative over all three-level combinations."""
    left = tv._lowest_confidence(a, tv._lowest_confidence(b, c))
    right = tv._lowest_confidence(tv._lowest_confidence(a, b), c)
    assert left == right, f"Associativity failed: ({a!r}, {b!r}, {c!r}) => {left!r} vs {right!r}"


# ---------------------------------------------------------------------------
# Property 5 — _confidence_from_freshness is total over all known statuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", FRESHNESS_STATUSES)
def test_confidence_from_freshness_is_total(status: str) -> None:
    """_confidence_from_freshness must return a known confidence level for every status."""
    result = tv._confidence_from_freshness(status)
    assert result in KNOWN_CONFIDENCE_LEVELS, (
        f"_confidence_from_freshness({status!r}) returned {result!r}, "
        f"expected one of {KNOWN_CONFIDENCE_LEVELS}"
    )


# ---------------------------------------------------------------------------
# Property 6 — _ensure_aware always produces a tz-aware datetime
# ---------------------------------------------------------------------------


@given(
    dt=st.datetimes(
        min_value=datetime(2000, 1, 1),
        max_value=datetime(2100, 1, 1),
        timezones=st.none() | st.timezones(),
    )
)
@settings(max_examples=300)
def test_ensure_aware_always_returns_aware_datetime(dt: datetime) -> None:
    """_ensure_aware must always return a datetime with tzinfo set."""
    result = tv._ensure_aware(dt)
    assert isinstance(result, datetime)
    assert result.tzinfo is not None, f"_ensure_aware({dt!r}) returned naive datetime {result!r}"
