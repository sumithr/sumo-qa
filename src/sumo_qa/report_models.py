# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Render-ready model for the local QA report artifact (issue #157).

The QA report is a *projection*: it composes the persisted ``.sumo-qa``
artifacts (repo-map #155, diff-impact #156, risk ledger #144, context bundle
#149) into one render-ready document. No inference lives here — the host LLM
(or the artifacts themselves) supplied every fact; this module only locks the
shape and derives the one piece of deterministic logic the report owns:
the readiness roll-up.

Missing data is a first-class state, never an error: every consumable source
appears in the artifact inventory with an explicit status, so an absent
artifact renders "not available" instead of silently dropping out (the
issue's missing-data-is-not-passing-evidence acceptance criterion).

``derive_readiness`` is an ordered decision table — most severe state first:

1. ``blocked``               — an uncovered blocker risk, a failing risk row,
                               or failing/mixed evidence.
2. ``stale_evidence``        — a stale artifact, a stale risk row, or stale
                               evidence (re-verify before trusting anything).
3. ``incomplete``            — a core artifact missing/invalid, a planned-only
                               risk row, an empty risk ledger, or core
                               evidence that never ran.
4. ``ready_with_residuals``  — green, but with accepted residuals or
                               not-yet-mitigated residual decisions on record.
5. ``ready``                 — everything green.

The ordering is load-bearing: a blocker plus stale evidence must read
``blocked`` (the more severe state wins), and stale-but-present data must
read ``stale_evidence`` rather than ``incomplete`` (re-verify outranks
gather-more-data).
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

ReadinessState = Literal[
    "ready",
    "ready_with_residuals",
    "stale_evidence",
    "blocked",
    "incomplete",
]

#: Roll-up status of one evidence stream. The first four mirror the context
#: bundle's ``EvidenceResult``; ``missing`` means the stream was never
#: supplied at all (no bundle, or no producer yet for coverage/mutation).
EvidenceStreamStatus = Literal["passing", "failing", "mixed", "not_run", "missing"]

EvidenceStreamFreshness = Literal["fresh", "stale", "unknown", "absent"]

#: Artifact kinds whose absence makes the report unable to claim readiness.
#: ``diff_impact`` is situational (a clean tree has no diff to analyse) and
#: ``readiness_scorecard`` / ``coverage_mutation`` have no producer yet
#: (#151 / #147), so none of those three forces ``incomplete``.
_CORE_ARTIFACT_KINDS: Final[frozenset[str]] = frozenset(
    {"repo_map", "risk_ledger", "context_bundle"}
)

#: Evidence streams that gate readiness. ``coverage`` / ``mutation`` have no
#: producer yet (#147), so their ``missing`` status must not drag an
#: otherwise-green repo to ``incomplete``.
_CORE_EVIDENCE_NAMES: Final[frozenset[str]] = frozenset({"tests", "ci"})


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
    """A changed/affected component projected from the diff-impact artifact."""

    model_config = ConfigDict(extra="forbid")

    id: str
    path: str
    type: str
    has_mapped_tests: bool


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


def derive_readiness(
    artifacts: list[ReportArtifact],
    risks: list[ReportRisk],
    evidence: list[ReportEvidence],
) -> ReportReadiness:
    """Roll the report's signals up into one readiness state, most severe first.

    Deterministic: reasons are collected in stable input order, and the first
    severity tier with any reason wins. See the module docstring for the
    decision table and why the ordering is load-bearing.
    """
    blocked: list[str] = []
    for risk in risks:
        if risk.uncovered_blocker:
            blocked.append(f"risk {risk.risk_id} is an uncovered blocker")
        elif risk.evidence_status == "failing":
            blocked.append(f"risk {risk.risk_id} has failing evidence")
    for fact in evidence:
        if fact.status in ("failing", "mixed"):
            blocked.append(f"{fact.name} evidence is {fact.status}")
    if blocked:
        return ReportReadiness(state="blocked", reasons=blocked)

    stale: list[str] = []
    for artifact in artifacts:
        if artifact.status == "stale":
            stale.append(f"{artifact.kind} artifact is stale")
    for risk in risks:
        if risk.evidence_status == "stale":
            stale.append(f"risk {risk.risk_id} evidence is stale")
    for fact in evidence:
        if fact.freshness == "stale":
            stale.append(f"{fact.name} evidence is stale")
    if stale:
        return ReportReadiness(state="stale_evidence", reasons=stale)

    incomplete: list[str] = []
    ledger_status = next((a.status for a in artifacts if a.kind == "risk_ledger"), "missing")
    for artifact in artifacts:
        if artifact.kind in _CORE_ARTIFACT_KINDS and artifact.status in ("missing", "invalid"):
            incomplete.append(f"{artifact.kind} is {artifact.status}")
    for risk in risks:
        if risk.evidence_status == "planned":
            incomplete.append(f"risk {risk.risk_id} is planned but not executed")
    if not risks and ledger_status == "available":
        # An available ledger with zero recorded risks is weak evidence, not a
        # green light — somebody opened the ledger and wrote nothing down.
        incomplete.append("risk ledger records no risks")
    for fact in evidence:
        if fact.name in _CORE_EVIDENCE_NAMES and fact.status in ("not_run", "missing"):
            incomplete.append(f"{fact.name} evidence is {fact.status}")
    if incomplete:
        return ReportReadiness(state="incomplete", reasons=incomplete)

    residuals: list[str] = []
    for risk in risks:
        if risk.evidence_status == "accepted_residual":
            residuals.append(f"risk {risk.risk_id} is an accepted residual")
        elif risk.residual != "mitigated":
            residuals.append(f"risk {risk.risk_id} residual decision is {risk.residual}")
    if residuals:
        return ReportReadiness(state="ready_with_residuals", reasons=residuals)

    return ReportReadiness(state="ready", reasons=[])
