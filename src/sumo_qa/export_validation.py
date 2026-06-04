# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Load + validation envelope for a QA-test-case export payload (issue #148).

``load_test_case_export`` accepts an already-parsed dict and returns a validated
:class:`QaTestCaseExport`. Every failure mode raises
:class:`ExportValidationError` with a stable ``kind`` so the MCP wrapper (and any
other caller) can branch on the category rather than parsing free-form messages —
the same contract the risk-ledger and context-bundle validation envelopes provide.

``schema_version_mismatch`` is surfaced before Pydantic sees the payload so a
stale export gives a clear "your payload says 2.0, this build expects 1.0"
message instead of a generic literal-type error. ``vocab_error`` distinguishes an
out-of-catalogue enum value (a priority / evidence-status typo) from a wrong-type
mistake. ``value_error`` covers the duplicate-id and non-blank model validators,
whose messages are the actionable signal the caller wants verbatim.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationError

from sumo_qa.export_models import EXPORT_SCHEMA_VERSION, QaTestCaseExport

ExportValidationErrorKind = Literal[
    "schema_version_mismatch",
    "missing_field",
    "unknown_field",
    "vocab_error",
    "value_error",
    "type_error",
]


class ExportValidationError(ValueError):
    def __init__(
        self,
        *,
        kind: ExportValidationErrorKind,
        message: str,
        path: str | None = None,
    ) -> None:
        self.kind = kind
        self.message = message
        self.path = path
        location = f" at {path}" if path else ""
        super().__init__(f"[{kind}]{location}: {message}")


def load_test_case_export(data: dict) -> QaTestCaseExport:
    """Load and validate a QA-test-case export from a parsed dict."""
    version = data.get("schema_version")
    # Any present-but-non-matching schema_version — string OR not (e.g. an int 2)
    # — is a version mismatch. Routing a non-string through Pydantic would surface
    # a confusing literal/vocab error instead of the clear "your artifact says X,
    # this build expects Y" signal. A missing schema_version (None) still falls
    # through so Pydantic reports it as a missing field.
    if version is not None and version != EXPORT_SCHEMA_VERSION:
        raise ExportValidationError(
            kind="schema_version_mismatch",
            message=(
                f"export schema_version is {version!r}; this build expects "
                f"{EXPORT_SCHEMA_VERSION!r}"
            ),
            path="/schema_version",
        )
    try:
        return QaTestCaseExport.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = "/".join(str(p) for p in first["loc"])
        raise ExportValidationError(
            kind=_classify(first["type"]),
            message=first["msg"],
            path=location,
        ) from exc


def _classify(error_type: str) -> ExportValidationErrorKind:
    if error_type == "missing":
        return "missing_field"
    if error_type == "extra_forbidden":
        return "unknown_field"
    if error_type == "literal_error":
        return "vocab_error"
    if error_type == "value_error":
        return "value_error"
    return "type_error"
