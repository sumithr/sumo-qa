# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Assemble a :class:`~sumo_qa.report_models.QAReport` from ``.sumo-qa`` artifacts (#157).

Split into a pure core and an IO shell so the rendered report can be
snapshot-tested byte-for-byte:

- :func:`load_report_inputs` (IO) reads the conventional ``.sumo-qa/*.json``
  artifacts off disk, validating each through its existing loader. A missing,
  malformed, or schema-drifted file becomes an honest :class:`ArtifactSource`
  state — never an exception. Inline overrides (the MCP chat flow, where a
  ledger or bundle was built in-conversation and never persisted) take
  precedence over whatever is on disk.
- :func:`build_report` (pure) projects a :class:`ReportInputs` into the
  render-ready :class:`QAReport` given an explicit clock and generator
  version — deterministic for fixed inputs, which is what lets the golden
  HTML fixtures pin the renderer.
- :func:`generate_report` composes the two for the CLI / MCP callers.

Artifact conventions: ``repo-map.json`` and ``diff-impact.json`` are written
by the #155/#156 producers. ``risk-ledger.json`` and ``context-bundle.json``
are opt-in conventional paths (the #144/#149 formatters are chat-only, so a
host persists them only if it chooses to) validated by the existing loaders.
The readiness scorecard (#151) is NOT a persisted artifact — it is derived
in-report from the risk ledger + context bundle via :class:`QaScorecard`, the
single source of truth for the readiness verdict. Coverage/mutation (#147) are
optional scorecard signals, not a persisted artifact; absent ones appear in the
inventory as honest not-supplied states.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ConfigDict

from sumo_qa.context_bundle_models import (
    ContextBundle,
    _sha_equivalent,
    detect_local_conflict,
)
from sumo_qa.context_bundle_validation import load_context_bundle
from sumo_qa.ledger_models import RiskLedger
from sumo_qa.ledger_validation import load_ledger
from sumo_qa.repo_map_models import DiffImpact, RepoMap
from sumo_qa.repo_map_scanner import _detect_git_commit
from sumo_qa.repo_map_validation import load_repo_map
from sumo_qa.report_models import (
    REPORT_SCHEMA_VERSION,
    ArtifactKind,
    QAReport,
    ReportArtifact,
    ReportComponent,
    ReportEvidence,
    ReportProject,
    ReportReadiness,
    ReportRisk,
)
from sumo_qa.scorecard_models import QaScorecard

REPO_MAP_RELPATH = ".sumo-qa/repo-map.json"
DIFF_IMPACT_RELPATH = ".sumo-qa/diff-impact.json"
RISK_LEDGER_RELPATH = ".sumo-qa/risk-ledger.json"
CONTEXT_BUNDLE_RELPATH = ".sumo-qa/context-bundle.json"

_ModelT = TypeVar("_ModelT", bound=BaseModel)


class ArtifactSource(BaseModel):
    """Where one artifact's data came from (or why it could not be read).

    ``path`` is the repo-relative posix path that was read (None when absent
    or inline). ``error`` carries the load failure detail (None on success or
    absence). ``inline`` marks a caller-supplied override that never touched
    disk. ``detail`` is optional free-text context surfaced on the report row.
    """

    model_config = ConfigDict(extra="forbid")

    path: str | None = None
    error: str | None = None
    inline: bool = False
    detail: str | None = None


class ReportInputs(BaseModel):
    """Everything :func:`build_report` needs, fully resolved — no IO beyond here."""

    model_config = ConfigDict(extra="forbid")

    root: str
    current_commit: str | None = None
    repo_map: RepoMap | None = None
    repo_map_source: ArtifactSource
    diff_impact: DiffImpact | None = None
    diff_impact_source: ArtifactSource
    ledger: RiskLedger | None = None
    ledger_source: ArtifactSource
    bundle: ContextBundle | None = None
    bundle_source: ArtifactSource


def _first_line(exc: Exception) -> str:
    """Collapse an exception to its first message line (envelope errors carry
    their ``[kind]`` prefix there; Pydantic's multi-line dumps get truncated)."""
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else exc.__class__.__name__


def _load_json_artifact(
    root: Path,
    relpath: str,
    loader: Callable[[dict], _ModelT],
) -> tuple[_ModelT | None, ArtifactSource]:
    """Read + validate one conventional artifact, mapping every failure mode
    to an honest source state: absent file → all-None source; unparseable
    JSON → ``malformed_json`` error; non-object JSON → ``type_error``;
    loader rejection (schema drift, vocab, missing field) → the loader's own
    ``[kind]``-prefixed message. Never raises."""
    target = root / relpath
    if not target.is_file():
        return None, ArtifactSource()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        # RecursionError: a hostile deeply-nested file overflows the recursive
        # JSON parser — an honest invalid state, never a crash.
        return None, ArtifactSource(path=relpath, error=f"[malformed_json] {_first_line(exc)}")
    if not isinstance(data, dict):
        return None, ArtifactSource(
            path=relpath,
            error=f"[type_error] expected a JSON object, got {type(data).__name__}",
        )
    try:
        return loader(data), ArtifactSource(path=relpath)
    except ValueError as exc:
        # Every artifact loader raises a ValueError subclass: the validation
        # envelopes (RepoMap/Ledger/ContextBundle) and pydantic's
        # ValidationError (DiffImpact) alike.
        return None, ArtifactSource(path=relpath, error=_first_line(exc))


_INLINE_SOURCE_DETAIL = "supplied inline by the caller (not read from disk)"


def load_report_inputs(
    root: Path | str,
    *,
    ledger_override: RiskLedger | None = None,
    bundle_override: ContextBundle | None = None,
) -> ReportInputs:
    """Gather every report input from ``root``'s ``.sumo-qa`` directory.

    Inline overrides take precedence over disk: when the MCP caller built a
    ledger or bundle in-conversation, the (possibly stale or invalid) on-disk
    file is not even read.
    """
    root_path = Path(root).resolve()
    current_commit = _detect_git_commit(root_path)

    repo_map, repo_map_source = _load_json_artifact(root_path, REPO_MAP_RELPATH, load_repo_map)
    repo_map_foreign = False
    if repo_map is not None and Path(repo_map.project.root).resolve() != root_path:
        # A repo-map copied from ANOTHER repository measures a different tree —
        # composing it would present foreign evidence as local. Mirror the
        # `_load_map_with_fallback` rejection precedent (server.py); here the
        # honest state is invalid (the report has no live-scan fallback).
        repo_map_foreign = True
        repo_map_source = ArtifactSource(
            path=REPO_MAP_RELPATH,
            error=(
                f"[foreign_root] artifact describes root {repo_map.project.root!r}, "
                f"not {root_path!s} — regenerate with `sumo-qa analyze`"
            ),
        )
        repo_map = None
    diff_impact, diff_impact_source = _load_json_artifact(
        root_path, DIFF_IMPACT_RELPATH, DiffImpact.model_validate
    )
    if diff_impact is not None and repo_map_foreign:
        # The overlay's changed/affected nodes are repo-map node ids; with the
        # map rejected as foreign, those references describe a different
        # repository. Reject the overlay in lockstep so it is neither composed
        # into the report body nor counted as local evidence — the overlay
        # carries no root of its own to re-validate against (schema 1.x has no
        # provenance), so the only honest signal is the foreign map beside it.
        diff_impact_source = ArtifactSource(
            path=DIFF_IMPACT_RELPATH,
            error=(
                "[foreign_root] overlay derives from a repo-map describing a different "
                "repository — regenerate with `sumo-qa analyze`"
            ),
        )
        diff_impact = None

    if ledger_override is not None:
        ledger: RiskLedger | None = ledger_override
        ledger_source = ArtifactSource(inline=True, detail=_INLINE_SOURCE_DETAIL)
    else:
        ledger, ledger_source = _load_json_artifact(root_path, RISK_LEDGER_RELPATH, load_ledger)

    if bundle_override is not None:
        bundle: ContextBundle | None = bundle_override
        bundle_source = ArtifactSource(inline=True, detail=_INLINE_SOURCE_DETAIL)
    else:
        bundle, bundle_source = _load_json_artifact(
            root_path, CONTEXT_BUNDLE_RELPATH, load_context_bundle
        )

    return ReportInputs(
        root=str(root_path),
        current_commit=current_commit,
        repo_map=repo_map,
        repo_map_source=repo_map_source,
        diff_impact=diff_impact,
        diff_impact_source=diff_impact_source,
        ledger=ledger,
        ledger_source=ledger_source,
        bundle=bundle,
        bundle_source=bundle_source,
    )


def _artifact_from_source(
    kind: ArtifactKind,
    source: ArtifactSource,
    *,
    missing_detail: str,
) -> ReportArtifact:
    """Inventory row for an artifact that did NOT load: invalid when a file
    was present but unreadable, missing otherwise."""
    if source.error is not None:
        return ReportArtifact(kind=kind, status="invalid", path=source.path, detail=source.error)
    return ReportArtifact(kind=kind, status="missing", path=None, detail=missing_detail)


def _repo_map_is_stale(inputs: ReportInputs) -> bool:
    """Prefix-aware (the context-bundle `_sha_equivalent` contract): an
    abbreviated recorded sha naming the SAME commit is not stale. No signal
    on either side (non-git root) means staleness is undetectable — the
    rendered age_days is the mitigating signal there."""
    repo_map = inputs.repo_map
    if repo_map is None:
        return False
    recorded = repo_map.project.git_commit
    current = inputs.current_commit
    return recorded is not None and current is not None and not _sha_equivalent(recorded, current)


def _repo_map_artifact(inputs: ReportInputs, now: datetime, *, map_stale: bool) -> ReportArtifact:
    repo_map = inputs.repo_map
    if repo_map is None:
        return _artifact_from_source(
            "repo_map",
            inputs.repo_map_source,
            missing_detail="not generated yet — run `sumo-qa analyze` to create it",
        )
    recorded = repo_map.project.git_commit
    current = inputs.current_commit
    detail = (
        f"recorded commit {recorded[:8]} differs from current HEAD {current[:8]}"
        if map_stale and recorded is not None and current is not None
        else inputs.repo_map_source.detail
    )
    generated_at = repo_map.project.generated_at
    return ReportArtifact(
        kind="repo_map",
        status="stale" if map_stale else "available",
        path=inputs.repo_map_source.path,
        detail=detail,
        generated_at=generated_at,
        age_days=(now - generated_at).days,
    )


def _diff_impact_artifact(inputs: ReportInputs, *, map_stale: bool) -> ReportArtifact:
    diff_impact = inputs.diff_impact
    if diff_impact is None:
        return _artifact_from_source(
            "diff_impact",
            inputs.diff_impact_source,
            missing_detail="no diff-impact overlay — run the diff-impact analysis to create one",
        )
    stale_messages = [w.message for w in diff_impact.warnings if w.kind == "stale"]
    if not stale_messages and map_stale:
        # The overlay carries no provenance of its own (schema 1.x): persisted
        # warnings are frozen at generation time, so they cannot reflect later
        # commits. When the repo-map the overlay was derived from is stale,
        # the overlay is at least as suspect. (A fresh map with an older
        # overlay remains undetectable until the overlay schema records
        # provenance.)
        stale_messages = [
            "repo-map is stale relative to HEAD; this overlay likely predates the current state"
        ]
    return ReportArtifact(
        kind="diff_impact",
        status="stale" if stale_messages else "available",
        path=inputs.diff_impact_source.path,
        detail="; ".join(stale_messages) if stale_messages else inputs.diff_impact_source.detail,
    )


def _ledger_artifact(inputs: ReportInputs) -> ReportArtifact:
    if inputs.ledger is None:
        return _artifact_from_source(
            "risk_ledger",
            inputs.ledger_source,
            missing_detail=(
                "no persisted risk ledger — persist one to .sumo-qa/risk-ledger.json "
                "or pass rows inline"
            ),
        )
    return ReportArtifact(
        kind="risk_ledger",
        status="available",
        path=inputs.ledger_source.path,
        detail=inputs.ledger_source.detail,
    )


def _bundle_artifact(inputs: ReportInputs, conflict: str | None) -> ReportArtifact:
    if inputs.bundle is None:
        return _artifact_from_source(
            "context_bundle",
            inputs.bundle_source,
            missing_detail=(
                "no persisted context bundle — persist one to .sumo-qa/context-bundle.json "
                "or pass it inline"
            ),
        )
    return ReportArtifact(
        kind="context_bundle",
        status="stale" if conflict is not None else "available",
        path=inputs.bundle_source.path,
        detail=conflict if conflict is not None else inputs.bundle_source.detail,
    )


def _scorecard_artifact(inputs: ReportInputs) -> ReportArtifact:
    # The readiness scorecard (#151) is composed in-report from the risk ledger
    # + context bundle — it is not a persisted artifact (#151's tool has no
    # write_to, and no deserializer exists). "available" requires real evidence
    # to derive from: a ledger with rows OR a bundle carrying actual signal
    # (test evidence, CI status, or changed files — the same predicate
    # QaScorecard.insufficiency_reasons uses). An empty ledger or an
    # evidence-free bundle is not evidence, so on its own it stays "missing" —
    # the row never counts as an available source while the verdict reads
    # insufficient.
    bundle = inputs.bundle
    has_bundle_signal = bundle is not None and (
        bundle.test_evidence is not None
        or bundle.ci_status is not None
        or bool(bundle.changed_files)
    )
    if (inputs.ledger is not None and inputs.ledger.rows) or has_bundle_signal:
        return ReportArtifact(
            kind="readiness_scorecard",
            status="available",
            path=None,
            detail="derived in-report from the risk ledger + context bundle (readiness engine)",
        )
    return ReportArtifact(
        kind="readiness_scorecard",
        status="missing",
        path=None,
        detail="not derivable — supply a risk ledger and/or context bundle",
    )


def _components(nodes: list) -> list[ReportComponent]:
    return sorted(
        (
            ReportComponent(
                id=node.id,
                path=node.path,
                type=node.type,
                # Normalise to tri-state on projection: a pre-tri-state overlay
                # carries a vacuous bool on non-source rows; "no" must only
                # ever render where it indicts, for any input vintage.
                has_mapped_tests=(node.has_mapped_tests if node.type == "source_file" else None),
            )
            for node in nodes
        ),
        key=lambda component: component.id,
    )


def _evidence_streams(inputs: ReportInputs) -> list[ReportEvidence]:
    """Project the bundle's go-stale facts (plus the not-yet-produced coverage
    and mutation streams) into the four named evidence rows."""
    bundle = inputs.bundle
    stale_fields = set(bundle.stale_evidence_fields()) if bundle is not None else set()
    untrusted_fields = set(bundle.untrustworthy_evidence_fields()) if bundle is not None else set()

    streams: list[ReportEvidence] = []
    for name, field in (("tests", "test_evidence"), ("ci", "ci_status")):
        fact = getattr(bundle, field) if bundle is not None else None
        if fact is None:
            streams.append(ReportEvidence(name=name, status="missing", trustworthy=False))
            continue
        streams.append(
            ReportEvidence(
                name=name,
                status=fact.result,
                # A fact captured against a different commit than the bundle
                # head is effectively stale even when labelled fresh.
                freshness="stale" if field in stale_fields else fact.freshness,
                trustworthy=field not in untrusted_fields,
                source=fact.source,
                captured_at=fact.captured_at,
                detail=fact.detail,
            )
        )
    for name in ("coverage", "mutation"):
        streams.append(
            ReportEvidence(
                name=name,
                status="missing",
                trustworthy=False,
                detail="not supplied — coverage/mutation are optional readiness-scorecard signals (guidance-only, not a persisted artifact)",
            )
        )
    return streams


def _readiness_from_scorecard(
    ledger: RiskLedger | None,
    bundle: ContextBundle | None,
    *,
    scope: str | None,
    local_head_sha: str | None,
) -> ReportReadiness:
    """Single source of truth: #151's :class:`QaScorecard` derives the verdict;
    the report only maps it onto :class:`ReportReadiness`.

    ``coverage``/``mutation`` are ``None`` — the report has no persisted producer
    for them (#147 is guidance-only). The four scorecard states are adopted
    verbatim as the report's ``ReadinessState``, so the report and the scorecard
    can never disagree.
    """
    card = QaScorecard(
        scope=scope,
        ledger=ledger,
        context_bundle=bundle,
        coverage=None,
        mutation=None,
    )
    state = card.recommendation(local_head_sha=local_head_sha)
    if state == "blocked":
        reasons = card.blocking_reasons(local_head_sha=local_head_sha)
    elif state == "insufficient_evidence":
        reasons = card.insufficiency_reasons(local_head_sha=local_head_sha)
    elif state == "ready_with_accepted_residuals":
        reasons = [
            f"{row.risk_id}: {row.risk} — accepted residual"
            for row in card.accepted_residual_rows()
        ]
    else:  # ready
        reasons = []
    return ReportReadiness(state=state, reasons=reasons)


def build_report(inputs: ReportInputs, *, now: datetime, generator_version: str) -> QAReport:
    """Project resolved inputs into the render-ready report. Pure: fixed
    inputs + fixed clock + fixed version ⇒ byte-identical output."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    conflict = (
        detect_local_conflict(inputs.bundle, inputs.current_commit)
        if inputs.bundle is not None
        else None
    )
    map_stale = _repo_map_is_stale(inputs)

    artifacts = [
        _repo_map_artifact(inputs, now, map_stale=map_stale),
        _diff_impact_artifact(inputs, map_stale=map_stale),
        _ledger_artifact(inputs),
        _bundle_artifact(inputs, conflict),
        _scorecard_artifact(inputs),
        ReportArtifact(
            kind="coverage_mutation",
            status="missing",
            path=None,
            detail="not supplied — coverage/mutation are optional readiness-scorecard signals (guidance-only, not a persisted artifact)",
        ),
    ]

    diff_impact = inputs.diff_impact
    risks = [
        ReportRisk(
            risk_id=row.risk_id,
            risk=row.risk,
            source_anchor=row.source_anchor,
            test=row.test,
            evidence_status=row.evidence_status,
            residual=row.residual,
            repo_map_node_id=row.repo_map_node_id,
            uncovered_blocker=row.is_uncovered_blocker(),
        )
        for row in (inputs.ledger.rows if inputs.ledger is not None else [])
    ]
    evidence = _evidence_streams(inputs)

    repo_map = inputs.repo_map
    project_name = (
        repo_map.project.name
        if repo_map is not None and repo_map.project.name
        else Path(inputs.root).name or None
    )

    return QAReport(
        schema_version=REPORT_SCHEMA_VERSION,
        project=ReportProject(
            root=inputs.root,
            name=project_name,
            head_commit=inputs.current_commit,
            generated_at=now,
            generator_version=generator_version,
        ),
        artifacts=artifacts,
        changed_components=_components(diff_impact.changed_nodes if diff_impact else []),
        affected_components=_components(diff_impact.affected_nodes if diff_impact else []),
        related_tests=sorted(diff_impact.related_tests) if diff_impact else [],
        unmapped_files=sorted(diff_impact.unmapped_files) if diff_impact else [],
        risk_surface=sorted(diff_impact.risk_surface) if diff_impact else [],
        risks=risks,
        uncovered_blocker_count=sum(1 for risk in risks if risk.uncovered_blocker),
        evidence=evidence,
        warnings=[conflict] if conflict is not None else [],
        readiness=_readiness_from_scorecard(
            inputs.ledger,
            inputs.bundle,
            scope=project_name,
            local_head_sha=inputs.current_commit,
        ),
    )


def generate_report(
    root: Path | str,
    *,
    generator_version: str,
    ledger_override: RiskLedger | None = None,
    bundle_override: ContextBundle | None = None,
    now: datetime | None = None,
) -> QAReport:
    """Load inputs from ``root`` and build the report. ``now`` defaults to the
    current UTC time; a naive ``now`` is rejected (in :func:`build_report`)."""
    if now is None:
        now = datetime.now(timezone.utc)
    inputs = load_report_inputs(
        root, ledger_override=ledger_override, bundle_override=bundle_override
    )
    return build_report(inputs, now=now, generator_version=generator_version)
