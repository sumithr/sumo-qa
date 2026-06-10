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
    "ready_with_residuals": "ready with residuals",
    "stale_evidence": "stale evidence",
    "blocked": "blocked",
    "incomplete": "incomplete",
}

_STATE_CLASSES = {
    "ready": "state-good",
    "ready_with_residuals": "state-warm",
    "stale_evidence": "state-warm",
    "blocked": "state-bad",
    "incomplete": "state-neutral",
}

#: A plain-language reading of each readiness state — the one line that says
#: what the verdict MEANS for merging, so the page interprets rather than just
#: labels. Static per state, so the render stays deterministic.
_STATE_GLOSS = {
    "ready": "Safe to merge on the evidence composed here.",
    "ready_with_residuals": "Mergeable — the remaining risks are recorded and accepted.",
    "stale_evidence": "Re-verify before trusting this — some evidence may be out of date.",
    "blocked": "Do not merge — unresolved blockers are present.",
    "incomplete": "Not enough evidence to judge yet — generate the missing sources.",
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
  table { width: 100%; border-collapse: collapse; margin-top: 0.6rem; }
  th {
    text-align: left; font-size: 0.66rem; letter-spacing: 0.16em;
    text-transform: uppercase; color: var(--label);
    border-bottom: 2px solid var(--crimson); padding: 0.4rem 0.7rem 0.4rem 0; white-space: nowrap;
  }
  td { padding: 0.5rem 0.7rem 0.5rem 0; border-bottom: 1px solid var(--rule); vertical-align: top;
    font-variant-numeric: tabular-nums; }
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
            f"<td>{_dash(artifact.path)}</td>"
            f"<td>{age}</td>"
            f"<td>{_dash(artifact.detail)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>artifact</th><th>status</th><th>path</th><th>age</th><th>notes</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _component_table(caption: str, components: list[ReportComponent]) -> str:
    shown, hidden = _bounded(components)
    rows = "".join(
        "<tr>"
        f"<td>{_esc(component.id)}</td><td>{_esc(component.type)}</td>"
        f"<td>{_esc(component.path)}</td>"
        f"<td>{'yes' if component.has_mapped_tests else 'no'}</td>"
        "</tr>"
        for component in shown
    )
    return (
        f"<h3>{_esc(caption)}</h3>"
        "<table><thead><tr><th>component</th><th>type</th><th>path</th>"
        f"<th>mapped tests</th></tr></thead><tbody>{rows}{_more_row(hidden, 4)}</tbody></table>"
    )


def _path_list(caption: str, paths: list[str]) -> str:
    shown, hidden = _bounded(paths)
    items = "".join(f"<li>{_esc(path)}</li>" for path in shown)
    more = f'<li class="more">+ {hidden} more not shown</li>' if hidden else ""
    body = f"<ul>{items}{more}</ul>" if items else '<p class="empty">none recorded</p>'
    return f"<h3>{_esc(caption)}</h3>{body}"


def _impact_section(report: QAReport) -> str:
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
    return (
        _component_table("Changed components", report.changed_components)
        + _component_table("Affected components (one hop)", report.affected_components)
        + _path_list("Related tests", report.related_tests)
        + _path_list("Risk surface (changed sources with no mapped test)", report.risk_surface)
        + _path_list("Unmapped files", report.unmapped_files)
    )


def _risk_section(risks: list[ReportRisk]) -> str:
    if not risks:
        return '<p class="empty">No risks recorded.</p>'
    shown, hidden = _bounded(risks)
    rows = []
    for risk in shown:
        residual = (
            '<span class="badge bad">blocker &#8212; uncovered</span>'
            if risk.uncovered_blocker
            else _esc(risk.residual)
        )
        rows.append(
            "<tr>"
            f"<td>{_esc(risk.risk_id)}</td><td>{_esc(risk.risk)}</td>"
            f"<td>{_esc(risk.source_anchor)}</td><td>{_esc(risk.test)}</td>"
            f"<td>{_esc(risk.evidence_status.replace('_', ' '))}</td>"
            f"<td>{residual}</td><td>{_dash(risk.repo_map_node_id)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>id</th><th>risk</th><th>anchor</th><th>test</th>"
        "<th>evidence</th><th>residual</th><th>repo-map node</th></tr></thead>"
        f"<tbody>{''.join(rows)}{_more_row(hidden, 7)}</tbody></table>"
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
            f"<td>{_dash(fact.source)}</td><td>{_dash(fact.captured_at)}</td>"
            f"<td>{_dash(fact.detail)}</td>"
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
    reasons = "".join(f"<li>{_esc(reason)}</li>" for reason in shown_reasons)
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
</header>
<main>
<section class="verdict {_STATE_CLASSES[state]}">
<p class="verdict-kicker">Readiness</p>
<p class="verdict-label">{_STATE_LABELS[state]}</p>
<p class="verdict-gloss">{_esc(_STATE_GLOSS[state])}</p>
{reasons_block}
</section>
<section class="statband">
<div class="stat"><span class="stat-num">{available}/{len(report.artifacts)}</span>\
<span class="stat-label">sources available</span></div>
<div class="stat"><span class="stat-num">{len(report.risks)}</span>\
<span class="stat-label">risks tracked</span></div>
<div class="stat{blocker_class}"><span class="stat-num">{report.uncovered_blocker_count}</span>\
<span class="stat-label">uncovered blockers</span></div>
<div class="stat"><span class="stat-num">{len(report.warnings)}</span>\
<span class="stat-label">warnings</span></div>
</section>
<section>
<h2>Artifact inventory</h2>
{_artifact_section(report.artifacts)}
</section>
<section>
<h2>Change impact</h2>
{_impact_section(report)}
</section>
<section>
<h2>Risk ledger</h2>
{_risk_section(report.risks)}
</section>
<section>
<h2>Evidence</h2>
{_evidence_section(report.evidence)}
</section>
<section>
<h2>Warnings</h2>
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
