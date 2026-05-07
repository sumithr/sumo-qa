"""Build the prompt the main thread sends to a subagent.

The brief tells the subagent:
  1. read the LATEST sumo-qa source files (prompts, per-tool builders,
     standards) so the iteration loop sees edits immediately
  2. read the relevant by-variant-data-feeder files for repo context
  3. reason as the host LLM would, producing the structured QA output
  4. self-eval against the ISTQB rubric
  5. return a tight verdict to the main thread

No disk writes; all the bulky context lives in the subagent's context.
"""
from __future__ import annotations

import json
import os

from sumo_qa.rubric import build_rubric_prompt

from evaluation.repo_scenarios import RepoScenario


# Path to the repo we test against. Override via SUMO_QA_TARGET_REPO env var.
TARGET_REPO_PATH = os.environ.get(
    "SUMO_QA_TARGET_REPO",
    "/Users/SumithRamsookbhai/Desktop/repos/apo/apo-configurator/by-variant-data-feeder",
)


_TOOL_TO_PROMPT_BUILDER: dict[str, str] = {
    "qa_decide_approach": "_build_decide_approach_sampling_prompt",
    "qa_review_local_change": "_build_review_sampling_prompt",
    "qa_prepare_for_work": "_build_prepare_sampling_prompt",
    "qa_create_test_plan": "_build_test_plan_sampling_prompt",
    "qa_scaffold_tests": "_build_scaffold_sampling_prompt",
    "qa_answer_testing_question": "_build_question_sampling_prompt",
}


def build_subagent_brief(scenario: RepoScenario) -> str:
    """Return the prompt for a subagent that runs ONE scenario end-to-end."""
    try:
        builder_name = _TOOL_TO_PROMPT_BUILDER[scenario.tool]
    except KeyError as exc:
        raise ValueError(
            f"No prompt builder mapped for tool {scenario.tool!r}. "
            f"Add it to _TOOL_TO_PROMPT_BUILDER in evaluation/iteration_brief.py."
        ) from exc
    repo_files_block = (
        "\n".join(f"  - {p}" for p in scenario.repo_files_to_load)
        if scenario.repo_files_to_load
        else "  (none — reason from the scenario description alone)"
    )
    rubric_prompt = build_rubric_prompt(
        scenario_id=scenario.id,
        scenario_description=scenario.description,
        ai_output="<your step-3 output — substitute the full text here>",
    )

    return (
        f"You are a senior ISTQB-certified QA engineer grading sumo-qa output "
        f"on scenario `{scenario.id}`.\n\n"
        f"Scenario description: {scenario.description}\n\n"
        f"## Step 1 — read the live sumo-qa grounding\n\n"
        f"Read these files VERBATIM (use the Read tool on each):\n"
        f"  - src/sumo_qa/prompts.py (this is your standing context — "
        f"`SENIOR_QA_SYSTEM_PROMPT`)\n"
        f"  - src/sumo_qa/tools.py (look for the `{builder_name}` function — "
        f"this is the per-tool grounding for `{scenario.tool}`)\n"
        f"  - standards/packs/*.yaml (the team's loaded QA standards)\n"
        f"  - standards/rules/change_rules.yaml\n\n"
        f"## Step 2 — read the by-variant-data-feeder repo context\n\n"
        f"Read these paths from the by-variant-data-feeder repo (located at "
        f"{TARGET_REPO_PATH}):\n"
        f"{repo_files_block}\n\n"
        f"## Step 3 — apply the prompts to the scenario inputs\n\n"
        f"The MCP would invoke `{scenario.tool}` with these arguments:\n"
        f"```json\n{json.dumps(scenario.args, indent=2)}\n```\n\n"
        f"Reason as the host LLM grounded by `SENIOR_QA_SYSTEM_PROMPT` and the "
        f"`{builder_name}` user prompt. Produce the structured QA output the "
        f"MCP would return — verdict / approach / top_risks / suggested_tests / "
        f"techniques / specialty / etc., as appropriate for the tool.\n\n"
        f"Be honest: if the prompts as written would produce weak output, "
        f"reflect that weak output. Do NOT compensate for prompt gaps.\n\n"
        f"## Step 4 — self-eval against the ISTQB rubric\n\n"
        f"Substitute your step-3 output into `<your output...>` below and "
        f"grade it against the rubric:\n\n"
        f"```\n{rubric_prompt}\n```\n\n"
        f"## Step 5 — return\n\n"
        f"Return ONLY the JSON verdict from step 4. No prose. The main thread "
        f"will aggregate verdicts across scenarios and use them to decide "
        f"which prompts/standards to edit next."
    )
