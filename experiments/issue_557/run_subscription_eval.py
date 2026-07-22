# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Run issue #557's complete review comparison through ChatGPT Codex auth.

No provider API key is permitted in child processes. Each baseline, candidate,
and judge turn runs as an isolated ephemeral ``codex exec`` session. Evidence is
written after every scenario so a subscription limit or interruption is safely
resumable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sumo_qa.review_gate_poc import ReviewGateValidationError, validate_review_response

from .run_candidate import (
    ALL_GROUPS,
    EVAL_ROOT,
    FULL_REVIEW_GROUPS,
    _render_prompt,
    _resolve_file_value,
    build_prompts,
    candidate_prompt,
    load_group,
)

METERED_KEY_NAMES = ("OPENAI_API_KEY", "GEMINI_API_KEY", "CODEX_API_KEY")
DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_REASONING_EFFORT = "low"
SKILL_PATH = Path(__file__).resolve().parents[2] / "skills/sumo-qa-reviewing-before-merge/SKILL.md"
_LOOP_RE = re.compile(
    r"{%\s*for\s+ap\s+in\s+anti_patterns\s*%}(.*?){%\s*endfor\s*%}",
    re.DOTALL,
)
_SECURITY_RE = re.compile(
    r"security|securit|vulnerab|owasp|\bxss\b|\bcsrf\b|\bsqli\b|injection|"
    r"authoris|authoriz|authentic|ownership|\btoken\b|\bsecret\b|sanitis|sanitiz|"
    r"replay|tamper|privilege escalation|idor|forbidden",
    re.IGNORECASE,
)
_FORBIDDEN_EVENT_ITEMS = {
    "command_execution",
    "file_change",
    "mcp_tool_call",
    "web_search",
    "image_generation",
}
_GENERATION_PREFIX = """This is a controlled prompt-only evaluation.
Do not use tools, inspect files, browse, or modify anything. The task below is
complete and self-contained. Answer it directly and return only the requested
review response, without commentary about this evaluation.

--- BEGIN EVALUATION TASK ---
"""
_GENERATION_SUFFIX = "\n--- END EVALUATION TASK ---\n"


@dataclass(frozen=True)
class CodexResult:
    output: str
    usage: dict[str, int]


def subscription_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """Return an environment that cannot select usage-billed provider auth."""
    env = dict(os.environ if source is None else source)
    for name in METERED_KEY_NAMES:
        env.pop(name, None)
    env["CODEX_NON_INTERACTIVE"] = "1"
    return env


def codex_command(
    *,
    model: str,
    reasoning_effort: str,
    runner_dir: Path,
    output_schema: Path | None = None,
) -> list[str]:
    command = [
        "codex",
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--model",
        model,
        "--config",
        f"model_reasoning_effort={json.dumps(reasoning_effort)}",
        "--sandbox",
        "read-only",
        "--cd",
        str(runner_dir),
        "--color",
        "never",
        "--json",
    ]
    if output_schema is not None:
        command.extend(("--output-schema", str(output_schema)))
    command.append("-")
    return command


def parse_codex_jsonl(stdout: str) -> CodexResult:
    output: str | None = None
    usage: dict[str, int] | None = None
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"non-JSON Codex stdout line: {line[:120]}") from exc
        item = event.get("item")
        if isinstance(item, dict):
            item_type = item.get("type")
            if item_type in _FORBIDDEN_EVENT_ITEMS:
                raise ValueError(f"Codex evaluation used forbidden item: {item_type}")
            if event.get("type") == "item.completed" and item_type == "agent_message":
                text = item.get("text")
                if isinstance(text, str) and text:
                    output = text
        if event.get("type") == "turn.completed":
            raw_usage = event.get("usage")
            if isinstance(raw_usage, dict):
                required = (
                    "input_tokens",
                    "cached_input_tokens",
                    "output_tokens",
                    "reasoning_output_tokens",
                )
                if all(type(raw_usage.get(key)) is int for key in required):
                    usage = {key: raw_usage[key] for key in required}
        if event.get("type") in {"turn.failed", "error"}:
            raise ValueError(f"Codex evaluation failed: {event}")
    if output is None or usage is None:
        raise ValueError("Codex JSONL lacked a final agent message or usage")
    return CodexResult(output=output, usage=usage)


def run_codex(
    prompt: str,
    *,
    model: str,
    reasoning_effort: str,
    runner_dir: Path,
    output_schema: Path | None = None,
    timeout_seconds: int = 600,
) -> CodexResult:
    completed = subprocess.run(
        codex_command(
            model=model,
            reasoning_effort=reasoning_effort,
            runner_dir=runner_dir,
            output_schema=output_schema,
        ),
        input=prompt,
        text=True,
        capture_output=True,
        env=subscription_environment(),
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()[-2_000:]
        raise RuntimeError(f"codex exec failed ({completed.returncode}): {stderr}")
    return parse_codex_jsonl(completed.stdout)


def verify_chatgpt_auth() -> None:
    completed = subprocess.run(
        ["codex", "login", "status"],
        text=True,
        capture_output=True,
        env=subscription_environment(),
        timeout=30,
        check=False,
    )
    status = f"{completed.stdout}\n{completed.stderr}".strip()
    if completed.returncode != 0 or "Logged in using ChatGPT" not in status:
        raise RuntimeError(f"subscription harness requires ChatGPT Codex auth; got: {status}")


def _sha256(value: str | bytes) -> str:
    data = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def _scenario_variables(group: str, index: int) -> tuple[dict[str, Any], dict[str, Any]]:
    config, tests, _ = load_group(group)
    config_dir = (EVAL_ROOT / ALL_GROUPS[group].config).parent
    defaults = {
        key: _resolve_file_value(value, config_dir=config_dir)
        for key, value in config.get("defaultTest", {}).get("vars", {}).items()
    }
    variables = defaults | {
        key: _resolve_file_value(value, config_dir=config_dir)
        for key, value in tests[index].get("vars", {}).items()
    }
    return config, variables


def render_llm_rubric(group: str, index: int, output: str) -> str:
    """Render the existing Promptfoo LLM rubric without invoking a provider."""
    config, variables = _scenario_variables(group, index)
    assertions = config["defaultTest"]["assert"]
    llm_assertions = [item for item in assertions if item["type"] == "llm-rubric"]
    if len(llm_assertions) != 1:
        raise ValueError(f"expected one LLM rubric for {group}")
    template = llm_assertions[0]["value"]
    anti_patterns = variables.get("anti_patterns")
    if not isinstance(anti_patterns, list):
        raise ValueError(f"anti_patterns must remain a native list for {group}")

    def render_loop(match: re.Match[str]) -> str:
        body = match.group(1)
        # Match Nunjucks/JavaScript string coercion exactly. One historical YAML
        # row parses a colon-bearing anti-pattern as an object, which Promptfoo
        # renders as ``[object Object]``.
        return "".join(
            body.replace("{{ ap }}", "[object Object]" if isinstance(item, dict) else str(item))
            for item in anti_patterns
        )

    rubric = _render_prompt(_LOOP_RE.sub(render_loop, template), variables)
    rubric_prompt = config["defaultTest"]["options"]["rubricPrompt"]
    rendered = _render_prompt(rubric_prompt, variables | {"rubric": rubric, "output": output})
    if "{{" in rendered or "{%" in rendered:
        raise ValueError(f"unresolved rubric template syntax for {group}")
    ground_truth = variables.get("ground_truth_context")
    if not isinstance(ground_truth, str):
        raise ValueError(f"ground_truth_context must remain a string for {group}")
    return (
        f"{rendered}\n\n"
        "--- SCENARIO GROUND TRUTH ---\n"
        f"{ground_truth}\n"
        "--- END SCENARIO GROUND TRUTH ---\n\n"
        "Use the scenario ground truth only to determine what evidence was supplied. "
        "Apply the existing rubric and decision table unchanged."
    )


def _javascript_grade(group: str, index: int, output: str) -> dict[str, Any] | None:
    config, variables = _scenario_variables(group, index)
    js_assertions = [
        item for item in config["defaultTest"]["assert"] if item["type"] == "javascript"
    ]
    if not js_assertions:
        return None
    if group != "full-security-relevance" or len(js_assertions) != 1:
        raise ValueError(f"unsupported JavaScript assertion in {group}")
    required = variables.get("security_must_appear") is True
    passed = not required or bool(_SECURITY_RE.search(output))
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "security term required and present"
        if passed
        else "required security gap absent",
    }


def _generation_prompt(prompt: str) -> str:
    return f"{_GENERATION_PREFIX}{prompt}{_GENERATION_SUFFIX}"


def _sum_usage(items: list[dict[str, int]]) -> dict[str, int]:
    keys = (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    )
    return {key: sum(item[key] for item in items) for key in keys}


def generate_candidate(
    prompt: str,
    *,
    model: str,
    reasoning_effort: str,
    runner_dir: Path,
    timeout_seconds: int,
) -> tuple[str, list[dict[str, Any]], dict[str, int]]:
    attempts: list[dict[str, Any]] = []
    first = run_codex(
        _generation_prompt(prompt),
        model=model,
        reasoning_effort=reasoning_effort,
        runner_dir=runner_dir,
        timeout_seconds=timeout_seconds,
    )
    attempts.append({"output": first.output, "usage": first.usage})
    try:
        validated = validate_review_response(first.output)
    except ReviewGateValidationError as exc:
        repair = run_codex(
            _generation_prompt(prompt)
            + "\nThe previous response failed deterministic validation:\n"
            + f"{exc}\n\nPrevious response:\n{first.output}\n\n"
            + "Return the complete corrected GATE_REPORT and REVIEW envelopes. "
            + "Fix only the response contract; do not change the QA judgment.",
            model=model,
            reasoning_effort=reasoning_effort,
            runner_dir=runner_dir,
            timeout_seconds=timeout_seconds,
        )
        attempts.append({"output": repair.output, "usage": repair.usage})
        validated = validate_review_response(repair.output)
    return validated.review, attempts, _sum_usage([item["usage"] for item in attempts])


def grade_output(
    group: str,
    index: int,
    output: str,
    *,
    model: str,
    reasoning_effort: str,
    runner_dir: Path,
    grade_schema: Path,
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, int]]:
    rendered = render_llm_rubric(group, index, output)
    result = run_codex(
        "This is a controlled prompt-only grading task. Do not use tools, inspect files, "
        "browse, or modify anything. Apply the supplied rubric strictly and return only "
        f"the schema-conforming JSON result.\n\n{rendered}",
        model=model,
        reasoning_effort=reasoning_effort,
        runner_dir=runner_dir,
        output_schema=grade_schema,
        timeout_seconds=timeout_seconds,
    )
    try:
        llm_grade = json.loads(result.output)
    except json.JSONDecodeError as exc:
        raise ValueError("structured Codex judge returned invalid JSON") from exc
    if (
        type(llm_grade.get("pass")) is not bool
        or not isinstance(llm_grade.get("score"), int | float)
        or not 0 <= llm_grade["score"] <= 1
        or not isinstance(llm_grade.get("reason"), str)
    ):
        raise ValueError(f"invalid structured grade: {llm_grade}")
    components = [llm_grade]
    javascript_grade = _javascript_grade(group, index, output)
    if javascript_grade is not None:
        components.insert(0, javascript_grade)
    grade = {
        "pass": all(component["pass"] for component in components),
        "score": sum(float(component["score"]) for component in components) / len(components),
        "reason": " | ".join(component["reason"] for component in components),
        "components": components,
    }
    return grade, result.usage


def _scenario_record(
    group: str,
    index: int,
    *,
    baseline_record: dict[str, Any] | None,
    model: str,
    reasoning_effort: str,
    runner_dir: Path,
    grade_schema: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    config, tests, config_hash = load_group(group)
    del config
    description = tests[index]["description"]
    full_skill = SKILL_PATH.read_text(encoding="utf-8")
    _, baseline_prompts, _ = build_prompts(group, skill_content=full_skill)
    _, candidate_prompts, _ = build_prompts(group, candidate_profile="repaired-compact")
    baseline_prompt = baseline_prompts[index][1]
    candidate_prompt_text = candidate_prompts[index][1]

    baseline: dict[str, Any]
    if baseline_record is None:
        baseline_result = run_codex(
            _generation_prompt(baseline_prompt),
            model=model,
            reasoning_effort=reasoning_effort,
            runner_dir=runner_dir,
            timeout_seconds=timeout_seconds,
        )
        baseline_grade, baseline_grade_usage = grade_output(
            group,
            index,
            baseline_result.output,
            model=model,
            reasoning_effort=reasoning_effort,
            runner_dir=runner_dir,
            grade_schema=grade_schema,
            timeout_seconds=timeout_seconds,
        )
        baseline = {
            "prompt_sha256": _sha256(baseline_prompt),
            "output": baseline_result.output,
            "usage": baseline_result.usage,
            "grade": baseline_grade,
            "grade_usage": baseline_grade_usage,
        }
    else:
        if (
            baseline_record.get("scenario_id") != f"{group}:{index}"
            or baseline_record.get("description") != description
            or baseline_record.get("config_sha256") != config_hash
            or baseline_record.get("baseline", {}).get("prompt_sha256") != _sha256(baseline_prompt)
        ):
            raise ValueError(f"reused baseline does not match {group}:{index}")
        source_baseline = baseline_record["baseline"]
        baseline_grade, baseline_grade_usage = grade_output(
            group,
            index,
            source_baseline["output"],
            model=model,
            reasoning_effort=reasoning_effort,
            runner_dir=runner_dir,
            grade_schema=grade_schema,
            timeout_seconds=timeout_seconds,
        )
        baseline = {
            **source_baseline,
            "grade": baseline_grade,
            "grade_usage": baseline_grade_usage,
        }
    candidate_review, candidate_attempts, candidate_usage = generate_candidate(
        candidate_prompt_text,
        model=model,
        reasoning_effort=reasoning_effort,
        runner_dir=runner_dir,
        timeout_seconds=timeout_seconds,
    )
    candidate_grade, candidate_grade_usage = grade_output(
        group,
        index,
        candidate_review,
        model=model,
        reasoning_effort=reasoning_effort,
        runner_dir=runner_dir,
        grade_schema=grade_schema,
        timeout_seconds=timeout_seconds,
    )
    quality_preserved = (
        candidate_grade["pass"]
        if baseline["grade"]["pass"]
        else candidate_grade["pass"] or candidate_grade["score"] >= baseline["grade"]["score"]
    )
    return {
        "scenario_id": f"{group}:{index}",
        "group": group,
        "index": index,
        "description": description,
        "config_sha256": config_hash,
        "baseline": baseline,
        "candidate": {
            "prompt_sha256": _sha256(candidate_prompt_text),
            "output": candidate_review,
            "attempts": candidate_attempts,
            "usage": candidate_usage,
            "grade": candidate_grade,
            "grade_usage": candidate_grade_usage,
        },
        "quality_preserved": quality_preserved,
    }


def summarize(records: list[dict[str, Any]], *, minimum_input_reduction: float) -> dict[str, Any]:
    complete = [record for record in records if "error" not in record]
    baseline_input = sum(record["baseline"]["usage"]["input_tokens"] for record in complete)
    candidate_input = sum(record["candidate"]["usage"]["input_tokens"] for record in complete)
    baseline_total = sum(
        record["baseline"]["usage"]["input_tokens"]
        + record["baseline"]["usage"]["output_tokens"]
        + record["baseline"]["usage"]["reasoning_output_tokens"]
        for record in complete
    )
    candidate_total = sum(
        record["candidate"]["usage"]["input_tokens"]
        + record["candidate"]["usage"]["output_tokens"]
        + record["candidate"]["usage"]["reasoning_output_tokens"]
        for record in complete
    )
    input_reduction = (
        100 * (baseline_input - candidate_input) / baseline_input if baseline_input else 0.0
    )
    total_reduction = (
        100 * (baseline_total - candidate_total) / baseline_total if baseline_total else 0.0
    )
    all_complete = len(complete) == len(records) == 46
    quality_preserved = all(record.get("quality_preserved") for record in records)
    proven = all_complete and quality_preserved and input_reduction >= minimum_input_reduction
    return {
        "verdict": "PROVEN" if proven else "NOT PROVEN",
        "scenario_count": len(records),
        "completed_count": len(complete),
        "quality": {
            "baseline_passed": sum(record["baseline"]["grade"]["pass"] for record in complete),
            "candidate_passed": sum(record["candidate"]["grade"]["pass"] for record in complete),
            "regressions": sum(not record.get("quality_preserved", False) for record in records),
            "preserved": quality_preserved,
        },
        "tokens": {
            "baseline_input": baseline_input,
            "candidate_input": candidate_input,
            "input_reduction_percent": round(input_reduction, 2),
            "baseline_total": baseline_total,
            "candidate_total": candidate_total,
            "total_reduction_percent": round(total_reduction, 2),
            "minimum_input_reduction_percent": minimum_input_reduction,
        },
    }


def _write_evidence(
    output_path: Path,
    *,
    metadata: dict[str, Any],
    records: list[dict[str, Any]],
    minimum_input_reduction: float,
) -> None:
    ordered = sorted(
        records,
        key=lambda item: (list(FULL_REVIEW_GROUPS).index(item["group"]), item["index"]),
    )
    payload = {
        "metadata": metadata,
        "summary": summarize(ordered, minimum_input_reduction=minimum_input_reduction),
        "records": ordered,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output_path)


def _grade_schema(runner_dir: Path) -> Path:
    schema = {
        "type": "object",
        "properties": {
            "pass": {"type": "boolean"},
            "score": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
        "required": ["pass", "score", "reason"],
        "additionalProperties": False,
    }
    path = runner_dir / "grade-schema.json"
    path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--minimum-input-reduction-percent", type=float, default=0.01)
    parser.add_argument("--baseline-evidence", type=Path)
    parser.add_argument("--groups", nargs="+", choices=FULL_REVIEW_GROUPS)
    parser.add_argument("--filter-pattern")
    parser.add_argument("--max-scenarios", type=int)
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")

    verify_chatgpt_auth()
    runner_dir = args.output.parent / "codex-runner"
    runner_dir.mkdir(parents=True, exist_ok=True)
    grade_schema = _grade_schema(runner_dir)
    selected_groups = tuple(args.groups or FULL_REVIEW_GROUPS)
    matcher = re.compile(args.filter_pattern) if args.filter_pattern else None
    scenarios = [
        (group, index)
        for group in selected_groups
        for index, test in enumerate(load_group(group)[1])
        if matcher is None or matcher.search(test["description"])
    ]
    if args.max_scenarios is not None:
        scenarios = scenarios[: args.max_scenarios]
    if not scenarios:
        parser.error("no scenarios selected")

    metadata = {
        "auth": "ChatGPT subscription",
        "metered_api_keys_removed": list(METERED_KEY_NAMES),
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "candidate_profile": "repaired-compact",
        "judge_context": "rubric+scenario-ground-truth",
        "candidate_prompt_sha256": _sha256(candidate_prompt("repaired-compact")),
        "full_skill_sha256": _sha256(SKILL_PATH.read_bytes()),
        "selected_scenario_count": len(scenarios),
        "baseline_evidence": (
            {
                "path": str(args.baseline_evidence),
                "sha256": _sha256(args.baseline_evidence.read_bytes()),
            }
            if args.baseline_evidence is not None
            else None
        ),
    }
    baseline_by_id: dict[str, dict[str, Any]] = {}
    if args.baseline_evidence is not None:
        baseline_payload = json.loads(args.baseline_evidence.read_text(encoding="utf-8"))
        baseline_metadata = baseline_payload.get("metadata", {})
        expected_baseline_metadata = {
            "auth": "ChatGPT subscription",
            "model": args.model,
            "reasoning_effort": args.reasoning_effort,
            "full_skill_sha256": metadata["full_skill_sha256"],
        }
        if any(
            baseline_metadata.get(key) != value for key, value in expected_baseline_metadata.items()
        ):
            raise RuntimeError("baseline evidence model/auth/full-skill metadata does not match")
        baseline_by_id = {
            record["scenario_id"]: record
            for record in baseline_payload.get("records", [])
            if "error" not in record
        }
        missing_baselines = [
            f"{group}:{index}"
            for group, index in scenarios
            if f"{group}:{index}" not in baseline_by_id
        ]
        if missing_baselines:
            raise RuntimeError(f"baseline evidence is missing scenarios: {missing_baselines}")
    records_by_id: dict[str, dict[str, Any]] = {}
    if args.output.exists() and not args.fresh:
        existing = json.loads(args.output.read_text(encoding="utf-8"))
        if existing.get("metadata") != metadata:
            raise RuntimeError("existing subscription evidence metadata does not match this run")
        records_by_id = {
            record["scenario_id"]: record
            for record in existing.get("records", [])
            if "error" not in record
        }
    pending = [
        (group, index) for group, index in scenarios if f"{group}:{index}" not in records_by_id
    ]
    write_lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                _scenario_record,
                group,
                index,
                baseline_record=baseline_by_id.get(f"{group}:{index}"),
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                runner_dir=runner_dir,
                grade_schema=grade_schema,
                timeout_seconds=args.timeout_seconds,
            ): (group, index)
            for group, index in pending
        }
        for future in as_completed(futures):
            group, index = futures[future]
            scenario_id = f"{group}:{index}"
            try:
                record = future.result()
                outcome = "preserved" if record["quality_preserved"] else "REGRESSION"
            except Exception as exc:  # noqa: BLE001 - evidence must record infrastructure failures
                record = {
                    "scenario_id": scenario_id,
                    "group": group,
                    "index": index,
                    "description": load_group(group)[1][index]["description"],
                    "error": f"{type(exc).__name__}: {exc}",
                    "quality_preserved": False,
                }
                outcome = "ERROR"
            with write_lock:
                records_by_id[scenario_id] = record
                selected_records = [
                    records_by_id[f"{selected_group}:{selected_index}"]
                    for selected_group, selected_index in scenarios
                    if f"{selected_group}:{selected_index}" in records_by_id
                ]
                _write_evidence(
                    args.output,
                    metadata=metadata,
                    records=selected_records,
                    minimum_input_reduction=args.minimum_input_reduction_percent,
                )
                print(
                    f"[{len(selected_records)}/{len(scenarios)}] {scenario_id}: {outcome}",
                    flush=True,
                )

    final = json.loads(args.output.read_text(encoding="utf-8"))["summary"]
    print(json.dumps(final, indent=2))


if __name__ == "__main__":
    main()
