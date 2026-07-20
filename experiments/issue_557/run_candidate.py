# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Run issue #557's compact candidate against the pinned review scenarios.

This experiment intentionally bypasses promptfoo only for candidate generation
so deterministic gate validation can run before grading.  The emitted review
prose is then graded by each original promptfoo config and rubric unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from sumo_qa.review_gate_poc import ReviewGateValidationError, validate_review_response

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = Path(__file__).with_name("compact_review_prompt.md")
EVAL_ROOT = REPO_ROOT / "tests/evals/promptfoo"
_VARIABLE_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


@dataclass(frozen=True)
class PinnedGroup:
    config: str
    description_pattern: str


PINNED_GROUPS = {
    "core": PinnedGroup(
        "skill-reviewing-before-merge.yaml",
        r"^SEED - auth helper fix with fresh passing tests$",
    ),
    "adversarial": PinnedGroup(
        "skill-reviewing-before-merge-adversarial.yaml",
        r"weak-assertion|rollback-data-loss|NEGATIVE CONTROL docs-only typo",
    ),
    "verifier": PinnedGroup(
        "skill-reviewing-before-merge-verifier-evidence.yaml",
        r"missing-verifier|discharged",
    ),
    "unproven": PinnedGroup(
        "skill-reviewing-before-merge-unproven-escalation.yaml",
        r"unproven-substring",
    ),
}


def _sha256(value: str | bytes) -> str:
    data = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def _resolve_file_value(value: Any, *, config_dir: Path) -> Any:
    if not isinstance(value, str) or not value.startswith("file://"):
        return value
    path = (config_dir / value.removeprefix("file://")).resolve()
    content = path.read_text()
    if path.suffix in {".yaml", ".yml"}:
        return yaml.safe_load(content)
    if path.suffix == ".json":
        return json.loads(content)
    return content.rstrip()


def _render_prompt(template: str, variables: dict[str, Any]) -> str:
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            missing.add(key)
            return match.group(0)
        value = variables[key]
        if isinstance(value, str):
            return value.rstrip()
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    rendered = _VARIABLE_RE.sub(replace, template)
    if missing:
        raise ValueError(f"unresolved prompt variable(s): {', '.join(sorted(missing))}")
    return rendered


def load_group(group_name: str) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    group = PINNED_GROUPS[group_name]
    config_path = EVAL_ROOT / group.config
    config = yaml.safe_load(config_path.read_text())
    matcher = re.compile(group.description_pattern)
    tests = [test for test in config["tests"] if matcher.search(test["description"])]
    if not tests:
        raise ValueError(f"no pinned scenarios selected for {group_name}")
    return config, tests, _sha256(config_path.read_bytes())


def build_prompts(
    group_name: str,
    *,
    skill_content: str | None = None,
) -> tuple[str, list[tuple[str, str]], dict[str, str]]:
    config, tests, config_hash = load_group(group_name)
    compact_prompt = PROMPT_PATH.read_text()
    config_dir = (EVAL_ROOT / PINNED_GROUPS[group_name].config).parent
    defaults = {
        key: _resolve_file_value(value, config_dir=config_dir)
        for key, value in config.get("defaultTest", {}).get("vars", {}).items()
    }
    defaults["skill_content"] = (
        compact_prompt if skill_content is None else skill_content
    ).rstrip()
    template = config["prompts"][0]
    rendered: list[tuple[str, str]] = []
    for test in tests:
        variables = defaults | {
            key: _resolve_file_value(value, config_dir=config_dir)
            for key, value in test.get("vars", {}).items()
        }
        rendered.append((test["description"], _render_prompt(template, variables)))

    provider = config["providers"][0]
    model = provider["id"].removeprefix("openai:chat:")
    metadata = {
        "config": PINNED_GROUPS[group_name].config,
        "config_sha256": config_hash,
        "compact_prompt_sha256": _sha256(compact_prompt),
        "model": model,
    }
    return model, rendered, metadata


def _completion(
    client: httpx.Client,
    *,
    model: str,
    messages: list[dict[str, str]],
    api_key: str,
) -> tuple[str, dict[str, Any]]:
    request_body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "seed": 42,
    }
    if not model.startswith("gpt-5"):
        request_body["temperature"] = 0.0
    response = client.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=request_body,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"OpenAI candidate request failed: {response.text}") from exc
    body = response.json()
    content = body["choices"][0]["message"]["content"]
    if not content:
        raise RuntimeError("candidate returned an empty response")
    return content, body.get("usage", {})


def write_grade_config(group_name: str, reviews: list[str], output_dir: Path) -> Path:
    """Create an echo-provider config with the original rubric and selected tests."""
    config, tests, _ = load_group(group_name)
    if len(reviews) != len(tests):
        raise ValueError(
            f"review count mismatch for {group_name}: got {len(reviews)}, expected {len(tests)}"
        )

    default_test = config["defaultTest"]
    default_vars = {
        key: value
        for key, value in default_test.get("vars", {}).items()
        if key
        not in {"skill_content", "loaded_classifications", "loaded_rules", "loaded_techniques"}
    }
    grade_tests = []
    for test, review in zip(tests, reviews, strict=True):
        grade_tests.append(
            {
                "description": test["description"],
                "vars": default_vars | test.get("vars", {}) | {"output": review},
            }
        )

    grade_config = {
        "description": f"Issue #557 unchanged-rubric grading: {group_name}",
        "providers": ["echo"],
        "prompts": ["{{output}}"],
        "defaultTest": {
            "assert": default_test["assert"],
            "options": default_test["options"],
        },
        "tests": grade_tests,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"candidate-{group_name}-grade-config.yaml"
    path.write_text(yaml.safe_dump(grade_config, sort_keys=False, allow_unicode=True))
    return path


def validate_result_record(record: dict[str, Any]) -> tuple[str, int, int]:
    """Revalidate one stored candidate record and return review plus billed usage."""
    attempts = record.get("attempts")
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= 2:
        raise ValueError("candidate record must contain one or two attempts")

    prompt_tokens = 0
    completion_tokens = 0
    for index, attempt in enumerate(attempts, start=1):
        if attempt.get("number") != index:
            raise ValueError("candidate attempt numbers must be sequential")
        usage = attempt.get("usage")
        if not isinstance(usage, dict):
            raise ValueError("candidate attempt is missing usage")
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        total = usage.get("total_tokens")
        if (
            type(prompt) is not int
            or type(completion) is not int
            or type(total) is not int
            or prompt <= 0
            or completion <= 0
            or total != prompt + completion
        ):
            raise ValueError("candidate attempt usage must be positive and internally consistent")
        prompt_tokens += prompt
        completion_tokens += completion

        response = attempt.get("response")
        if not isinstance(response, str) or not response:
            raise ValueError("candidate attempt is missing its raw response")
        if index < len(attempts):
            try:
                validate_review_response(response)
            except ReviewGateValidationError:
                continue
            raise ValueError("candidate retried after an already-valid response")

    try:
        validated = validate_review_response(attempts[-1]["response"])
    except ReviewGateValidationError as exc:
        raise ValueError(f"selected candidate response is invalid: {exc}") from exc
    if record.get("review") != validated.review:
        raise ValueError("stored review does not match the validated raw response")
    if record.get("gate_report") != validated.report.model_dump():
        raise ValueError("stored gate report does not match the validated raw response")
    if record.get("safe_to_merge") is not validated.safe_to_merge:
        raise ValueError("stored verdict does not match the validated raw response")
    return validated.review, prompt_tokens, completion_tokens


def run_group(group_name: str, output_dir: Path) -> Path:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required")

    model, scenarios, metadata = build_prompts(group_name)
    results: list[dict[str, Any]] = []
    reviews: list[str] = []
    with httpx.Client(timeout=300) as client:
        for description, prompt in scenarios:
            messages = [{"role": "user", "content": prompt}]
            attempts: list[dict[str, Any]] = []
            validated = None
            for attempt_number in (1, 2):
                raw, usage = _completion(
                    client,
                    model=model,
                    messages=messages,
                    api_key=api_key,
                )
                attempts.append({"number": attempt_number, "usage": usage, "response": raw})
                try:
                    validated = validate_review_response(raw)
                    break
                except ReviewGateValidationError as exc:
                    if attempt_number == 2:
                        raise RuntimeError(
                            f"deterministic validation failed twice for {description}: {exc}; "
                            f"last response={raw!r}"
                        ) from exc
                    messages.extend(
                        [
                            {"role": "assistant", "content": raw},
                            {
                                "role": "user",
                                "content": (
                                    "Deterministic gate rejection: "
                                    f"{exc}. Return the complete corrected GATE_REPORT and REVIEW "
                                    "envelopes. If an evidence source is missing from REVIEW, add an "
                                    "explicit 'Command: <observed command> -> <observed result>' line "
                                    "using only the supplied evidence. Evidence in GATE_REPORT alone "
                                    "does not support the visible verdict. Do not change your QA judgment "
                                    "merely to pass validation."
                                ),
                            },
                        ]
                    )

            if validated is None:  # pragma: no cover - loop either validates or raises
                raise AssertionError("candidate validation did not terminate")
            reviews.append(validated.review)
            results.append(
                {
                    "description": description,
                    "rendered_prompt_sha256": _sha256(prompt),
                    "rendered_prompt_characters": len(prompt),
                    "attempts": attempts,
                    "gate_report": validated.report.model_dump(),
                    "safe_to_merge": validated.safe_to_merge,
                    "review": validated.review,
                }
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / f"candidate-{group_name}.json"
    model_outputs_path = output_dir / f"candidate-{group_name}-outputs.json"
    result_path.write_text(
        json.dumps({"group": group_name, **metadata, "results": results}, indent=2) + "\n"
    )
    model_outputs_path.write_text(json.dumps(reviews, indent=2) + "\n")
    write_grade_config(group_name, reviews, output_dir)
    return result_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("group", choices=PINNED_GROUPS)
    parser.add_argument("--output-dir", type=Path, default=Path("/private/tmp/issue557"))
    parser.add_argument("--grade-from-result", type=Path)
    args = parser.parse_args()
    if args.grade_from_result is not None:
        result = json.loads(args.grade_from_result.read_text())
        reviews = [validate_result_record(item)[0] for item in result["results"]]
        print(write_grade_config(args.group, reviews, args.output_dir))
        return
    print(run_group(args.group, args.output_dir))


if __name__ == "__main__":
    main()
