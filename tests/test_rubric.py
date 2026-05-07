from sumo_qa.rubric import (
    RUBRIC_DIMENSIONS,
    VERDICTS,
    build_rubric_prompt,
)


def test_rubric_has_ten_dimensions() -> None:
    assert len(RUBRIC_DIMENSIONS) == 10


def test_rubric_dimensions_cover_spec() -> None:
    """The rubric must implement EXACTLY the 10 dimensions from the spec.

    Strict equality so a renamed / dropped / silently-folded dimension
    surfaces as a test failure rather than a quiet drift.
    """
    expected_ids = {
        "principle_citation",
        "smallest_useful_test_set",
        "named_techniques",
        "risk_based_focus",
        "facts_vs_assumptions",
        "no_waived_evidence",
        "decisive_routing",
        "specialty_awareness",
        "domain_specificity",
        "no_generic_advice",
    }
    actual_ids = {d.id for d in RUBRIC_DIMENSIONS}
    assert actual_ids == expected_ids


def test_verdicts_match_spec() -> None:
    assert VERDICTS == (
        "senior-istqb-grade",
        "needs-iteration",
        "unfit-for-merge",
    )


def test_build_rubric_prompt_includes_every_dimension() -> None:
    prompt = build_rubric_prompt(
        scenario_id="x",
        scenario_description="x",
        ai_output="x",
    )
    for dim in RUBRIC_DIMENSIONS:
        assert dim.id in prompt or dim.title in prompt


def test_build_rubric_prompt_demands_structured_json_verdict() -> None:
    prompt = build_rubric_prompt(
        scenario_id="x", scenario_description="x", ai_output="x",
    )
    assert "JSON" in prompt or "json" in prompt
    assert "verdict" in prompt
    assert "named_gaps" in prompt
    assert "suggested_prompt_fixes" in prompt
