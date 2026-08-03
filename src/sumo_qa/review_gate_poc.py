# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Isolated code-enforced review gate proof of concept for issue #557.

This module is intentionally not registered as an MCP tool and is not imported
by the production server.  It tests one boundary only: the model owns QA
judgment, while code validates the workflow/evidence envelope and refuses an
unsupported favourable verdict.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from sumo_qa.gate_evidence_models import GateClaim, GateReport
from sumo_qa.gate_evidence_validation import (
    GateEvidenceValidationError,
    assert_transcript_supported,
    load_gate_report,
)

REQUIRED_REVIEW_GATES = frozenset({"scope", "risks", "verification"})

_ENVELOPE_RE = re.compile(
    r"\A\s*<GATE_REPORT>\s*(?P<report>.*?)\s*</GATE_REPORT>\s*"
    r"<REVIEW>\s*(?P<review>.*?)\s*</REVIEW>\s*\Z",
    re.DOTALL,
)
_CODE_FENCE_RE = re.compile(
    r"\A\s*```(?:text|json)?\s*\n(?P<body>.*?)\n```\s*\Z",
    re.DOTALL,
)
_VERDICT_RE = re.compile(r"(?mi)^\s*Verdict:\s*(?P<verdict>NOT SAFE TO MERGE|SAFE TO MERGE)\b.*$")
# The two optional appendices the review contract allows after the verdict.
_APPENDIX_MARKER_RE = re.compile(
    r"(?i)\A\s*(?:#{1,6}\s+)?(?:readiness\s+scorecard|risk\s+ledger)\b"
)
_TABLE_ROW_RE = re.compile(r"\A\s*\|")
_AC_ROW_RE = re.compile(r"(?mi)^\s*AC(?P<number>\d+)\s*:")
_COVERAGE_NONE_RE = re.compile(r"(?mi)\bCoverage:\s*NONE\b")
_UNRESOLVED_FIELD_RE = re.compile(
    r"(?mi)\b(?:Classification|Coverage|Status):\s*(?P<value>UNMET|UNVERIFIED|UNCOVERED|UNPROVEN)\b"
)
_ABSENT_MEMORY_RE = re.compile(r"(?i)no saved review feedback supplied")
_PRESENT_MEMORY_RE = re.compile(r"(?i)advisory hint from saved review feedback")
_NOT_FIRED_RE = re.compile(r"(?i)\A.*External-contract axis:\s*NOT FIRED")


class ReviewGateValidationError(ValueError):
    """The model response cannot pass the deterministic review boundary."""


class ReviewFeedback(BaseModel):
    """Saved review feedback the host supplied for this diff."""

    model_config = ConfigDict(extra="forbid")

    trigger: str
    probe: str


class InventoryDrift(BaseModel):
    """A documented inventory path the host flagged as stale, and its correction."""

    model_config = ConfigDict(extra="forbid")

    path: str
    old: str
    new: str


class ReviewContext(BaseModel):
    """Host-supplied inputs the deterministic boundary checks the review against.

    The validator previously saw only the model's response, so every rule that
    depends on what the host actually supplied -- one row per acceptance
    criterion, one row per stale path, the memory present/absent branches --
    had to be bought as prompt prose.  Carrying the supplied context here is
    what lets those be checked in code instead.
    """

    model_config = ConfigDict(extra="forbid")

    acceptance_criteria: list[str] = Field(default_factory=list)
    inventory_drift: list[InventoryDrift] = Field(default_factory=list)
    external_producers: list[str] = Field(default_factory=list)
    saved_review_feedback: ReviewFeedback | None = None


@dataclass(frozen=True)
class ValidatedReview:
    """Validated model judgment with the hidden mechanics removed."""

    report: GateReport
    review: str
    safe_to_merge: bool
    context: ReviewContext | None = None


def _split_envelopes(response: str) -> tuple[object, str]:
    fenced = _CODE_FENCE_RE.fullmatch(response)
    envelope_text = fenced.group("body") if fenced is not None else response
    match = _ENVELOPE_RE.fullmatch(envelope_text)
    if match is None:
        raise ReviewGateValidationError(
            "response must contain exactly one GATE_REPORT and REVIEW envelope "
            "with no content outside the envelopes"
        )
    try:
        report_data: object = json.loads(match.group("report"))
    except json.JSONDecodeError as exc:
        raise ReviewGateValidationError(f"gate report is not valid JSON: {exc.msg}") from exc
    return report_data, match.group("review")


def _required_claims(report: GateReport) -> dict[str, GateClaim]:
    claims_by_gate: dict[str, GateClaim] = {}
    for claim in report.claims:
        if claim.gate in claims_by_gate:
            raise ReviewGateValidationError(f"duplicate gate claim: {claim.gate}")
        claims_by_gate[claim.gate] = claim
    missing = sorted(REQUIRED_REVIEW_GATES - claims_by_gate.keys())
    if missing:
        raise ReviewGateValidationError(f"missing required gate claim(s): {', '.join(missing)}")
    return claims_by_gate


def _verdict(review: str) -> bool:
    matches = list(_VERDICT_RE.finditer(review))
    if len(matches) != 1:
        raise ReviewGateValidationError(
            "review must contain exactly one verdict line: SAFE TO MERGE or NOT SAFE TO MERGE"
        )
    return matches[0].group("verdict") == "SAFE TO MERGE"


def _partition_appendices(lines: list[str]) -> tuple[list[str], list[str]]:
    """Split review lines into body lines and appended scorecard/ledger lines."""
    body: list[str] = []
    appendix: list[str] = []
    in_appendix = False
    for line in lines:
        if _APPENDIX_MARKER_RE.match(line):
            in_appendix = True
        elif in_appendix and line.strip() and not _TABLE_ROW_RE.match(line):
            # Prose resumed, so the appended block ended here.
            in_appendix = False
        (appendix if in_appendix else body).append(line)
    return body, appendix


def _normalise_appendix_order(review: str) -> str:
    """Move an appended scorecard/ledger below the verdict line.

    The review contract requires the literal verdict line to precede the
    scorecard heading and the risk-ledger table.  That is presentation order,
    not judgment, so the boundary repairs it rather than spending prompt tokens
    instructing it.  Every model-authored line survives verbatim; only the
    order of the blocks changes, and a review already in contract order is
    returned untouched.
    """
    lines = review.splitlines()
    first_marker = next(
        (index for index, line in enumerate(lines) if _APPENDIX_MARKER_RE.match(line)),
        None,
    )
    if first_marker is None:
        return review
    verdict_index = next(
        (index for index, line in enumerate(lines) if _VERDICT_RE.match(line)),
        None,
    )
    if verdict_index is None or verdict_index < first_marker:
        return review

    body, appendix = _partition_appendices(lines)
    return "\n".join(body + appendix)


def _check_coverage_status(review: str) -> None:
    """``NONE`` names no coverage outcome, so it cannot stand in for one."""
    if _COVERAGE_NONE_RE.search(review) is not None:
        raise ReviewGateValidationError(
            "'NONE' is not a coverage status; use 'UNCOVERED' when no matching test "
            "ran, or 'UNPROVEN' when one ran without a discriminating assertion"
        )


def _check_no_unresolved_field(review: str) -> None:
    """A favourable verdict cannot coexist with an unresolved classification."""
    match = _UNRESOLVED_FIELD_RE.search(review)
    if match is not None:
        raise ReviewGateValidationError(
            f"SAFE TO MERGE is blocked by an unresolved field: {match.group('value')}"
        )


def _check_acceptance_criteria(review: str, criteria: list[str]) -> None:
    """One row per supplied criterion, and none the host did not supply."""
    emitted = {int(match.group("number")) for match in _AC_ROW_RE.finditer(review)}
    expected = set(range(1, len(criteria) + 1))
    missing = sorted(expected - emitted)
    if missing:
        raise ReviewGateValidationError(
            "missing a row for supplied acceptance criterion/criteria: "
            + ", ".join(f"AC{number}" for number in missing)
        )
    invented = sorted(emitted - expected)
    if invented:
        raise ReviewGateValidationError(
            "acceptance criterion row(s) the host did not supply: "
            + ", ".join(f"AC{number}" for number in invented)
        )


def _check_inventory_drift(review: str, drift: list[InventoryDrift]) -> None:
    """Each supplied stale path needs a row copying its pair verbatim."""
    lines = review.splitlines()
    for entry in drift:
        pair = f"{entry.old} → {entry.new}"
        if not any(entry.path in line and pair in line for line in lines):
            raise ReviewGateValidationError(
                f"inventory drift row for {entry.path!r} must copy the supplied pair "
                f"verbatim: {pair!r}"
            )


def _check_review_feedback(review: str, feedback: ReviewFeedback | None) -> None:
    """The present and absent memory branches are mutually exclusive."""
    if feedback is not None and _ABSENT_MEMORY_RE.search(review) is not None:
        raise ReviewGateValidationError(
            "saved review feedback was supplied, so the absent-memory line must not be emitted"
        )
    if feedback is None and _PRESENT_MEMORY_RE.search(review) is not None:
        raise ReviewGateValidationError(
            "no saved review feedback was supplied, so the advisory-hint line must not be emitted"
        )


def _check_producers(review: str, producers: list[str]) -> None:
    """A named tool/CLI producer is external, so it cannot be declined as internal."""
    for line in review.splitlines():
        if _NOT_FIRED_RE.match(line) is None:
            continue
        for producer in producers:
            if producer.lower() in line.lower():
                raise ReviewGateValidationError(
                    f"external producer {producer!r} cannot be declined as internal/self-produced"
                )


def validate_review_response(
    response: str,
    *,
    context: ReviewContext | None = None,
) -> ValidatedReview:
    """Validate mechanics while preserving the model-authored review.

    The function does not classify the change, identify risks, choose a test
    technique, set test depth, or produce a verdict.  It accepts those model
    judgments and enforces only the surrounding contract:

    * a typed evidence report exists;
    * the mandatory workflow stages are represented exactly once;
    * a favourable verdict is impossible unless every mandatory stage passed
      and no additional gate is unresolved;
    * pass/safe prose cites an observable evidence source; and
    * an appended scorecard/ledger sits below the verdict line, repaired
      deterministically rather than instructed in the prompt.

    ``context`` carries what the host supplied for this review so completeness
    rules can be checked in code instead of prose.
    """

    report_data, review = _split_envelopes(response)
    try:
        report = load_gate_report(report_data)
    except GateEvidenceValidationError as exc:
        raise ReviewGateValidationError(str(exc)) from exc

    claims = _required_claims(report)
    safe_to_merge = _verdict(review)
    review = _normalise_appendix_order(review)
    if safe_to_merge:
        unresolved_required = sorted(
            gate for gate in REQUIRED_REVIEW_GATES if claims[gate].status != "passed"
        )
        unresolved_any = sorted(claim.gate for claim in report.unresolved_gates())
        unresolved = sorted(set(unresolved_required + unresolved_any))
        if unresolved:
            raise ReviewGateValidationError(
                "SAFE TO MERGE is blocked by unresolved gate(s): " + ", ".join(unresolved)
            )

    _check_coverage_status(review)
    if safe_to_merge:
        _check_no_unresolved_field(review)
    if context is not None:
        _check_acceptance_criteria(review, context.acceptance_criteria)
        _check_inventory_drift(review, context.inventory_drift)
        _check_review_feedback(review, context.saved_review_feedback)
        _check_producers(review, context.external_producers)

    try:
        assert_transcript_supported(review)
    except GateEvidenceValidationError as exc:
        raise ReviewGateValidationError(str(exc)) from exc

    return ValidatedReview(
        report=report,
        review=review,
        safe_to_merge=safe_to_merge,
        context=context,
    )
