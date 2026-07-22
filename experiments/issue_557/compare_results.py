# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Produce the deterministic PROVEN/NOT PROVEN verdict for issue #557."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .run_candidate import (
    FULL_REVIEW_GROUPS,
    PINNED_GROUPS,
    _resolve_file_value,
    build_direct_config,
    build_prompts,
    candidate_prompt,
    candidate_prompt_for_group,
    load_group,
    validate_result_record,
)

GROUPS = ("core", "adversarial", "verifier", "unproven")
FULL_REVIEW_GROUP_NAMES = tuple(FULL_REVIEW_GROUPS)
REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = Path(__file__).with_name("compact_review_prompt.md")
SKILL_PATH = REPO_ROOT / "skills/sumo-qa-reviewing-before-merge/SKILL.md"
EVAL_ROOT = REPO_ROOT / "tests/evals/promptfoo"
CONFIGS = {
    name: selection.config for name, selection in (PINNED_GROUPS | FULL_REVIEW_GROUPS).items()
}
_COLD_CONTEXT_VARS = {
    "skill_content",
    "loaded_classifications",
    "loaded_rules",
    "loaded_techniques",
}


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _direct_positive_usage(
    usage: object,
    *,
    minimum_requests: int,
) -> tuple[int, int] | None:
    """Validate direct-run usage while allowing explicit infrastructure retries."""
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
        or total < prompt + completion
        or requests < minimum_requests
    ):
        return None
    # Reasoning providers include hidden reasoning in ``total`` but not in
    # ``completion``. Treat every non-input token as completion-side usage so
    # aggregate and per-row totals remain comparable across providers.
    return prompt, total - prompt


def _promptfoo_file_content(value: object, *, config_dir: Path) -> str | None:
    if not isinstance(value, str) or not value.startswith("file://"):
        return None
    path = (config_dir / value.removeprefix("file://")).resolve()
    content = path.read_text(encoding="utf-8")
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


def _direct_config_matches(artifact: object, expected: dict[str, Any]) -> bool:
    """Match generated configs while allowing Promptfoo's serialized grader object."""
    if not isinstance(artifact, dict):
        return False
    adjusted = dict(expected)
    adjusted_default = dict(expected.get("defaultTest", {}))
    adjusted_options = dict(adjusted_default.get("options", {}))
    adjusted_options["provider"] = (
        artifact.get("defaultTest", {}).get("options", {}).get("provider")
    )
    adjusted_default["options"] = adjusted_options
    adjusted["defaultTest"] = adjusted_default
    return _baseline_config_matches(artifact, adjusted)


def _judge_model(row: dict[str, Any]) -> object:
    provider = row.get("testCase", {}).get("options", {}).get("provider")
    if isinstance(provider, dict):
        return provider.get("modelName") or provider.get("id")
    return provider


def _grade_config_matches(
    artifact: object,
    current: dict[str, Any],
    current_tests: list[dict[str, Any]],
    reviews: list[str | None],
    *,
    group: str,
    allow_provider_override: bool = False,
) -> bool:
    if not isinstance(artifact, dict) or any(review is None for review in reviews):
        return False
    current_default = current.get("defaultTest", {})
    config_dir = (EVAL_ROOT / CONFIGS[group]).parent
    default_vars = {
        key: _resolve_file_value(value, config_dir=config_dir)
        for key, value in current_default.get("vars", {}).items()
        if key not in _COLD_CONTEXT_VARS
    }
    expected_tests = [
        {
            "description": test["description"],
            "vars": default_vars
            | {
                key: _resolve_file_value(value, config_dir=config_dir)
                for key, value in test.get("vars", {}).items()
                if key not in _COLD_CONTEXT_VARS
            }
            | {"output": review},
        }
        for test, review in zip(current_tests, reviews, strict=True)
    ]
    artifact_default = artifact.get("defaultTest", {})
    expected_options = current_default.get("options", {})
    if allow_provider_override:
        expected_options = dict(expected_options)
        expected_options["provider"] = artifact_default.get("options", {}).get("provider")
    return (
        artifact.get("description") == f"Issue #557 unchanged-rubric grading: {group}"
        and artifact.get("providers") == ["echo"]
        and artifact.get("prompts") == ["{{output}}"]
        and artifact.get("tests") == expected_tests
        and artifact_default.get("assert") == current_default.get("assert", [])
        and artifact_default.get("options") == expected_options
    )


def _grading_result_matches(
    row: dict[str, Any],
    *,
    assertions: list[dict[str, Any]],
    graded_output: str,
    allow_reasoning_usage: bool = False,
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

    def usage_validator(usage: object) -> tuple[int, int] | None:
        if allow_reasoning_usage:
            return _direct_positive_usage(usage, minimum_requests=1)
        return _positive_usage(usage, expected_requests=1)

    if usage_validator(grading.get("tokensUsed")) is None:
        return False
    marker = f"--- CANDIDATE RESPONSE ---\n{graded_output}\n--- END CANDIDATE RESPONSE ---"
    for component, assertion in zip(components, assertions, strict=True):
        if (
            component.get("assertion") != assertion
            or type(component.get("pass")) is not bool
            or not isinstance(component.get("score"), int | float)
        ):
            return False
        if assertion.get("type") == "llm-rubric":
            metadata = component.get("metadata", {})
            if usage_validator(component.get("tokensUsed")) is None or marker not in metadata.get(
                "renderedGradingPrompt", ""
            ):
                return False
    if success is not all(component["pass"] for component in components):
        return False
    return True


def compare_evidence(
    baseline_dir: Path,
    candidate_dir: Path,
    *,
    minimum_input_reduction_percent: float = 30.0,
    groups: tuple[str, ...] = GROUPS,
    candidate_profile: str = "compact",
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

    for group in groups:
        baseline = _read(baseline_dir / f"issue557-baseline-{group}.json")
        candidate = _read(candidate_dir / f"candidate-{group}.json")
        candidate_grade = _read(candidate_dir / f"candidate-{group}-grade.json")
        current_model, current_scenarios, current_metadata = build_prompts(
            group,
            candidate_profile=candidate_profile,
        )
        _, current_baseline_scenarios, _ = build_prompts(
            group,
            skill_content=SKILL_PATH.read_text(encoding="utf-8"),
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
            candidate_pass = validated_review is not None and bool(after["success"])
            baseline_score = float(before["score"])
            candidate_score = float(after["score"]) if validated_review is not None else 0.0
            model_integrity &= _provider_id(before["provider"]) == (f"openai:chat:{current_model}")
            model_integrity &= _provider_id(after["provider"]) == "echo"
            rubric_integrity &= before["testCase"]["assert"] == current_assertions
            rubric_integrity &= after["testCase"]["assert"] == current_assertions
            rubric_integrity &= before["testCase"]["options"] == current_options
            rubric_integrity &= after["testCase"]["options"] == current_options

            expected_baseline_vars = current_default_vars | current_test.get("vars", {})
            expected_grade_vars = {
                key: _resolve_file_value(value, config_dir=(EVAL_ROOT / CONFIGS[group]).parent)
                for key, value in current_default_vars.items()
                if key not in _COLD_CONTEXT_VARS
            } | {
                key: _resolve_file_value(value, config_dir=(EVAL_ROOT / CONFIGS[group]).parent)
                for key, value in current_test.get("vars", {}).items()
                if key not in _COLD_CONTEXT_VARS
            }
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
    expected_candidate_hash = hashlib.sha256(
        candidate_prompt(candidate_profile).encode()
    ).hexdigest()
    same_candidate_prompt = prompt_hashes == {expected_candidate_hash}
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
            "config_count": len(groups),
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


def compare_direct_evidence(
    baseline_dir: Path,
    candidate_dir: Path,
    *,
    candidate_profile: str,
    minimum_input_reduction_percent: float = 0.0,
    groups: tuple[str, ...] = FULL_REVIEW_GROUP_NAMES,
    baseline_profile: str | None = None,
    target_provider_id: str | None = None,
) -> dict[str, Any]:
    """Compare a plain reduced skill against the full-skill Promptfoo baseline."""
    baseline_prompt_tokens = 0
    baseline_completion_tokens = 0
    candidate_prompt_tokens = 0
    candidate_completion_tokens = 0
    config_integrity = True
    scenario_integrity = True
    prompt_integrity = True
    model_integrity = True
    rubric_integrity = True
    usage_integrity = True
    grading_integrity = True
    quality_rows: list[dict[str, Any]] = []
    full_skill = SKILL_PATH.read_text(encoding="utf-8")
    candidate_hashes: set[str] = set()
    identity_preserved_count = 0

    for group in groups:
        baseline_path = (
            baseline_dir / f"candidate-direct-{group}.json"
            if baseline_profile is not None
            else baseline_dir / f"issue557-baseline-{group}.json"
        )
        candidate_path = candidate_dir / f"candidate-direct-{group}-merged.json"
        if not candidate_path.exists():
            candidate_path = candidate_dir / f"candidate-direct-{group}.json"
        baseline = _read(baseline_path)
        candidate = _read(candidate_path)
        current_config, current_tests, _ = load_group(group)
        expected_candidate_config = build_direct_config(
            group,
            candidate_profile=candidate_profile,
        )
        reduced_skill = candidate_prompt_for_group(candidate_profile, group)
        candidate_hashes.add(hashlib.sha256(reduced_skill.encode()).hexdigest())
        _, baseline_scenarios, _ = build_prompts(group, skill_content=full_skill)
        current_model, candidate_scenarios, _ = build_prompts(
            group,
            skill_content=reduced_skill,
        )
        baseline_rows = baseline["results"]["results"]
        candidate_rows = candidate["results"]["results"]
        expected_count = len(current_tests)
        if not (
            len(baseline_rows)
            == len(candidate_rows)
            == len(baseline_scenarios)
            == len(candidate_scenarios)
            == expected_count
        ):
            raise ValueError(f"scenario count mismatch for {group}")

        expected_baseline_config = (
            build_direct_config(group, candidate_profile=baseline_profile)
            if baseline_profile is not None
            else current_config
        )
        config_integrity &= _direct_config_matches(
            baseline.get("config"),
            expected_baseline_config,
        )
        config_integrity &= _direct_config_matches(
            candidate.get("config"),
            expected_candidate_config,
        )
        baseline_usage = _direct_positive_usage(
            baseline["results"]["stats"].get("tokenUsage"),
            minimum_requests=expected_count,
        )
        candidate_usage = _direct_positive_usage(
            candidate["results"]["stats"].get("tokenUsage"),
            minimum_requests=expected_count,
        )
        if baseline_usage is None or candidate_usage is None:
            usage_integrity = False
        else:
            baseline_prompt_tokens += baseline_usage[0]
            baseline_completion_tokens += baseline_usage[1]
            candidate_prompt_tokens += candidate_usage[0]
            candidate_completion_tokens += candidate_usage[1]

        baseline_row_usage = [0, 0]
        candidate_row_usage = [0, 0]
        assertions = current_config.get("defaultTest", {}).get("assert", [])
        options = current_config.get("defaultTest", {}).get("options", {})
        option_shape = {key: value for key, value in options.items() if key != "provider"}
        for before, after, baseline_scenario, candidate_scenario, current_test in zip(
            baseline_rows,
            candidate_rows,
            baseline_scenarios,
            candidate_scenarios,
            current_tests,
            strict=True,
        ):
            description = current_test["description"]
            scenario_integrity &= before["testCase"]["description"] == description
            scenario_integrity &= after["testCase"]["description"] == description
            prompt_integrity &= before["prompt"]["raw"] == baseline_scenario[1]
            prompt_integrity &= after["prompt"]["raw"] == candidate_scenario[1]
            expected_provider = target_provider_id or f"openai:chat:{current_model}"
            model_integrity &= _provider_id(before["provider"]) == expected_provider
            model_integrity &= _provider_id(after["provider"]) == expected_provider
            rubric_integrity &= before["testCase"]["assert"] == assertions
            rubric_integrity &= after["testCase"]["assert"] == assertions
            rubric_integrity &= {
                key: value
                for key, value in before["testCase"]["options"].items()
                if key != "provider"
            } == option_shape
            rubric_integrity &= {
                key: value
                for key, value in after["testCase"]["options"].items()
                if key != "provider"
            } == option_shape
            rubric_integrity &= _judge_model(before) == _judge_model(after)

            before_output = before.get("response", {}).get("output")
            after_output = after.get("response", {}).get("output")
            if not isinstance(before_output, str) or not isinstance(after_output, str):
                grading_integrity = False
                before_output = before_output if isinstance(before_output, str) else ""
                after_output = after_output if isinstance(after_output, str) else ""
            grading_integrity &= _grading_result_matches(
                before,
                assertions=assertions,
                graded_output=before_output,
                allow_reasoning_usage=True,
            )
            grading_integrity &= _grading_result_matches(
                after,
                assertions=assertions,
                graded_output=after_output,
                allow_reasoning_usage=True,
            )
            for row, totals in ((before, baseline_row_usage), (after, candidate_row_usage)):
                response_usage = _direct_positive_usage(
                    row.get("response", {}).get("tokenUsage"),
                    minimum_requests=1,
                )
                if response_usage is None:
                    usage_integrity = False
                else:
                    totals[0] += response_usage[0]
                    totals[1] += response_usage[1]

            baseline_pass = bool(before["success"])
            candidate_pass = bool(after["success"])
            baseline_score = float(before["score"])
            candidate_score = float(after["score"])
            unchanged_prompt = baseline_scenario[1] == candidate_scenario[1]
            quality_preserved = (
                unchanged_prompt
                or candidate_pass
                or (not baseline_pass and candidate_score >= baseline_score)
            )
            identity_preserved_count += int(unchanged_prompt)
            quality_rows.append(
                {
                    "group": group,
                    "description": description,
                    "baseline_pass": baseline_pass,
                    "candidate_pass": candidate_pass,
                    "baseline_score": baseline_score,
                    "candidate_score": candidate_score,
                    "unchanged_prompt": unchanged_prompt,
                    "quality_preserved": quality_preserved,
                }
            )

        if baseline_usage is not None:
            usage_integrity &= tuple(baseline_row_usage) == baseline_usage
        if candidate_usage is not None:
            usage_integrity &= tuple(candidate_row_usage) == candidate_usage

    input_reduction_percent = (
        round(
            100 * (baseline_prompt_tokens - candidate_prompt_tokens) / baseline_prompt_tokens,
            2,
        )
        if baseline_prompt_tokens > 0
        else 0.0
    )
    baseline_total = baseline_prompt_tokens + baseline_completion_tokens
    candidate_total = candidate_prompt_tokens + candidate_completion_tokens
    total_reduction_percent = (
        round(100 * (baseline_total - candidate_total) / baseline_total, 2)
        if baseline_total > 0
        else 0.0
    )
    integrity_preserved = all(
        (
            config_integrity,
            scenario_integrity,
            prompt_integrity,
            model_integrity,
            rubric_integrity,
            usage_integrity,
            grading_integrity,
        )
    )
    quality_preserved = all(row["quality_preserved"] for row in quality_rows)
    token_target_met = input_reduction_percent >= minimum_input_reduction_percent
    proven = integrity_preserved and quality_preserved and token_target_met
    return {
        "verdict": "PROVEN" if proven else "NOT PROVEN",
        "candidate_profile": candidate_profile,
        "candidate_prompt_sha256": (
            next(iter(candidate_hashes)) if len(candidate_hashes) == 1 else None
        ),
        "candidate_prompt_sha256s": sorted(candidate_hashes),
        "integrity": {
            "preserved": integrity_preserved,
            "configs_match": config_integrity,
            "scenarios_match": scenario_integrity,
            "rendered_prompts_match": prompt_integrity,
            "models_match": model_integrity,
            "rubrics_and_judges_match": rubric_integrity,
            "usage_is_valid": usage_integrity,
            "grading_results_are_consistent": grading_integrity,
        },
        "quality": {
            "baseline_passed": sum(row["baseline_pass"] for row in quality_rows),
            "candidate_passed": sum(row["candidate_pass"] for row in quality_rows),
            "scenario_count": len(quality_rows),
            "config_count": len(groups),
            "preserved": quality_preserved,
            "preserved_by_identical_prompt": identity_preserved_count,
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
            "baseline_total": baseline_total,
            "candidate_total": candidate_total,
            "total_reduction_percent": total_reduction_percent,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-dir", type=Path, default=Path("/private/tmp"))
    parser.add_argument("--candidate-dir", type=Path, default=Path("/private/tmp/issue557"))
    parser.add_argument("--minimum-input-reduction-percent", type=float, default=30.0)
    parser.add_argument(
        "--profile",
        choices=(
            "compact",
            "repaired-compact",
            "full-gated",
            "core-gated",
            "full-plain",
            "routed-root-plain",
            "balanced-plain",
            "warm-plain",
            "core-plain",
        ),
        default="compact",
    )
    parser.add_argument("--direct-baseline-profile", choices=("full-plain",))
    parser.add_argument("--direct-provider-id")
    parser.add_argument(
        "--direct",
        action="store_true",
        help="compare direct Promptfoo candidate artifacts without the deterministic gate",
    )
    parser.add_argument(
        "--all-review",
        action="store_true",
        help="compare all non-control reviewing-before-merge eval scenarios",
    )
    args = parser.parse_args()
    if args.direct:
        if not args.all_review or not args.profile.endswith("-plain"):
            parser.error("--direct requires --all-review and a *-plain profile")
        result = compare_direct_evidence(
            args.baseline_dir,
            args.candidate_dir,
            minimum_input_reduction_percent=args.minimum_input_reduction_percent,
            candidate_profile=args.profile,
            baseline_profile=args.direct_baseline_profile,
            target_provider_id=args.direct_provider_id,
        )
    else:
        result = compare_evidence(
            args.baseline_dir,
            args.candidate_dir,
            minimum_input_reduction_percent=args.minimum_input_reduction_percent,
            groups=FULL_REVIEW_GROUP_NAMES if args.all_review else GROUPS,
            candidate_profile=args.profile,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
