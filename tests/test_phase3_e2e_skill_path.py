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

import pytest

from sumo_qa.server import build_mcp_server
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_approaches,
    sumo_qa_load_classifications,
    sumo_qa_load_principles,
    sumo_qa_load_specialty_tools,
    sumo_qa_load_techniques,
)


EXPECTED_SKILL_PROMPTS = {
    "using_sumo_qa",
    "qa_deciding_approach",
    "qa_preparing_for_work",
    "qa_creating_test_plan",
    "qa_implementing_with_tdd",
    "qa_reviewing_before_merge",
    "qa_strengthening_tests",
    "qa_finding_test_data",
    "qa_answering_testing_question",
    "sumo_qa_strategising",
}


def test_all_ten_skill_prompts_register():
    mcp = build_mcp_server()
    registered = set(mcp._prompt_manager._prompts.keys())
    missing = EXPECTED_SKILL_PROMPTS - registered
    assert not missing, f"Missing skill prompts: {missing}"


def test_each_skill_prompt_body_carries_iron_law_and_checklist():
    """Every skill body must show Iron Law + Checklist + Process Flow + Red Flags
    when served via the MCP prompts protocol. This catches drift between
    SKILL.md on disk and what hosts actually see."""
    mcp = build_mcp_server()

    async def _fetch_all():
        bodies = {}
        for name in EXPECTED_SKILL_PROMPTS:
            result = await mcp.get_prompt(name, {})
            bodies[name] = result.messages[0].content.text
        return bodies

    bodies = asyncio.run(_fetch_all())
    for name, body in bodies.items():
        assert "## The Iron Law" in body, f"{name}: missing Iron Law in served body"
        assert "## Checklist" in body, f"{name}: missing Checklist in served body"
        assert "```dot" in body, f"{name}: missing Process Flow dot block in served body"
        assert "## Red Flags" in body, f"{name}: missing Red Flags in served body"


def test_knowledge_loaders_return_canonical_entries():
    """The 5 always-thin catalogues must return their canonical entries.
    Confirms Phase 1's loaders still work after Phase 2's content rewrite."""
    classifications = sumo_qa_load_classifications()
    for entry in [
        "api_contract_change", "business_logic_change", "security_change",
        "data_migration",
    ]:
        assert entry in classifications

    approaches = sumo_qa_load_approaches()
    for entry in [
        "tdd-scaffold", "regression-first", "coverage-first-then-refactor",
        "strategy-orchestration",
    ]:
        assert entry in approaches

    principles = sumo_qa_load_principles()
    assert "ISTQB Foundation" in principles
    assert "Pesticide paradox" in principles

    techniques = sumo_qa_load_techniques()
    for entry in ["boundary value analysis", "mutation testing", "property-based testing"]:
        assert entry in techniques

    specialty = sumo_qa_load_specialty_tools()
    for entry in ["OWASP ZAP", "Pact", "Pitest", "Hypothesis", "k6"]:
        assert entry in specialty


def test_typical_flow_stays_under_token_budget():
    """A typical create-test-plan / prep-for-work flow loads ~5 catalogues.
    Total returned tokens must stay under PER_FLOW_BUDGET. Reuses the
    token-weight test's chars/4 estimator."""
    PER_FLOW_BUDGET = 2500

    def _tokens(text: str) -> int:
        return (len(text) + 3) // 4

    flow_total = sum(
        _tokens(text)
        for text in [
            sumo_qa_load_classifications(),
            sumo_qa_load_approaches(),
            sumo_qa_load_techniques(),
            sumo_qa_load_specialty_tools(),
        ]
    )
    assert flow_total <= PER_FLOW_BUDGET, (
        f"Typical 4-call flow returned {flow_total} tokens "
        f"(>{PER_FLOW_BUDGET}); the new path is too heavy"
    )


def test_heavy_tools_and_skill_path_coexist():
    """Phase 3 precondition: heavy tools still register so we can compare
    senior-istqb-grade output between the old and new paths during
    verification. Phase 4 deletes the heavy tools after this gate."""
    mcp = build_mcp_server()
    tool_names = set(mcp._tool_manager._tools.keys())
    heavy = {
        "sumo_qa_decide_approach", "sumo_qa_prepare_for_work",
        "sumo_qa_create_test_plan", "sumo_qa_review_local_change",
        "sumo_qa_scaffold_tests", "sumo_qa_answer_testing_question",
    }
    assert heavy.issubset(tool_names), f"Heavy tools missing: {heavy - tool_names}"
    knowledge = {
        "sumo_qa_load_classifications", "sumo_qa_load_approaches",
        "sumo_qa_load_principles", "sumo_qa_load_techniques",
        "sumo_qa_load_specialty_tools", "sumo_qa_load_standards",
        "sumo_qa_load_rules",
    }
    assert knowledge.issubset(tool_names), f"Knowledge tools missing: {knowledge - tool_names}"
