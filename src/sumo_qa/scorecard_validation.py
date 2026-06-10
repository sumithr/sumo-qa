# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Load + validation envelope for a QA readiness scorecard payload (issue #151).

``load_scorecard`` composes an already-parsed scorecard from its parts. It does
NOT re-define the risk-ledger or context-bundle schema — it delegates to the
existing #144 ``load_ledger`` and #149 ``load_context_bundle`` loaders, so those
artifacts validate exactly as they do on their own and their typed errors
propagate unchanged. Only the scorecard-native coverage/mutation signals are
validated here, raising :class:`ScorecardValidationError` with a stable ``kind``
so the MCP wrapper can branch on the category — the same contract the ledger and
context-bundle envelopes provide.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from sumo_qa.context_bundle_validation import load_context_bundle
from sumo_qa.ledger_models import LEDGER_SCHEMA_VERSION
from sumo_qa.ledger_validation import load_ledger
from sumo_qa.scorecard_models import CoverageSignal, MutationSignal, QaScorecard

# Note the kinds are a subset of the ledger/context-bundle envelopes': the
# coverage/mutation signals this envelope validates have NO required fields, so a
# Pydantic "missing" error is unreachable here. Keeping a dead ``missing_field``
# branch would be a permanent coverage gap, so it is deliberately absent.
ScorecardValidationErrorKind = Literal[
    "unknown_field",
    "vocab_error",
    "value_error",
    "type_error",
]


class ScorecardValidationError(ValueError):
    def __init__(
        self,
        *,
        kind: ScorecardValidationErrorKind,
        message: str,
        path: str | None = None,
    ) -> None:
        self.kind = kind
        self.message = message
        self.path = path
        location = f" at {path}" if path else ""
        super().__init__(f"[{kind}]{location}: {message}")


def load_scorecard(
    *,
    ledger_rows: list[dict[str, Any]] | None = None,
    context_bundle: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
    mutation: dict[str, Any] | None = None,
    scope: str | None = None,
) -> QaScorecard:
    """Validate the scorecard's parts and compose a :class:`QaScorecard`.

    Each part is optional — an all-``None`` payload composes a valid (if
    minimally useful) scorecard that derives ``insufficient_evidence``. The
    ledger and context-bundle parts are validated by their own loaders (their
    ``LedgerValidationError`` / ``ContextBundleValidationError`` propagate
    verbatim); the coverage/mutation signals are validated here.
    """
    ledger = None
    if ledger_rows is not None:
        ledger = load_ledger({"schema_version": LEDGER_SCHEMA_VERSION, "rows": ledger_rows})

    bundle = None
    if context_bundle is not None:
        bundle = load_context_bundle(context_bundle)

    cov = _load_signal(coverage, CoverageSignal, "coverage")
    mut = _load_signal(mutation, MutationSignal, "mutation")

    return QaScorecard(
        scope=scope,
        ledger=ledger,
        context_bundle=bundle,
        coverage=cov,
        mutation=mut,
    )


def _load_signal(
    data: dict[str, Any] | None,
    model_cls: type[BaseModel],
    field_name: str,
) -> Any:
    if data is None:
        return None
    try:
        return model_cls.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = "/".join([field_name, *(str(p) for p in first["loc"])])
        raise ScorecardValidationError(
            kind=_classify(first["type"]),
            message=first["msg"],
            path=location,
        ) from exc


def _classify(error_type: str) -> ScorecardValidationErrorKind:
    if error_type == "extra_forbidden":
        return "unknown_field"
    if error_type == "literal_error":
        return "vocab_error"
    if error_type == "value_error":
        return "value_error"
    return "type_error"
