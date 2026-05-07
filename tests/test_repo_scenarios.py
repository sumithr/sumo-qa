import dataclasses

import pytest

from evaluation.repo_scenarios import RepoScenario, SCENARIOS, SPECIFICITY_VALUES


def test_repo_scenario_has_required_fields() -> None:
    s = RepoScenario(
        id="x",
        description="x",
        tool="qa_decide_approach",
        args={},
        specificity="moderate",
        rubric_focus=["principle_citation"],
        repo_files_to_load=[],
    )
    assert s.id == "x"
    assert s.specificity in SPECIFICITY_VALUES


def test_specificity_values_cover_full_spectrum() -> None:
    assert SPECIFICITY_VALUES == (
        "very-specific",
        "specific",
        "moderate",
        "generic",
        "very-generic",
    )


def test_repo_scenario_is_frozen() -> None:
    s = RepoScenario(
        id="x", description="x", tool="qa_decide_approach", args={},
        specificity="moderate", rubric_focus=[], repo_files_to_load=[],
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.id = "y"


def test_initial_suite_has_at_least_ten_scenarios() -> None:
    assert len(SCENARIOS) >= 10


def test_every_scenario_has_a_unique_id() -> None:
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids))


def test_suite_spans_full_specificity_spectrum() -> None:
    seen = {s.specificity for s in SCENARIOS}
    for level in SPECIFICITY_VALUES:
        assert level in seen, f"missing specificity level {level!r}"


def test_every_canonical_approach_has_a_scenario() -> None:
    """Per spec: at least one scenario per canonical approach."""
    descriptions = " ".join(s.description.lower() for s in SCENARIOS) + " ".join(
        " ".join(s.rubric_focus).lower() for s in SCENARIOS
    )
    for approach in (
        "tdd-scaffold",
        "regression-first",
        "coverage-first-then-refactor",
        "strengthen-test-coverage",
        "verify-existing",
        "no-tests-recommended",
        "spike-first-then-tests",
        "strategy-orchestration",
    ):
        assert approach in descriptions, f"missing scenario for approach {approach!r}"


def test_every_scenario_targets_an_existing_qa_tool() -> None:
    valid_tools = {
        "qa_decide_approach",
        "qa_review_local_change",
        "qa_prepare_for_work",
        "qa_create_test_plan",
        "qa_scaffold_tests",
        "qa_answer_testing_question",
    }
    for s in SCENARIOS:
        assert s.tool in valid_tools, f"unknown tool {s.tool!r} in scenario {s.id!r}"


def test_every_scenario_has_a_specificity_in_the_canonical_set() -> None:
    for s in SCENARIOS:
        assert s.specificity in SPECIFICITY_VALUES, (
            f"scenario {s.id!r} has unknown specificity {s.specificity!r}"
        )
