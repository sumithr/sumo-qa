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


class ReviewGateValidationError(ValueError):
    """The model response cannot pass the deterministic review boundary."""


@dataclass(frozen=True)
class ValidatedReview:
    """Validated model judgment with the hidden mechanics removed."""

    report: GateReport
    review: str
    safe_to_merge: bool


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


def validate_review_response(response: str) -> ValidatedReview:
    """Validate mechanics while preserving the model-authored review verbatim.

    The function does not classify the change, identify risks, choose a test
    technique, set test depth, or produce a verdict.  It accepts those model
    judgments and enforces only the surrounding contract:

    * a typed evidence report exists;
    * the mandatory workflow stages are represented exactly once;
    * a favourable verdict is impossible unless every mandatory stage passed
      and no additional gate is unresolved; and
    * pass/safe prose cites an observable evidence source.
    """

    report_data, review = _split_envelopes(response)
    try:
        report = load_gate_report(report_data)
    except GateEvidenceValidationError as exc:
        raise ReviewGateValidationError(str(exc)) from exc

    claims = _required_claims(report)
    safe_to_merge = _verdict(review)
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

    try:
        assert_transcript_supported(review)
    except GateEvidenceValidationError as exc:
        raise ReviewGateValidationError(str(exc)) from exc

    return ValidatedReview(report=report, review=review, safe_to_merge=safe_to_merge)
