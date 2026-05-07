"""Local feedback loop: simulate a well-behaved MCP host rendering each response.

This file gives the maintainer a fast, free, deterministic check that the
`presentation` hints produce sleek output. It does NOT replace a real-model
end-to-end test - it just catches the cases where the hint design itself is
broken (asks for too much, omits essentials, allows essay markers).

If these tests pass, the hint shape is correct. The only remaining failure
mode is 'the real host model ignores the hint' - check that once at the end,
not on every iteration.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sumo_qa.render_preview import render_response
from sumo_qa.tools import QAShiftLeftService


ROOT = Path(__file__).resolve().parents[1]


def _service() -> QAShiftLeftService:
    return QAShiftLeftService.from_standards_path(ROOT / "standards" / "packs")


# Phrases that signal the host is writing essays instead of rendering structured output.
ESSAY_MARKERS = [
    "## ",  # markdown subsections
    "### ",
    "Decision-boundary tests",
    "Negative / edge tests",
    "Failure-path tests",
    "Open questions for the team",
    "Done-when",
    "Test data needs",
    "Regression focus",
    "Primary checks (tied",
]


def _assert_sleek(rendered: str, max_words: int, must_contain: list[str]) -> None:
    """The soft target may be exceeded when content needs it. The hard ceiling
    catches genuine runaway (essay mode).
    """
    word_count = len(rendered.split())
    hard_ceiling = max_words * 2
    assert word_count <= hard_ceiling, (
        f"rendered output is {word_count} words; runaway above hard ceiling {hard_ceiling}\n"
        f"--- rendered ---\n{rendered}\n--- end ---"
    )
    for needle in must_contain:
        assert needle in rendered, f"rendered output missing required substring {needle!r}"
    for marker in ESSAY_MARKERS:
        assert marker not in rendered, f"rendered output contains essay marker {marker!r}: {rendered[:200]!r}"


def test_prepare_for_work_renders_sleekly() -> None:
    response = _service().qa_prepare_for_work(
        work_item="Add bundle variant validation rules",
        acceptance_criteria=["Invalid bundle variants are blocked at write time and emit a clear violation reason."],
    )
    rendered = render_response(response)
    print("\n--- prepare rendered ---\n" + rendered + "\n--- end ---\n")
    _assert_sleek(
        rendered,
        max_words=response["presentation"]["max_words"],
        must_contain=[response["headline"][:40]],
    )


def test_review_local_change_renders_sleekly() -> None:
    response = _service().qa_review_local_change(
        change_summary="Changed API payload schema for orders endpoint",
        touched_files=["src/orders/api.py"],
    )
    rendered = render_response(response)
    print("\n--- review rendered ---\n" + rendered + "\n--- end ---\n")
    _assert_sleek(
        rendered,
        max_words=response["presentation"]["max_words"],
        must_contain=[
            "VERDICT:",
            response["verdict"],
        ],
    )


def test_create_test_plan_renders_sleekly_with_phases_and_exit_criteria() -> None:
    response = _service().qa_create_test_plan(
        work_item=(
            "Add an API endpoint that validates bundle variants on the order pipeline; "
            "block invalid payload shapes at write time."
        ),
        scope_size="medium",
        acceptance_criteria=[
            "Invalid bundle variants are blocked at write time.",
            "Each violation surfaces a clear reason and SKU.",
        ],
    )
    rendered = render_response(response)
    print("\n--- testplan rendered ---\n" + rendered + "\n--- end ---\n")
    _assert_sleek(
        rendered,
        max_words=response["presentation"]["max_words"],
        must_contain=["In scope:", "Entry:", "Phases:", "Exit:"],
    )


def test_answer_testing_question_renders_sleekly() -> None:
    response = _service().qa_answer_testing_question(
        question="How do I test a webhook retry that has to be idempotent?",
    )
    rendered = render_response(response)
    print("\n--- question rendered ---\n" + rendered + "\n--- end ---\n")
    _assert_sleek(
        rendered,
        max_words=response["presentation"]["max_words"],
        must_contain=[response["answer"]["short_answer"][:30]],
    )


def test_render_response_handles_thin_input_without_crashing() -> None:
    # Pass a whitespace-only diff and an explicit empty touched_files list so
    # the test does not shell out to `git diff` against the actual working
    # tree (which would defeat the thin-input path that this test pins).
    response = _service().qa_review_local_change(
        change_summary="fix bug", diff=" ", touched_files=[]
    )
    rendered = render_response(response)
    # Thin input - we still render under cap and lead with the headline asking for more detail.
    assert "Need more detail" in rendered or "more specific" in rendered.lower()
    word_count = len(rendered.split())
    assert word_count <= response["presentation"]["max_words"]


def test_render_cli_keeps_stdout_free_of_diagnostics(capsys) -> None:
    """The CLI's stdout must contain ONLY the rendered text - no word-count
    footer, no JSON. Diagnostics go to stderr behind opt-in flags.
    """
    from sumo_qa.render_cli import main

    exit_code = main(
        [
            "review",
            "--change-summary",
            "Changed API payload schema for orders endpoint",
            "--touched-files",
            "src/orders/api.py",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0

    forbidden_in_stdout = ["[stats]", "soft target", "raw JSON", "{", "}"]
    for needle in forbidden_in_stdout:
        assert needle not in captured.out, (
            f"CLI stdout leaked diagnostic {needle!r}; should be on stderr only"
        )

    # Sanity: stdout still has the rendered output.
    assert "VERDICT:" in captured.out


def test_render_cli_emits_stats_on_stderr_when_opted_in(capsys) -> None:
    from sumo_qa.render_cli import main

    exit_code = main(
        [
            "--stats",
            "review",
            "--change-summary",
            "Changed API payload schema",
            "--touched-files",
            "src/orders/api.py",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "[stats]" in captured.err
    assert "soft target" in captured.err
    assert "[stats]" not in captured.out


def test_rendered_output_cites_named_istqb_techniques_when_relevant() -> None:
    """The rendered text should name an ISTQB technique relevant to the change.
    Caller supplies the classification — the harness no longer pattern-matches.
    """
    response = _service().qa_review_local_change(
        change_summary="Refactored cache TTL behavior on the availability cache",
        touched_files=["src/stock/cache/availability_cache.py"],
        explicit_classifications=["caching_change"],
    )
    rendered = render_response(response).lower()

    # caching_change rule lists boundary-value, state-transition, decision-table techniques
    assert any(
        marker in rendered
        for marker in ["boundary value", "state transition", "decision table", "error guessing"]
    ), f"rendered output omitted any named ISTQB technique:\n{render_response(response)}"


def test_rendered_output_leads_with_recommended_approach() -> None:
    """Every rendered output begins with an APPROACH line so the host model
    knows whether to scaffold, write a regression test, refactor, or skip.

    The deterministic fallback's APPROACH line shows the safe default
    (tdd-scaffold) plus the next tool — the AI-sampling path is what
    swaps in regression-first / strengthen-test-coverage / etc."""
    bug_response = _service().qa_review_local_change(
        change_summary="fix the bug where bundles with stale stock get blocked",
        touched_files=["src/orders/bundle.py"],
    )
    rendered = render_response(bug_response)
    first_line = rendered.splitlines()[0]
    assert first_line.startswith("APPROACH:")
    # Deterministic default; the AI path can refine to regression-first.
    assert "tdd-scaffold" in first_line
    assert "qa_scaffold_tests" in first_line


def test_decide_approach_renders_no_tests_when_caller_signals_docs_only() -> None:
    """Pure-docs routing requires an explicit `is_docs_only` signal — the
    harness no longer pattern-matches `.md` extensions. The AI path is
    what reads paths and decides docs-vs-code; the deterministic path
    needs the signal."""
    decision = _service().qa_decide_approach(
        intent_text="update README and add architecture diagram",
        target_paths=["README.md", "docs/architecture.md"],
        signals={"is_docs_only": True},
    )
    assert decision["recommended_approach"]["approach"] == "no-tests-recommended"


def test_rendered_output_surfaces_specialty_pull_in_when_relevant() -> None:
    """When the caller supplies a classification that maps to a specialty,
    the rendered output names what to pull in. The harness no longer
    pattern-matches paths or text to guess specialties."""
    response = _service().qa_review_local_change(
        change_summary="Refactored the checkout button hover state and form layout",
        touched_files=["src/components/CheckoutButton.tsx"],
        explicit_classifications=["ui_only_change"],
    )
    rendered = render_response(response)
    assert "Pull in:" in rendered, f"specialty 'Pull in:' block missing:\n{rendered}"
    lowered = rendered.lower()
    assert "playwright" in lowered or "cypress" in lowered


def test_response_carries_iso25010_quality_characteristics() -> None:
    """quality_characteristics is in the JSON for users who want it - even if
    we deliberately keep it out of the rendered prose to stay sleek."""
    response = _service().qa_review_local_change(
        change_summary="Refactored cache TTL behavior",
        touched_files=["src/stock/cache/availability_cache.py"],
        explicit_classifications=["caching_change"],
    )
    chars = response.get("quality_characteristics", [])
    assert chars, "expected ISO/IEC 25010 quality characteristics on caching_change response"
    chars_lower = " ".join(chars).lower()
    assert "performance" in chars_lower or "reliability" in chars_lower


def test_render_response_rejects_payload_without_presentation() -> None:
    with pytest.raises(KeyError):
        render_response({"headline": "x"})


def test_render_does_not_truncate_with_ellipsis_when_content_is_legitimately_long() -> None:
    """Soft cap means: aim for the target, but do not cut mid-sentence.

    A long-but-honest response must render in full. The structure-based bound
    (fixed number of fields x bounded per-field text) keeps it from running
    away; we never use mid-sentence ellipsis as a chainsaw.
    """
    response = _service().qa_review_local_change(
        change_summary=(
            "Refactored the orders API payload mapper, the validation layer, "
            "and the downstream consumer; touches multiple boundaries and the "
            "diff is intentionally broad."
        ),
        touched_files=[
            "src/orders/api.py",
            "src/orders/mapper.py",
            "src/orders/validator.py",
            "src/orders/consumer.py",
            "src/orders/state.py",
        ],
    )

    rendered = render_response(response)

    # No mid-sentence ellipsis from a runaway truncation.
    assert "..." not in rendered, (
        "rendered text was hard-truncated; soft target means natural bound, not chainsaw\n"
        f"--- rendered ---\n{rendered}\n--- end ---"
    )
    # Still bounded by structure - well under any sane runaway ceiling.
    word_count = len(rendered.split())
    assert word_count < response["presentation"]["max_words"] * 3, (
        f"rendered output exceeded the runaway ceiling: {word_count} words"
    )


def test_presentation_hint_describes_word_cap_as_soft() -> None:
    """The hint copy must tell the host model the cap is a soft target."""
    svc = _service()
    for response in (
        svc.qa_prepare_for_work(work_item="x"),
        svc.qa_review_local_change(change_summary="x", touched_files=["src/x.py"]),
        svc.qa_answer_testing_question(question="how do I test x"),
    ):
        instructions = response["presentation"]["render_instructions"].lower()
        assert "soft" in instructions or "may exceed" in instructions or "if needed" in instructions, (
            f"presentation hint should describe the cap as a soft target, got: {instructions[:200]!r}"
        )
