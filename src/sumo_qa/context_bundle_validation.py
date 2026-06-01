# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Load + validation envelope for a context-bundle payload (issue #149).

``load_context_bundle`` accepts an already-parsed dict and returns a validated
:class:`ContextBundle`. Every failure mode raises
:class:`ContextBundleValidationError` with a stable ``kind`` so the MCP wrapper
(and any other caller) can branch on the category rather than parsing free-form
messages — the same contract the risk-ledger and repo-map validation envelopes
provide.

A *partial* bundle is NOT an error: every field except ``schema_version`` is
optional, so an empty-but-stamped bundle loads cleanly. Only genuine shape
problems (wrong version, unknown field, bad enum value, wrong type) raise. This
keeps "absent / partial bundle" a first-class, non-failing path — the consuming
skill falls back to direct repo inspection rather than choking on a thin bundle.

``schema_version_mismatch`` is surfaced before Pydantic sees the payload so a
stale bundle gives a clear "your payload says 2.0, this build expects 1.0"
message instead of a generic literal-type error. ``vocab_error`` distinguishes
an out-of-catalogue enum value (a freshness/source/result typo) from a
wrong-type mistake.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationError

from sumo_qa.context_bundle_models import CONTEXT_BUNDLE_SCHEMA_VERSION, ContextBundle

ContextBundleValidationErrorKind = Literal[
    "schema_version_mismatch",
    "missing_field",
    "unknown_field",
    "vocab_error",
    "value_error",
    "type_error",
]


class ContextBundleValidationError(ValueError):
    def __init__(
        self,
        *,
        kind: ContextBundleValidationErrorKind,
        message: str,
        path: str | None = None,
    ) -> None:
        self.kind = kind
        self.message = message
        self.path = path
        location = f" at {path}" if path else ""
        super().__init__(f"[{kind}]{location}: {message}")


def load_context_bundle(data: dict) -> ContextBundle:
    """Load and validate a context bundle from a parsed dict.

    A partial/empty bundle (everything but ``schema_version`` omitted) is valid.
    """
    version = data.get("schema_version")
    # Any present-but-non-matching schema_version — string OR not (e.g. an int 2)
    # — is a version mismatch. Routing a non-string through Pydantic would surface
    # a confusing literal/vocab error instead of the clear "your artifact says X,
    # this build expects Y" signal. A missing schema_version (None) still falls
    # through so Pydantic reports it as a missing field.
    if version is not None and version != CONTEXT_BUNDLE_SCHEMA_VERSION:
        raise ContextBundleValidationError(
            kind="schema_version_mismatch",
            message=(
                f"context bundle schema_version is {version!r}; this build expects "
                f"{CONTEXT_BUNDLE_SCHEMA_VERSION!r}"
            ),
            path="/schema_version",
        )
    try:
        return ContextBundle.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = "/".join(str(p) for p in first["loc"])
        raise ContextBundleValidationError(
            kind=_classify(first["type"]),
            message=first["msg"],
            path=location,
        ) from exc


def _classify(error_type: str) -> ContextBundleValidationErrorKind:
    if error_type == "missing":
        return "missing_field"
    if error_type == "extra_forbidden":
        return "unknown_field"
    if error_type == "literal_error":
        return "vocab_error"
    if error_type == "value_error":
        return "value_error"
    return "type_error"
