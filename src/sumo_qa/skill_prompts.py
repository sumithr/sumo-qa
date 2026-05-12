"""Register every skills/*/SKILL.md so every supported host can invoke them.

MCP hosts surface skills differently in their slash menu:

- Claude Code auto-loads `~/.claude/skills/sumo-qa/` natively (you see
  `/qa-deciding-approach`, hyphens, in the slash menu) AND surfaces MCP
  prompts. Both routes point at the same SKILL.md files.
- IntelliJ AI Assistant and VS Code + Copilot surface MCP **tools** in the
  slash menu but not MCP prompts. They have no native skill loader.

To make every host expose the 10 skills, this module registers each
SKILL.md as:

1. An MCP prompt (`qa_creating_test_plan` etc.) — for hosts that surface
   prompts (Claude Code), and as the canonical MCP prompts surface.
2. An MCP tool with the same name — for hosts that surface tools only
   (IntelliJ, Copilot). Calling the tool returns the SKILL.md body, which
   the host LLM then follows as if the skill had been loaded natively.

The SKILL.md file is read fresh on each invocation so editing it propagates
without restart.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter from a markdown file. Returns {} when absent or
    malformed; we never want a bad frontmatter to break server startup."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    return parsed or {}


def register_skills_as_prompts(mcp: Any) -> None:
    """Register every SKILL.md under skills/ as both an MCP prompt and an MCP tool.

    Name kept as the historic `register_skills_as_prompts` for backwards
    compatibility with `server.py`; the implementation now does dual
    registration so every host has a slash-command surface.

    Name: directory name with `-` -> `_`. Description: from frontmatter.
    Body: full file content (including frontmatter), read fresh on each call
    so editing the SKILL.md propagates without restart.
    """
    if not _SKILLS_DIR.is_dir():
        return
    for skill_dir in sorted(_SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.is_file():
            continue
        text = skill_path.read_text(encoding="utf-8")
        frontmatter = _parse_frontmatter(text)
        name = skill_dir.name.replace("-", "_")
        description = frontmatter.get("description") or f"Skill: {skill_dir.name}"
        # Collapse multi-line YAML folded descriptions to a single line so MCP
        # hosts that render descriptions inline don't show stray newlines.
        if isinstance(description, str):
            description = " ".join(description.split())
        _bind_prompt(mcp, name, description, skill_path)
        _bind_tool(mcp, name, description, skill_path)


def _make_skill_callable(path: Path):
    """Factory returning a zero-argument function that reads `path` at call time.

    The factory closes over `path` so each generated function returns its OWN
    skill content. Using a factory (instead of a default-argument closure)
    keeps the function's signature parameter-free, which FastMCP's tool
    introspection requires.
    """

    def _skill_body() -> str:
        return path.read_text(encoding="utf-8")

    return _skill_body


def _bind_prompt(mcp: Any, name: str, description: str, path: Path) -> None:
    """Bind one SKILL.md as an MCP prompt named `name`."""
    fn = _make_skill_callable(path)
    fn.__name__ = name
    mcp.prompt(name=name, description=description)(fn)


def _bind_tool(mcp: Any, name: str, description: str, path: Path) -> None:
    """Bind one SKILL.md as an MCP tool named `name`.

    Same content as the prompt registration, exposed via the tools surface
    so hosts whose slash menus only surface tools (IntelliJ AI Assistant,
    VS Code + Copilot) can still invoke skills.
    """
    fn = _make_skill_callable(path)
    fn.__name__ = name
    mcp.tool(name=name, description=description)(fn)
