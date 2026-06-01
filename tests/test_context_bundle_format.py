# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for sumo_qa.context_bundle_format — the deterministic markdown
projection of a context bundle (issue #149).

The projection MUST be honest about freshness: a stale (or otherwise non-fresh)
go-stale fact produces an explicit stale-evidence warning, and a bundle-vs-local
sha conflict produces a conflict block. Output must stay bounded for a large
diff and survive separator-injection in free-text fields.
"""

from __future__ import annotations

from sumo_qa.context_bundle_format import (
    compact_summary,
    format_context_bundle_markdown,
)
from sumo_qa.context_bundle_models import CONTEXT_BUNDLE_SCHEMA_VERSION, ContextBundle


def _bundle(**overrides) -> ContextBundle:
    data = {"schema_version": CONTEXT_BUNDLE_SCHEMA_VERSION}
    data.update(overrides)
    return ContextBundle.model_validate(data)


def test_empty_bundle_renders_without_warnings():
    md = format_context_bundle_markdown(_bundle())
    assert "**Context bundle**" in md
    assert "Changed files:** none supplied" in md
    assert "Stale-evidence warning" not in md
    assert "Conflict" not in md


def test_fresh_passing_evidence_has_no_stale_warning():
    bundle = _bundle(
        test_evidence={"result": "passing", "freshness": "fresh", "source": "local_git"},
        ci_status={"result": "passing", "freshness": "fresh", "source": "ci_provider"},
    )
    md = format_context_bundle_markdown(bundle)
    assert "Stale-evidence warning" not in md


def test_stale_ci_emits_warning_block():
    bundle = _bundle(
        ci_status={"result": "passing", "freshness": "stale", "source": "ci_provider"},
    )
    md = format_context_bundle_markdown(bundle)
    assert "Stale-evidence warning" in md
    assert "`ci_status` is NOT safety-supporting (stale)" in md
    assert "do not claim safety from it" in md


def test_unknown_freshness_pass_also_warned():
    # A stale-only check would miss this; the safety projection must flag it.
    bundle = _bundle(
        test_evidence={"result": "passing", "freshness": "unknown", "source": "manual"},
    )
    md = format_context_bundle_markdown(bundle)
    assert "Stale-evidence warning" in md
    assert "`test_evidence` is NOT safety-supporting" in md


def test_conflict_block_emitted_on_sha_mismatch():
    bundle = _bundle(head_sha="aaa")
    md = format_context_bundle_markdown(bundle, local_head_sha="bbb")
    assert "Conflict — bundle vs. local state" in md
    assert "aaa" in md and "bbb" in md


def test_no_conflict_block_when_shas_match():
    bundle = _bundle(head_sha="aaa")
    md = format_context_bundle_markdown(bundle, local_head_sha="aaa")
    assert "Conflict" not in md


def test_changed_files_truncated_past_cap():
    files = [{"path": f"f{i}.py"} for i in range(5)]
    bundle = _bundle(changed_files=files)
    md = format_context_bundle_markdown(bundle, max_files=2)
    assert "+3 more file(s) truncated" in md


def test_separator_injection_flattened_in_summary_fields():
    # A newline-laden issue summary must not break the bullet structure or
    # inject a fresh markdown line.
    bundle = _bundle(issue_summary="line one\n\n## Injected heading\nline two")
    md = format_context_bundle_markdown(bundle)
    issue_line = next(line for line in md.splitlines() if line.startswith("- **Issue:**"))
    assert "## Injected heading" in issue_line  # stayed on the one bullet line
    assert "\n" not in issue_line


def test_compact_summary_reports_evidence_and_conflict():
    bundle = _bundle(
        head_sha="aaa",
        changed_files=[{"path": "a.py"}, {"path": "b.py"}],
        test_evidence={"result": "passing", "freshness": "fresh", "source": "local_git"},
        ci_status={"result": "passing", "freshness": "stale", "source": "ci_provider"},
    )
    summary = compact_summary(bundle, local_head_sha="bbb")
    assert "2 changed file(s)" in summary
    assert "tests passing/fresh" in summary
    assert "CI passing/stale" in summary
    assert "1 non-fresh evidence field(s)" in summary
    assert "bundle-vs-local conflict" in summary


def test_full_bundle_renders_all_optional_sections():
    # Exercises pr_summary, captured_at + detail on an evidence fact, and the
    # user-constraints list rendering.
    bundle = _bundle(
        pr_summary="Add idempotency key.",
        test_evidence={
            "result": "passing",
            "freshness": "fresh",
            "source": "local_git",
            "captured_at": "2026-06-01T10:00:00Z",
            "detail": "211 passed",
        },
        user_constraints=["No schema changes.", "No new dependencies."],
    )
    md = format_context_bundle_markdown(bundle)
    assert "**PR:** Add idempotency key." in md
    assert "captured_at=2026-06-01T10:00:00Z" in md
    assert "211 passed" in md
    assert "- **Constraints:**" in md
    assert "  - No schema changes." in md
    assert "  - No new dependencies." in md


def test_stale_test_evidence_field_is_listed():
    # Covers the test_evidence stale branch (distinct from ci_status).
    bundle = _bundle(
        test_evidence={"result": "passing", "freshness": "stale", "source": "local_git"},
    )
    assert bundle.stale_evidence_fields() == ["test_evidence"]
    md = format_context_bundle_markdown(bundle)
    assert "`test_evidence` is NOT safety-supporting (stale)" in md


def test_compact_summary_clean_bundle_omits_optional_clauses():
    bundle = _bundle(
        test_evidence={"result": "passing", "freshness": "fresh", "source": "local_git"},
    )
    summary = compact_summary(bundle)
    assert "non-fresh evidence" not in summary
    assert "conflict" not in summary
