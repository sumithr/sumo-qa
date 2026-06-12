# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Static HTML renderer for the local QA report (issue #157).

Pure deterministic projection of a :class:`~sumo_qa.report_models.QAReport`
into one self-contained page: inline CSS only, no scripts, no images, no
external fonts or stylesheets, no network references of any kind (the issue's
no-network / no-hosted-service acceptance criterion). The page renders fully
from local disk via ``file://``.

Every dynamic string is HTML-escaped — artifact content is host-LLM- and
repo-supplied text, which is attacker-ish input to this page. Missing data
renders an explicit "not available" state, never an empty cell that could
read as passing. Long tables truncate with an explicit "+ N more" notice so
a giant diff cannot produce an unbounded page.

Visual identity: editorial style — crimson on paper, near-black ink, serif
type, no icons or pictograms.
"""

from __future__ import annotations

import html as _html

from sumo_qa.report_models import (
    QAReport,
    ReportArtifact,
    ReportComponent,
    ReportEvidence,
    ReportRisk,
)

#: Hard cap per table/list. A deliberate bound: the report is a summary, not
#: a dump — anything past the cap is summarised as "+ N more not shown".
_MAX_TABLE_ROWS = 50

_STATE_LABELS = {
    "ready": "ready",
    "ready_with_accepted_residuals": "ready with accepted residuals",
    "blocked": "blocked",
    "insufficient_evidence": "insufficient evidence",
}

_STATE_CLASSES = {
    "ready": "state-good",
    "ready_with_accepted_residuals": "state-warm",
    "blocked": "state-bad",
    "insufficient_evidence": "state-neutral",
}

#: A plain-language reading of each readiness state — the one line that says
#: what the verdict MEANS for merging, so the page interprets rather than just
#: labels. Static per state, so the render stays deterministic.
_STATE_GLOSS = {
    "ready": "Safe to merge on the evidence composed here.",
    "ready_with_accepted_residuals": "Mergeable — the remaining risks are recorded and accepted.",
    "blocked": "Do not merge — unresolved blockers are present.",
    "insufficient_evidence": "Not enough fresh evidence to judge — see the reasons below.",
}

_STATUS_LABELS = {
    "available": "available",
    "missing": "not available",
    "invalid": "invalid",
    "stale": "stale",
}

_STATUS_CLASSES = {
    "available": "ok",
    "missing": "off",
    "invalid": "bad",
    "stale": "warm",
}

_STYLE = """
  :root {
    color-scheme: light;
    --paper: #FAF7F2; --ink: #1B1B1B; --crimson: #7A1F1F; --crimson-deep: #5E1717;
    --label: #8A7B5C; --rule: #E2D9C8; --rule-soft: #EDE6D8;
    --olive: #3F4A2E; --olive-bg: #E8EDDF; --ochre-bg: #F0EAE0; --note-bg: #F4EFE6;
    --display: "Hoefler Text", "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
    --body: Charter, "Iowan Old Style", "Palatino Linotype", Georgia, serif;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 3rem 1.5rem 4rem;
    color: var(--ink);
    background:
      radial-gradient(120% 60% at 50% -10%, rgba(122,31,31,0.05), rgba(122,31,31,0) 60%),
      linear-gradient(180deg, #FCFAF6 0%, var(--paper) 28%);
    background-color: var(--paper);
    font-family: var(--body); font-size: 16px; line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }
  .sheet { max-width: 62rem; margin: 0 auto; }
  header.masthead { border-bottom: 3px double var(--crimson); padding-bottom: 0.9rem; }
  header.masthead .kicker {
    margin: 0 0 0.5rem; font-size: 0.72rem; letter-spacing: 0.32em;
    text-transform: uppercase; color: var(--label);
  }
  header.masthead h1 {
    margin: 0; font-family: var(--display); font-size: 2.7rem; line-height: 1.04;
    color: var(--crimson); font-weight: 700; letter-spacing: -0.012em;
    word-break: break-word;
  }
  .dateline {
    margin: 0.7rem 0 0; font-size: 0.8rem; letter-spacing: 0.02em; color: var(--label);
    font-variant-numeric: tabular-nums;
  }
  .dateline b { color: var(--label); font-weight: 400; text-transform: uppercase;
    letter-spacing: 0.12em; font-size: 0.68rem; }
  .dateline .sep { color: var(--rule); margin: 0 0.55rem; }
  .dateline code { font-family: var(--body); }
  main { counter-reset: sec; }
  section { margin-top: 2.4rem; }
  /* Verdict hero */
  .verdict {
    margin-top: 2.2rem; padding: 1.5rem 1.6rem 1.6rem;
    border: 1px solid var(--rule); border-left: 0.6rem solid var(--crimson);
    background: linear-gradient(180deg, rgba(255,255,255,0.5), rgba(255,255,255,0) 70%), var(--ochre-bg);
  }
  .verdict-kicker { margin: 0 0 0.2rem; font-size: 0.7rem; letter-spacing: 0.28em;
    text-transform: uppercase; opacity: 0.8; }
  .verdict-label {
    margin: 0; font-family: var(--display); font-size: 2.4rem; line-height: 1;
    font-weight: 700; text-transform: lowercase; letter-spacing: -0.01em;
  }
  .verdict-gloss { margin: 0.55rem 0 0; font-size: 1.05rem; font-style: italic; max-width: 44rem; }
  .verdict ul.reasons { margin: 0.9rem 0 0; padding-left: 1.1rem; }
  .verdict ul.reasons li { margin: 0.15rem 0; }
  .verdict p.reasons-none { margin: 0.9rem 0 0; font-style: italic; opacity: 0.85; }
  .verdict.state-good { border-left-color: var(--olive); background:
    linear-gradient(180deg, rgba(255,255,255,0.55), rgba(255,255,255,0) 70%), var(--olive-bg); }
  .verdict.state-good .verdict-label, .verdict.state-good .verdict-kicker { color: var(--olive); }
  .verdict.state-warm { border-left-color: #9A7B2E; }
  .verdict.state-warm .verdict-label, .verdict.state-warm .verdict-kicker { color: #7A5E1E; }
  .verdict.state-bad { border: 1px solid var(--crimson-deep); border-left: 0.6rem solid var(--ink);
    background: linear-gradient(180deg, #7A1F1F, #641A1A); color: var(--paper); }
  .verdict.state-bad .verdict-label, .verdict.state-bad .verdict-kicker { color: var(--paper); }
  .verdict.state-neutral .verdict-label, .verdict.state-neutral .verdict-kicker { color: var(--crimson); }
  /* Stat band */
  .statband {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px;
    margin-top: 1px; background: var(--rule); border: 1px solid var(--rule);
  }
  .stat { background: var(--paper); padding: 1rem 1.1rem; }
  .stat-num { display: block; font-family: var(--display); font-size: 1.9rem;
    line-height: 1; font-variant-numeric: tabular-nums; color: var(--ink); }
  .stat-label { display: block; margin-top: 0.35rem; font-size: 0.66rem;
    letter-spacing: 0.16em; text-transform: uppercase; color: var(--label); }
  .stat.alert .stat-num { color: var(--crimson); }
  .stat.alert .stat-label { color: var(--crimson); }
  /* Sections */
  h2 {
    font-size: 0.86rem; letter-spacing: 0.2em; text-transform: uppercase;
    color: var(--crimson); border-bottom: 1px solid var(--rule); padding-bottom: 0.35rem;
    display: flex; align-items: baseline; gap: 0.7rem;
  }
  h2::before {
    counter-increment: sec; content: counter(sec, decimal-leading-zero);
    font-family: var(--display); font-size: 0.9rem; letter-spacing: 0;
    color: var(--label); font-weight: 400;
  }
  h3 { font-size: 0.95rem; margin: 1.5rem 0 0.3rem; font-weight: 600; }
  h2 .badge { margin-left: auto; font-weight: 500; }
  a.stat { text-decoration: none; color: inherit; }
  a.stat:hover .stat-num { color: var(--crimson); }
  p.lead { margin: 1rem 0 0.2rem; font-style: italic; }
  p.delta { margin: 0.5rem 0 0; font-size: 0.8rem; color: var(--label);
    font-variant-numeric: tabular-nums; }
  td.meta { font-size: 0.8rem; color: var(--label); }
  .verdict a { color: inherit; }
  details { margin: 1.1rem 0 0; }
  summary {
    cursor: pointer; font-size: 0.95rem; font-weight: 600;
    padding: 0.15rem 0; color: var(--ink);
    list-style: none;
  }
  summary::-webkit-details-marker { display: none; }
  summary::before {
    content: "+"; display: inline-block; width: 1.1rem;
    color: var(--label); font-variant-numeric: tabular-nums;
  }
  details[open] > summary::before { content: "\2013"; }
  summary:hover, summary:hover::before { color: var(--crimson); }
  summary:focus-visible { outline: 2px solid var(--crimson); outline-offset: 2px; }
  table { width: 100%; border-collapse: collapse; margin-top: 0.6rem; }
  th {
    text-align: left; font-size: 0.66rem; letter-spacing: 0.16em;
    text-transform: uppercase; color: var(--label);
    border-bottom: 2px solid var(--crimson); padding: 0.4rem 0.7rem 0.4rem 0; white-space: nowrap;
  }
  td { padding: 0.5rem 0.7rem 0.5rem 0; border-bottom: 1px solid var(--rule); vertical-align: top;
    font-variant-numeric: tabular-nums; }
  /* Long unbreakable tokens (paths, anchors, pytest node ids) wrap inside
     their column instead of setting a hard min-width that pushes the table
     off-screen. Applied per-cell — a global rule lets auto-layout crush
     short columns to one character. */
  td.brk, li { overflow-wrap: anywhere; }
  tbody tr:nth-child(even) td { background: rgba(226,217,200,0.18); }
  td.more, li.more { font-style: italic; color: var(--label); background: none; }
  .badge {
    display: inline-block; padding: 0.08rem 0.55rem; font-size: 0.66rem;
    letter-spacing: 0.1em; text-transform: uppercase; font-family: var(--display);
    border: 1px solid; border-radius: 1px; white-space: nowrap;
  }
  .badge.ok { color: var(--olive); background: var(--olive-bg); border-color: var(--olive); }
  .badge.warm { color: #7A5E1E; background: var(--ochre-bg); border-color: #9A7B2E; }
  .badge.bad { color: var(--paper); background: var(--crimson); border-color: var(--crimson-deep); }
  .badge.off { color: var(--label); background: var(--note-bg); border-color: var(--rule); }
  p.empty {
    color: var(--label); font-style: italic; margin-top: 0.6rem;
    padding: 0.85rem 1rem; background: var(--note-bg);
    border: 1px solid var(--rule); border-left: 3px solid #C9BDA3;
  }
  ul { padding-left: 1.2rem; }
  ul.warnings { list-style: none; padding-left: 0; }
  ul.warnings li { color: var(--crimson); padding: 0.4rem 0.8rem; border-left: 3px solid var(--crimson);
    background: var(--note-bg); margin-top: 0.4rem; }
  footer.colophon { margin-top: 3.5rem; border-top: 1px solid var(--rule); padding-top: 0.7rem;
    font-size: 0.74rem; letter-spacing: 0.08em; color: var(--label); text-transform: uppercase; }
  @media (max-width: 46rem) {
    body { padding: 1.75rem 1rem 3rem; }
    header.masthead h1 { font-size: 2rem; }
    .verdict-label { font-size: 1.9rem; }
    .statband { grid-template-columns: repeat(2, 1fr); }
    table { font-size: 0.86rem; }
  }
  @media print {
    body { background: #fff; padding: 0; }
    .verdict.state-bad { background: #fff; color: var(--ink); border-left-color: var(--crimson); }
    .verdict.state-bad .verdict-label, .verdict.state-bad .verdict-kicker { color: var(--crimson); }
    .badge.bad { color: var(--crimson); background: #fff; }
  }
"""


def _esc(value: object) -> str:
    return _html.escape(str(value), quote=True)


def _dash(value: object | None) -> str:
    """Escaped value, or an explicit em-dash placeholder for absent fields."""
    return _esc(value) if value not in (None, "") else "&#8212;"


def _bounded(items: list) -> tuple[list, int]:
    """Cap a list at the table bound; the second element is the hidden count."""
    over = len(items) - _MAX_TABLE_ROWS
    return (items[:_MAX_TABLE_ROWS], over) if over > 0 else (items, 0)


def _more_row(hidden: int, colspan: int) -> str:
    return (
        f'<tr><td class="more" colspan="{colspan}">+ {hidden} more not shown</td></tr>'
        if hidden
        else ""
    )


def _artifact_section(artifacts: list[ReportArtifact]) -> str:
    rows = []
    for artifact in artifacts:
        age = f"{artifact.age_days} days" if artifact.age_days is not None else "&#8212;"
        rows.append(
            "<tr>"
            f"<td>{_esc(artifact.kind.replace('_', ' '))}</td>"
            f'<td><span class="badge {_STATUS_CLASSES[artifact.status]}">'
            f"{_STATUS_LABELS[artifact.status]}</span></td>"
            f'<td class="brk">{_dash(artifact.path)}</td>'
            f"<td>{age}</td>"
            f'<td class="brk">{_dash(artifact.detail)}</td>'
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>artifact</th><th>status</th><th>path</th><th>age</th><th>notes</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _mapped_tests_cell(verdict: bool | None) -> str:
    """Tri-state mapped-tests cell: yes/no only for source rows (where the
    verdict is real); the em-dash for None so 'no' only appears where it
    indicts."""
    if verdict is None:
        return "&#8212;"
    return "yes" if verdict else "no"


def _component_table(components: list[ReportComponent]) -> str:
    shown, hidden = _bounded(components)
    rows = "".join(
        "<tr>"
        f'<td class="brk">{_esc(component.id)}</td><td>{_esc(component.type)}</td>'
        f'<td class="brk">{_esc(component.path)}</td>'
        f"<td>{_mapped_tests_cell(component.has_mapped_tests)}</td>"
        "</tr>"
        for component in shown
    )
    return (
        "<table><thead><tr><th>component</th><th>type</th><th>path</th>"
        f"<th>mapped tests</th></tr></thead><tbody>{rows}{_more_row(hidden, 4)}</tbody></table>"
    )


def _path_items(paths: list[str]) -> str:
    shown, hidden = _bounded(paths)
    items = "".join(f"<li>{_esc(path)}</li>" for path in shown)
    more = f'<li class="more">+ {hidden} more not shown</li>' if hidden else ""
    return f"<ul>{items}{more}</ul>"


def _path_list(caption: str, paths: list[str]) -> str:
    body = _path_items(paths) if paths else '<p class="empty">none recorded</p>'
    return f"<h3>{_esc(caption)}</h3>{body}"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _type_breakdown(components: list[ReportComponent]) -> str:
    """Count line for a component set: source / test / docs named, everything
    else bucketed as 'other' — the summary a reader scans instead of rows."""
    named = (("source", "source_file"), ("test", "test_file"), ("docs", "docs"))
    parts = []
    remaining = len(components)
    for label, node_type in named:
        count = sum(1 for c in components if c.type == node_type)
        if count:
            parts.append(f"{count} {label}")
            remaining -= count
    if remaining:
        parts.append(f"{remaining} other")
    return " &#183; ".join(parts)


def _collapsed(summary: str, body: str) -> str:
    """A natively collapsed disclosure — no scripts, summary-first reading."""
    return f"<details><summary>{summary}</summary>{body}</details>"


def _rollup(label: str, cls: str) -> str:
    """The short state badge a section heading carries — a scroll down the
    page reads as a colour scan (the Lighthouse gauge-per-category move in
    this page's idiom)."""
    return f'<span class="badge {cls}">{_esc(label)}</span>'


def _inventory_rollup(artifacts: list[ReportArtifact]) -> str:
    invalid = sum(1 for a in artifacts if a.status == "invalid")
    stale = sum(1 for a in artifacts if a.status == "stale")
    available = sum(1 for a in artifacts if a.status == "available")
    if invalid:
        return _rollup(f"{invalid} invalid", "bad")
    if stale:
        return _rollup(f"{stale} stale", "warm")
    if available == len(artifacts):
        return _rollup("all available", "ok")
    return _rollup(f"{available} of {len(artifacts)} available", "off")


def _impact_rollup(report: QAReport) -> str:
    if report.risk_surface:
        return _rollup(_plural(len(report.risk_surface), "uncovered source"), "bad")
    if not (
        report.changed_components
        or report.affected_components
        or report.related_tests
        or report.unmapped_files
    ):
        return _rollup("no data", "off")
    return _rollup("clean", "ok")


def _risk_rollup(risks: list[ReportRisk]) -> str:
    uncovered = sum(1 for r in risks if r.uncovered_blocker)
    if uncovered:
        return _rollup(_plural(uncovered, "uncovered blocker"), "bad")
    if not risks:
        return _rollup("none recorded", "off")
    pending = sum(1 for r in risks if r.evidence_status != "passing")
    if pending:
        return _rollup(f"{pending} without passing evidence", "warm")
    return _rollup("all covered", "ok")


def _evidence_rollup(evidence: list[ReportEvidence]) -> str:
    if not evidence:
        return _rollup("none recorded", "off")
    untrusted = sum(1 for fact in evidence if not fact.trustworthy)
    if untrusted:
        return _rollup(f"{untrusted} not trusted", "warm")
    return _rollup("trusted", "ok")


def _warning_rollup(warnings: list[str]) -> str:
    if warnings:
        return _rollup(_plural(len(warnings), "warning"), "warm")
    return _rollup("none", "ok")


def _risk_lead(risks: list[ReportRisk]) -> str:
    """One-sentence finding before the ledger — the sentence is the report,
    the table is the appendix."""
    if not risks:
        return ""
    n = len(risks)
    uncovered = sum(1 for r in risks if r.uncovered_blocker)
    if uncovered:
        ids = ", ".join(r.risk_id for r in risks if r.uncovered_blocker)
        verb = "is an uncovered blocker" if uncovered == 1 else "are uncovered blockers"
        return f'<p class="lead">{uncovered} of {_plural(n, "risk")} {verb}: {_esc(ids)}.</p>'
    pending = [r.risk_id for r in risks if r.evidence_status != "passing"]
    if pending:
        return (
            f'<p class="lead">{len(pending)} of {_plural(n, "risk")} await passing '
            f"evidence: {_esc(', '.join(pending))}.</p>"
        )
    return f'<p class="lead">All {_plural(n, "risk")} carry passing evidence.</p>'


def _inventory_lead(artifacts: list[ReportArtifact]) -> str:
    available = sum(1 for a in artifacts if a.status == "available")
    if available == len(artifacts):
        return f'<p class="lead">All {len(artifacts)} sources are available.</p>'
    missing = ", ".join(
        f"{a.kind.replace('_', ' ')} {_STATUS_LABELS[a.status]}"
        for a in artifacts
        if a.status != "available"
    )
    return (
        f'<p class="lead">{available} of {len(artifacts)} sources available; {_esc(missing)}.</p>'
    )


def _evidence_lead(evidence: list[ReportEvidence]) -> str:
    # Only called from _evidence_block when evidence exists and at least one
    # stream is untrusted (the all-trusted case collapses instead).
    trusted = [fact.name for fact in evidence if fact.trustworthy]
    rest = ", ".join(fact.name for fact in evidence if not fact.trustworthy)
    head = f"{len(trusted)} of {len(evidence)} streams trusted"
    head += f" ({_esc(', '.join(trusted))})" if trusted else ""
    return f'<p class="lead">{head}; not trusted: {_esc(rest)}.</p>'


def _delta_line(report: QAReport) -> str:
    """Run-over-run trend under the dateline — only the quantities that
    changed, verdict first; honest 'no change' otherwise."""
    prev = report.previous_run
    if prev is None:
        return ""
    available = sum(1 for a in report.artifacts if a.status == "available")
    uncovered = sum(1 for r in report.risks if r.uncovered_blocker)
    parts: list[str] = []
    if prev.readiness_state != report.readiness.state:
        parts.append(
            f"verdict {_esc(_STATE_LABELS[prev.readiness_state])} &#8594; "
            f"{_esc(_STATE_LABELS[report.readiness.state])}"
        )
    if prev.risk_count != len(report.risks):
        parts.append(f"risks {prev.risk_count} &#8594; {len(report.risks)}")
    if prev.uncovered_blocker_count != uncovered:
        parts.append(f"uncovered blockers {prev.uncovered_blocker_count} &#8594; {uncovered}")
    if prev.sources_available != available:
        parts.append(f"sources available {prev.sources_available} &#8594; {available}")
    when = _esc(prev.generated_at.isoformat())
    if not parts:
        return f'<p class="delta">no change since previous run ({when})</p>'
    return f'<p class="delta">since previous run ({when}): {" &#183; ".join(parts)}</p>'


def _inventory_block(artifacts: list[ReportArtifact]) -> str:
    """Green folds away: a fully available inventory collapses to its lead
    sentence; any other state stays open above the table."""
    lead = _inventory_lead(artifacts)
    if all(a.status == "available" for a in artifacts):
        return _collapsed(
            f"All {len(artifacts)} sources are available", _artifact_section(artifacts)
        )
    return f"{lead}{_artifact_section(artifacts)}"


def _evidence_block(evidence: list[ReportEvidence]) -> str:
    if not evidence:
        return _evidence_section(evidence)
    if all(fact.trustworthy for fact in evidence):
        return _collapsed(
            f"All {len(evidence)} evidence streams are trusted", _evidence_section(evidence)
        )
    return f"{_evidence_lead(evidence)}{_evidence_section(evidence)}"


def _impact_lead(report: QAReport) -> str:
    if report.risk_surface:
        shown = ", ".join(report.risk_surface[:3])
        extra = len(report.risk_surface) - 3
        tail = f" (+ {extra} more)" if extra > 0 else ""
        n = len(report.risk_surface)
        verb = "has" if n == 1 else "have"
        return (
            f'<p class="lead">{_plural(n, "changed source")} {verb} no mapped test: '
            f"{_esc(shown)}{tail}.</p>"
        )
    if report.changed_components:
        return '<p class="lead">All changed sources have mapped tests.</p>'
    return ""


def _impact_section(report: QAReport) -> str:
    """Summary-first change impact: each enumeration collapses to a count
    line (full rows one click away); only the risk surface — the indictment —
    stays open. Empty enumerations earn no collapsed stub."""
    has_impact_data = bool(
        report.changed_components
        or report.affected_components
        or report.related_tests
        or report.unmapped_files
        or report.risk_surface
    )
    if not has_impact_data:
        return (
            '<p class="empty">Diff-impact data is not available &#8212; '
            "change-impact tables are omitted.</p>"
        )
    parts: list[str] = []
    changed = report.changed_components
    if changed:
        parts.append(
            _collapsed(
                f"{_plural(len(changed), 'file')} changed: {_type_breakdown(changed)}",
                _component_table(changed),
            )
        )
    affected = report.affected_components
    if affected:
        parts.append(
            _collapsed(
                f"{_plural(len(affected), 'affected component')} (one hop): "
                f"{_type_breakdown(affected)}",
                _component_table(affected),
            )
        )
    if report.related_tests:
        parts.append(
            _collapsed(
                _plural(len(report.related_tests), "related test"),
                _path_items(report.related_tests),
            )
        )
    parts.append(
        _path_list("Risk surface (changed sources with no mapped test)", report.risk_surface)
    )
    if report.unmapped_files:
        parts.append(
            _collapsed(
                _plural(len(report.unmapped_files), "unmapped file"),
                _path_items(report.unmapped_files),
            )
        )
    return "".join(parts)


def _risk_severity(risk: ReportRisk) -> tuple[int, str]:
    """Severity-first ordering: uncovered blockers, then rows without passing
    evidence, then the covered rest — so the row cap truncates the safe end,
    never the findings. Ties break on risk_id, deliberately: deterministic,
    reproducible row order regardless of artifact insertion order."""
    if risk.uncovered_blocker:
        rank = 0
    elif risk.evidence_status != "passing":
        rank = 1
    else:
        rank = 2
    return (rank, risk.risk_id)


def _risk_section(risks: list[ReportRisk]) -> str:
    if not risks:
        return '<p class="empty">No risks recorded.</p>'
    shown, hidden = _bounded(sorted(risks, key=_risk_severity))
    rows = []
    for risk in shown:
        residual = (
            '<span class="badge bad">blocker &#8212; uncovered</span>'
            if risk.uncovered_blocker
            else _esc(risk.residual)
        )
        rows.append(
            f'<tr id="risk-{_esc(risk.risk_id)}">'
            f"<td>{_esc(risk.risk_id)}</td><td>{_esc(risk.risk)}</td>"
            f'<td class="brk">{_esc(risk.source_anchor)}</td><td class="brk">{_esc(risk.test)}</td>'
            f"<td>{_esc(risk.evidence_status.replace('_', ' '))}</td>"
            f"<td>{residual}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>id</th><th>risk</th><th>anchor</th><th>test</th>"
        "<th>evidence</th><th>residual</th></tr></thead>"
        f"<tbody>{''.join(rows)}{_more_row(hidden, 6)}</tbody></table>"
    )


def _evidence_section(evidence: list[ReportEvidence]) -> str:
    rows = []
    for fact in evidence:
        status = "not available" if fact.status == "missing" else fact.status.replace("_", " ")
        rows.append(
            "<tr>"
            f"<td>{_esc(fact.name)}</td><td>{_esc(status)}</td>"
            f"<td>{_dash(fact.freshness)}</td>"
            f"<td>{'yes' if fact.trustworthy else 'no'}</td>"
            f'<td class="meta">{_dash(fact.source)}</td>'
            f'<td class="meta">{_dash(fact.captured_at)}</td>'
            f'<td class="brk">{_dash(fact.detail)}</td>'
            "</tr>"
        )
    return (
        "<table><thead><tr><th>stream</th><th>status</th><th>freshness</th>"
        "<th>trustworthy</th><th>source</th><th>captured at</th><th>detail</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _warning_section(warnings: list[str]) -> str:
    if not warnings:
        return '<p class="empty">No warnings.</p>'
    return f'<ul class="warnings">{"".join(f"<li>{_esc(w)}</li>" for w in warnings)}</ul>'


def render_report_html(report: QAReport) -> str:
    """Render the report into one self-contained static HTML page.

    Pure: the same report model renders byte-for-byte identically — the golden
    snapshots under ``tests/fixtures/report/`` pin this.
    """
    project = report.project
    state = report.readiness.state
    shown_reasons, hidden_reasons = _bounded(report.readiness.reasons)
    risk_ids = {risk.risk_id for risk in report.risks}

    def _reason_item(reason: str) -> str:
        # A reason that opens with a ledger risk id links to that row — the
        # verdict is wired to the evidence that proves it. Exact string match
        # against the rendered ids (ledger ids only need to be nonblank, so a
        # tidy-identifier regex would skip ids with spaces or punctuation).
        prefix, sep, rest = reason.partition(": ")
        if sep and prefix in risk_ids:
            return f'<li><a href="#risk-{_esc(prefix)}">{_esc(prefix)}</a>: {_esc(rest)}</li>'
        return f"<li>{_esc(reason)}</li>"

    reasons = "".join(_reason_item(reason) for reason in shown_reasons)
    more_reasons = (
        f'<li class="more">+ {hidden_reasons} more not shown</li>' if hidden_reasons else ""
    )
    reasons_block = (
        f'<ul class="reasons">{reasons}{more_reasons}</ul>'
        if reasons
        else '<p class="reasons-none">All composed signals are green.</p>'
    )
    available = sum(1 for artifact in report.artifacts if artifact.status == "available")
    blocker_class = " alert" if report.uncovered_blocker_count else ""
    title = _esc(project.name or project.root)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QA report &#8212; {title}</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="sheet">
<header class="masthead">
<p class="kicker">sumo-qa &#183; local QA report</p>
<h1>{title}</h1>
<p class="dateline"><b>root</b> <code>{_esc(project.root)}</code>\
<span class="sep">&#183;</span><b>head</b> <code>{_dash(project.head_commit)}</code>\
<span class="sep">&#183;</span><b>generated</b> {_esc(project.generated_at.isoformat())}</p>
{_delta_line(report)}</header>
<main>
<section class="verdict {_STATE_CLASSES[state]}">
<p class="verdict-kicker">Readiness</p>
<p class="verdict-label">{_STATE_LABELS[state]}</p>
<p class="verdict-gloss">{_esc(_STATE_GLOSS[state])}</p>
{reasons_block}
</section>
<section class="statband">
<a class="stat" href="#inventory"><span class="stat-num">{available}/{len(report.artifacts)}</span>\
<span class="stat-label">sources available</span></a>
<a class="stat" href="#risks"><span class="stat-num">{len(report.risks)}</span>\
<span class="stat-label">risks tracked</span></a>
<a class="stat{blocker_class}" href="#risks"><span class="stat-num">{report.uncovered_blocker_count}</span>\
<span class="stat-label">uncovered blockers</span></a>
<a class="stat" href="#warnings"><span class="stat-num">{len(report.warnings)}</span>\
<span class="stat-label">warnings</span></a>
</section>
<section id="inventory">
<h2>Artifact inventory {_inventory_rollup(report.artifacts)}</h2>
{_inventory_block(report.artifacts)}
</section>
<section id="impact">
<h2>Change impact {_impact_rollup(report)}</h2>
{_impact_lead(report)}{_impact_section(report)}
</section>
<section id="risks">
<h2>Risk ledger {_risk_rollup(report.risks)}</h2>
{_risk_lead(report.risks)}{_risk_section(report.risks)}
</section>
<section id="evidence">
<h2>Evidence {_evidence_rollup(report.evidence)}</h2>
{_evidence_block(report.evidence)}
</section>
<section id="warnings">
<h2>Warnings {_warning_rollup(report.warnings)}</h2>
{_warning_section(report.warnings)}
</section>
</main>
<footer class="colophon">
Generated by {_esc(project.generator_version)} &#183; report schema {_esc(report.schema_version)}
</footer>
</div>
</body>
</html>
"""
