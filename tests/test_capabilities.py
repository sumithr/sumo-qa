# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the sumo_qa_capabilities discovery tool (issue #87).

The tool returns a compact, typed map of the core QA workflows — each with a
sample prompt, the skill it routes to, and a one-line outcome. It is discovery
only: it must stay small, route to skills that actually exist, and not drift
into a replacement for the using-sumo-qa entry router.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sumo_qa.capabilities import build_capabilities
from sumo_qa.server import build_mcp_server
from sumo_qa.server_schemas import CapabilitiesOutput

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def _approx_tokens(text: str) -> int:
    """chars/4 estimator — same one used by the SKILL.md budget tests."""
    return (len(text) + 3) // 4


def test_build_capabilities_returns_the_core_workflows() -> None:
    out = build_capabilities()
    assert isinstance(out, CapabilitiesOutput)
    assert out.tool == "sumo_qa_capabilities"
    # The issue (#87) enumerated eight core workflows; #150 added triage and
    # #283 added the focused security-testing path.
    assert len(out.workflows) == 10


def test_every_workflow_field_is_populated() -> None:
    for w in build_capabilities().workflows:
        assert w.workflow.strip()
        assert w.sample_prompt.strip()
        assert w.target_skill.strip()
        assert w.outcome.strip()


def test_target_skills_route_to_existing_skills_only() -> None:
    """AC: sample prompts must route to existing skills only."""
    for w in build_capabilities().workflows:
        assert (SKILLS_DIR / w.target_skill / "SKILL.md").is_file(), (
            f"{w.target_skill!r} is not an existing skills/<name>/SKILL.md"
        )


def test_target_skills_are_unique() -> None:
    skills = [w.target_skill for w in build_capabilities().workflows]
    assert len(set(skills)) == len(skills), "a workflow points at a duplicate skill"


def test_output_stays_under_500_approx_tokens() -> None:
    """AC: output stays under 500 approximate tokens."""
    approx = _approx_tokens(build_capabilities().model_dump_json())
    assert approx < 500, f"capabilities output is ~{approx} approx tokens (must be <500)"


def test_output_is_schema_stable() -> None:
    """Round-trips through the strict (extra=forbid) model without loss."""
    out = build_capabilities()
    assert CapabilitiesOutput.model_validate(out.model_dump()) == out


def test_tool_registered_and_body_reachable_via_server() -> None:
    """The MCP tool is registered and its closure body executes in-process."""
    server = build_mcp_server()
    assert "sumo_qa_capabilities" in server._tool_manager._tools
    result = asyncio.run(server.call_tool("sumo_qa_capabilities", {}))
    assert result is not None
