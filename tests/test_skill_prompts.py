"""Tests for src/sumo_qa/skill_prompts.py.

Every skills/*/SKILL.md must register as an MCP prompt at server startup.
The prompt name is the skill directory name with `-` replaced by `_`.
The prompt description matches the skill's frontmatter `description`.
The prompt body is the full SKILL.md content, read fresh on each call.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from sumo_qa.server import build_mcp_server

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / "skills"

_EXPECTED_SKILL_PROMPT_NAMES = {
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


def test_every_skill_registers_as_an_mcp_prompt() -> None:
    """Every skills/*/SKILL.md must surface as an MCP prompt at startup."""
    server = build_mcp_server()
    prompt_names = set(server._prompt_manager._prompts.keys())

    missing = _EXPECTED_SKILL_PROMPT_NAMES - prompt_names
    assert not missing, f"Missing skill prompts: {missing}"


def test_skill_prompt_body_matches_skill_md_content() -> None:
    """The prompt body for each skill must be the full SKILL.md text,
    read fresh from disk on each invocation (single source of truth)."""
    server = build_mcp_server()

    async def collect() -> dict[str, str]:
        bodies: dict[str, str] = {}
        for prompt_name in _EXPECTED_SKILL_PROMPT_NAMES:
            rendered = await server.get_prompt(prompt_name, {})
            text_parts: list[str] = []
            for message in rendered.messages:
                text = getattr(message.content, "text", "") or ""
                text_parts.append(text)
            bodies[prompt_name] = "\n".join(text_parts)
        return bodies

    bodies = asyncio.run(collect())

    for prompt_name in _EXPECTED_SKILL_PROMPT_NAMES:
        skill_dir_name = prompt_name.replace("_", "-")
        # `sumo-qa-strategising` is the only multi-hyphen name; `_` -> `-`
        # round-trips correctly because none of the directory names contain
        # underscores.
        skill_path = _SKILLS_DIR / skill_dir_name / "SKILL.md"
        assert skill_path.is_file(), f"missing skill file: {skill_path}"
        expected_text = skill_path.read_text(encoding="utf-8")
        assert expected_text in bodies[prompt_name], (
            f"prompt {prompt_name!r} body does not contain SKILL.md content"
        )


def test_skill_prompt_description_matches_frontmatter() -> None:
    """Each skill prompt's MCP description should come from the SKILL.md
    frontmatter `description`, so hosts that show prompt menus surface the
    canonical sentence the skill author wrote."""
    import yaml

    server = build_mcp_server()
    prompts = server._prompt_manager._prompts

    for prompt_name in _EXPECTED_SKILL_PROMPT_NAMES:
        skill_dir_name = prompt_name.replace("_", "-")
        skill_path = _SKILLS_DIR / skill_dir_name / "SKILL.md"
        text = skill_path.read_text(encoding="utf-8")
        # Cheap frontmatter parse mirroring the implementation; if this
        # diverges from the implementation, the test failure points at the
        # discrepancy, which is what we want.
        assert text.startswith("---"), f"{skill_path} missing frontmatter"
        _, fm, _ = text.split("---", 2)
        meta = yaml.safe_load(fm) or {}
        expected_description = meta.get("description")
        assert expected_description, (
            f"{skill_path} frontmatter missing `description`"
        )

        prompt = prompts[prompt_name]
        assert prompt.description == expected_description, (
            f"prompt {prompt_name!r} description mismatch: "
            f"expected={expected_description!r} got={prompt.description!r}"
        )
