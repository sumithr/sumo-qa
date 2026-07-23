# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Isolation checks for issue #557's real-MCP A/B server."""

from __future__ import annotations

import asyncio
import json

import pytest

from experiments.issue_557.mcp_ab_server import build_variant_server
from experiments.issue_557.run_candidate import candidate_prompt
from experiments.issue_557.run_mcp_subscription_eval import (
    MCP_SKILL_DIRECTIVE,
    McpCall,
    McpCodexResult,
    build_mcp_prompts,
    mcp_codex_command,
    parse_mcp_codex_jsonl,
    summarize,
    validate_frozen_baseline_metadata,
    validate_mcp_trace,
)
from experiments.issue_557.run_subscription_eval import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    SKILL_PATH,
    _sha256,
)


def _tool_text(server, name: str, arguments: dict | None = None) -> str:
    async def call() -> str:
        result = await server.call_tool(name, arguments or {})
        content = result[0] if isinstance(result, tuple) else result
        return next(block.text for block in content if getattr(block, "text", None))

    return asyncio.run(call())


def test_mcp_ab_variants_keep_identical_tool_surfaces() -> None:
    baseline = build_variant_server("baseline")
    candidate = build_variant_server("candidate")

    def surface(server) -> dict:
        return {
            name: (tool.description, tool.parameters)
            for name, tool in server._tool_manager._tools.items()
        }

    assert surface(candidate) == surface(baseline)


def test_mcp_ab_candidate_changes_only_direct_review_skill_result() -> None:
    baseline = build_variant_server("baseline")
    candidate = build_variant_server("candidate")

    baseline_review = _tool_text(baseline, "sumo_qa_reviewing_before_merge")
    candidate_review = _tool_text(candidate, "sumo_qa_reviewing_before_merge")
    loader_arguments = {
        "skill_name": "sumo-qa-reviewing-before-merge",
        "mode": "manifest",
    }

    assert "too large to return in one response" in baseline_review
    assert candidate_review == candidate_prompt("repaired-compact")
    assert _tool_text(candidate, "sumo_qa_load_skill_context", loader_arguments) == _tool_text(
        baseline, "sumo_qa_load_skill_context", loader_arguments
    )


def test_mcp_ab_rejects_unknown_variant() -> None:
    with pytest.raises(ValueError, match="unknown MCP A/B variant"):
        build_variant_server("unknown")


def test_mcp_jsonl_parser_captures_real_tool_results_and_usage() -> None:
    events = [
        {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "issue557",
                "tool": "sumo_qa_reviewing_before_merge",
                "arguments": {},
                "result": {"content": [{"type": "text", "text": "skill body"}]},
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "review"},
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 20,
                "output_tokens": 10,
                "reasoning_output_tokens": 5,
            },
        },
    ]

    result = parse_mcp_codex_jsonl("\n".join(json.dumps(event) for event in events))

    assert result.output == "review"
    assert result.usage["input_tokens"] == 100
    assert result.calls[0].result_text == "skill body"
    assert result.calls[0].estimated_result_tokens == 3


def test_mcp_command_isolates_the_variant_server(tmp_path) -> None:
    command = mcp_codex_command(
        variant="candidate",
        model="test-model",
        reasoning_effort="low",
        runner_dir=tmp_path,
    )

    assert "--ignore-user-config" in command
    assert "mcp_servers.issue557.required=true" in command
    assert any("mcp_ab_server" in item and "candidate" in item for item in command)
    assert command[-1] == "-"


def test_mcp_prompts_replace_embedded_skill_with_tool_directive() -> None:
    prompts = build_mcp_prompts("full-base")

    assert len(prompts) == 1
    assert MCP_SKILL_DIRECTIVE in prompts[0][1]
    assert candidate_prompt("repaired-compact") not in prompts[0][1]


def test_frozen_baseline_metadata_does_not_require_candidate_only_fields() -> None:
    metadata = {
        "auth": "ChatGPT subscription",
        "model": DEFAULT_MODEL,
        "reasoning_effort": DEFAULT_REASONING_EFFORT,
        "full_skill_sha256": _sha256(SKILL_PATH.read_bytes()),
        "judge_context": "rubric+scenario-ground-truth",
    }

    validate_frozen_baseline_metadata(
        metadata,
        model=DEFAULT_MODEL,
        reasoning_effort=DEFAULT_REASONING_EFFORT,
    )


def test_frozen_baseline_metadata_error_names_the_mismatched_field() -> None:
    metadata = {
        "auth": "wrong auth",
        "model": DEFAULT_MODEL,
        "reasoning_effort": DEFAULT_REASONING_EFFORT,
        "full_skill_sha256": _sha256(SKILL_PATH.read_bytes()),
        "judge_context": "rubric+scenario-ground-truth",
    }

    with pytest.raises(RuntimeError, match=r'"auth".*"expected".*"actual"'):
        validate_frozen_baseline_metadata(
            metadata,
            model=DEFAULT_MODEL,
            reasoning_effort=DEFAULT_REASONING_EFFORT,
        )


def test_mcp_trace_requires_progressive_loading_only_for_baseline() -> None:
    def result(*tools: str, server: str = "issue557") -> McpCodexResult:
        return McpCodexResult(
            output="review",
            usage={},
            calls=[McpCall(server, tool, {}, "result") for tool in tools],
        )

    candidate = result("using_sumo_qa", "sumo_qa_reviewing_before_merge")
    validate_mcp_trace(candidate, variant="candidate")
    with pytest.raises(ValueError, match="progressive skill-loading"):
        validate_mcp_trace(candidate, variant="baseline")
    with pytest.raises(ValueError, match="unexpected MCP servers"):
        validate_mcp_trace(
            result("using_sumo_qa", "sumo_qa_reviewing_before_merge", server="foreign"),
            variant="candidate",
        )


def test_mcp_summary_requires_all_46_scenarios_and_both_reduction_thresholds() -> None:
    records = []
    for index in range(46):
        records.append(
            {
                "scenario_id": f"scenario:{index}",
                "candidate": {
                    "quality_preserved": True,
                    "usage": {"input_tokens": 50},
                    "mcp_calls": [
                        {
                            "tool": "sumo_qa_reviewing_before_merge",
                            "estimated_result_tokens": 10,
                        }
                    ],
                },
                "baseline_mcp": {
                    "usage": {"input_tokens": 100},
                    "mcp_calls": [
                        {
                            "tool": "sumo_qa_load_skill_context",
                            "estimated_result_tokens": 30,
                        }
                    ],
                },
            }
        )

    summary = summarize(
        records,
        minimum_skill_reduction=60.0,
        minimum_total_reduction=40.0,
    )
    assert summary["verdict"] == "PROVEN"
    assert summary["quality_regressions"] == 0
    assert summary["total_input_reduction_percent"] == 50.0
    assert summary["estimated_skill_context_reduction_percent"] == 66.67

    records[0]["baseline_mcp_error"] = "failed"
    failed = summarize(
        records,
        minimum_skill_reduction=60.0,
        minimum_total_reduction=40.0,
    )
    assert failed["verdict"] == "NOT PROVEN"
    assert failed["baseline_completed"] == 45
