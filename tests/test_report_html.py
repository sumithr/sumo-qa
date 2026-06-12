# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.report_html — the static QA report renderer (#157).

The renderer is pure deterministic projection, so the contract is pinned the
same way the export renderers are: byte-for-byte snapshots. The five goldens
under tests/fixtures/report/ are the issue's required fixture states
(full-data, ready-with-residuals, stale-evidence, blocked, partial-data),
built by scripts/regen_report_snapshots.py — this module imports that script's
case table so the goldens and the assertions can never drift apart. On a
deliberate renderer change, regenerate via
`uv run python scripts/regen_report_snapshots.py` and inspect the diff in the
same PR.
"""

from __future__ import annotations

import importlib.util
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sumo_qa.report_html import render_report_html
from sumo_qa.report_models import (
    QAReport,
    ReportArtifact,
    ReportComponent,
    ReportEvidence,
    ReportProject,
    ReportReadiness,
    ReportRisk,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "report"

_spec = importlib.util.spec_from_file_location(
    "regen_report_snapshots", REPO_ROOT / "scripts" / "regen_report_snapshots.py"
)
assert _spec is not None and _spec.loader is not None
_regen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_regen)

_CASE_REPORTS = _regen.build_case_reports()

_NOW = datetime(2026, 6, 8, 8, 0, 0, tzinfo=timezone.utc)


def _minimal_report(**overrides) -> QAReport:
    data = {
        "schema_version": "1.0",
        "project": ReportProject(
            root="/fixtures/minimal",
            name="minimal",
            head_commit=None,
            generated_at=_NOW,
            generator_version="sumo-qa 0.0.0-fixture",
        ),
        "artifacts": [
            ReportArtifact(kind=kind, status="missing", path=None, detail=None)
            for kind in (
                "repo_map",
                "diff_impact",
                "risk_ledger",
                "context_bundle",
                "readiness_scorecard",
                "coverage_mutation",
            )
        ],
        "readiness": ReportReadiness(state="insufficient_evidence", reasons=["nothing recorded"]),
    }
    data.update(overrides)
    return QAReport(**data)


# ---------------------------------------------------------------------------
# golden snapshots — the five issue-mandated states
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", sorted(_CASE_REPORTS), ids=lambda c: c)
def test_golden_snapshot_is_byte_for_byte_stable(case):
    golden = GOLDEN_DIR / f"{case}.html"
    assert golden.is_file(), (
        f"missing golden {golden}; run `uv run python scripts/regen_report_snapshots.py` "
        "and commit the result with a rationale"
    )
    assert render_report_html(_CASE_REPORTS[case]) == golden.read_text(encoding="utf-8")


def test_render_is_deterministic_across_calls():
    report = _CASE_REPORTS["full-data-ready"]
    assert render_report_html(report) == render_report_html(report)


@pytest.mark.parametrize("case", sorted(_CASE_REPORTS), ids=lambda c: c)
def test_report_is_self_contained_static_html(case):
    """No network access and no hosted service (AC): nothing in the page may
    fetch — no scripts, stylesheets links, images, imports, or remote fonts."""
    html = render_report_html(_CASE_REPORTS[case])
    lowered = html.lower()
    assert lowered.startswith("<!doctype html>")
    for forbidden in ("<script", "<link", "<img", "src=", "@import", "url(", "http://", "https://"):
        assert forbidden not in lowered, f"{forbidden!r} found in rendered report"


@pytest.mark.parametrize("case", sorted(_CASE_REPORTS), ids=lambda c: c)
def test_report_carries_no_tracker_issue_references(case):
    """The page is product output rendered on ANY target repo: a bare '#N'
    reads as the TARGET repo's issue number, so sumo-qa's internal tracker
    references must never leak into it. The stylesheet is stripped first (CSS
    hex colours) and HTML character entities (&#183;) are excluded via the
    (?<!&) guard — everything else containing '#digits' is a leak."""
    html = render_report_html(_CASE_REPORTS[case])
    body = re.sub(r"<style>.*?</style>", "", html, flags=re.S)
    leaked = re.findall(r"(?<!&)#\d+", body)
    assert not leaked, f"tracker references leaked into the rendered page: {leaked}"


def test_missing_states_are_visibly_distinct_from_passing():
    """AC: the report must distinguish missing data from passing evidence."""
    html = render_report_html(_CASE_REPORTS["partial-data"])
    assert "not available" in html.lower()
    blocked = render_report_html(_CASE_REPORTS["blocked"])
    assert "blocked" in blocked.lower()


def test_readiness_state_is_prominent_per_case():
    expectations = {
        "full-data-ready": "ready",
        "ready-with-residuals": "ready with accepted residuals",
        "stale-evidence": "insufficient evidence",
        "blocked": "blocked",
        "partial-data": "insufficient evidence",
    }
    for case, label in expectations.items():
        assert label in render_report_html(_CASE_REPORTS[case]).lower()


# ---------------------------------------------------------------------------
# escaping — artifact strings are attacker-ish input to the page
# ---------------------------------------------------------------------------


def test_hostile_artifact_strings_are_escaped():
    report = _minimal_report(
        risks=[
            ReportRisk(
                risk_id="R1",
                risk='<script>alert("x")</script> & "quotes"',
                source_anchor="src/<b>bold</b>.py:1",
                test="planned: <img src=x onerror=alert(1)>",
                evidence_status="planned",
                residual="open",
                repo_map_node_id=None,
                uncovered_blocker=False,
            )
        ],
    )
    html = render_report_html(report)
    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html
    assert "onerror" not in html or "&lt;img" in html


def test_warnings_are_rendered_and_escaped():
    """Cross-artifact warnings (e.g. a bundle/local head-commit conflict) must
    surface on the page, escaped like every other artifact-supplied string."""
    report = _minimal_report(warnings=["head <b>conflict</b> detected against local state"])
    html = render_report_html(report)
    assert "head" in html
    assert "&lt;b&gt;conflict&lt;/b&gt;" in html
    assert "<b>conflict</b>" not in html


def test_hostile_project_strings_are_escaped():
    report = _minimal_report(
        project=ReportProject(
            root='/tmp/<script>"evil"</script>',
            name="<svg/onload=alert(1)>",
            head_commit=None,
            generated_at=_NOW,
            generator_version="sumo-qa 0.0.0-fixture",
        )
    )
    html = render_report_html(report)
    assert "<svg" not in html
    assert "&lt;svg" in html


# ---------------------------------------------------------------------------
# bounded output
# ---------------------------------------------------------------------------


def _risk(risk_id, *, evidence="passing", residual="mitigated", blocker=False) -> ReportRisk:
    return ReportRisk(
        risk_id=risk_id,
        risk=f"risk {risk_id}",
        source_anchor=f"src/{risk_id}.py:1",
        test=f"tests/test_{risk_id}.py::t",
        evidence_status=evidence,
        residual=residual,
        repo_map_node_id=f"file:src/{risk_id}.py",
        uncovered_blocker=blocker,
    )


def test_stat_band_cells_link_to_their_sections():
    """Counts navigate (move 1): every stat cell is an anchor to the section
    that proves its number."""
    html = render_report_html(_minimal_report())
    for target in ("#inventory", "#risks", "#warnings"):
        assert f'href="{target}"' in html
    assert '<a class="stat' in html


def test_risk_rows_carry_anchors_and_verdict_reasons_link_to_them():
    """A verdict reason that names a risk id links to that ledger row."""
    report = _minimal_report(
        readiness=ReportReadiness(state="blocked", reasons=["R2: risk R2 — planned but not run"]),
        risks=[_risk("R1"), _risk("R2", evidence="planned", residual="blocker", blocker=True)],
    )
    html = render_report_html(report)
    assert 'id="risk-R2"' in html
    assert '<a href="#risk-R2">R2</a>' in html


def test_verdict_reason_links_risk_ids_with_unusual_characters():
    """Ledger ids only need to be nonblank — linkification matches the exact
    id by string, not a tidy-identifier regex."""
    report = _minimal_report(
        readiness=ReportReadiness(state="blocked", reasons=["R 2: spaced id — failing"]),
        risks=[_risk("R 2", evidence="failing", residual="blocker", blocker=True)],
    )
    html = render_report_html(report)
    assert '<a href="#risk-R 2">R 2</a>' in html


def test_unmapped_only_impact_is_not_badged_no_data():
    """unmapped_files IS impact data: the rollup badge must not say 'no data'
    above a section that renders rows."""
    html = render_report_html(_minimal_report(unmapped_files=["mystery.py"]))
    section = html[html.find('id="impact"') : html.find('id="risks"')]
    assert "no data" not in section
    assert "mystery.py" in section


def test_verdict_reason_without_matching_risk_stays_plain():
    report = _minimal_report(
        readiness=ReportReadiness(
            state="insufficient_evidence", reasons=["no QA evidence supplied"]
        ),
    )
    html = render_report_html(report)
    assert "no QA evidence supplied" in html
    assert 'href="#risk-' not in html


def test_section_headings_carry_status_rollups():
    """Move 2: a scroll is a colour scan — each section heading carries a
    short state badge."""
    report = _minimal_report(
        risks=[_risk("R1", evidence="planned", residual="blocker", blocker=True)],
        warnings=["bundle conflict"],
    )
    html = render_report_html(report)
    assert "1 uncovered blocker" in html
    assert "0 of 6 available" in html
    assert "1 warning" in html
    # An invalid artifact outranks stale/missing in the inventory rollup.
    invalid = [
        ReportArtifact(kind="repo_map", status="invalid", path=None, detail="[x] bad"),
        ReportArtifact(kind="diff_impact", status="stale", path=None, detail=None),
    ]
    assert "1 invalid" in render_report_html(_minimal_report(artifacts=invalid))


def test_risk_rows_sort_severity_first_before_the_cap():
    """Move 3: uncovered blockers sort to the top, then rows without passing
    evidence — the row cap must truncate the SAFE end, never the findings."""
    report = _minimal_report(
        risks=[_risk("R1"), _risk("R2", evidence="planned"), _risk("R3", blocker=True)]
    )
    html = render_report_html(report)
    assert html.find('id="risk-R3"') < html.find('id="risk-R2"') < html.find('id="risk-R1"')


def test_clean_sections_collapse_green():
    """Move 3: a fully clean section folds away (Lighthouse's passed-audits
    move); a section with any non-available state stays open."""
    clean_artifacts = [
        ReportArtifact(kind=kind, status="available", path=None, detail=None)
        for kind in (
            "repo_map",
            "diff_impact",
            "risk_ledger",
            "context_bundle",
            "readiness_scorecard",
            "coverage_mutation",
        )
    ]
    html = render_report_html(_minimal_report(artifacts=clean_artifacts))
    inv = html[html.find('id="inventory"') :]
    assert inv.index("<details>") < inv.index("<table>")
    # default report has missing artifacts -> inventory stays open
    html_open = render_report_html(_minimal_report())
    inv_open = html_open[html_open.find('id="inventory"') : html_open.find('id="impact"')]
    assert "<table>" in inv_open and "<details>" not in inv_open


def test_sections_lead_with_one_sentence_findings():
    """Move 5: the sentence is the report; the table is the appendix."""
    report = _minimal_report(
        risks=[_risk("R1"), _risk("R2", evidence="planned", residual="blocker", blocker=True)]
    )
    html = render_report_html(report)
    assert '<p class="lead">' in html
    assert "1 of 2 risks is an uncovered blocker" in html


def test_ledger_demotes_provenance_and_evidence_meta_is_quiet():
    """Move 6: provenance never competes with signal — the repo-map node
    column is gone from the ledger (it duplicates the anchor), and the
    evidence table's source/captured-at cells render in the quiet meta
    style."""
    report = _minimal_report(risks=[_risk("R1")])
    html = render_report_html(report)
    assert "repo-map node" not in html
    assert "file:src/R1.py" not in html
    with_evidence = _minimal_report(
        evidence=[
            ReportEvidence(
                name="tests",
                status="passing",
                freshness="fresh",
                trustworthy=True,
                source="local_git",
                captured_at="2026-06-08T07:30:00+00:00",
                detail=None,
            )
        ]
    )
    assert 'class="meta"' in render_report_html(with_evidence)


def test_delta_line_shows_what_changed_since_previous_run():
    """Move 7: the dateline carries the run-over-run trend — only the
    quantities that changed, verdict first."""
    from sumo_qa.report_models import ReportPreviousRun

    report = _minimal_report(
        readiness=ReportReadiness(state="ready", reasons=[]),
        previous_run=ReportPreviousRun(
            generated_at=datetime(2026, 6, 7, 8, 0, 0, tzinfo=timezone.utc),
            readiness_state="blocked",
            risk_count=3,
            uncovered_blocker_count=1,
            sources_available=0,
        ),
    )
    html = render_report_html(report)
    assert '<p class="delta">' in html
    assert "verdict blocked &#8594; ready" in html
    assert "risks 3 &#8594; 0" in html
    assert "uncovered blockers 1 &#8594; 0" in html

    available = _minimal_report(
        artifacts=[ReportArtifact(kind="repo_map", status="available", path=None, detail=None)],
        previous_run=ReportPreviousRun(
            generated_at=datetime(2026, 6, 7, 8, 0, 0, tzinfo=timezone.utc),
            readiness_state="insufficient_evidence",
            risk_count=0,
            uncovered_blocker_count=0,
            sources_available=0,
        ),
    )
    assert "sources available 0 &#8594; 1" in render_report_html(available)


def test_delta_line_reports_no_change_and_is_absent_without_previous():
    from sumo_qa.report_models import ReportPreviousRun

    unchanged = _minimal_report(
        previous_run=ReportPreviousRun(
            generated_at=datetime(2026, 6, 7, 8, 0, 0, tzinfo=timezone.utc),
            readiness_state="insufficient_evidence",
            risk_count=0,
            uncovered_blocker_count=0,
            sources_available=0,
        )
    )
    html = render_report_html(unchanged)
    assert "no change since previous run" in html
    assert 'class="delta"' not in render_report_html(_minimal_report())


def test_mapped_tests_renders_na_for_non_source_rows():
    """'no' must only ever appear where it indicts: source_file rows keep
    their yes/no verdict; every other type renders the muted 'n/a' marker (never
    an em-dash), so a docs or fixture row can never read as a coverage gap."""
    components = [
        ReportComponent(
            id="file:src/a.py", path="src/a.py", type="source_file", has_mapped_tests=False
        ),
        ReportComponent(id="file:README.md", path="README.md", type="docs"),
    ]
    report = _minimal_report(changed_components=components)
    html = render_report_html(report)
    assert '<td class="brk">src/a.py</td><td>no</td>' in html
    assert '<td class="brk">README.md</td><td><span class="na">n/a</span></td>' in html
    assert html.count("<td>no</td>") == 1
    # No em-dash anywhere on the page — it reads as an unfinished/AI-slop tell.
    assert "—" not in html and "&#8212;" not in html


def test_machine_tokens_are_humanized_on_the_page():
    """The page is editorial: no raw snake_case enum or machine node-id prefix
    reaches the reader. Component rows read the type as plain words and a short
    name (the full path is its own column); evidence reads its source and
    freshness humanized — ``absent`` becomes the same 'not available' the
    inventory uses, never the bare enum the user would otherwise see."""
    report = _minimal_report(
        changed_components=[
            ReportComponent(
                id="file:src/billing/refund.py",
                path="src/billing/refund.py",
                type="source_file",
                has_mapped_tests=True,
            ),
        ],
        affected_components=[
            ReportComponent(
                id="file:tests/test_refund.py", path="tests/test_refund.py", type="test_file"
            ),
        ],
        evidence=[
            ReportEvidence(
                name="coverage",
                status="missing",
                freshness="absent",
                trustworthy=False,
                source="local_git",
            ),
        ],
    )
    html = render_report_html(report)
    # No raw machine tokens anywhere on the rendered page.
    for token in ("source_file", "test_file", "file:", "local_git", ">absent<"):
        assert token not in html, f"machine token {token!r} leaked to the page"
    # Component type reads as plain words; the short name leads, full path stays.
    assert "<td>source</td>" in html and "<td>test</td>" in html
    assert '<td class="brk">refund.py</td>' in html  # short name in the component column
    assert '<td class="brk">src/billing/refund.py</td>' in html  # full path retained
    # Evidence source de-underscored; absent freshness reads as 'not available'.
    assert '<td class="meta">local git</td>' in html
    assert "<td>not available</td>" in html


def test_change_impact_sections_collapse_by_default():
    """The page is a summary of findings, not an enumeration: the changed /
    affected / related-tests / unmapped sections render as native <details>
    collapsed by default, each summarised to a count line with a type
    breakdown. The risk surface — the indictment — stays open."""
    report = _minimal_report(
        changed_components=[
            ReportComponent(
                id="file:src/a.py", path="src/a.py", type="source_file", has_mapped_tests=True
            ),
            ReportComponent(id="file:README.md", path="README.md", type="docs"),
            ReportComponent(id="file:conf.yml", path="conf.yml", type="config"),
        ],
        affected_components=[
            ReportComponent(id="file:tests/test_a.py", path="tests/test_a.py", type="test_file"),
        ],
        related_tests=["tests/test_a.py", "tests/test_b.py"],
        risk_surface=["src/lonely.py"],
        unmapped_files=["new.py"],
    )
    html = render_report_html(report)
    # Collapsed by default: <details> without the open attribute.
    assert "<details>" in html
    assert "<details open" not in html
    # Count-line summaries with type breakdowns (source/test/docs named,
    # everything else bucketed as other).
    assert "<summary>3 files changed: 1 source &#183; 1 docs &#183; 1 other</summary>" in html
    assert "<summary>1 affected component (one hop): 1 test</summary>" in html
    assert "<summary>2 related tests</summary>" in html
    assert "<summary>1 unmapped file</summary>" in html
    # The full rows are still there, one click away.
    assert '<td class="brk">src/a.py</td><td>yes</td>' in html
    assert "<li>tests/test_b.py</li>" in html
    # The risk surface is NOT collapsed — it must indict at first glance.
    risk_pos = html.find("Risk surface")
    assert risk_pos != -1
    assert "<h3>" in html[risk_pos - 4 : risk_pos]
    assert "<li>src/lonely.py</li>" in html


def test_empty_collapsed_sections_are_omitted_but_risk_surface_keeps_empty_state():
    """An empty enumeration earns no collapsed stub; the risk surface keeps
    its honest 'none recorded' line even when empty."""
    report = _minimal_report(
        changed_components=[
            ReportComponent(
                id="file:src/a.py", path="src/a.py", type="source_file", has_mapped_tests=True
            )
        ],
        affected_components=[],
        related_tests=[],
        unmapped_files=[],
        risk_surface=[],
    )
    html = render_report_html(report)
    assert "affected component" not in html
    assert "related test" not in html
    assert "unmapped file" not in html
    assert "Risk surface" in html and "none recorded" in html


def test_long_component_tables_truncate_with_notice():
    components = [
        ReportComponent(
            id=f"src/mod_{i:03d}.py",
            path=f"src/mod_{i:03d}.py",
            type="source_file",
            has_mapped_tests=False,
        )
        for i in range(120)
    ]
    report = _minimal_report(changed_components=components)
    html = render_report_html(report)
    assert "src/mod_000.py" in html
    assert "src/mod_119.py" not in html
    assert "more" in html.lower()  # an explicit "+N more" style notice


def test_long_readiness_reason_lists_truncate_with_notice():
    """Reasons scale 1:1 with ledger rows — the banner is a list like any
    other and must honour the same bound."""
    from sumo_qa.report_models import ReportReadiness

    reasons = [f"risk R{i} is an uncovered blocker" for i in range(120)]
    report = _minimal_report(readiness=ReportReadiness(state="blocked", reasons=reasons))
    html = render_report_html(report)
    assert "risk R0 is an uncovered blocker" in html
    assert "risk R119 is an uncovered blocker" not in html
    assert "more" in html.lower()
