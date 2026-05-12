# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for src/sumo_qa/skill_prompts.py.

Every skills/*/SKILL.md must register as an MCP TOOL at server startup
(not a prompt). Single delivery channel across hosts — Claude Code,
IntelliJ AI Assistant, and VS Code + Copilot all surface MCP tools in
their slash menu identically. Registering as prompts would only surface
in Claude Code, creating asymmetric behavior. See
src/sumo_qa/skill_prompts.py module docstring for the full rationale.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sumo_qa.server import build_mcp_server

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / "skills"

_EXPECTED_SKILL_TOOL_NAMES = {
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


def test_every_skill_registers_as_an_mcp_tool() -> None:
    """Every skills/*/SKILL.md must surface as an MCP tool at startup."""
    server = build_mcp_server()
    tool_names = set(server._tool_manager._tools.keys())

    missing = _EXPECTED_SKILL_TOOL_NAMES - tool_names
    assert not missing, f"Missing skill tools: {missing}"


def test_no_skill_registered_as_a_prompt() -> None:
    """Skills must register as tools only, never as prompts. Dual
    registration would create duplicate slash-menu entries in Claude
    Code (the host that surfaces both) — the confusion this design
    explicitly avoids."""
    server = build_mcp_server()
    prompt_names = set(server._prompt_manager._prompts.keys())

    leaked = _EXPECTED_SKILL_TOOL_NAMES & prompt_names
    assert not leaked, f"Skills leaked into MCP prompts: {leaked}"


def test_skill_tool_body_matches_skill_md_content() -> None:
    """Calling each skill tool returns the full SKILL.md content, read
    fresh from disk on each invocation (single source of truth)."""
    server = build_mcp_server()

    async def collect() -> dict[str, str]:
        bodies: dict[str, str] = {}
        for tool_name in _EXPECTED_SKILL_TOOL_NAMES:
            result = await server.call_tool(tool_name, {})
            # FastMCP returns (content_list, structured_content) for tool
            # results. Extract the text from the first text content block.
            text = ""
            if isinstance(result, tuple) and result:
                content_list = result[0]
                for content in content_list:
                    block_text = getattr(content, "text", None)
                    if block_text:
                        text = block_text
                        break
            bodies[tool_name] = text
        return bodies

    bodies = asyncio.run(collect())

    for tool_name in _EXPECTED_SKILL_TOOL_NAMES:
        skill_dir_name = tool_name.replace("_", "-")
        # `sumo-qa-strategising` is the only multi-hyphen name; `_` -> `-`
        # round-trips correctly because none of the directory names contain
        # underscores.
        skill_path = _SKILLS_DIR / skill_dir_name / "SKILL.md"
        assert skill_path.is_file(), f"missing skill file: {skill_path}"
        expected_text = skill_path.read_text(encoding="utf-8")
        assert expected_text in bodies[tool_name], (
            f"tool {tool_name!r} body does not contain SKILL.md content"
        )


def test_skill_tool_description_matches_frontmatter() -> None:
    """Each skill tool's MCP description should come from the SKILL.md
    frontmatter `description`, so hosts that show tool menus surface the
    canonical sentence the skill author wrote."""
    import yaml

    server = build_mcp_server()
    tools = server._tool_manager._tools

    for tool_name in _EXPECTED_SKILL_TOOL_NAMES:
        skill_dir_name = tool_name.replace("_", "-")
        skill_path = _SKILLS_DIR / skill_dir_name / "SKILL.md"
        text = skill_path.read_text(encoding="utf-8")
        # Cheap frontmatter parse mirroring the implementation; if this
        # diverges from the implementation, the test failure points at the
        # discrepancy, which is what we want.
        assert text.startswith("---"), f"{skill_path} missing frontmatter"
        _, fm, _ = text.split("---", 2)
        meta = yaml.safe_load(fm) or {}
        expected_description = meta.get("description")
        assert expected_description, f"{skill_path} frontmatter missing `description`"
        # The implementation collapses folded YAML descriptions to a single
        # line, so compare against the same transformation.
        expected_collapsed = " ".join(expected_description.split())

        tool = tools[tool_name]
        assert tool.description == expected_collapsed, (
            f"tool {tool_name!r} description mismatch: "
            f"expected={expected_collapsed!r} got={tool.description!r}"
        )
