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
    import dataclasses
    s = RepoScenario(
        id="x", description="x", tool="qa_decide_approach", args={},
        specificity="moderate", rubric_focus=[], repo_files_to_load=[],
    )
    try:
        s.id = "y"
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("RepoScenario must be frozen")
