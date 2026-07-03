# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.gate_evidence_validation — the gate-evidence validators (#213).

Covers both entry points:

* ``load_gate_report`` — the STRUCTURED path: happy load plus every stable
  ``kind`` (schema mismatch, missing field, unknown field, vocab error, the
  unsupported-claim ``value_error``, and a type error).
* ``find_unsupported_claims`` / ``assert_transcript_supported`` — the
  TRANSCRIPT lint: an unsupported "tests passed" / "safe to merge" is flagged,
  the same claim with command/tool/CI evidence or an ``unverified`` hedge is
  not, and the raising counterpart fails on an unsupported claim.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sumo_qa.gate_evidence_models import GateReport
from sumo_qa.gate_evidence_validation import (
    GateEvidenceValidationError,
    UnsupportedClaim,
    assert_transcript_supported,
    find_unsupported_claims,
    load_gate_report,
)


def _report_dict(**claim_overrides) -> dict:
    claim = {
        "gate": "tests",
        "status": "passed",
        "statement": "The suite passed this turn.",
        "evidence": [{"source": "command", "detail": "$ uv run pytest -q -> 512 passed"}],
    }
    claim.update(claim_overrides)
    return {"schema_version": "1.0", "claims": [claim]}


# --- structured path -------------------------------------------------------


def test_load_valid_report_returns_model():
    report = load_gate_report(_report_dict())
    assert isinstance(report, GateReport)
    assert report.claims[0].gate == "tests"


def test_load_empty_report_is_valid():
    report = load_gate_report({"schema_version": "1.0", "claims": []})
    assert report.claims == []


def test_load_rejects_schema_version_mismatch():
    with pytest.raises(GateEvidenceValidationError) as excinfo:
        load_gate_report({"schema_version": "2.0", "claims": []})
    assert excinfo.value.kind == "schema_version_mismatch"
    assert excinfo.value.path == "/schema_version"


def test_load_rejects_non_string_schema_version_as_mismatch():
    with pytest.raises(GateEvidenceValidationError) as excinfo:
        load_gate_report({"schema_version": 2, "claims": []})
    assert excinfo.value.kind == "schema_version_mismatch"


def test_load_missing_schema_version_is_missing_field():
    with pytest.raises(GateEvidenceValidationError) as excinfo:
        load_gate_report({"claims": []})
    assert excinfo.value.kind == "missing_field"


def test_load_unknown_field_is_unknown_field():
    with pytest.raises(GateEvidenceValidationError) as excinfo:
        load_gate_report({"schema_version": "1.0", "claims": [], "rogue": True})
    assert excinfo.value.kind == "unknown_field"


def test_load_out_of_vocab_status_is_vocab_error():
    with pytest.raises(GateEvidenceValidationError) as excinfo:
        load_gate_report(_report_dict(status="probably_fine"))
    assert excinfo.value.kind == "vocab_error"


def test_load_unsupported_pass_claim_is_value_error():
    # The deterministic rejection the acceptance criteria require: a 'passed'
    # claim with no cited evidence fails to load.
    with pytest.raises(GateEvidenceValidationError) as excinfo:
        load_gate_report(_report_dict(status="passed", evidence=[]))
    assert excinfo.value.kind == "value_error"
    assert "cite at least one evidence item" in excinfo.value.message


def test_load_unverified_with_evidence_is_value_error():
    with pytest.raises(GateEvidenceValidationError) as excinfo:
        load_gate_report(_report_dict(status="unverified"))
    assert excinfo.value.kind == "value_error"


def test_load_wrong_type_is_type_error():
    with pytest.raises(GateEvidenceValidationError) as excinfo:
        load_gate_report({"schema_version": "1.0", "claims": "not-a-list"})
    assert excinfo.value.kind == "type_error"


def test_load_non_dict_list_is_type_error():
    # A non-dict parsed-JSON value must surface as the stable ``type_error``
    # kind, not a raw AttributeError from ``data.get``.
    with pytest.raises(GateEvidenceValidationError) as excinfo:
        load_gate_report([])
    assert excinfo.value.kind == "type_error"
    assert "dict" in excinfo.value.message


def test_load_non_dict_string_is_type_error():
    with pytest.raises(GateEvidenceValidationError) as excinfo:
        load_gate_report("not-a-report")
    assert excinfo.value.kind == "type_error"


def test_validation_error_str_includes_kind_and_path():
    err = GateEvidenceValidationError(kind="value_error", message="boom", path="/claims/0")
    assert "[value_error]" in str(err)
    assert "/claims/0" in str(err)


def test_validation_error_str_without_path():
    err = GateEvidenceValidationError(kind="unsupported_claim", message="boom")
    assert str(err) == "[unsupported_claim]: boom"


# --- transcript path -------------------------------------------------------


def test_unsupported_tests_passed_is_flagged():
    findings = find_unsupported_claims("All good — tests passed, safe to merge.")
    phrases = {f.phrase.lower() for f in findings}
    assert any("passed" in p for p in phrases)
    assert any("safe to merge" in p for p in phrases)
    assert all(isinstance(f, UnsupportedClaim) for f in findings)


def test_finding_carries_line_number():
    transcript = "Reviewed the diff.\nLooks fine.\ntests passed."
    findings = find_unsupported_claims(transcript)
    assert len(findings) == 1
    assert findings[0].line_number == 3
    assert "line 3" in findings[0].message


def test_claim_with_command_evidence_is_not_flagged():
    transcript = "$ uv run pytest -q\n512 passed, 0 failed in 4.2s\nTests passed — safe to merge."
    assert find_unsupported_claims(transcript) == []


def test_claim_with_count_evidence_is_not_flagged():
    assert find_unsupported_claims("128 passed. Safe to merge.") == []


def test_claim_with_tool_call_label_is_not_flagged():
    assert find_unsupported_claims("Ran the suite via tool_call. All tests passed.") == []


def test_claim_with_command_caption_is_not_flagged():
    assert find_unsupported_claims("Command: pytest -q\nTests passed.") == []


def test_unverified_hedge_on_same_line_suppresses_the_flag():
    # An honest 'unverified' hedge is not an overstatement.
    assert find_unsupported_claims("Tests passed status is unverified this turn.") == []


def test_unverified_hedge_on_another_line_does_not_suppress():
    # The hedge must sit on the claim's own line; a stray 'unverified' elsewhere
    # does not launder a bare pass claim (and there is no evidence signal here).
    transcript = "Some gate is unverified.\nBut tests passed anyway."
    findings = find_unsupported_claims(transcript)
    assert len(findings) == 1
    assert findings[0].line_number == 2


def test_no_pass_claim_no_findings():
    assert find_unsupported_claims("I read the diff and named three risks.") == []


def test_gate_passed_phrase_is_flagged():
    findings = find_unsupported_claims("The gate is passed.")
    assert len(findings) == 1


def test_assert_transcript_supported_raises_on_unsupported_claim():
    with pytest.raises(GateEvidenceValidationError) as excinfo:
        assert_transcript_supported("tests passed")
    assert excinfo.value.kind == "unsupported_claim"


def test_assert_transcript_supported_passes_with_evidence():
    # No exception raised.
    assert_transcript_supported("$ pytest\n10 passed\nTests passed.")


def test_unsupported_claim_model_forbids_extra():
    with pytest.raises(ValidationError):
        UnsupportedClaim(phrase="x", line_number=1, message="m", rogue=True)


# --- transcript path: negation (fix 1) -------------------------------------


def test_negated_safe_to_merge_is_not_flagged():
    # "safe to merge" also appears inside "NOT SAFE TO MERGE"; a negated verdict
    # is a blocked call with no evidence, not an unsupported PASS claim.
    assert find_unsupported_claims("Verdict: NOT SAFE TO MERGE.") == []


def test_plain_safe_to_merge_still_flagged():
    findings = find_unsupported_claims("Verdict: safe to merge.")
    assert len(findings) == 1
    assert "safe to merge" in findings[0].phrase.lower()


def test_negated_ready_to_release_is_not_flagged():
    # The same containment for "ready to release" inside "not ready to release".
    assert find_unsupported_claims("This is not ready to release.") == []


def test_negation_with_one_intervening_word_is_not_flagged():
    # "not yet <phrase>": a single intervening word between the negation and the
    # phrase still counts as negated.
    assert find_unsupported_claims("This is not yet ready to release.") == []


# --- transcript path: empty evidence label (fix 2) -------------------------


def test_bare_command_label_is_flagged():
    # A `Command:` with nothing after it names no observation, so it must not
    # satisfy the lint; the pass claim is flagged.
    findings = find_unsupported_claims("Command:\nSafe to merge.")
    assert len(findings) == 1


def test_command_label_with_content_is_not_flagged():
    transcript = "Command: $ uv run pytest -> 2570 passed\nSafe to merge."
    assert find_unsupported_claims(transcript) == []


# --- transcript path: added pass-claim phrasings (fix 3) -------------------


def test_merge_ready_unsupported_is_flagged():
    findings = find_unsupported_claims("The branch is merge-ready.")
    assert len(findings) == 1
    assert "merge-ready" in findings[0].phrase.lower()


def test_negated_merge_ready_is_not_flagged():
    assert find_unsupported_claims("The branch is not merge-ready.") == []


def test_shippable_unsupported_is_flagged():
    assert len(find_unsupported_claims("This is shippable.")) == 1


def test_shippable_with_evidence_is_not_flagged():
    assert find_unsupported_claims("128 passed. This is shippable.") == []


def test_ready_for_merge_unsupported_is_flagged():
    assert len(find_unsupported_claims("It is ready for merge.")) == 1


def test_green_for_merge_unsupported_is_flagged():
    assert len(find_unsupported_claims("All green for merge.")) == 1


def test_release_ready_unsupported_is_flagged():
    assert len(find_unsupported_claims("It is release-ready.")) == 1


def test_negated_release_ready_is_not_flagged():
    assert find_unsupported_claims("It is not release-ready.") == []
