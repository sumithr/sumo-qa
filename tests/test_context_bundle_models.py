# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.context_bundle_models — the freshness, staleness, and
bundle-vs-local-conflict logic of the host-neutral context bundle (issue #149).

These cover the load-bearing acceptance criteria:
  * stale / unknown / absent evidence is NEVER trustworthy for a safety claim;
  * stale evidence is reported as stale (distinct from absent/unknown);
  * a bundle whose head_sha differs from the live local head is a reported
    conflict, and equal/absent shas are not.

Technique: decision tables over (freshness × result) for the safety gate, and
over (bundle sha × local sha) for the conflict gate.
"""

from __future__ import annotations

import pytest

from sumo_qa.context_bundle_models import (
    CONTEXT_BUNDLE_SCHEMA_VERSION,
    ContextBundle,
    EvidenceFact,
    detect_local_conflict,
)


def _fact(result: str, freshness: str, source: str = "ci_provider") -> EvidenceFact:
    return EvidenceFact(result=result, freshness=freshness, source=source)


# --- safety gate: ONLY a fresh pass is trustworthy ---------------------------


def test_fresh_passing_is_trustworthy():
    assert _fact("passing", "fresh").is_trustworthy_for_safety() is True


@pytest.mark.parametrize("freshness", ["stale", "unknown", "absent"])
def test_non_fresh_pass_is_not_trustworthy(freshness):
    # A pass that is stale/unknown/absent must NOT back a safety claim — this is
    # the "do not claim safety from stale evidence" criterion.
    assert _fact("passing", freshness).is_trustworthy_for_safety() is False


@pytest.mark.parametrize("result", ["failing", "mixed", "not_run"])
def test_fresh_non_pass_is_not_trustworthy(result):
    # Even fresh evidence is only safety-supporting when it actually passed.
    assert _fact(result, "fresh").is_trustworthy_for_safety() is False


# --- stale detection is distinct from unknown/absent -------------------------


def test_only_explicit_stale_is_reported_stale():
    assert _fact("passing", "stale").is_stale() is True
    assert _fact("passing", "unknown").is_stale() is False
    assert _fact("not_run", "absent").is_stale() is False
    assert _fact("passing", "fresh").is_stale() is False


def _bundle(**overrides) -> ContextBundle:
    data = {"schema_version": CONTEXT_BUNDLE_SCHEMA_VERSION}
    data.update(overrides)
    return ContextBundle.model_validate(data)


def test_stale_evidence_fields_lists_only_stale():
    bundle = _bundle(
        test_evidence={"result": "passing", "freshness": "fresh", "source": "local_git"},
        ci_status={"result": "passing", "freshness": "stale", "source": "ci_provider"},
    )
    assert bundle.stale_evidence_fields() == ["ci_status"]


def test_untrustworthy_includes_unknown_not_just_stale():
    # A stale-only view would miss an unknown-freshness pass; the safety view
    # must flag it too.
    bundle = _bundle(
        test_evidence={"result": "passing", "freshness": "unknown", "source": "manual"},
        ci_status={"result": "passing", "freshness": "fresh", "source": "ci_provider"},
    )
    assert bundle.stale_evidence_fields() == []
    assert bundle.untrustworthy_evidence_fields() == ["test_evidence"]


def test_absent_evidence_is_not_listed_as_present_fields():
    # No evidence supplied at all ⇒ nothing to flag (the consumer falls back).
    bundle = _bundle()
    assert bundle.stale_evidence_fields() == []
    assert bundle.untrustworthy_evidence_fields() == []


# --- conflict gate: differing shas conflict, equal/absent do not -------------


def test_differing_shas_conflict():
    bundle = _bundle(head_sha="aaa")
    msg = detect_local_conflict(bundle, "bbb")
    assert msg is not None
    assert "aaa" in msg and "bbb" in msg


def test_equal_shas_no_conflict():
    bundle = _bundle(head_sha="aaa")
    assert detect_local_conflict(bundle, "aaa") is None


def test_missing_bundle_sha_no_conflict():
    bundle = _bundle()
    assert detect_local_conflict(bundle, "bbb") is None


def test_missing_local_sha_no_conflict():
    bundle = _bundle(head_sha="aaa")
    assert detect_local_conflict(bundle, None) is None
