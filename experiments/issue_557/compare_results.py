# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Produce the deterministic PROVEN/NOT PROVEN verdict for issue #557."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .run_candidate import build_prompts, load_group, validate_result_record

GROUPS = ("core", "adversarial", "verifier", "unproven")
REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = Path(__file__).with_name("compact_review_prompt.md")
SKILL_PATH = REPO_ROOT / "skills/sumo-qa-reviewing-before-merge/SKILL.md"
EVAL_ROOT = REPO_ROOT / "tests/evals/promptfoo"
CONFIGS = {
    "core": "skill-reviewing-before-merge.yaml",
    "adversarial": "skill-reviewing-before-merge-adversarial.yaml",
    "verifier": "skill-reviewing-before-merge-verifier-evidence.yaml",
    "unproven": "skill-reviewing-before-merge-unproven-escalation.yaml",
}
_COLD_CONTEXT_VARS = {
    "skill_content",
    "loaded_classifications",
    "loaded_rules",
    "loaded_techniques",
}


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provider_id(provider: object) -> object:
    return provider.get("id") if isinstance(provider, dict) else provider


def _positive_usage(usage: object, *, expected_requests: int) -> tuple[int, int] | None:
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt")
    completion = usage.get("completion")
    total = usage.get("total")
    requests = usage.get("numRequests")
    if (
        type(prompt) is not int
        or type(completion) is not int
        or type(total) is not int
        or type(requests) is not int
        or prompt <= 0
        or completion <= 0
        or total != prompt + completion
        or requests != expected_requests
    ):
        return None
    return prompt, completion


def _promptfoo_file_content(value: object, *, config_dir: Path) -> str | None:
    if not isinstance(value, str) or not value.startswith("file://"):
        return None
    path = (config_dir / value.removeprefix("file://")).resolve()
    content = path.read_text()
    if path.suffix in {".yaml", ".yml"}:
        return json.dumps(yaml.safe_load(content), ensure_ascii=False, separators=(",", ":"))
    if path.suffix == ".json":
        return json.dumps(json.loads(content), ensure_ascii=False, separators=(",", ":"))
    return content


def _baseline_config_matches(artifact: object, current: dict[str, Any]) -> bool:
    if not isinstance(artifact, dict):
        return False
    current_default = current.get("defaultTest", {})
    artifact_default = artifact.get("defaultTest", {})
    return (
        artifact.get("description") == current.get("description")
        and artifact.get("prompts") == current.get("prompts")
        and artifact.get("providers") == current.get("providers")
        and artifact.get("tests") == current.get("tests")
        and artifact_default.get("vars") == current_default.get("vars", {})
        and artifact_default.get("assert") == current_default.get("assert", [])
        and artifact_default.get("options") == current_default.get("options", {})
    )


def _grade_config_matches(
    artifact: object,
    current: dict[str, Any],
    current_tests: list[dict[str, Any]],
    reviews: list[str | None],
    *,
    group: str,
) -> bool:
    if not isinstance(artifact, dict) or any(review is None for review in reviews):
        return False
    current_default = current.get("defaultTest", {})
    default_vars = {
        key: value
        for key, value in current_default.get("vars", {}).items()
        if key not in _COLD_CONTEXT_VARS
    }
    expected_tests = [
        {
            "description": test["description"],
            "vars": default_vars | test.get("vars", {}) | {"output": review},
        }
        for test, review in zip(current_tests, reviews, strict=True)
    ]
    artifact_default = artifact.get("defaultTest", {})
    return (
        artifact.get("description") == f"Issue #557 unchanged-rubric grading: {group}"
        and artifact.get("providers") == ["echo"]
        and artifact.get("prompts") == ["{{output}}"]
        and artifact.get("tests") == expected_tests
        and artifact_default.get("assert") == current_default.get("assert", [])
        and artifact_default.get("options") == current_default.get("options", {})
    )


def _grading_result_matches(
    row: dict[str, Any],
    *,
    assertions: list[dict[str, Any]],
    graded_output: str,
) -> bool:
    grading = row.get("gradingResult")
    if not isinstance(grading, dict):
        return False
    components = grading.get("componentResults")
    if not isinstance(components, list) or len(components) != len(assertions):
        return False
    success = row.get("success")
    score = row.get("score")
    if type(success) is not bool or not isinstance(score, int | float):
        return False
    if grading.get("pass") is not success or grading.get("score") != score:
        return False
    if _positive_usage(grading.get("tokensUsed"), expected_requests=1) is None:
        return False
    marker = f"--- CANDIDATE RESPONSE ---\n{graded_output}\n--- END CANDIDATE RESPONSE ---"
    for component, assertion in zip(components, assertions, strict=True):
        metadata = component.get("metadata", {})
        if (
            component.get("assertion") != assertion
            or component.get("pass") is not success
            or component.get("score") != score
            or _positive_usage(component.get("tokensUsed"), expected_requests=1) is None
            or marker not in metadata.get("renderedGradingPrompt", "")
        ):
            return False
    return True


def compare_evidence(
    baseline_dir: Path,
    candidate_dir: Path,
    *,
    minimum_input_reduction_percent: float = 30.0,
) -> dict[str, Any]:
    baseline_prompt_tokens = 0
    baseline_completion_tokens = 0
    candidate_prompt_tokens = 0
    candidate_completion_tokens = 0
    prompt_hashes: set[str] = set()
    config_integrity = True
    model_integrity = True
    rubric_integrity = True
    scenario_integrity = True
    rendered_prompt_integrity = True
    baseline_context_integrity = True
    candidate_response_integrity = True
    usage_integrity = True
    grade_binding_integrity = True
    current_config_integrity = True
    embedded_config_integrity = True
    grading_result_integrity = True
    quality_rows: list[dict[str, Any]] = []

    for group in GROUPS:
        baseline = _read(baseline_dir / f"issue557-baseline-{group}.json")
        candidate = _read(candidate_dir / f"candidate-{group}.json")
        candidate_grade = _read(candidate_dir / f"candidate-{group}-grade.json")
        current_model, current_scenarios, current_metadata = build_prompts(group)
        _, current_baseline_scenarios, _ = build_prompts(
            group,
            skill_content=SKILL_PATH.read_text(),
        )
        current_config, current_tests, _ = load_group(group)
        current_defaults = current_config.get("defaultTest", {})
        current_default_vars = current_defaults.get("vars", {})
        current_assertions = current_defaults.get("assert", [])
        current_options = current_defaults.get("options", {})
        config_integrity &= candidate["config_sha256"] == _file_sha256(EVAL_ROOT / CONFIGS[group])
        current_config_integrity &= candidate.get("group") == group
        current_config_integrity &= candidate.get("config") == CONFIGS[group]
        current_config_integrity &= candidate.get("model") == current_model
        current_config_integrity &= current_metadata["config_sha256"] == candidate.get(
            "config_sha256"
        )
        embedded_config_integrity &= _baseline_config_matches(
            baseline.get("config"), current_config
        )
        prompt_hashes.add(candidate["compact_prompt_sha256"])
        baseline_rows = baseline["results"]["results"]
        candidate_rows = candidate_grade["results"]["results"]
        expected_count = len(current_tests)
        if not (
            len(baseline_rows)
            == len(candidate["results"])
            == len(candidate_rows)
            == len(current_scenarios)
            == expected_count
        ):
            raise ValueError(f"scenario count mismatch for {group}")

        baseline_usage = _positive_usage(
            baseline["results"]["stats"].get("tokenUsage"),
            expected_requests=expected_count,
        )
        if baseline_usage is None:
            usage_integrity = False
        else:
            baseline_prompt_tokens += baseline_usage[0]
            baseline_completion_tokens += baseline_usage[1]

        if len(candidate["results"]) != len(current_scenarios):
            rendered_prompt_integrity = False
        for result, (description, rendered_prompt) in zip(
            candidate["results"], current_scenarios, strict=False
        ):
            rendered_prompt_integrity &= result["description"] == description
            rendered_prompt_integrity &= (
                result["rendered_prompt_sha256"]
                == hashlib.sha256(rendered_prompt.encode()).hexdigest()
            )
        validated_reviews: list[str | None] = []
        for result in candidate["results"]:
            try:
                review, prompt_tokens, completion_tokens = validate_result_record(result)
            except (KeyError, TypeError, ValueError):
                candidate_response_integrity = False
                usage_integrity = False
                validated_reviews.append(None)
                continue
            validated_reviews.append(review)
            candidate_prompt_tokens += prompt_tokens
            candidate_completion_tokens += completion_tokens
        embedded_config_integrity &= _grade_config_matches(
            candidate_grade.get("config"),
            current_config,
            current_tests,
            validated_reviews,
            group=group,
        )

        baseline_row_prompt_tokens = 0
        baseline_row_completion_tokens = 0

        for before, result, after, current_test, validated_review, baseline_scenario in zip(
            baseline_rows,
            candidate["results"],
            candidate_rows,
            current_tests,
            validated_reviews,
            current_baseline_scenarios,
            strict=True,
        ):
            before_description = before["testCase"]["description"]
            after_description = after["testCase"]["description"]
            expected_description = current_test["description"]
            scenario_integrity &= before_description == expected_description
            scenario_integrity &= after_description == expected_description
            scenario_integrity &= result.get("description") == expected_description
            baseline_pass = bool(before["success"])
            candidate_pass = bool(after["success"])
            baseline_score = float(before["score"])
            candidate_score = float(after["score"])
            model_integrity &= _provider_id(before["provider"]) == (f"openai:chat:{current_model}")
            model_integrity &= _provider_id(after["provider"]) == "echo"
            rubric_integrity &= before["testCase"]["assert"] == current_assertions
            rubric_integrity &= after["testCase"]["assert"] == current_assertions
            rubric_integrity &= before["testCase"]["options"] == current_options
            rubric_integrity &= after["testCase"]["options"] == current_options

            expected_baseline_vars = current_default_vars | current_test.get("vars", {})
            expected_grade_vars = {
                key: value
                for key, value in current_default_vars.items()
                if key not in _COLD_CONTEXT_VARS
            } | current_test.get("vars", {})
            scenario_integrity &= before["testCase"]["vars"] == expected_baseline_vars
            after_vars = after["testCase"]["vars"]
            scenario_integrity &= {
                key: value for key, value in after_vars.items() if key != "output"
            } == expected_grade_vars
            grade_binding_integrity &= after_vars.get("output") == validated_review
            grade_binding_integrity &= after.get("prompt", {}).get("raw") == validated_review
            grade_binding_integrity &= after.get("response", {}).get("output") == validated_review
            grade_binding_integrity &= after.get("response", {}).get("raw") == validated_review

            expected_baseline_description, expected_baseline_prompt = baseline_scenario
            baseline_context_integrity &= (
                expected_baseline_description == expected_description
                and before["prompt"]["raw"] == expected_baseline_prompt
            )
            baseline_output = before.get("response", {}).get("output")
            if not isinstance(baseline_output, str):
                grading_result_integrity = False
                baseline_output = ""
            grading_result_integrity &= _grading_result_matches(
                before,
                assertions=current_assertions,
                graded_output=baseline_output,
            )
            if validated_review is None:
                grading_result_integrity = False
            else:
                grading_result_integrity &= _grading_result_matches(
                    after,
                    assertions=current_assertions,
                    graded_output=validated_review,
                )
            row_usage = _positive_usage(
                before.get("response", {}).get("tokenUsage"),
                expected_requests=1,
            )
            if row_usage is None:
                usage_integrity = False
            else:
                baseline_row_prompt_tokens += row_usage[0]
                baseline_row_completion_tokens += row_usage[1]
            quality_preserved = (
                candidate_pass
                if baseline_pass
                else (candidate_pass or candidate_score >= baseline_score)
            )
            quality_rows.append(
                {
                    "group": group,
                    "description": before_description,
                    "baseline_pass": baseline_pass,
                    "baseline_score": baseline_score,
                    "candidate_pass": candidate_pass,
                    "candidate_score": candidate_score,
                    "quality_preserved": quality_preserved,
                }
            )
        if baseline_usage is not None:
            usage_integrity &= baseline_usage == (
                baseline_row_prompt_tokens,
                baseline_row_completion_tokens,
            )

    input_reduction_percent = (
        round(
            100 * (baseline_prompt_tokens - candidate_prompt_tokens) / baseline_prompt_tokens,
            2,
        )
        if baseline_prompt_tokens > 0
        else 0.0
    )
    baseline_total_tokens = baseline_prompt_tokens + baseline_completion_tokens
    candidate_total_tokens = candidate_prompt_tokens + candidate_completion_tokens
    total_reduction_percent = (
        round(
            100 * (baseline_total_tokens - candidate_total_tokens) / baseline_total_tokens,
            2,
        )
        if baseline_total_tokens > 0
        else 0.0
    )
    same_candidate_prompt = prompt_hashes == {_file_sha256(PROMPT_PATH)}
    integrity_preserved = (
        same_candidate_prompt
        and config_integrity
        and model_integrity
        and rubric_integrity
        and scenario_integrity
        and rendered_prompt_integrity
        and baseline_context_integrity
        and candidate_response_integrity
        and usage_integrity
        and grade_binding_integrity
        and current_config_integrity
        and embedded_config_integrity
        and grading_result_integrity
    )
    quality_preserved = all(row["quality_preserved"] for row in quality_rows)
    token_target_met = input_reduction_percent >= minimum_input_reduction_percent
    proven = integrity_preserved and quality_preserved and token_target_met
    return {
        "verdict": "PROVEN" if proven else "NOT PROVEN",
        "same_candidate_prompt": same_candidate_prompt,
        "compact_prompt_sha256": next(iter(prompt_hashes)) if same_candidate_prompt else None,
        "integrity": {
            "preserved": integrity_preserved,
            "config_hashes_match": config_integrity,
            "candidate_models_match": model_integrity,
            "rubrics_and_judges_match": rubric_integrity,
            "scenario_variables_match": scenario_integrity,
            "candidate_rendered_prompts_match": rendered_prompt_integrity,
            "baseline_contains_current_context": baseline_context_integrity,
            "candidate_responses_revalidate": candidate_response_integrity,
            "usage_is_valid": usage_integrity,
            "grades_bind_validated_reviews": grade_binding_integrity,
            "current_configs_match": current_config_integrity,
            "embedded_configs_match": embedded_config_integrity,
            "grading_results_are_consistent": grading_result_integrity,
        },
        "quality": {
            "baseline_passed": sum(row["baseline_pass"] for row in quality_rows),
            "candidate_passed": sum(row["candidate_pass"] for row in quality_rows),
            "scenario_count": len(quality_rows),
            "preserved": quality_preserved,
            "scenarios": quality_rows,
        },
        "tokens": {
            "baseline_input": baseline_prompt_tokens,
            "candidate_input": candidate_prompt_tokens,
            "input_reduction_percent": input_reduction_percent,
            "minimum_input_reduction_percent": minimum_input_reduction_percent,
            "target_met": token_target_met,
            "baseline_completion": baseline_completion_tokens,
            "candidate_completion": candidate_completion_tokens,
            "baseline_total": baseline_total_tokens,
            "candidate_total": candidate_total_tokens,
            "total_reduction_percent": total_reduction_percent,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-dir", type=Path, default=Path("/private/tmp"))
    parser.add_argument("--candidate-dir", type=Path, default=Path("/private/tmp/issue557"))
    parser.add_argument("--minimum-input-reduction-percent", type=float, default=30.0)
    args = parser.parse_args()
    result = compare_evidence(
        args.baseline_dir,
        args.candidate_dir,
        minimum_input_reduction_percent=args.minimum_input_reduction_percent,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
