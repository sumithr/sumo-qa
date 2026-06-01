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


# --- sha-mismatch gate: a fresh+passing fact captured against another commit
# --- is effectively stale and MUST NOT back safety (FIX 1) -------------------


def test_fresh_passing_fact_with_mismatched_sha_is_untrustworthy_and_stale():
    # The load-bearing FIX-1 case: a fact labelled fresh+passing but captured
    # against a DIFFERENT commit than head_sha must be reported untrustworthy AND
    # surfaced as stale. This test fails if the sha-mismatch gate is removed.
    bundle = _bundle(
        head_sha="aaaaaaaa1111",
        ci_status={
            "result": "passing",
            "freshness": "fresh",
            "source": "ci_provider",
            "captured_against_sha": "bbbbbbbb2222",
        },
    )
    assert bundle.untrustworthy_evidence_fields() == ["ci_status"]
    assert bundle.stale_evidence_fields() == ["ci_status"]


def test_fresh_passing_fact_with_matching_sha_is_trustworthy():
    # Control: a fresh+passing fact whose captured_against_sha matches head_sha
    # is fully trustworthy — the gate fires ONLY on a genuine mismatch.
    bundle = _bundle(
        head_sha="aaaaaaaa1111",
        ci_status={
            "result": "passing",
            "freshness": "fresh",
            "source": "ci_provider",
            "captured_against_sha": "aaaaaaaa1111",
        },
    )
    assert bundle.untrustworthy_evidence_fields() == []
    assert bundle.stale_evidence_fields() == []


def test_fresh_passing_fact_abbreviated_matching_sha_is_trustworthy():
    # Prefix-aware (FIX 3 cross-check): an abbreviated captured_against_sha that
    # prefixes the full head_sha is the SAME commit — not a mismatch.
    bundle = _bundle(
        head_sha="aaaaaaaa1111deadbeef",
        ci_status={
            "result": "passing",
            "freshness": "fresh",
            "source": "ci_provider",
            "captured_against_sha": "aaaaaaaa",
        },
    )
    assert bundle.untrustworthy_evidence_fields() == []
    assert bundle.stale_evidence_fields() == []


def test_sha_mismatch_gate_inert_when_head_or_capture_absent():
    # No head_sha (or no captured_against_sha) ⇒ no sha signal to cross-check, so
    # the gate stays inert and a fresh pass remains trustworthy.
    no_head = _bundle(
        ci_status={
            "result": "passing",
            "freshness": "fresh",
            "source": "ci_provider",
            "captured_against_sha": "bbbbbbbb2222",
        },
    )
    assert no_head.untrustworthy_evidence_fields() == []
    no_capture = _bundle(
        head_sha="aaaaaaaa1111",
        ci_status={"result": "passing", "freshness": "fresh", "source": "ci_provider"},
    )
    assert no_capture.untrustworthy_evidence_fields() == []


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


# --- conflict gate is prefix-aware (FIX 3) -----------------------------------


def test_abbreviated_bundle_sha_prefixing_full_local_no_conflict():
    # An abbreviated bundle sha that prefixes the full local sha names the SAME
    # commit — exact-equality would falsely flag a conflict. Prefix-aware ⇒ none.
    bundle = _bundle(head_sha="abc1234")
    assert detect_local_conflict(bundle, "abc1234deadbeef0099") is None


def test_full_bundle_sha_prefixed_by_abbreviated_local_no_conflict():
    # Same in the other direction: an abbreviated local sha prefixing the full
    # bundle sha is no conflict.
    bundle = _bundle(head_sha="abc1234deadbeef0099")
    assert detect_local_conflict(bundle, "abc1234") is None


def test_case_insensitive_sha_prefix_no_conflict():
    bundle = _bundle(head_sha="ABC1234")
    assert detect_local_conflict(bundle, "abc1234deadbeef") is None


def test_genuinely_different_shas_still_conflict():
    bundle = _bundle(head_sha="abc1234")
    msg = detect_local_conflict(bundle, "def5678abcdef")
    assert msg is not None
    assert "abc1234" in msg and "def5678abcdef" in msg


def test_short_prefix_below_floor_does_not_falsely_match():
    # A too-short string ("abc", < 7 chars) must NOT prefix-match an unrelated
    # full sha — that would be a 3-char false match. It is a genuine conflict.
    bundle = _bundle(head_sha="abc")
    assert detect_local_conflict(bundle, "abcdef1234567") is not None


def test_whitespace_only_sha_treated_as_conflict():
    # A whitespace-only sha is not a real commit identifier: after stripping it
    # is empty, so the two are not equivalent and a conflict is reported.
    bundle = _bundle(head_sha="   ")
    assert detect_local_conflict(bundle, "abc1234deadbeef") is not None
