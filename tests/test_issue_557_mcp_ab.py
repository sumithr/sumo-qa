# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Isolation checks for issue #557's real-MCP A/B server."""

from __future__ import annotations

import asyncio
import json

import pytest

from experiments.issue_557.mcp_ab_server import build_variant_server, clear_variant_override
from experiments.issue_557.run_candidate import build_prompts, candidate_prompt, load_group
from experiments.issue_557.run_mcp_subscription_eval import (
    MCP_SKILL_DIRECTIVE,
    McpCall,
    McpCodexResult,
    build_mcp_prompts,
    candidate_quality_preserved,
    mcp_codex_command,
    parse_mcp_codex_jsonl,
    summarize,
    validate_frozen_baseline_metadata,
    validate_frozen_baseline_record,
    validate_mcp_trace,
)
from experiments.issue_557.run_subscription_eval import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    SKILL_PATH,
    _sha256,
)


@pytest.fixture(autouse=True)
def _restore_production_skill_records():
    # The candidate override is process-wide state; never let it outlive a test.
    yield
    clear_variant_override()


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


def _resource_text(server, uri: str) -> str:
    async def read() -> str:
        contents = list(await server.read_resource(uri))
        return str(contents[0].content)

    return asyncio.run(read())


_REVIEW = "sumo-qa-reviewing-before-merge"
_OTHER = "sumo-qa-finding-test-data"


def _review_surfaces(server) -> dict[str, str]:
    """Every MCP surface that can hand out the review skill's body."""
    return {
        "tool": _tool_text(server, "sumo_qa_reviewing_before_merge"),
        "loader_full": _tool_text(
            server, "sumo_qa_load_skill_context", {"skill_name": _REVIEW, "mode": "full"}
        ),
        "loader_manifest": _tool_text(
            server, "sumo_qa_load_skill_context", {"skill_name": _REVIEW, "mode": "manifest"}
        ),
        "resource_full": _resource_text(server, f"sumoqa://skills/{_REVIEW}/full"),
        "resource_manifest": _resource_text(server, f"sumoqa://skills/{_REVIEW}/manifest"),
        "index": _resource_text(server, "sumoqa://skills"),
    }


def test_mcp_ab_candidate_serves_compact_prompt_on_every_review_surface() -> None:
    # The record override is process-wide, so read each variant's surfaces
    # right after building it.
    baseline = build_variant_server("baseline")
    baseline_surfaces = _review_surfaces(baseline)
    baseline_other = _tool_text(
        baseline, "sumo_qa_load_skill_context", {"skill_name": _OTHER, "mode": "full"}
    )
    candidate = build_variant_server("candidate")
    candidate_surfaces = _review_surfaces(candidate)
    candidate_other = _tool_text(
        candidate, "sumo_qa_load_skill_context", {"skill_name": _OTHER, "mode": "full"}
    )
    compact = candidate_prompt("repaired-compact")
    full_skill = SKILL_PATH.read_text(encoding="utf-8")
    full_marker = full_skill.splitlines()[-1]

    assert "too large to return in one response" in baseline_surfaces["tool"]
    assert candidate_surfaces["tool"] == compact
    for surface in ("loader_full", "resource_full"):
        assert json.loads(candidate_surfaces[surface])["content"] == compact, surface
        assert full_marker not in candidate_surfaces[surface], surface
        assert compact not in baseline_surfaces[surface], surface
    compact_hash = _sha256(compact)
    for surface in ("loader_manifest", "resource_manifest", "index"):
        assert compact_hash in candidate_surfaces[surface], surface
        assert compact_hash not in baseline_surfaces[surface], surface
    # Every other skill is untouched.
    assert candidate_other == baseline_other
    assert full_marker not in candidate_other


def test_mcp_ab_candidate_serves_compact_prompt_for_a_host_installed_review_skill(
    tmp_path,
) -> None:
    from experiments.issue_557.mcp_ab_server import set_active_variant
    from sumo_qa import external_skills, server

    installed = tmp_path / ".claude" / "skills" / _REVIEW
    installed.mkdir(parents=True)
    full_skill = SKILL_PATH.read_text(encoding="utf-8")
    (installed / "SKILL.md").write_text(full_skill, encoding="utf-8")
    other = tmp_path / ".claude" / "skills" / _OTHER
    other.mkdir(parents=True)
    (other / "SKILL.md").write_text("# other skill\n", encoding="utf-8")
    renamed = tmp_path / ".claude" / "skills" / "my-review-copy"
    renamed.mkdir(parents=True)
    (renamed / "SKILL.md").write_text(full_skill, encoding="utf-8")
    # Copies that differ from the bundled body without changing what the model
    # reads, plus an older revision that still declares its frontmatter name.
    lines = full_skill.splitlines()
    variants = {
        "copy-trailing-newline": full_skill + "\n\n",
        "copy-stripped": full_skill.strip(),
        "copy-bom": "\ufeff" + full_skill,
        "copy-leading-blank": "\n" + full_skill,
        "copy-older-revision": "\n".join(lines[:-3]) + "\n",
        "copy-edited": "\n\n" + full_skill + "\n<!-- local note -->\n",
        "copy-commented": "\n<!-- local note -->\n" + full_skill,
        # The realistic rename: the frontmatter name now names the new directory.
        "copy-renamed-frontmatter": full_skill.replace(
            "name: sumo-qa-reviewing-before-merge", "name: copy-renamed-frontmatter", 1
        ),
        # Frontmatter dropped entirely; only the body the model reads remains.
        "copy-no-frontmatter": full_skill.split("\n---\n", 1)[1],
        # Directory, frontmatter name and body all changed: still the review skill.
        "copy-edited-everywhere": full_skill.replace(
            "name: sumo-qa-reviewing-before-merge", "name: copy-edited-everywhere", 1
        )
        + "\nLocal host edit.\n",
    }
    assert "name: sumo-qa-reviewing-before-merge" not in variants["copy-renamed-frontmatter"]
    assert not variants["copy-no-frontmatter"].startswith("---")
    for name, body in variants.items():
        (tmp_path / ".claude" / "skills" / name).mkdir(parents=True)
        (tmp_path / ".claude" / "skills" / name / "SKILL.md").write_text(body, encoding="utf-8")

    set_active_variant("baseline")
    assert (
        external_skills.execute_external_skill(_REVIEW, scope="global", home=tmp_path)["skill_body"]
        == full_skill
    )

    set_active_variant("candidate")
    candidate = external_skills.execute_external_skill(_REVIEW, scope="global", home=tmp_path)
    assert candidate["skill_body"] == candidate_prompt("repaired-compact")
    assert candidate["path"] == (installed / "SKILL.md").as_posix()
    # The server's own binding is patched too, not only the module attribute.
    server_bound = [
        value
        for value in vars(server).values()
        if callable(value) and getattr(value, "__name__", "") == "execute_external_skill"
    ]
    assert server_bound and all(
        bound(_REVIEW, scope="global", home=tmp_path)["skill_body"]
        == candidate_prompt("repaired-compact")
        for bound in server_bound
    )
    assert (
        external_skills.execute_external_skill(_OTHER, scope="global", home=tmp_path)["skill_body"]
        == "# other skill\n"
    )
    # A renamed host copy of the review skill is recognised by its directory
    # name, its frontmatter name, or (for a renamed or stripped frontmatter)
    # its body, even when the copy differs by whitespace, a BOM, or is an older
    # revision.
    for name in ("my-review-copy", *variants):
        served = external_skills.execute_external_skill(name, scope="global", home=tmp_path)
        assert served["skill_body"] == candidate_prompt("repaired-compact"), name
    # Any spelling the filesystem resolves (case-insensitive hosts) is covered.
    for spelling in (_REVIEW.upper(), _REVIEW.replace("-", "_")):
        try:
            resolved = external_skills.execute_external_skill(
                spelling, scope="global", home=tmp_path
            )
        except external_skills.ExternalSkillError:
            continue  # case-sensitive filesystem: nothing to serve
        assert resolved["skill_body"] == candidate_prompt("repaired-compact"), spelling

    clear_variant_override()
    assert (
        external_skills.execute_external_skill(_REVIEW, scope="global", home=tmp_path)["skill_body"]
        == full_skill
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


def test_mcp_trace_rejects_a_candidate_that_reads_the_full_review_skill() -> None:
    compact = candidate_prompt("repaired-compact")
    expected = _sha256(compact)

    def result(*calls: McpCall) -> McpCodexResult:
        return McpCodexResult(output="review", usage={}, calls=list(calls))

    router = McpCall("issue557", "using_sumo_qa", {}, "router")
    review = McpCall("issue557", "sumo_qa_reviewing_before_merge", {}, compact)
    other_skill = McpCall(
        "issue557",
        "sumo_qa_load_skill_context",
        {"skill_name": "sumo-qa-finding-test-data"},
        "other skill",
    )
    validate_mcp_trace(
        result(router, review, other_skill),
        variant="candidate",
        candidate_review_sha256=expected,
    )

    leaked = McpCall(
        "issue557",
        "sumo_qa_load_skill_context",
        {"skill_name": "sumo-qa-reviewing-before-merge", "section": "verdict-format-discipline"},
        "full skill section",
    )
    with pytest.raises(ValueError, match="full review skill"):
        validate_mcp_trace(
            result(router, review, leaked),
            variant="candidate",
            candidate_review_sha256=expected,
        )
    leaked_as_json_string = McpCall(
        "issue557",
        "sumo_qa_load_skill_context",
        json.dumps({"skill_name": "sumo-qa-reviewing-before-merge"}),
        "full skill",
    )
    with pytest.raises(ValueError, match="full review skill"):
        validate_mcp_trace(
            result(router, review, leaked_as_json_string),
            variant="candidate",
            candidate_review_sha256=expected,
        )
    # The rule keys on the exact skill_name, so another skill whose arguments
    # merely mention the review skill is not a false positive.
    mentions_only = McpCall(
        "issue557",
        "sumo_qa_load_skill_context",
        {"skill_name": "sumo-qa-finding-test-data", "known_hash": "sumo-qa-reviewing-before-merge"},
        "other skill",
    )
    validate_mcp_trace(
        result(router, review, mentions_only),
        variant="candidate",
        candidate_review_sha256=expected,
    )

    swapped = McpCall("issue557", "sumo_qa_reviewing_before_merge", {}, "full skill body")
    with pytest.raises(ValueError, match="does not match the candidate prompt"):
        validate_mcp_trace(
            result(router, swapped),
            variant="candidate",
            candidate_review_sha256=expected,
        )

    resource_read = McpCall(
        "issue557",
        "read_mcp_resource",
        {"uri": "sumoqa://skills/sumo-qa-reviewing-before-merge/full"},
        "anything",
    )
    with pytest.raises(ValueError, match="read MCP resources directly"):
        validate_mcp_trace(
            result(router, review, resource_read),
            variant="candidate",
            candidate_review_sha256=expected,
        )
    # Resource reads are ordinary production behaviour for the baseline.
    validate_mcp_trace(result(router, swapped, leaked, resource_read), variant="baseline")

    for spelling in (
        "sumo_qa_reviewing_before_merge",
        "sumo-qa-reviewing-before-merge/",
        "sumo-qa-reviewing-before-merge/.",
        "../../skills/sumo-qa-reviewing-before-merge/.",
        "./SUMO-QA-REVIEWING-BEFORE-MERGE//./",
        "sumo-qa-reviewing-before-merge/references/..",
        "sumo-qa-finding-test-data/../sumo-qa-reviewing-before-merge/./x/..",
    ):
        external_review = McpCall(
            "issue557",
            "sumo_qa_execute_external_skill",
            {"skill": spelling, "intent": "review"},
            "full skill body",
        )
        with pytest.raises(ValueError, match="external skill"):
            validate_mcp_trace(
                result(router, review, external_review),
                variant="candidate",
                candidate_review_sha256=expected,
            )
    external_other = McpCall(
        "issue557",
        "sumo_qa_execute_external_skill",
        json.dumps({"skill": "sumo-qa-finding-test-data"}),
        "other skill body",
    )
    validate_mcp_trace(
        result(router, review, external_other),
        variant="candidate",
        candidate_review_sha256=expected,
    )
    # The baseline is required to load the full skill; the candidate rule must
    # not fire on it.
    validate_mcp_trace(result(router, swapped, leaked), variant="baseline")

    # An alias the name rule cannot see is caught by what it returned.
    full_skill = SKILL_PATH.read_text(encoding="utf-8")
    for served in (full_skill, compact, json.dumps({"skill_body": full_skill})):
        aliased = McpCall(
            "issue557",
            "sumo_qa_execute_external_skill",
            {"skill": "aliases/review-current"},
            served,
        )
        with pytest.raises(ValueError, match="external skill"):
            validate_mcp_trace(
                result(router, review, aliased),
                variant="candidate",
                candidate_review_sha256=expected,
            )


def test_external_skill_loads_count_as_skill_context() -> None:
    from experiments.issue_557.run_mcp_subscription_eval import _skill_context_tokens

    calls = [
        {"tool": "sumo_qa_execute_external_skill", "estimated_result_tokens": 40},
        {"tool": "sumo_qa_find_test_data", "estimated_result_tokens": 7},
    ]
    assert _skill_context_tokens(calls) == 40


def test_shares_skill_body_recognises_edits_but_not_other_skills() -> None:
    from experiments.issue_557.mcp_ab_server import shares_skill_body

    full_skill = SKILL_PATH.read_text(encoding="utf-8")
    lines = full_skill.splitlines()
    assert shares_skill_body(full_skill, full_skill)
    assert shares_skill_body("\n".join(lines[: len(lines) * 9 // 10]), full_skill)
    assert shares_skill_body(full_skill + "\nLocal host edit.\n", full_skill)
    assert not shares_skill_body("# other skill\n\nSome unrelated guidance here.\n", full_skill)
    assert not shares_skill_body("", full_skill)
    assert not shares_skill_body(full_skill, "")


def test_frozen_baseline_record_must_match_the_current_scenario() -> None:
    group = "core"
    _, tests, config_hash = load_group(group)
    baseline_prompt = build_prompts(
        group,
        skill_content=SKILL_PATH.read_text(encoding="utf-8"),
    )[1][0][1]
    record = {
        "scenario_id": f"{group}:0",
        "description": tests[0]["description"],
        "config_sha256": config_hash,
        "baseline": {
            "prompt_sha256": _sha256(baseline_prompt),
            "output": "Verdict: NOT SAFE TO MERGE",
            "grade": {"pass": True, "score": 1.0},
        },
    }

    validate_frozen_baseline_record(record, group=group, index=0)

    for broken_grade in (
        None,
        {"pass": "yes", "score": 1.0},
        {"pass": True, "score": "1"},
        {"pass": False, "score": -1.0},
        {"pass": True, "score": 1.5},
        {"pass": False, "score": float("nan")},
    ):
        broken = {**record, "baseline": {**record["baseline"], "grade": broken_grade}}
        with pytest.raises(RuntimeError, match="lacks a graded output"):
            validate_frozen_baseline_record(broken, group=group, index=0)
    no_output = {**record, "baseline": {**record["baseline"], "output": ""}}
    with pytest.raises(RuntimeError, match="lacks a graded output"):
        validate_frozen_baseline_record(no_output, group=group, index=0)

    stale_config = {**record, "config_sha256": "stale"}
    with pytest.raises(RuntimeError, match=r'"config_sha256".*"expected".*"actual"'):
        validate_frozen_baseline_record(stale_config, group=group, index=0)
    stale_prompt = {**record, "baseline": {"prompt_sha256": "stale"}}
    with pytest.raises(RuntimeError, match=r'"baseline_prompt_sha256"'):
        validate_frozen_baseline_record(stale_prompt, group=group, index=0)
    missing_baseline = {key: value for key, value in record.items() if key != "baseline"}
    with pytest.raises(RuntimeError, match=r'"baseline_prompt_sha256"'):
        validate_frozen_baseline_record(missing_baseline, group=group, index=0)


def test_repaired_candidate_cannot_preserve_quality() -> None:
    passing = {"pass": True, "score": 1.0}
    failing_baseline = {"pass": False, "score": 0.4}

    assert candidate_quality_preserved(passing, passing, attempt_count=1) is True
    assert candidate_quality_preserved(passing, passing, attempt_count=2) is False
    assert (
        candidate_quality_preserved({"pass": False, "score": 0.9}, passing, attempt_count=1)
        is False
    )
    assert (
        candidate_quality_preserved(
            {"pass": False, "score": 0.5}, failing_baseline, attempt_count=1
        )
        is True
    )
    assert (
        candidate_quality_preserved(
            {"pass": False, "score": 0.3}, failing_baseline, attempt_count=1
        )
        is False
    )
    assert (
        candidate_quality_preserved(
            {"pass": False, "score": 0.5}, failing_baseline, attempt_count=2
        )
        is False
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
