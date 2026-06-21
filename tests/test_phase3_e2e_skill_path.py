# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Phase 3 end-to-end verification: the new skill+tool surface works.

Covers the automatable parts of Phase 3. The full senior-istqb-grade
verification needs (a) AI-graded scenario simulation (Task 2) and (b)
manual smoke-tests on IntelliJ + Copilot (Task 3) — both of which sit
outside this file.

This test is the regression sentinel that catches "did Phase 4's deletion
break the skill-driven path?"
"""

from __future__ import annotations

import asyncio

from sumo_qa.knowledge_loaders import (
    sumo_qa_load_approaches,
    sumo_qa_load_classifications,
    sumo_qa_load_principles,
    sumo_qa_load_techniques,
)
from sumo_qa.server import build_mcp_server

EXPECTED_SKILL_PROMPTS = {
    "using_sumo_qa",
    "sumo_qa_deciding_approach",
    "sumo_qa_preparing_for_work",
    "sumo_qa_creating_test_plan",
    "sumo_qa_implementing_with_tdd",
    "sumo_qa_reviewing_before_merge",
    "sumo_qa_strengthening_tests",
    "sumo_qa_finding_test_data",
    "sumo_qa_answering_testing_question",
    "sumo_qa_strategising",
}


def test_all_ten_skills_register_as_tools():
    """Skills are registered as MCP tools (not prompts) so every host's
    slash menu surfaces them identically. See skill_prompts.py docstring."""
    mcp = build_mcp_server()
    registered = set(mcp._tool_manager._tools.keys())
    missing = EXPECTED_SKILL_PROMPTS - registered
    assert not missing, f"Missing skill tools: {missing}"


def test_each_skill_tool_body_carries_iron_law_and_checklist():
    """Every under-cap skill body must show Iron Law + Checklist + Process Flow
    + Red Flags when served via the MCP tools protocol. This catches drift
    between SKILL.md on disk and what hosts actually see. An over-cap body
    (#393) is served as a progressive-loading pointer instead, so it carries
    the route rather than the structural sections."""
    from sumo_qa.skill_prompts import (
        DEFAULT_SKILL_RESPONSE_TOKEN_CAP,
        _approx_tokens,
        _skills_dir,
    )

    mcp = build_mcp_server()

    async def _fetch_all():
        bodies = {}
        for name in EXPECTED_SKILL_PROMPTS:
            result = await mcp.call_tool(name, {})
            # The server drops outputSchema, so call_tool returns a bare
            # content list (unstructured text). Older FastMCP returned a
            # (content_list, structured_content) tuple — handle both.
            content_list = result[0] if isinstance(result, tuple) else result
            text = ""
            for content in content_list:
                block_text = getattr(content, "text", None)
                if block_text:
                    text = block_text
                    break
            bodies[name] = text
        return bodies

    bodies = asyncio.run(_fetch_all())
    for name, body in bodies.items():
        skill_path = _skills_dir() / name.replace("_", "-") / "SKILL.md"
        if (
            _approx_tokens(skill_path.read_text(encoding="utf-8"))
            > DEFAULT_SKILL_RESPONSE_TOKEN_CAP
        ):
            # Over-cap: a progressive-loading pointer, not the structural body.
            assert "sumo_qa_load_skill_context" in body, f"{name}: pointer missing route"
            continue
        assert "## The Iron Law" in body, f"{name}: missing Iron Law in served body"
        assert "## Checklist" in body, f"{name}: missing Checklist in served body"
        # Process Flow section is required; the inline graphviz `dot` block
        # is optional after the token-reduction pass (skills now point at the
        # Checklist as the canonical flow encoding).
        assert "## Process Flow" in body, f"{name}: missing Process Flow section in served body"
        assert "## Red Flags" in body, f"{name}: missing Red Flags in served body"


def test_knowledge_loaders_return_canonical_entries():
    """The 4 always-thin catalogues must return their canonical entries.
    Confirms Phase 1's loaders still work after Phase 2's content rewrite."""
    classifications = sumo_qa_load_classifications()
    for entry in [
        "api_contract_change",
        "business_logic_change",
        "security_change",
        "data_migration",
    ]:
        assert entry in classifications

    approaches = sumo_qa_load_approaches()
    for entry in [
        "tdd-scaffold",
        "regression-first",
        "coverage-first-then-refactor",
        "strategy-orchestration",
    ]:
        assert entry in approaches

    principles = sumo_qa_load_principles()
    assert "ISTQB Foundation" in principles
    assert "Pesticide paradox" in principles

    techniques = sumo_qa_load_techniques()
    for entry in ["boundary value analysis", "mutation testing", "property-based testing"]:
        assert entry in techniques


def test_typical_flow_stays_under_token_budget():
    """A typical create-test-plan / prep-for-work flow loads ~3 catalogues.
    Total returned tokens must stay under PER_FLOW_BUDGET. Reuses the
    token-weight test's chars/4 estimator.

    Budget history: 2500 with nine canonical approaches; #146's tenth
    approach (`closed-loop-gap-fix`) raised the measured flow to ~2513, so
    the budget moved to 2600; #150's eleventh approach (`triage-test-failure`)
    raised it to ~2655, so the budget moved to 2700 — still a fraction of the
    >10k single-shot path this guard exists to keep out."""
    PER_FLOW_BUDGET = 2700

    def _tokens(text: str) -> int:
        return (len(text) + 3) // 4

    flow_total = sum(
        _tokens(text)
        for text in [
            sumo_qa_load_classifications(),
            sumo_qa_load_approaches(),
            sumo_qa_load_techniques(),
        ]
    )
    assert flow_total <= PER_FLOW_BUDGET, (
        f"Typical 3-call flow returned {flow_total} tokens "
        f"(>{PER_FLOW_BUDGET}); the new path is too heavy"
    )


def test_heavy_tools_are_deleted_and_skill_path_is_canonical():
    """Phase 4 postcondition: the 6 heavy reasoning tools are gone. The 6
    knowledge loader tools remain so skill prompts can drive the host LLM.
    The 4 test-data tools remain because they back deterministic catalogue
    operations (find / validate / register / explain)."""
    mcp = build_mcp_server()
    tool_names = set(mcp._tool_manager._tools.keys())
    heavy = {
        "sumo_qa_decide_approach",
        "sumo_qa_prepare_for_work",
        "sumo_qa_create_test_plan",
        "sumo_qa_review_local_change",
        "sumo_qa_scaffold_tests",
        "sumo_qa_answer_testing_question",
    }
    leaked = heavy & tool_names
    assert not leaked, f"Heavy tools must be deleted in Phase 4 but still registered: {leaked}"
    knowledge = {
        "sumo_qa_load_classifications",
        "sumo_qa_load_approaches",
        "sumo_qa_load_principles",
        "sumo_qa_load_techniques",
        "sumo_qa_load_standards",
        "sumo_qa_load_rules",
    }
    assert knowledge.issubset(tool_names), f"Knowledge tools missing: {knowledge - tool_names}"
    test_data = {
        "sumo_qa_explain_test_data_requirements",
        "sumo_qa_find_test_data",
        "sumo_qa_validate_test_data",
        "sumo_qa_register_known_good_test_data",
    }
    assert test_data.issubset(tool_names), f"Test-data tools missing: {test_data - tool_names}"
