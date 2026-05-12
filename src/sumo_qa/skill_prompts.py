# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Register every skills/*/SKILL.md as an MCP tool.

Single delivery channel for skills across every supported host. MCP tools
are surfaced in the slash menu by Claude Code, IntelliJ AI Assistant, and
VS Code + Copilot — so registering each SKILL.md as a tool means
`/qa_deciding_approach`, `/qa_creating_test_plan`, etc. appear identically
in every host. Calling the tool returns the SKILL.md body, which the host
LLM follows.

Why not also register as MCP prompts? MCP prompts are surfaced by Claude
Code but not by IntelliJ. Registering as both creates duplicate entries
in Claude Code's slash menu — same name, two routes — which is the
confusion the user pushed back on. One channel keeps the experience
identical.

Why not also symlink into ~/.claude/skills/ for Claude Code's native
skill loader? The native loader has richer features (auto-loads checklist
into TodoWrite, treats Iron Law as system-prompt-grade discipline) but
those features don't exist in IntelliJ or Copilot. Symlinking creates
asymmetric behavior the user shouldn't have to think about. install.py
no longer creates the symlink.

The SKILL.md file is read fresh on each invocation so editing it propagates
without restart.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT_SKILLS = Path(__file__).resolve().parent.parent.parent / "skills"
_BUNDLED_SKILLS = Path(__file__).resolve().parent / "_data" / "skills"
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _skills_dir() -> Path:
    """Return the directory holding SKILL.md files.

    Resolution order:
    1. The bundled `_data/skills/` shipped inside the wheel (production
       installs via uv/pipx land here).
    2. The repo's top-level `skills/` (development / source checkout).

    Returning a path that doesn't exist is fine — the iteration code below
    no-ops cleanly when there are no skill dirs."""
    if _BUNDLED_SKILLS.is_dir():
        return _BUNDLED_SKILLS
    return _REPO_ROOT_SKILLS


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
    """Register every SKILL.md under skills/ as an MCP tool.

    Name kept as the historic `register_skills_as_prompts` for backwards
    compatibility with existing `server.py` call sites. The implementation
    is now tool-only (see module docstring for why).

    Name: directory name with `-` -> `_`. Description: from frontmatter.
    Body: full file content (including frontmatter), read fresh on each call
    so editing the SKILL.md propagates without restart.
    """
    skills_dir = _skills_dir()
    if not skills_dir.is_dir():
        return
    for skill_dir in sorted(skills_dir.iterdir()):
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


def _bind_tool(mcp: Any, name: str, description: str, path: Path) -> None:
    """Bind one SKILL.md as an MCP tool named `name`. The tool returns the
    SKILL.md body, which the host LLM follows."""
    fn = _make_skill_callable(path)
    fn.__name__ = name
    mcp.tool(name=name, description=description)(fn)
