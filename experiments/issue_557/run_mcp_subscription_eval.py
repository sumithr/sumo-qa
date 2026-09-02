# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Run issue #557's final A/B through the real MCP path and ChatGPT auth.

Phase B runs first and supplies both final quality evidence and candidate token
usage. Phase A then runs the unchanged production skill only for comparable MCP
token usage. Provider API keys are removed from every child process.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sumo_qa.review_gate_poc import ReviewGateValidationError, validate_review_response

from .mcp_ab_server import shares_skill_body
from .run_candidate import FULL_REVIEW_GROUPS, build_prompts, candidate_prompt, load_group
from .run_subscription_eval import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    METERED_KEY_NAMES,
    SKILL_PATH,
    _grade_schema,
    _sha256,
    _sum_usage,
    codex_command,
    grade_output,
    subscription_environment,
    verify_chatgpt_auth,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SERVER_MODULE = "experiments.issue_557.mcp_ab_server"
MCP_SERVER_NAME = "issue557"
MCP_SKILL_DIRECTIVE = """Before answering, use the real MCP path. Call `using_sumo_qa`, then
`sumo_qa_reviewing_before_merge`, and follow any progressive-loading instructions returned
by the review-skill tool. The actual skill body must come from MCP, not from this prompt."""
MCP_PREFIX = """This is a controlled MCP evaluation. Use only the issue557 MCP server.
Do not run shell commands, inspect files, browse, or modify anything; the task is complete
and self-contained. Load the review discipline through MCP before answering.

--- BEGIN EVALUATION TASK ---
"""
MCP_SUFFIX = "\n--- END EVALUATION TASK ---\n"
_FORBIDDEN_ITEMS = {"command_execution", "file_change", "web_search", "image_generation"}
_REQUIRED_TOOLS = ("using_sumo_qa", "sumo_qa_reviewing_before_merge")
REVIEW_SKILL_NAME = "sumo-qa-reviewing-before-merge"
# Codex's built-in MCP resource tools. A resource read is invisible to the
# skill-context token estimate, so the candidate may not use them.
_RESOURCE_TOOLS = frozenset(
    {"read_mcp_resource", "list_mcp_resources", "list_mcp_resource_templates"}
)


@dataclass(frozen=True)
class McpCall:
    server: str
    tool: str
    arguments: Any
    result_text: str

    @property
    def estimated_result_tokens(self) -> int:
        return (len(self.result_text) + 3) // 4


@dataclass(frozen=True)
class McpCodexResult:
    output: str
    usage: dict[str, int]
    calls: list[McpCall]


def _result_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    blocks = value.get("content")
    if not isinstance(blocks, list):
        return ""
    texts = []
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            texts.append(block["text"])
    return "\n".join(texts)


def parse_mcp_codex_jsonl(stdout: str) -> McpCodexResult:
    output: str | None = None
    usage: dict[str, int] | None = None
    calls: list[McpCall] = []
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
            if item_type in _FORBIDDEN_ITEMS:
                raise ValueError(f"MCP evaluation used forbidden item: {item_type}")
            if event.get("type") == "item.completed" and item_type == "agent_message":
                text = item.get("text")
                if isinstance(text, str) and text:
                    output = text
            if event.get("type") == "item.completed" and item_type in {
                "mcp_tool_call",
                "mcpToolCall",
            }:
                if item.get("error") or item.get("status") in {"failed", "error"}:
                    raise ValueError(f"MCP tool call failed: {item}")
                server = item.get("server")
                tool = item.get("tool")
                if not isinstance(server, str) or not isinstance(tool, str):
                    raise ValueError(f"malformed MCP tool call: {item}")
                calls.append(
                    McpCall(
                        server=server,
                        tool=tool,
                        arguments=item.get("arguments"),
                        result_text=_result_text(item.get("result")),
                    )
                )
        if event.get("type") == "turn.completed":
            raw_usage = event.get("usage")
            required = (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
            )
            if isinstance(raw_usage, dict) and all(
                type(raw_usage.get(key)) is int for key in required
            ):
                usage = {key: raw_usage[key] for key in required}
        if event.get("type") in {"turn.failed", "error"}:
            raise ValueError(f"Codex MCP evaluation failed: {event}")
    if output is None or usage is None:
        raise ValueError("Codex MCP JSONL lacked a final agent message or usage")
    return McpCodexResult(output=output, usage=usage, calls=calls)


def mcp_codex_command(
    *, variant: str, model: str, reasoning_effort: str, runner_dir: Path
) -> list[str]:
    command = codex_command(
        model=model,
        reasoning_effort=reasoning_effort,
        runner_dir=runner_dir,
    )
    command[-1:-1] = [
        "--config",
        f"mcp_servers.{MCP_SERVER_NAME}.command={json.dumps(sys.executable)}",
        "--config",
        (
            f"mcp_servers.{MCP_SERVER_NAME}.args="
            f"{json.dumps(['-m', MCP_SERVER_MODULE, '--variant', variant])}"
        ),
        "--config",
        f"mcp_servers.{MCP_SERVER_NAME}.cwd={json.dumps(str(REPO_ROOT))}",
        "--config",
        f"mcp_servers.{MCP_SERVER_NAME}.required=true",
    ]
    return command


def run_mcp_codex(
    prompt: str,
    *,
    variant: str,
    model: str,
    reasoning_effort: str,
    runner_dir: Path,
    timeout_seconds: int,
) -> McpCodexResult:
    completed = subprocess.run(
        mcp_codex_command(
            variant=variant,
            model=model,
            reasoning_effort=reasoning_effort,
            runner_dir=runner_dir,
        ),
        input=f"{MCP_PREFIX}{prompt}{MCP_SUFFIX}",
        text=True,
        capture_output=True,
        env=subscription_environment(),
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"codex exec MCP {variant} failed ({completed.returncode}): "
            f"{completed.stderr.strip()[-2_000:]}"
        )
    return parse_mcp_codex_jsonl(completed.stdout)


def _normalised_tool_name(name: str) -> str:
    return re.split(r"__|/", name)[-1]


def _string_argument(arguments: Any, key: str) -> str | None:
    """One string argument of an MCP call, from a dict or JSON-string payload."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return None
    if not isinstance(arguments, dict):
        return None
    value = arguments.get(key)
    return value if isinstance(value, str) else None


def _loaded_skill_name(arguments: Any) -> str | None:
    """The ``skill_name`` a ``sumo_qa_load_skill_context`` call targeted, if any."""
    return _string_argument(arguments, "skill_name")


def _served_bodies(result_text: str) -> list[str]:
    """The raw result plus every string inside it if it is JSON (skill_body etc.)."""
    bodies = [result_text]
    try:
        payload = json.loads(result_text)
    except (TypeError, ValueError):
        return bodies

    def walk(value: Any) -> None:
        if isinstance(value, str):
            bodies.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return bodies


def _names_review_skill(value: str | None) -> bool:
    """Whether an external-skill name resolves to the review skill.

    The resolver joins the raw name onto a skills root, so a path-shaped name
    ("../../skills/<name>/.") resolves the same directory as the bare name;
    the last real path segment is what names the skill.
    """
    if value is None:
        return False
    normalised = posixpath.normpath(value.strip().replace("\\", "/"))
    name = posixpath.basename(normalised)
    return name.lower().replace("_", "-") == REVIEW_SKILL_NAME


def validate_mcp_trace(
    result: McpCodexResult,
    *,
    variant: str,
    candidate_review_sha256: str | None = None,
) -> None:
    """Reject a trace that breaks the A/B question.

    Both variants must stay on the issue557 server and reach the router and
    review tools. The baseline must follow the progressive-loading pointer.
    The candidate server serves the compact prompt on every review-skill
    surface, so no MCP path returns the full skill; the trace rules below keep
    the token accounting honest on top of that. The candidate must not load the
    review skill through ``sumo_qa_load_skill_context`` or
    ``sumo_qa_execute_external_skill`` (the compact profile is one tool call),
    must not read MCP resources directly (invisible to the skill-context
    estimate), and when ``candidate_review_sha256`` is given every review-tool
    result must hash to the candidate prompt.
    """
    foreign_servers = sorted(
        {call.server for call in result.calls if call.server != MCP_SERVER_NAME}
    )
    if foreign_servers:
        raise ValueError(f"{variant} used unexpected MCP servers: {foreign_servers}")
    tools = {_normalised_tool_name(call.tool) for call in result.calls}
    missing = [name for name in _REQUIRED_TOOLS if name not in tools]
    if missing:
        raise ValueError(f"{variant} skipped required MCP tools: {missing}; called={sorted(tools)}")
    if variant == "baseline" and "sumo_qa_load_skill_context" not in tools:
        raise ValueError("baseline did not follow the progressive skill-loading pointer")
    if variant != "candidate":
        return
    for call in result.calls:
        name = _normalised_tool_name(call.tool)
        if name in _RESOURCE_TOOLS:
            raise ValueError(
                f"candidate read MCP resources directly ({name}); resource reads are "
                "invisible to the skill-context token estimate"
            )
        if name == "sumo_qa_execute_external_skill":
            # Reject by name, and by what came back: an alias or symlink that the
            # name rule cannot see still returns the review skill's lines.
            named = _names_review_skill(_string_argument(call.arguments, "skill"))
            full_skill = SKILL_PATH.read_text(encoding="utf-8")
            compact = candidate_prompt("repaired-compact")
            served_review = any(
                shares_skill_body(body, full_skill) or shares_skill_body(body, compact)
                for body in _served_bodies(call.result_text)
            )
            if named or served_review:
                raise ValueError(
                    "candidate executed the review skill as an external skill; that path "
                    "is not part of the compact profile"
                )
        if (
            name == "sumo_qa_load_skill_context"
            and _loaded_skill_name(call.arguments) == REVIEW_SKILL_NAME
        ):
            raise ValueError(
                "candidate loaded the full review skill through sumo_qa_load_skill_context"
            )
        if (
            name == "sumo_qa_reviewing_before_merge"
            and candidate_review_sha256 is not None
            and _sha256(call.result_text) != candidate_review_sha256
        ):
            raise ValueError("candidate review-tool result does not match the candidate prompt")


def _serialise_calls(calls: list[McpCall]) -> list[dict[str, Any]]:
    return [
        {
            "server": call.server,
            "tool": call.tool,
            "arguments": call.arguments,
            "result_sha256": _sha256(call.result_text),
            "result_chars": len(call.result_text),
            "estimated_result_tokens": call.estimated_result_tokens,
        }
        for call in calls
    ]


def _skill_context_tokens(calls: list[dict[str, Any]]) -> int:
    relevant = {
        "using_sumo_qa",
        "sumo_qa_reviewing_before_merge",
        "sumo_qa_load_skill_context",
        # Any external-skill load is skill context too, whatever it was named.
        "sumo_qa_execute_external_skill",
    }
    return sum(
        call["estimated_result_tokens"]
        for call in calls
        if _normalised_tool_name(call["tool"]) in relevant
    )


def build_mcp_prompts(group: str) -> list[tuple[str, str]]:
    return build_prompts(group, skill_content=MCP_SKILL_DIRECTIVE)[1]


def validate_frozen_baseline_metadata(
    frozen_metadata: dict[str, Any],
    *,
    model: str,
    reasoning_effort: str,
) -> None:
    expected = {
        "auth": "ChatGPT subscription",
        "model": model,
        "reasoning_effort": reasoning_effort,
        "full_skill_sha256": _sha256(SKILL_PATH.read_bytes()),
        "judge_context": "rubric+scenario-ground-truth",
    }
    mismatches = {
        key: {"expected": value, "actual": frozen_metadata.get(key)}
        for key, value in expected.items()
        if frozen_metadata.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"frozen baseline metadata mismatch: {json.dumps(mismatches)}")


def validate_frozen_baseline_record(record: dict[str, Any], *, group: str, index: int) -> None:
    """A frozen baseline grade is reusable only for the scenario it was captured on."""
    _, tests, config_hash = load_group(group)
    full_skill = SKILL_PATH.read_text(encoding="utf-8")
    baseline_prompt = build_prompts(group, skill_content=full_skill)[1][index][1]
    expected = {
        "scenario_id": f"{group}:{index}",
        "description": tests[index]["description"],
        "config_sha256": config_hash,
        "baseline_prompt_sha256": _sha256(baseline_prompt),
    }
    baseline = record.get("baseline")
    actual = {
        "scenario_id": record.get("scenario_id"),
        "description": record.get("description"),
        "config_sha256": record.get("config_sha256"),
        "baseline_prompt_sha256": (
            baseline.get("prompt_sha256") if isinstance(baseline, dict) else None
        ),
    }
    mismatches = {
        key: {"expected": value, "actual": actual[key]}
        for key, value in expected.items()
        if actual[key] != value
    }
    if mismatches:
        raise RuntimeError(
            f"frozen baseline record mismatch for {group}:{index}: {json.dumps(mismatches)}"
        )
    grade = baseline.get("grade") if isinstance(baseline, dict) else None
    output = baseline.get("output") if isinstance(baseline, dict) else None
    if (
        not isinstance(output, str)
        or not output
        or not isinstance(grade, dict)
        or not isinstance(grade.get("pass"), bool)
        or type(grade.get("score")) not in (int, float)
        or not 0 <= grade["score"] <= 1
    ):
        raise RuntimeError(
            f"frozen baseline record for {group}:{index} lacks a graded output: "
            "expected baseline.output (non-empty text) and baseline.grade with a boolean "
            "'pass' and a numeric 'score' between 0 and 1"
        )


def candidate_quality_preserved(
    grade: dict[str, Any],
    baseline_grade: dict[str, Any],
    *,
    attempt_count: int,
) -> bool:
    """Only a first-attempt candidate can preserve quality.

    A repair turn carries the validation error and the previous response, which
    the frozen baseline never received, so a repaired pass is not one-prompt
    evidence. It still counts toward candidate token usage.
    """
    if attempt_count != 1:
        return False
    if baseline_grade["pass"]:
        return bool(grade["pass"])
    return bool(grade["pass"]) or grade["score"] >= baseline_grade["score"]


def _candidate_result(
    group: str,
    index: int,
    *,
    frozen: dict[str, Any],
    model: str,
    reasoning_effort: str,
    runner_dir: Path,
    grade_schema: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    prompt = build_mcp_prompts(group)[index][1]
    review_sha256 = _sha256(candidate_prompt("repaired-compact"))
    attempts: list[McpCodexResult] = []
    first = run_mcp_codex(
        prompt,
        variant="candidate",
        model=model,
        reasoning_effort=reasoning_effort,
        runner_dir=runner_dir,
        timeout_seconds=timeout_seconds,
    )
    validate_mcp_trace(first, variant="candidate", candidate_review_sha256=review_sha256)
    attempts.append(first)
    try:
        validated = validate_review_response(first.output)
    except ReviewGateValidationError as exc:
        repair = run_mcp_codex(
            prompt
            + "\n\nThe previous response failed deterministic validation:\n"
            + f"{exc}\n\nPrevious response:\n{first.output}\n\n"
            + "Return the complete corrected GATE_REPORT and REVIEW envelopes.",
            variant="candidate",
            model=model,
            reasoning_effort=reasoning_effort,
            runner_dir=runner_dir,
            timeout_seconds=timeout_seconds,
        )
        validate_mcp_trace(repair, variant="candidate", candidate_review_sha256=review_sha256)
        attempts.append(repair)
        validated = validate_review_response(repair.output)

    grade, grade_usage = grade_output(
        group,
        index,
        validated.review,
        model=model,
        reasoning_effort=reasoning_effort,
        runner_dir=runner_dir,
        grade_schema=grade_schema,
        timeout_seconds=timeout_seconds,
    )
    baseline_grade = frozen["baseline"]["grade"]
    preserved = candidate_quality_preserved(grade, baseline_grade, attempt_count=len(attempts))
    calls = [call for attempt in attempts for call in attempt.calls]
    usage = _sum_usage([attempt.usage for attempt in attempts])
    return {
        "output": validated.review,
        "attempt_count": len(attempts),
        "usage": usage,
        "mcp_calls": _serialise_calls(calls),
        "grade": grade,
        "grade_usage": grade_usage,
        "frozen_baseline_grade": baseline_grade,
        "graded_quality_preserved": candidate_quality_preserved(
            grade, baseline_grade, attempt_count=1
        ),
        "quality_preserved": preserved,
    }


def _baseline_result(
    group: str,
    index: int,
    *,
    model: str,
    reasoning_effort: str,
    runner_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    prompt = build_mcp_prompts(group)[index][1]
    result = run_mcp_codex(
        prompt,
        variant="baseline",
        model=model,
        reasoning_effort=reasoning_effort,
        runner_dir=runner_dir,
        timeout_seconds=timeout_seconds,
    )
    validate_mcp_trace(result, variant="baseline")
    return {
        "output": result.output,
        "usage": result.usage,
        "mcp_calls": _serialise_calls(result.calls),
    }


def summarize(
    records: list[dict[str, Any]],
    *,
    minimum_skill_reduction: float,
    minimum_total_reduction: float,
) -> dict[str, Any]:
    complete_b = [r for r in records if "candidate" in r and "candidate_error" not in r]
    complete_a = [r for r in records if "baseline_mcp" in r and "baseline_mcp_error" not in r]
    regressions = sum(not record["candidate"]["quality_preserved"] for record in complete_b)
    candidate_input = sum(r["candidate"]["usage"]["input_tokens"] for r in complete_b)
    baseline_input = sum(r["baseline_mcp"]["usage"]["input_tokens"] for r in complete_a)
    candidate_skill = sum(_skill_context_tokens(r["candidate"]["mcp_calls"]) for r in complete_b)
    baseline_skill = sum(_skill_context_tokens(r["baseline_mcp"]["mcp_calls"]) for r in complete_a)
    total_reduction = (
        100 * (baseline_input - candidate_input) / baseline_input if baseline_input else 0.0
    )
    skill_reduction = (
        100 * (baseline_skill - candidate_skill) / baseline_skill if baseline_skill else 0.0
    )
    proven = (
        len(records) == len(complete_a) == len(complete_b) == 46
        and regressions == 0
        and total_reduction >= minimum_total_reduction
        and skill_reduction >= minimum_skill_reduction
    )
    return {
        "verdict": "PROVEN" if proven else "NOT PROVEN",
        "scenario_count": len(records),
        "candidate_completed": len(complete_b),
        "baseline_completed": len(complete_a),
        "quality_regressions": regressions,
        "candidate_input_tokens": candidate_input,
        "baseline_input_tokens": baseline_input,
        "total_input_reduction_percent": round(total_reduction, 2),
        "minimum_total_input_reduction_percent": minimum_total_reduction,
        "candidate_estimated_skill_context_tokens": candidate_skill,
        "baseline_estimated_skill_context_tokens": baseline_skill,
        "estimated_skill_context_reduction_percent": round(skill_reduction, 2),
        "minimum_estimated_skill_context_reduction_percent": minimum_skill_reduction,
    }


def _write(
    path: Path,
    *,
    metadata: dict[str, Any],
    records: dict[str, dict[str, Any]],
    minimum_skill_reduction: float,
    minimum_total_reduction: float,
) -> None:
    ordered = sorted(
        records.values(),
        key=lambda item: (list(FULL_REVIEW_GROUPS).index(item["group"]), item["index"]),
    )
    payload = {
        "metadata": metadata,
        "summary": summarize(
            ordered,
            minimum_skill_reduction=minimum_skill_reduction,
            minimum_total_reduction=minimum_total_reduction,
        ),
        "records": ordered,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frozen-baseline-evidence", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--minimum-skill-reduction-percent", type=float, default=60.0)
    parser.add_argument("--minimum-total-reduction-percent", type=float, default=40.0)
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")

    verify_chatgpt_auth()
    frozen_payload = json.loads(args.frozen_baseline_evidence.read_text(encoding="utf-8"))
    frozen_metadata = frozen_payload.get("metadata", {})
    validate_frozen_baseline_metadata(
        frozen_metadata,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
    )
    frozen_by_id = {
        record["scenario_id"]: record
        for record in frozen_payload.get("records", [])
        if "error" not in record
    }
    scenarios = [
        (group, index) for group in FULL_REVIEW_GROUPS for index in range(len(load_group(group)[1]))
    ]
    if len(scenarios) != 46 or any(f"{g}:{i}" not in frozen_by_id for g, i in scenarios):
        raise RuntimeError("frozen baseline must contain all 46 matching scenarios")
    for group, index in scenarios:
        validate_frozen_baseline_record(frozen_by_id[f"{group}:{index}"], group=group, index=index)

    runner_dir = args.output.parent / "codex-mcp-runner"
    runner_dir.mkdir(parents=True, exist_ok=True)
    grade_schema = _grade_schema(runner_dir)
    metadata = {
        "auth": "ChatGPT subscription",
        "metered_api_keys_removed": list(METERED_KEY_NAMES),
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "skill_context_token_estimator": "ceil(MCP result characters / 4)",
        "candidate_prompt_sha256": _sha256(candidate_prompt("repaired-compact")),
        "mcp_server_sha256": _sha256((Path(__file__).with_name("mcp_ab_server.py")).read_bytes()),
        # Pin this harness, so evidence written before a trace or quality rule
        # changed cannot be resumed under the new rules without --fresh.
        "harness_sha256": _sha256(Path(__file__).read_bytes()),
        "frozen_baseline": {
            "path": str(args.frozen_baseline_evidence),
            "sha256": _sha256(args.frozen_baseline_evidence.read_bytes()),
        },
        "execution_order": ["candidate_b_quality_and_tokens", "baseline_a_tokens"],
    }
    records: dict[str, dict[str, Any]] = {}
    if args.output.exists() and not args.fresh:
        existing = json.loads(args.output.read_text(encoding="utf-8"))
        if existing.get("metadata") != metadata:
            raise RuntimeError("existing MCP A/B evidence metadata does not match")
        records = {record["scenario_id"]: record for record in existing.get("records", [])}
    for group, index in scenarios:
        scenario_id = f"{group}:{index}"
        records.setdefault(
            scenario_id,
            {
                "scenario_id": scenario_id,
                "group": group,
                "index": index,
                "description": load_group(group)[1][index]["description"],
            },
        )

    lock = threading.Lock()

    def run_phase(phase: str) -> None:
        field = "candidate" if phase == "candidate" else "baseline_mcp"
        pending = [(g, i) for g, i in scenarios if field not in records[f"{g}:{i}"]]
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {}
            for group, index in pending:
                scenario_id = f"{group}:{index}"
                if phase == "candidate":
                    future = executor.submit(
                        _candidate_result,
                        group,
                        index,
                        frozen=frozen_by_id[scenario_id],
                        model=args.model,
                        reasoning_effort=args.reasoning_effort,
                        runner_dir=runner_dir,
                        grade_schema=grade_schema,
                        timeout_seconds=args.timeout_seconds,
                    )
                else:
                    future = executor.submit(
                        _baseline_result,
                        group,
                        index,
                        model=args.model,
                        reasoning_effort=args.reasoning_effort,
                        runner_dir=runner_dir,
                        timeout_seconds=args.timeout_seconds,
                    )
                futures[future] = scenario_id
            for future in as_completed(futures):
                scenario_id = futures[future]
                try:
                    result = future.result()
                    records[scenario_id].pop(f"{field}_error", None)
                    records[scenario_id][field] = result
                    outcome = (
                        "preserved"
                        if phase == "candidate" and result["quality_preserved"]
                        else "REGRESSION"
                        if phase == "candidate"
                        else "measured"
                    )
                except Exception as exc:  # noqa: BLE001 - evidence records infrastructure errors
                    records[scenario_id][f"{field}_error"] = f"{type(exc).__name__}: {exc}"
                    outcome = "ERROR"
                with lock:
                    _write(
                        args.output,
                        metadata=metadata,
                        records=records,
                        minimum_skill_reduction=args.minimum_skill_reduction_percent,
                        minimum_total_reduction=args.minimum_total_reduction_percent,
                    )
                    done = sum(
                        field in record or f"{field}_error" in record for record in records.values()
                    )
                    print(f"[{phase} {done}/46] {scenario_id}: {outcome}", flush=True)

    run_phase("candidate")
    run_phase("baseline")
    final = json.loads(args.output.read_text(encoding="utf-8"))["summary"]
    print(json.dumps(final, indent=2))


if __name__ == "__main__":
    main()
