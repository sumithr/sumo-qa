from evaluation.iteration_brief import build_subagent_brief
from evaluation.repo_scenarios import SCENARIOS


def test_brief_includes_scenario_inputs_verbatim() -> None:
    scenario = SCENARIOS[0]
    brief = build_subagent_brief(scenario)
    # Tool name + the scenario description appear in the brief.
    assert scenario.tool in brief
    assert scenario.description in brief
    # Args are surfaced as JSON.
    if scenario.args.get("change_summary"):
        assert scenario.args["change_summary"] in brief


def test_brief_tells_subagent_to_read_live_prompts_file() -> None:
    brief = build_subagent_brief(SCENARIOS[0])
    assert "src/sumo_qa/prompts.py" in brief
    assert "SENIOR_QA_SYSTEM_PROMPT" in brief


def test_brief_tells_subagent_to_read_repo_files_when_listed() -> None:
    scenario = SCENARIOS[0]
    brief = build_subagent_brief(scenario)
    if scenario.repo_files_to_load:
        assert scenario.repo_files_to_load[0] in brief


def test_brief_includes_rubric_in_full() -> None:
    brief = build_subagent_brief(SCENARIOS[0])
    # The rubric is embedded so the subagent can self-eval.
    assert "principle_citation" in brief
    assert "decisive_routing" in brief
    assert "senior-istqb-grade" in brief


def test_brief_demands_structured_verdict_back_to_main_thread() -> None:
    brief = build_subagent_brief(SCENARIOS[0])
    assert "named_gaps" in brief
    assert "suggested_prompt_fixes" in brief
    assert "JSON" in brief or "json" in brief


def test_target_repo_path_is_configurable_via_env(monkeypatch) -> None:
    monkeypatch.setenv("SUMO_QA_TARGET_REPO", "/some/other/repo")
    # The constant is read at import time; reload to pick up the override.
    import importlib
    import evaluation.iteration_brief as brief_mod
    importlib.reload(brief_mod)
    try:
        assert brief_mod.TARGET_REPO_PATH == "/some/other/repo"
    finally:
        # Reload again without the env so other tests see the default.
        monkeypatch.delenv("SUMO_QA_TARGET_REPO")
        importlib.reload(brief_mod)


def test_brief_uses_target_repo_path_constant() -> None:
    from evaluation.iteration_brief import TARGET_REPO_PATH, build_subagent_brief
    brief = build_subagent_brief(SCENARIOS[0])
    assert TARGET_REPO_PATH in brief


def test_brief_raises_for_unmapped_tool() -> None:
    import pytest
    from evaluation.iteration_brief import build_subagent_brief
    from evaluation.repo_scenarios import RepoScenario

    bogus = RepoScenario(
        id="x",
        description="x",
        tool="qa_does_not_exist",
        args={},
        specificity="moderate",
    )
    with pytest.raises(ValueError, match="No prompt builder mapped"):
        build_subagent_brief(bogus)
