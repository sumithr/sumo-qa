# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for src/sumo_qa/skill_prompts.py.

Every skills/*/SKILL.md must register as an MCP TOOL at server startup
(not a prompt). Baseline delivery channel across hosts: every supported
host can REACH an MCP tool, though how each surfaces them differs (only
JetBrains AI Assistant slash-invokes them; Claude Code, Junie and VS Code
+ Copilot call them by natural language). Registering as prompts would
only surface in Claude Code, creating asymmetric behavior. Claude Code
additionally loads these skills through its native loader: via the
``~/.claude/skills/`` entries on a pip/``sumo-qa-install`` setup, or
straight from ``skills/<name>/SKILL.md`` in the plugin directory on a
plugin install. See src/sumo_qa/skill_prompts.py module docstring for the
full rationale.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sumo_qa.server import build_mcp_server

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / "skills"

_EXPECTED_SKILL_TOOL_NAMES = {
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
    """Calling each skill tool returns the full SKILL.md content, read fresh
    from disk on each invocation (single source of truth), UNLESS the body
    exceeds the per-response token cap (#393), in which case the tool returns a
    compact progressive-loading pointer instead of the over-cap body the host
    would refuse."""
    from sumo_qa.skill_prompts import DEFAULT_SKILL_RESPONSE_TOKEN_CAP, _approx_tokens

    server = build_mcp_server()

    async def collect() -> dict[str, str]:
        bodies: dict[str, str] = {}
        for tool_name in _EXPECTED_SKILL_TOOL_NAMES:
            result = await server.call_tool(tool_name, {})
            # The server drops outputSchema, so call_tool returns a bare
            # content list (unstructured text). Older FastMCP returned a
            # (content_list, structured_content) tuple — handle both. Extract
            # the text from the first text content block.
            content_list = result[0] if isinstance(result, tuple) else result
            text = ""
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
        if _approx_tokens(expected_text) > DEFAULT_SKILL_RESPONSE_TOKEN_CAP:
            # Over-cap: a compact pointer to the progressive-loading route, NOT
            # the oversized body the host refuses to inline.
            pointer = bodies[tool_name]
            assert expected_text not in pointer, (
                f"tool {tool_name!r} returned the over-cap body inline"
            )
            assert "sumo_qa_load_skill_context" in pointer, (
                f"tool {tool_name!r} pointer does not name the progressive-loading route"
            )
        else:
            assert bodies[tool_name] == expected_text, (
                f"tool {tool_name!r} body is not byte-for-byte the SKILL.md content"
            )


def test_output_profile_env_is_inert_after_revert(tmp_path, monkeypatch) -> None:
    """The output-profile feature was removed (#556 reverts #215/#471). Setting
    SUMO_QA_OUTPUT_PROFILE must have NO effect: the served body stays byte-for-byte
    the SKILL.md content. This guards against a silent reintroduction of a
    serve-time overlay under the old env var."""
    from sumo_qa.skill_prompts import _make_skill_callable

    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    raw = "---\ndescription: d\n---\n# Body\n" + "word " * 40
    (skill_dir / "SKILL.md").write_text(raw, encoding="utf-8")

    assert _make_skill_callable(skill_dir / "SKILL.md")() == raw
    for value in ("concise", "strict", "lean", "nonsense"):
        monkeypatch.setenv("SUMO_QA_OUTPUT_PROFILE", value)
        assert _make_skill_callable(skill_dir / "SKILL.md")() == raw, (
            f"SUMO_QA_OUTPUT_PROFILE={value!r} changed the served body; "
            f"the removed profile feature must stay inert"
        )


# ---------------------------------------------------------------------------
# Branch coverage for skill_prompts.py
# ---------------------------------------------------------------------------


def test_parse_frontmatter_returns_empty_when_no_frontmatter() -> None:
    """_parse_frontmatter() returns {} when the text has no --- block (line 61)."""
    from sumo_qa.skill_prompts import _parse_frontmatter

    result = _parse_frontmatter("# Skill\n\nJust markdown, no frontmatter.\n")
    assert result == {}


def test_parse_frontmatter_returns_empty_on_yaml_error() -> None:
    """_parse_frontmatter() returns {} when the YAML inside --- is malformed (lines 64-65)."""
    from sumo_qa.skill_prompts import _parse_frontmatter

    # Valid frontmatter delimiters but invalid YAML content.
    text = "---\nkey: [unclosed\n---\n# Body"
    result = _parse_frontmatter(text)
    assert result == {}


def test_register_skills_as_prompts_noop_when_skills_dir_missing(tmp_path) -> None:
    """register_skills_as_prompts() returns immediately when the skills dir
    doesn't exist — the inner loop is never entered (line 82)."""
    from unittest.mock import MagicMock, patch

    from sumo_qa.skill_prompts import register_skills_as_prompts

    mcp = MagicMock()
    nonexistent = tmp_path / "no_such_dir"
    with patch("sumo_qa.skill_prompts._skills_dir", return_value=nonexistent):
        register_skills_as_prompts(mcp)

    mcp.tool.assert_not_called()


def test_register_skills_skips_non_directory_entries(tmp_path) -> None:
    """register_skills_as_prompts() skips files inside the skills dir (line 85)."""
    from unittest.mock import MagicMock, patch

    from sumo_qa.skill_prompts import register_skills_as_prompts

    # Create a file (not a directory) inside the fake skills dir.
    (tmp_path / "not_a_skill.txt").write_text("hello", encoding="utf-8")

    mcp = MagicMock()
    with patch("sumo_qa.skill_prompts._skills_dir", return_value=tmp_path):
        register_skills_as_prompts(mcp)

    mcp.tool.assert_not_called()


def test_register_skills_skips_directories_without_skill_md(tmp_path) -> None:
    """register_skills_as_prompts() skips skill dirs that have no SKILL.md (line 88)."""
    from unittest.mock import MagicMock, patch

    from sumo_qa.skill_prompts import register_skills_as_prompts

    # A directory with no SKILL.md.
    (tmp_path / "my-skill").mkdir()

    mcp = MagicMock()
    with patch("sumo_qa.skill_prompts._skills_dir", return_value=tmp_path):
        register_skills_as_prompts(mcp)

    mcp.tool.assert_not_called()


def test_register_skills_uses_description_from_frontmatter(tmp_path) -> None:
    """register_skills_as_prompts() reads description from frontmatter (line 92-96)
    and collapses multi-line folded YAML descriptions."""
    from unittest.mock import MagicMock, patch

    from sumo_qa.skill_prompts import register_skills_as_prompts

    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: A multi-line\n  description here\n---\n# Body",
        encoding="utf-8",
    )

    mcp = MagicMock()
    mcp.tool.return_value = lambda fn: fn  # decorator passthrough
    with patch("sumo_qa.skill_prompts._skills_dir", return_value=tmp_path):
        register_skills_as_prompts(mcp)

    # tool() should have been called once for the one skill directory.
    assert mcp.tool.called


def test_register_skills_falls_back_to_skill_name_when_no_description(tmp_path) -> None:
    """When frontmatter has no description, the name is used as fallback (line 92)."""
    from unittest.mock import MagicMock, patch

    from sumo_qa.skill_prompts import register_skills_as_prompts

    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nid: x\n---\n# Body", encoding="utf-8")

    mcp = MagicMock()
    mcp.tool.return_value = lambda fn: fn
    with patch("sumo_qa.skill_prompts._skills_dir", return_value=tmp_path):
        register_skills_as_prompts(mcp)

    assert mcp.tool.called


def test_skills_dir_returns_bundled_when_exists() -> None:
    """_skills_dir() returns the bundled path when it exists (line 52)."""
    from pathlib import Path
    from unittest.mock import patch

    from sumo_qa.skill_prompts import _BUNDLED_SKILLS, _skills_dir

    with patch.object(Path, "is_dir", return_value=True):
        result = _skills_dir()

    assert result == _BUNDLED_SKILLS


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
