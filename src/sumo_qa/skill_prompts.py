"""Register every skills/*/SKILL.md as an MCP prompt.

The skill content IS the prompt body. No copy lives anywhere else; the file
is read fresh on each prompt invocation. Hosts that auto-load skills (Claude
Code) read the same files via symlinks. This single source of truth + two
delivery channels mechanism means editing a skill propagates to every host
without rebuild or restart.
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
    """Register every SKILL.md under skills/ as an MCP prompt.

    Prompt name: directory name with `-` -> `_`. Description: from frontmatter.
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
        prompt_name = skill_dir.name.replace("-", "_")
        description = frontmatter.get("description") or f"Skill: {skill_dir.name}"
        # Collapse multi-line YAML folded descriptions to a single line so MCP
        # hosts that render descriptions inline don't show stray newlines.
        if isinstance(description, str):
            description = " ".join(description.split())
        _bind_prompt(mcp, prompt_name, description, skill_path)


def _bind_prompt(mcp: Any, name: str, description: str, path: Path) -> None:
    """Bind a single skill file as an MCP prompt.

    The default-argument indirection on `_skill_prompt` is critical: Python
    closures capture `path` by reference, so binding inside a loop without
    it would make every prompt return the last skill's content.
    """

    @mcp.prompt(name=name, description=description)
    def _skill_prompt(_path: Path = path) -> str:
        return _path.read_text(encoding="utf-8")
