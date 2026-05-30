# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Load + validation envelope for a risk-to-test ledger payload (issue #144).

``load_ledger`` accepts an already-parsed dict and returns a validated
:class:`RiskLedger`. Every failure mode raises :class:`LedgerValidationError`
with a stable ``kind`` so the MCP wrapper (and any other caller) can branch on
the category rather than parsing free-form messages — the same contract the
repo-map validation envelope provides.

``schema_version_mismatch`` is surfaced before Pydantic sees the payload so a
stale ledger gives a clear "your payload says 2.0, this build expects 1.0"
message instead of a generic literal-type error. ``vocab_error`` distinguishes
an out-of-catalogue enum value (an evidence-status typo) from a wrong-type
mistake. ``value_error`` covers the duplicate-risk-id model validator, whose
message is the actionable signal the caller wants verbatim.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationError

from sumo_qa.ledger_models import LEDGER_SCHEMA_VERSION, RiskLedger

LedgerValidationErrorKind = Literal[
    "schema_version_mismatch",
    "missing_field",
    "unknown_field",
    "vocab_error",
    "value_error",
    "type_error",
]


class LedgerValidationError(ValueError):
    def __init__(
        self,
        *,
        kind: LedgerValidationErrorKind,
        message: str,
        path: str | None = None,
    ) -> None:
        self.kind = kind
        self.message = message
        self.path = path
        location = f" at {path}" if path else ""
        super().__init__(f"[{kind}]{location}: {message}")


def load_ledger(data: dict) -> RiskLedger:
    """Load and validate a risk-to-test ledger from a parsed dict."""
    version = data.get("schema_version")
    if isinstance(version, str) and version != LEDGER_SCHEMA_VERSION:
        raise LedgerValidationError(
            kind="schema_version_mismatch",
            message=(
                f"ledger schema_version is {version!r}; this build expects "
                f"{LEDGER_SCHEMA_VERSION!r}"
            ),
            path="/schema_version",
        )
    try:
        return RiskLedger.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = "/".join(str(p) for p in first["loc"])
        raise LedgerValidationError(
            kind=_classify(first["type"]),
            message=first["msg"],
            path=location,
        ) from exc


def _classify(error_type: str) -> LedgerValidationErrorKind:
    if error_type == "missing":
        return "missing_field"
    if error_type == "extra_forbidden":
        return "unknown_field"
    if error_type == "literal_error":
        return "vocab_error"
    if error_type == "value_error":
        return "value_error"
    return "type_error"
