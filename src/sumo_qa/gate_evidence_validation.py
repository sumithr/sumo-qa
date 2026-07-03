# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Validators for gate-evidence claims (issue #213).

Two entry points, matching the issue's "transcript snippets OR structured
evidence blocks":

* :func:`load_gate_report` — the STRUCTURED path. A parsed dict is validated
  against :class:`~sumo_qa.gate_evidence_models.GateReport`; an unsupported
  ``passed`` / ``failed`` / ``blocked`` claim (one with no cited evidence)
  raises :class:`GateEvidenceValidationError` with ``kind="value_error"`` — the
  deterministic rejection the acceptance criteria require. Every failure mode
  carries a stable ``kind`` so callers branch on the category rather than
  parsing free-form messages (the same contract the ledger-validation envelope
  provides).

* :func:`find_unsupported_claims` / :func:`assert_transcript_supported` — the
  TRANSCRIPT path: a lint-grade guard over free-text output. It flags a
  pass/safe phrase ("tests passed", "safe to merge", …) that appears with NO
  evidence signal anywhere in the snippet and no ``unverified`` hedge on its
  own line. It is deliberately COARSE (whole-snippet evidence signal, not
  per-sentence provenance) — a lint, not a proof, because a probabilistic
  transcript can't be parsed to a proof. The structured path above is the
  rigorous one; this catches the blatant "tests passed" with zero evidence.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ValidationError

from sumo_qa.gate_evidence_models import GATE_EVIDENCE_SCHEMA_VERSION, GateReport

GateEvidenceValidationErrorKind = Literal[
    "schema_version_mismatch",
    "missing_field",
    "unknown_field",
    "vocab_error",
    "value_error",
    "type_error",
    "unsupported_claim",
]


class GateEvidenceValidationError(ValueError):
    def __init__(
        self,
        *,
        kind: GateEvidenceValidationErrorKind,
        message: str,
        path: str | None = None,
    ) -> None:
        self.kind = kind
        self.message = message
        self.path = path
        location = f" at {path}" if path else ""
        super().__init__(f"[{kind}]{location}: {message}")


def load_gate_report(data: dict) -> GateReport:
    """Load and validate a structured gate report from a parsed dict.

    An unsupported pass/fail/blocked claim surfaces as ``kind="value_error"``
    (the model's evidence-requirement validator), distinct from a wrong-vocab
    status (``vocab_error``) or a stale schema version.
    """
    version = data.get("schema_version")
    # Any present-but-non-matching schema_version (string or not) is a version
    # mismatch; routing a non-string through Pydantic would surface a confusing
    # literal error instead of the clear "your artifact says X, expects Y"
    # signal. A missing version (None) falls through so Pydantic reports it as a
    # missing field.
    if version is not None and version != GATE_EVIDENCE_SCHEMA_VERSION:
        raise GateEvidenceValidationError(
            kind="schema_version_mismatch",
            message=(
                f"gate report schema_version is {version!r}; this build expects "
                f"{GATE_EVIDENCE_SCHEMA_VERSION!r}"
            ),
            path="/schema_version",
        )
    try:
        return GateReport.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = "/".join(str(p) for p in first["loc"])
        raise GateEvidenceValidationError(
            kind=_classify(first["type"]),
            message=first["msg"],
            path=location,
        ) from exc


def _classify(error_type: str) -> GateEvidenceValidationErrorKind:
    if error_type == "missing":
        return "missing_field"
    if error_type == "extra_forbidden":
        return "unknown_field"
    if error_type == "literal_error":
        return "vocab_error"
    if error_type == "value_error":
        return "value_error"
    return "type_error"


# --- Transcript (lint-grade) path -----------------------------------------

# Pass/safe phrases that assert a favourable execution outcome. Kept to the
# claim shapes the issue names ("tests passed", "safe to merge") plus their
# common paraphrases; deliberately narrow to avoid flagging neutral prose.
_PASS_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\ball tests?\s+(?:pass|passed|passing|green)\b", re.IGNORECASE),
    re.compile(r"\btests?\s+(?:all\s+)?(?:pass|passed|passing)\b", re.IGNORECASE),
    re.compile(r"\bsafe\s+to\s+merge\b", re.IGNORECASE),
    re.compile(r"\b(?:good|ready|safe)\s+to\s+(?:merge|ship|release)\b", re.IGNORECASE),
    re.compile(r"\bgate\s+(?:is\s+)?(?:passed|green|clear)\b", re.IGNORECASE),
)

# Signals that the snippet carries observed evidence. Any one present makes the
# lint pass (documented coarseness). A shell prompt, a pytest-style count line,
# an explicit tool-call / evidence-source label, or a `Command:` caption.
_EVIDENCE_SIGNAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?m)^\s*\$\s+\S"),  # a shell command line
    re.compile(r"\b\d+\s+passed\b", re.IGNORECASE),  # pytest/jest count line
    re.compile(r"\b\d+\s+failed\b", re.IGNORECASE),
    re.compile(r"\bcommand\s*:", re.IGNORECASE),  # a captioned command
    re.compile(
        r"\b(?:tool[_ ]call|file[_ ]read|external[_ ]ci|manual[_ ]observation|user[_ ]fact)\b",
        re.IGNORECASE,
    ),
)

_UNVERIFIED_HEDGE = re.compile(r"\bunverified\b", re.IGNORECASE)


class UnsupportedClaim(BaseModel):
    """One pass/safe phrase found with no backing evidence in the snippet."""

    model_config = {"extra": "forbid"}

    phrase: str
    line_number: int
    message: str


def _line_containing(text: str, index: int) -> tuple[int, str]:
    """Return the 1-based line number and text of the line containing ``index``."""
    line_number = text.count("\n", 0, index) + 1
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    if end == -1:
        end = len(text)
    return line_number, text[start:end]


def find_unsupported_claims(transcript: str) -> list[UnsupportedClaim]:
    """Flag pass/safe claims that cite no evidence and carry no ``unverified`` hedge.

    Returns an empty list when the snippet either makes no pass/safe claim or
    carries any evidence signal. Otherwise one :class:`UnsupportedClaim` per
    unhedged pass/safe phrase.
    """
    if any(signal.search(transcript) for signal in _EVIDENCE_SIGNAL_PATTERNS):
        return []
    findings: list[UnsupportedClaim] = []
    for pattern in _PASS_CLAIM_PATTERNS:
        for match in pattern.finditer(transcript):
            line_number, line_text = _line_containing(transcript, match.start())
            # A claim explicitly hedged as unverified on its own line is honest,
            # not an overstatement — leave it alone.
            if _UNVERIFIED_HEDGE.search(line_text):
                continue
            phrase = match.group(0)
            findings.append(
                UnsupportedClaim(
                    phrase=phrase,
                    line_number=line_number,
                    message=(
                        f"unsupported claim {phrase!r} on line {line_number}: no command / "
                        "tool_call / file_read (or other evidence source) is cited, and the "
                        "claim is not marked 'unverified'"
                    ),
                )
            )
    return findings


def assert_transcript_supported(transcript: str) -> None:
    """Raise :class:`GateEvidenceValidationError` if the snippet has an unsupported claim.

    The raising counterpart to :func:`find_unsupported_claims`, for callers /
    tests that want a hard failure on an unsupported "tests passed" / "safe to
    merge" claim.
    """
    findings = find_unsupported_claims(transcript)
    if findings:
        raise GateEvidenceValidationError(
            kind="unsupported_claim",
            message="; ".join(f.message for f in findings),
        )
