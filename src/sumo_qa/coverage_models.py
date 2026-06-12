# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Persisted coverage/mutation artifact shapes + validation (issue #147 follow-up).

These artifacts are the persisted producer the local QA report lacked. #147
shipped coverage/mutation as host-read guidance with no persisted producer, so
``report_builder`` had to hardcode ``coverage=None, mutation=None`` and the
report always rendered ``coverage_mutation: missing``. Here a host skill runs the
repo's coverage/mutation tools, the LLM collects the results in ANY format, and
these models lock the canonical shape written to ``.sumo-qa/coverage.json`` /
``.sumo-qa/mutation.json``.

No inference lives here: the host supplies every field. Each artifact wraps
provenance (``generated_at``, ``source_tool``) around the measurement fields and
maps via :meth:`to_signal` onto the existing :class:`CoverageSignal` /
:class:`MutationSignal` the readiness scorecard already consumes — so coverage
stays *reported, never gated*.

The validation envelope mirrors ``ledger_validation.load_ledger``: every failure
raises a ``ValueError`` subclass carrying a stable ``kind`` so the MCP wrapper
can branch on the category instead of parsing free-form messages. A present-but-
mismatched ``schema_version`` (string OR not) is surfaced before Pydantic sees
the payload, giving a clear "your artifact says X, this build expects Y" signal.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sumo_qa.scorecard_models import CoverageSignal, EvidenceFreshness, MutationSignal

COVERAGE_SCHEMA_VERSION: Final[Literal["1.0"]] = "1.0"

ArtifactErrorKind = Literal[
    "schema_version_mismatch",
    "missing_field",
    "unknown_field",
    "vocab_error",
    "value_error",
    "type_error",
]


class _ArtifactError(ValueError):
    """Shared base for the coverage/mutation validation errors."""

    def __init__(
        self,
        *,
        kind: ArtifactErrorKind,
        message: str,
        path: str | None = None,
    ) -> None:
        self.kind = kind
        self.message = message
        self.path = path
        location = f" at {path}" if path else ""
        super().__init__(f"[{kind}]{location}: {message}")


class CoverageArtifactError(_ArtifactError):
    pass


class MutationArtifactError(_ArtifactError):
    pass


class CoverageArtifact(BaseModel):
    """The persisted ``.sumo-qa/coverage.json`` shape (provenance + signal)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = COVERAGE_SCHEMA_VERSION
    generated_at: str = Field(description="ISO-8601 timestamp the host stamped at collection.")
    source_tool: str = Field(description="The tool the host ran (e.g. 'pytest-cov (coverage.py)').")
    line_percent: float | None = Field(
        default=None, description="Optional line-coverage percentage in [0, 100]."
    )
    freshness: EvidenceFreshness = Field(
        default="unknown",
        description="Freshness of the signal; only a fresh measurement is safety-supporting.",
    )
    detail: str | None = Field(
        default=None,
        description="Optional compact note — e.g. uncovered changed files/functions.",
    )

    @field_validator("line_percent")
    @classmethod
    def _percent_in_range(cls, value: float | None) -> float | None:
        if value is not None and not (0.0 <= value <= 100.0):
            raise ValueError("line_percent must be between 0 and 100")
        return value

    def to_signal(self) -> CoverageSignal:
        """Map onto the scorecard's coverage signal (drops provenance)."""
        return CoverageSignal(
            line_percent=self.line_percent,
            freshness=self.freshness,
            detail=self.detail,
        )


class MutationArtifact(BaseModel):
    """The persisted ``.sumo-qa/mutation.json`` shape (provenance + signal)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = COVERAGE_SCHEMA_VERSION
    generated_at: str = Field(description="ISO-8601 timestamp the host stamped at collection.")
    source_tool: str = Field(description="The tool the host ran (e.g. 'mutmut', 'Stryker').")
    survivors: int | None = Field(
        default=None, description="Optional count of surviving mutants (>= 0)."
    )
    killed: int | None = Field(default=None, description="Optional count of killed mutants (>= 0).")
    freshness: EvidenceFreshness = Field(
        default="unknown",
        description="Freshness of the signal; only a fresh measurement is safety-supporting.",
    )
    detail: str | None = Field(
        default=None, description="Optional compact note — e.g. where survivors live."
    )

    @field_validator("survivors", "killed")
    @classmethod
    def _non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("mutant counts must be non-negative")
        return value

    def to_signal(self) -> MutationSignal:
        """Map onto the scorecard's mutation signal (drops provenance)."""
        return MutationSignal(
            survivors=self.survivors,
            killed=self.killed,
            freshness=self.freshness,
            detail=self.detail,
        )


def _classify(error_type: str) -> ArtifactErrorKind:
    if error_type == "missing":
        return "missing_field"
    if error_type == "extra_forbidden":
        return "unknown_field"
    if error_type == "literal_error":
        return "vocab_error"
    if error_type == "value_error":
        return "value_error"
    return "type_error"


def _load(
    data: dict,
    model: type[CoverageArtifact] | type[MutationArtifact],
    error: type[_ArtifactError],
) -> CoverageArtifact | MutationArtifact:
    version = data.get("schema_version")
    # Any present-but-non-matching schema_version (string or not) is a mismatch;
    # routing a non-string through Pydantic would surface a confusing
    # literal/type error instead of the clear version signal. A missing
    # schema_version (None) falls through so Pydantic reports the default-filled
    # model — the field has a default, so absence is valid.
    if version is not None and version != COVERAGE_SCHEMA_VERSION:
        raise error(
            kind="schema_version_mismatch",
            message=(
                f"schema_version is {version!r}; this build expects {COVERAGE_SCHEMA_VERSION!r}"
            ),
            path="/schema_version",
        )
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = "/".join(str(p) for p in first["loc"])
        raise error(
            kind=_classify(first["type"]),
            message=first["msg"],
            path=location,
        ) from exc


def load_coverage_artifact(data: dict) -> CoverageArtifact:
    """Load + validate a coverage artifact from a parsed dict."""
    result = _load(data, CoverageArtifact, CoverageArtifactError)
    assert isinstance(result, CoverageArtifact)  # narrow for type-checkers
    return result


def load_mutation_artifact(data: dict) -> MutationArtifact:
    """Load + validate a mutation artifact from a parsed dict."""
    result = _load(data, MutationArtifact, MutationArtifactError)
    assert isinstance(result, MutationArtifact)  # narrow for type-checkers
    return result
