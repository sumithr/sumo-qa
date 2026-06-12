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


def test_mapped_tests_renders_em_dash_for_non_source_rows():
    """'no' must only ever appear where it indicts: source_file rows keep
    their yes/no verdict; every other type renders an em-dash, so a docs or
    fixture row can never read as a coverage gap."""
    components = [
        ReportComponent(
            id="file:src/a.py", path="src/a.py", type="source_file", has_mapped_tests=False
        ),
        ReportComponent(id="file:README.md", path="README.md", type="docs"),
    ]
    report = _minimal_report(changed_components=components)
    html = render_report_html(report)
    assert '<td class="brk">src/a.py</td><td>no</td>' in html
    assert '<td class="brk">README.md</td><td>&#8212;</td>' in html
    assert html.count("<td>no</td>") == 1


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
