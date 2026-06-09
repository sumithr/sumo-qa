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
  :root { color-scheme: light; }
  body {
    margin: 0; padding: 2.5rem 1.5rem 4rem;
    background: #FAF7F2; color: #1B1B1B;
    font-family: Charter, "Iowan Old Style", Georgia, serif;
    font-size: 16px; line-height: 1.55;
  }
  main, header.masthead, footer { max-width: 60rem; margin: 0 auto; }
  header.masthead { border-bottom: 3px double #7A1F1F; padding-bottom: 1rem; }
  header.masthead h1 { margin: 0; font-size: 1.9rem; color: #7A1F1F; font-weight: 600; }
  header.masthead .kicker {
    margin: 0 0 0.35rem; font-size: 0.78rem; letter-spacing: 0.18em;
    text-transform: uppercase; color: #8A7B5C;
  }
  dl.meta { display: grid; grid-template-columns: max-content 1fr; gap: 0.15rem 1.2rem; margin: 1rem 0 0; }
  dl.meta dt { font-size: 0.78rem; letter-spacing: 0.12em; text-transform: uppercase; color: #8A7B5C; }
  dl.meta dd { margin: 0; font-variant-numeric: tabular-nums; }
  section { margin-top: 2.2rem; }
  h2 {
    font-size: 1.05rem; letter-spacing: 0.14em; text-transform: uppercase;
    color: #7A1F1F; border-bottom: 1px solid #E2D9C8; padding-bottom: 0.3rem;
  }
  h3 { font-size: 0.95rem; margin: 1.4rem 0 0.4rem; }
  .banner { padding: 1.1rem 1.3rem; border-left: 0.5rem solid; }
  .banner .verdict-label { margin: 0; font-size: 1.6rem; font-weight: 700; }
  .banner.state-good { background: #E8EDDF; color: #3F4A2E; border-color: #3F4A2E; }
  .banner.state-warm { background: #F0EAE0; color: #8A7B5C; border-color: #8A7B5C; }
  .banner.state-bad { background: #7A1F1F; color: #FAF7F2; border-color: #1B1B1B; }
  .banner.state-neutral { background: #F0EAE0; color: #1B1B1B; border-color: #8A7B5C; }
  .banner ul.reasons { margin: 0.6rem 0 0; padding-left: 1.2rem; }
  .banner p.reasons-none { margin: 0.6rem 0 0; }
  table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
  th {
    text-align: left; font-size: 0.72rem; letter-spacing: 0.14em;
    text-transform: uppercase; color: #8A7B5C;
    border-bottom: 2px solid #7A1F1F; padding: 0.35rem 0.6rem 0.35rem 0;
  }
  td { padding: 0.45rem 0.6rem 0.45rem 0; border-bottom: 1px solid #E2D9C8; vertical-align: top; }
  td.more, li.more { font-style: italic; color: #8A7B5C; }
  .badge {
    display: inline-block; padding: 0.05rem 0.5rem; font-size: 0.78rem;
    border: 1px solid; border-radius: 2px; white-space: nowrap;
  }
  .badge.ok { color: #3F4A2E; background: #E8EDDF; border-color: #3F4A2E; }
  .badge.warm { color: #8A7B5C; background: #F0EAE0; border-color: #8A7B5C; }
  .badge.bad { color: #FAF7F2; background: #7A1F1F; border-color: #7A1F1F; }
  .badge.off { color: #1B1B1B; background: #F0EAE0; border-color: #8A7B5C; }
  p.empty { color: #8A7B5C; font-style: italic; }
  ul.warnings li { color: #7A1F1F; }
  footer { margin-top: 3rem; border-top: 1px solid #E2D9C8; padding-top: 0.6rem;
    font-size: 0.82rem; color: #8A7B5C; }
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
    reasons = "".join(f"<li>{_esc(reason)}</li>" for reason in report.readiness.reasons)
    reasons_block = (
        f'<ul class="reasons">{reasons}</ul>'
        if reasons
        else '<p class="reasons-none">All composed signals are green.</p>'
    )
    available = sum(1 for artifact in report.artifacts if artifact.status == "available")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>QA report &#8212; {_esc(project.name or project.root)}</title>
<style>{_STYLE}</style>
</head>
<body>
<header class="masthead">
<p class="kicker">sumo-qa &#183; local QA report</p>
<h1>{_esc(project.name or project.root)}</h1>
<dl class="meta">
<dt>root</dt><dd>{_esc(project.root)}</dd>
<dt>head commit</dt><dd>{_dash(project.head_commit)}</dd>
<dt>generated</dt><dd>{_esc(project.generated_at.isoformat())}</dd>
<dt>artifacts</dt><dd>{available} of {len(report.artifacts)} available &#183; \
{len(report.risks)} risks &#183; {report.uncovered_blocker_count} uncovered blockers &#183; \
{len(report.warnings)} warnings</dd>
</dl>
</header>
<main>
<section class="banner {_STATE_CLASSES[state]}">
<p class="verdict-label">{_STATE_LABELS[state]}</p>
{reasons_block}
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
<footer>
Generated by {_esc(project.generator_version)} &#183; report schema {_esc(report.schema_version)}
</footer>
</body>
</html>
"""
