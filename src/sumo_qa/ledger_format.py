# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Deterministic markdown projection of the risk-to-test ledger (issue #144).

Pure formatting — NO inference. Given an already-validated :class:`RiskLedger`,
``format_ledger_markdown`` renders the structured appendix the markdown-first
verdict carries, and ``compact_summary`` renders a one-line roll-up. Both are
bounded: ``format_ledger_markdown`` truncates past ``max_rows`` so a large ledger
cannot blow the host/MCP token budget (the #89/#137 token-budget guard), and the
compact summary is a single line regardless of ledger size.

The optional ``Repo-map node`` column appears only when at least one row carries
a ``repo_map_node_id`` link — keeping the common case (no repo-map) as narrow as
possible.
"""

from __future__ import annotations

from sumo_qa.ledger_models import RiskLedger, RiskLedgerRow

#: Default cap on rendered rows. A ledger larger than this is truncated with an
#: explicit "+N more" notice rather than silently dropping rows.
DEFAULT_MAX_ROWS = 25


def _escape(value: str) -> str:
    # A literal pipe in a field would create a phantom table column; escape it
    # so the markdown table stays well-formed.
    return value.replace("|", "\\|")


def format_ledger_markdown(ledger: RiskLedger, *, max_rows: int = DEFAULT_MAX_ROWS) -> str:
    """Render the ledger as a markdown table headed ``Risk ledger``.

    ``max_rows`` caps the rendered data rows; the remainder are summarised with a
    ``… +N more`` line so the output stays bounded.
    """
    if not ledger.rows:
        return "**Risk ledger** — no risks recorded."

    show_node_id = any(row.repo_map_node_id for row in ledger.rows)
    shown = ledger.rows[:max_rows]
    hidden = len(ledger.rows) - len(shown)

    header = "| Risk | Statement | Source | Test / check | Evidence | Residual |"
    rule = "|---|---|---|---|---|---|"
    if show_node_id:
        header = header[:-1] + " Repo-map node |"
        rule = rule[:-1] + "---|"

    lines = ["**Risk ledger**", "", header, rule]
    for row in shown:
        lines.append(_render_row(row, show_node_id=show_node_id))
    if hidden:
        lines.append("")
        lines.append(f"… +{hidden} more risk row(s) truncated.")
    return "\n".join(lines)


def _render_row(row: RiskLedgerRow, *, show_node_id: bool) -> str:
    cells = [
        _escape(row.risk_id),
        _escape(row.risk),
        _escape(row.source_anchor),
        _escape(row.test),
        row.evidence_status,
        row.residual,
    ]
    if show_node_id:
        cells.append(_escape(row.repo_map_node_id) if row.repo_map_node_id else "—")
    return "| " + " | ".join(cells) + " |"


def compact_summary(ledger: RiskLedger) -> str:
    """Render a single-line roll-up of the ledger's evidence state.

    Example: ``Risk ledger: 3 risks — 1 passing, 1 planned, 1 failing; 1
    uncovered blocker.`` The blocker clause is omitted when no row is an
    uncovered blocker.
    """
    rows = ledger.rows
    total = len(rows)
    if total == 0:
        return "Risk ledger: 0 risks."

    counts: dict[str, int] = {}
    for row in rows:
        counts[row.evidence_status] = counts.get(row.evidence_status, 0) + 1
    # Stable, human order — only states that occur are mentioned.
    order = ["passing", "planned", "failing", "stale", "accepted_residual"]
    parts = [f"{counts[s]} {s.replace('_', ' ')}" for s in order if counts.get(s)]
    breakdown = ", ".join(parts)

    blockers = sum(1 for row in rows if row.is_uncovered_blocker())
    suffix = ""
    if blockers:
        suffix = f"; {blockers} uncovered blocker{'s' if blockers != 1 else ''}"
    return f"Risk ledger: {total} risks — {breakdown}{suffix}."
