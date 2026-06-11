# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Regenerate tests/fixtures/report/*.html from the report renderer (#157).

The five cases mirror the issue's required fixture states — full-data (ready),
ready-with-residuals, stale-evidence, blocked, and partial-data — built from
fully pinned inputs (fixed clock, fixed generator version, fixed fake root) so
the rendered HTML is byte-for-byte deterministic across machines and releases.

tests/test_report_html.py imports this module's case table, so the goldens and
the assertions can never drift apart. Run when a deliberate renderer or model
change lands and the snapshot test fails. Always inspect the diff before
committing — the snapshot exists to make drift visible, so a 'just regen'
workflow defeats the purpose. Include a one-line rationale in the same commit.

Usage:
    uv run python scripts/regen_report_snapshots.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from sumo_qa.context_bundle_models import ContextBundle  # noqa: E402
from sumo_qa.ledger_models import RiskLedger  # noqa: E402
from sumo_qa.repo_map_models import DiffImpact, RepoMap  # noqa: E402
from sumo_qa.report_builder import ArtifactSource, ReportInputs, build_report  # noqa: E402
from sumo_qa.report_html import render_report_html  # noqa: E402

GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "report"

# Pinned so the goldens never depend on the wall clock or the release version.
FIXED_NOW = datetime(2026, 6, 8, 8, 0, 0, tzinfo=timezone.utc)
FIXED_VERSION = "sumo-qa 0.0.0-fixture"
SHA_FRESH = "f" * 40
SHA_STALE = "0" * 40


def _repo_map(root: str, *, git_commit: str | None) -> RepoMap:
    return RepoMap.model_validate(
        {
            "schema_version": "1.0",
            "project": {
                "root": root,
                "name": root.rsplit("/", 1)[-1],
                "git_commit": git_commit,
                "generated_at": "2026-06-01T12:00:00+00:00",
                "generator_version": FIXED_VERSION,
            },
            "nodes": [
                {
                    "id": "src/billing/refund.py",
                    "type": "source_file",
                    "path": "src/billing/refund.py",
                },
                {"id": "tests/test_refund.py", "type": "test_file", "path": "tests/test_refund.py"},
                {
                    "id": ".github/workflows/ci.yml",
                    "type": "ci_workflow",
                    "path": ".github/workflows/ci.yml",
                },
            ],
            "edges": [
                {
                    "source": "tests/test_refund.py",
                    "target": "src/billing/refund.py",
                    "type": "likely_tests",
                    "confidence": "high",
                    "reason": "name match",
                }
            ],
            "commands": [
                {"name": "pytest", "kind": "test", "source": "pyproject.toml"},
            ],
            "warnings": [],
        }
    )


def _diff_impact() -> DiffImpact:
    return DiffImpact.model_validate(
        {
            "changed_nodes": [
                {
                    "id": "src/billing/refund.py",
                    "type": "source_file",
                    "path": "src/billing/refund.py",
                    "has_mapped_tests": True,
                }
            ],
            "affected_nodes": [
                {
                    "id": "tests/test_refund.py",
                    "type": "test_file",
                    "path": "tests/test_refund.py",
                    "has_mapped_tests": False,
                }
            ],
            "related_tests": ["tests/test_refund.py"],
            "unmapped_files": ["docs/refund-notes.md"],
            "risk_surface": ["src/billing/refund.py"],
            "suggested_inspections": ["double-refund idempotency"],
            "warnings": [],
            "probable_mapping_gap": False,
        }
    )


def _ledger(rows: list[dict]) -> RiskLedger:
    return RiskLedger.model_validate({"schema_version": "1.0", "rows": rows})


_ROW_PASSING = {
    "risk_id": "R1",
    "risk": "Refund applied twice on a retried request",
    "source_anchor": "src/billing/refund.py:42",
    "test": "tests/test_refund.py::test_refund_is_idempotent",
    "evidence_status": "passing",
    "residual": "mitigated",
    "repo_map_node_id": "src/billing/refund.py",
}

_ROW_RESIDUAL = {
    "risk_id": "R2",
    "risk": "Legacy ledger export drifts on partial refunds",
    "source_anchor": "src/billing/export.py:9",
    "test": "accepted: manual quarterly reconciliation",
    "evidence_status": "accepted_residual",
    "residual": "accepted",
}

_ROW_BLOCKER = {
    "risk_id": "R3",
    "risk": "Currency rounding regresses on multi-line refunds",
    "source_anchor": "src/billing/rounding.py:17",
    "test": "tests/test_rounding.py::test_multi_line_refund",
    "evidence_status": "failing",
    "residual": "blocker",
}

_ROW_STALE = {
    "risk_id": "R4",
    "risk": "Webhook retry storm duplicates refund events",
    "source_anchor": "src/billing/webhooks.py:88",
    "test": "tests/test_webhooks.py::test_retry_dedupe",
    "evidence_status": "stale",
    "residual": "open",
}


def _bundle(*, tests_freshness: str = "fresh", ci_freshness: str = "fresh") -> ContextBundle:
    return ContextBundle.model_validate(
        {
            "schema_version": "1.0",
            "issue_summary": "Refund idempotency hardening",
            "head_sha": SHA_FRESH,
            "changed_files": [{"path": "src/billing/refund.py", "change_kind": "modified"}],
            "test_evidence": {
                "result": "passing",
                "freshness": tests_freshness,
                "source": "local_git",
                "captured_at": "2026-06-08T07:30:00+00:00",
            },
            "ci_status": {
                "result": "passing",
                "freshness": ci_freshness,
                "source": "ci_provider",
                "captured_at": "2026-06-08T07:45:00+00:00",
            },
        }
    )


def _absent(detail: str | None = None) -> ArtifactSource:
    return ArtifactSource(path=None, error=None, inline=False, detail=detail)


def _on_disk(path: str) -> ArtifactSource:
    return ArtifactSource(path=path, error=None, inline=False, detail=None)


def _inputs(case: str, **overrides) -> ReportInputs:
    root = f"/fixtures/{case}"
    data = {
        "root": root,
        "current_commit": SHA_FRESH,
        "repo_map": _repo_map(root, git_commit=SHA_FRESH),
        "repo_map_source": _on_disk(".sumo-qa/repo-map.json"),
        "diff_impact": _diff_impact(),
        "diff_impact_source": _on_disk(".sumo-qa/diff-impact.json"),
        "ledger": _ledger([_ROW_PASSING]),
        "ledger_source": _on_disk(".sumo-qa/risk-ledger.json"),
        "bundle": _bundle(),
        "bundle_source": _on_disk(".sumo-qa/context-bundle.json"),
    }
    data.update(overrides)
    return ReportInputs.model_validate(data)


def build_case_reports() -> dict[str, object]:
    """The five issue-mandated fixture states, keyed by golden filename stem."""
    root_stale = "/fixtures/stale-evidence"
    cases = {
        "full-data-ready": _inputs("full-data-ready"),
        "ready-with-residuals": _inputs(
            "ready-with-residuals",
            ledger=_ledger([_ROW_PASSING, _ROW_RESIDUAL]),
        ),
        "stale-evidence": _inputs(
            "stale-evidence",
            current_commit=SHA_FRESH,
            repo_map=_repo_map(root_stale, git_commit=SHA_STALE),
            ledger=_ledger([_ROW_PASSING, _ROW_STALE]),
            bundle=_bundle(tests_freshness="stale"),
        ),
        "blocked": _inputs(
            "blocked",
            ledger=_ledger([_ROW_PASSING, _ROW_BLOCKER]),
        ),
        "partial-data": _inputs(
            "partial-data",
            current_commit=None,
            diff_impact=None,
            diff_impact_source=_absent(),
            ledger=None,
            ledger_source=_absent(),
            bundle=None,
            bundle_source=_absent(),
        ),
    }
    return {
        name: build_report(inputs, now=FIXED_NOW, generator_version=FIXED_VERSION)
        for name, inputs in cases.items()
    }


def main() -> int:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for name, report in sorted(build_case_reports().items()):
        target = GOLDEN_DIR / f"{name}.html"
        target.write_text(render_report_html(report), encoding="utf-8")
        print(f"wrote {target.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
