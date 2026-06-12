# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Render-ready model for the local QA report artifact (issue #157).

The QA report is a *projection*: it composes the persisted ``.sumo-qa``
artifacts (repo-map #155, diff-impact #156, risk ledger #144, context bundle
#149) into one render-ready document. No inference lives here — the host LLM
(or the artifacts themselves) supplied every fact; this module only locks the
shape of the document.

Missing data is a first-class state, never an error: every consumable source
appears in the artifact inventory with an explicit status, so an absent
artifact renders "not available" instead of silently dropping out (the
issue's missing-data-is-not-passing-evidence acceptance criterion).

The readiness verdict is NOT derived here. It is derived by #151's
:class:`~sumo_qa.scorecard_models.QaScorecard` (the single source of truth)
from the risk ledger + context bundle, and mapped onto :class:`ReportReadiness`
by ``report_builder._readiness_from_scorecard``. ``ReadinessState`` is the
scorecard's four-state ``ScorecardRecommendation`` adopted verbatim, so the
report and the scorecard can never disagree.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sumo_qa.ledger_models import EvidenceStatus, ResidualDecision

REPORT_SCHEMA_VERSION: Final[Literal["1.0"]] = "1.0"

#: Every consumable source the issue names. The inventory always carries all
#: of them so an absent producer renders an explicit "not available" state.
ARTIFACT_KINDS: Final[tuple[str, ...]] = (
    "repo_map",
    "diff_impact",
    "risk_ledger",
    "context_bundle",
    "readiness_scorecard",
    "coverage_mutation",
)

ArtifactKind = Literal[
    "repo_map",
    "diff_impact",
    "risk_ledger",
    "context_bundle",
    "readiness_scorecard",
    "coverage_mutation",
]

#: ``missing`` (no producer ran), ``invalid`` (a file exists but cannot be
#: read), and ``stale`` (present but no longer reflecting HEAD) are DISTINCT
#: honest states — collapsing any of them into ``available`` would let absent
#: or outdated data masquerade as evidence.
ArtifactStatus = Literal["available", "missing", "invalid", "stale"]

#: The report's readiness verdict — adopted verbatim from #151's
#: ``ScorecardRecommendation`` so the report and the scorecard can never
#: disagree. The verdict itself is derived by ``QaScorecard`` (the single
#: source of truth); the report only maps it onto :class:`ReportReadiness`.
ReadinessState = Literal[
    "ready",
    "ready_with_accepted_residuals",
    "blocked",
    "insufficient_evidence",
]

#: Roll-up status of one evidence stream. The first four mirror the context
#: bundle's ``EvidenceResult``; ``missing`` means the stream was never
#: supplied at all (no bundle, or no coverage/mutation signals — #147 is
#: guidance, not a persisted artifact).
EvidenceStreamStatus = Literal["passing", "failing", "mixed", "not_run", "missing"]

EvidenceStreamFreshness = Literal["fresh", "stale", "unknown", "absent"]


class ReportProject(BaseModel):
    """Identity block of the report: which repo, when, by what generator."""

    model_config = ConfigDict(extra="forbid")

    root: str
    name: str | None = None
    head_commit: str | None = None
    generated_at: datetime
    generator_version: str

    @field_validator("generated_at")
    @classmethod
    def _require_aware_datetime(cls, value: datetime) -> datetime:
        # Freshness math (artifact age, staleness) is meaningless on a naive
        # datetime — mirror the repo-map model's timezone-aware requirement.
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value


class ReportArtifact(BaseModel):
    """One row of the artifact inventory: a consumable source and its state."""

    model_config = ConfigDict(extra="forbid")

    kind: ArtifactKind
    status: ArtifactStatus
    path: str | None = None
    detail: str | None = None
    generated_at: datetime | None = None
    age_days: int | None = None


class ReportComponent(BaseModel):
    """A changed/affected component projected from the diff-impact artifact.

    ``has_mapped_tests`` is tri-state (mirrors ``ImpactNode``): a real yes/no
    verdict only for ``source_file`` rows, None for every other type —
    rendered as an em-dash, never a vacuous "no".
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    path: str
    type: str
    has_mapped_tests: bool | None = None


class ReportPreviousRun(BaseModel):
    """Compact summary of the previous report run — the source of the page's
    run-over-run delta line. Persisted as ``.sumo-qa/qa-report-summary.json``
    by whatever writes the page; absent/corrupt summaries simply mean no
    delta."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    readiness_state: ReadinessState
    risk_count: int
    uncovered_blocker_count: int
    sources_available: int


class ReportRisk(BaseModel):
    """A risk-ledger row projected for rendering, with the derived blocker flag."""

    model_config = ConfigDict(extra="forbid")

    risk_id: str
    risk: str
    source_anchor: str
    test: str
    evidence_status: EvidenceStatus
    residual: ResidualDecision
    repo_map_node_id: str | None = None
    uncovered_blocker: bool


class ReportEvidence(BaseModel):
    """One evidence stream (tests, ci, coverage, mutation) with its trust verdict."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: EvidenceStreamStatus
    freshness: EvidenceStreamFreshness | None = None
    trustworthy: bool
    source: str | None = None
    captured_at: str | None = None
    detail: str | None = None


class ReportReadiness(BaseModel):
    """The derived readiness roll-up plus the reasons that produced it."""

    model_config = ConfigDict(extra="forbid")

    state: ReadinessState
    reasons: list[str] = Field(default_factory=list)


class QAReport(BaseModel):
    """The full render-ready QA report document."""

    model_config = ConfigDict(extra="forbid")

    # `schema_version` is required, not defaulted: a versioned artifact must
    # carry its version explicitly so a producer that forgot to stamp the
    # field can't sneak past validation (the ledger/repo-map pattern).
    schema_version: Literal["1.0"]
    project: ReportProject
    artifacts: list[ReportArtifact]
    changed_components: list[ReportComponent] = Field(default_factory=list)
    affected_components: list[ReportComponent] = Field(default_factory=list)
    related_tests: list[str] = Field(default_factory=list)
    unmapped_files: list[str] = Field(default_factory=list)
    risk_surface: list[str] = Field(default_factory=list)
    risks: list[ReportRisk] = Field(default_factory=list)
    uncovered_blocker_count: int = 0
    evidence: list[ReportEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    readiness: ReportReadiness
    previous_run: ReportPreviousRun | None = None
