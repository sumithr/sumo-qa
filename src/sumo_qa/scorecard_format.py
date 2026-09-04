# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Deterministic projections of a QA readiness scorecard (issue #151).

Three pure projections of an already-built :class:`QaScorecard`:

* ``format_scorecard_markdown`` — the human-facing scorecard: a recommendation
  headline, a per-dimension table, and the blocker / insufficiency reasons.
* ``compact_summary`` — a single-line roll-up the review skill can drop inline
  when the user did NOT ask for a full readiness report (the "omit from short
  answers" acceptance criterion).
* ``serialize_scorecard`` — a JSON-able snapshot of the same facts so #157's
  ``.sumo-qa/qa-report.html`` can render the scorecard without re-deriving
  anything. This is the serializability the #154 scope comment requires.

NO inference and NO fake precision: the projections render exactly the derived
states and the counts of real evidence. No percentage is invented, and an absent
coverage/mutation signal renders as "not measured", never as passing. Output is
bounded — the reason lists truncate past ``max_reasons`` so a large scorecard
cannot blow the host/MCP token budget.
"""

from __future__ import annotations

import re
from typing import Any

from sumo_qa.scorecard_models import (
    SCORECARD_SCHEMA_VERSION,
    DimensionStatus,
    QaScorecard,
    ScorecardRecommendation,
)

#: Default cap on rendered reason rows (blockers / insufficiencies).
DEFAULT_MAX_REASONS = 25

#: Human-facing headline label per recommendation state.
_HEADLINE: dict[ScorecardRecommendation, str] = {
    "blocked": "BLOCKED",
    "insufficient_evidence": "INSUFFICIENT EVIDENCE",
    "ready_with_accepted_residuals": "READY (with accepted residuals)",
    "ready": "READY",
}

#: Human-facing label per dimension status (the enum is machine-side).
_STATUS_LABEL: dict[DimensionStatus, str] = {
    "ok": "ok",
    "gap": "gap",
    "blocker": "blocker",
    "stale": "stale",
    "unverified": "unverified",
    "not_measured": "not measured",
}

_DISCLAIMER = (
    "This scorecard summarises the evidence supplied; it is not a predictive "
    'quality score. Absent coverage/mutation signals are reported as "not '
    'measured", never assumed passing.'
)


def _escape(value: str) -> str:
    # Collapse any line/paragraph/vertical separator to a space and escape pipes
    # so a free-text detail can't break the markdown table or inject markdown on
    # a fresh line. Mirrors the ledger/context-bundle formatters.
    flattened = re.sub(r"[\r\n\x0b\x0c\x1c\x1d\x1e\x85  ]+", " ", value)
    return flattened.replace("|", "\\|")


def _headline_line(card: QaScorecard, *, local_head_sha: str | None) -> str:
    rec = card.recommendation(local_head_sha=local_head_sha)
    label = _HEADLINE[rec]
    if rec == "blocked":
        n = len(card.blocking_reasons(local_head_sha=local_head_sha))
        return (
            f"Recommendation: **{label}** — {n} hard stop(s) must be resolved before this is ready."
        )
    if rec == "insufficient_evidence":
        n = len(card.insufficiency_reasons(local_head_sha=local_head_sha))
        return (
            f"Recommendation: **{label}** — {n} evidence gap(s); readiness cannot be asserted yet."
        )
    if rec == "ready_with_accepted_residuals":
        n = len(card.accepted_residual_rows())
        return f"Recommendation: **{label}** — {n} accepted residual risk(s) recorded."
    return (
        f"Recommendation: **{label}** — evidence is fresh, passing, and complete; "
        "no uncovered blockers."
    )


def _reason_block(title: str, reasons: list[str], *, max_reasons: int) -> list[str]:
    if not reasons:
        return []
    cap = max(max_reasons, 0)
    shown = reasons[:cap]
    hidden = len(reasons) - len(shown)
    lines = ["", f"{title}"]
    lines.extend(f"- {_escape(reason)}" for reason in shown)
    if hidden:
        lines.append(f"- … +{hidden} more.")
    return lines


def format_scorecard_markdown(
    card: QaScorecard,
    *,
    local_head_sha: str | None = None,
    max_reasons: int = DEFAULT_MAX_REASONS,
) -> str:
    """Render the scorecard as markdown: headline, dimension table, reasons."""
    scope = f" — {_escape(card.scope)}" if card.scope else ""
    lines = [
        f"**QA readiness scorecard{scope}**",
        "",
        _headline_line(card, local_head_sha=local_head_sha),
    ]

    lines.append("")
    lines.append("| Dimension | Status | Evidence |")
    lines.append("|---|---|---|")
    for dim in card.dimensions(local_head_sha=local_head_sha):
        lines.append(
            f"| {_escape(dim.name)} | {_STATUS_LABEL[dim.status]} | {_escape(dim.detail)} |"
        )

    lines.extend(
        _reason_block(
            "Blockers (resolve before ready):",
            card.blocking_reasons(local_head_sha=local_head_sha),
            max_reasons=max_reasons,
        )
    )
    lines.extend(
        _reason_block(
            "Insufficient evidence (supply or refresh to assess readiness):",
            card.insufficiency_reasons(local_head_sha=local_head_sha),
            max_reasons=max_reasons,
        )
    )

    lines.append("")
    lines.append(_DISCLAIMER)
    return "\n".join(lines)


def compact_summary(card: QaScorecard, *, local_head_sha: str | None = None) -> str:
    """Render a single-line roll-up — the form to drop inline in short answers.

    Example: ``QA readiness: BLOCKED — 5 risk(s), 2 uncovered blocker(s); tests
    passing/fresh, CI passing/stale; coverage+mutation not measured.``
    """
    rec = card.recommendation(local_head_sha=local_head_sha)
    parts: list[str] = []

    rows = card.ledger.rows if card.ledger is not None else []
    if rows:
        blockers = len(card.uncovered_blocker_rows())
        clause = f"{len(rows)} risk(s)"
        if blockers:
            clause += f", {blockers} uncovered blocker(s)"
        parts.append(clause)

    bundle = card.context_bundle
    ev_parts: list[str] = []
    if bundle is not None:
        if bundle.test_evidence is not None:
            ev_parts.append(f"tests {bundle.test_evidence.result}/{bundle.test_evidence.freshness}")
        if bundle.ci_status is not None:
            ev_parts.append(f"CI {bundle.ci_status.result}/{bundle.ci_status.freshness}")
    if ev_parts:
        parts.append(", ".join(ev_parts))

    not_measured = [
        dim.name.lower()
        for dim in card.dimensions(local_head_sha=local_head_sha)
        if dim.status == "not_measured" and dim.name in ("Coverage", "Mutation")
    ]
    if len(not_measured) == 2:
        parts.append("coverage+mutation not measured")
    elif not_measured:
        parts.append(f"{not_measured[0]} not measured")

    body = "; ".join(parts) if parts else "no evidence supplied"
    return f"QA readiness: {_HEADLINE[rec]} — {body}."


def serialize_scorecard(card: QaScorecard, *, local_head_sha: str | None = None) -> dict[str, Any]:
    """JSON-able snapshot of the scorecard for #157's report renderer.

    Carries the derived recommendation, every dimension, the counts, and the
    reason lists — everything a downstream HTML/dashboard renderer needs without
    re-deriving. Deterministic and self-contained.
    """
    dims = card.dimensions(local_head_sha=local_head_sha)
    # Only the readiness-GATING dimensions count as `stale_evidence`: a stale
    # optional coverage/mutation signal is reported in the dimension table but
    # does NOT gate readiness, so listing it here would break the contract that a
    # non-empty `stale_evidence` implies a non-ready recommendation.
    non_gating = {"Coverage", "Mutation"}
    return {
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "scope": card.scope,
        "recommendation": card.recommendation(local_head_sha=local_head_sha),
        "is_ready": card.is_ready(local_head_sha=local_head_sha),
        "dimensions": [
            {"name": dim.name, "status": dim.status, "detail": dim.detail} for dim in dims
        ],
        "uncovered_blocker_count": len(card.uncovered_blocker_rows()),
        "accepted_residual_count": len(card.accepted_residual_rows()),
        "open_residual_count": len(card.open_residual_rows()),
        "stale_evidence": [
            dim.name for dim in dims if dim.status == "stale" and dim.name not in non_gating
        ],
        "not_measured": [dim.name for dim in dims if dim.status == "not_measured"],
        "blocking_reasons": card.blocking_reasons(local_head_sha=local_head_sha),
        "insufficiency_reasons": card.insufficiency_reasons(local_head_sha=local_head_sha),
    }
