"""Skill conformance — every skills/*/SKILL.md must follow the upstream
superpowers structure.

In Phase 1, only frontmatter checks are active. Phase 2 unskips the
structure checks (Iron Law, Checklist, Process Flow, Red Flags, Examples)
once the stub skills get their full content."""
import re
from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).parent.parent / "skills"
SKILL_PATHS = sorted(SKILLS_DIR.glob("*/SKILL.md"))
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _frontmatter(path: Path) -> dict:
    match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    return yaml.safe_load(match.group(1)) if match else {}


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_has_frontmatter_with_name_and_description(skill_path):
    fm = _frontmatter(skill_path)
    assert "name" in fm, f"Missing 'name' frontmatter in {skill_path}"
    assert "description" in fm, f"Missing 'description' frontmatter in {skill_path}"


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_name_matches_directory_name(skill_path):
    fm = _frontmatter(skill_path)
    assert fm.get("name") == skill_path.parent.name, (
        f"Frontmatter name '{fm.get('name')}' must match directory '{skill_path.parent.name}'"
    )


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_descriptions_are_non_empty(skill_path):
    fm = _frontmatter(skill_path)
    desc = fm.get("description") or ""
    assert len(desc.strip()) >= 30, (
        f"Description too short in {skill_path}: {desc[:80]}"
    )


def test_skill_descriptions_are_unique():
    descriptions = [_frontmatter(p).get("description") for p in SKILL_PATHS]
    assert len(set(descriptions)) == len(descriptions), (
        "Duplicate skill descriptions detected — auto-trigger will be ambiguous"
    )


# Structure checks — un-skipped in Phase 2.
@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_has_iron_law_section(skill_path):
    text = skill_path.read_text(encoding="utf-8")
    assert "## The Iron Law" in text or "## Iron Law" in text


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_has_checklist_section_with_at_least_four_items(skill_path):
    text = skill_path.read_text(encoding="utf-8")
    assert "## Checklist" in text
    checklist_section = text.split("## Checklist", 1)[1].split("##", 1)[0]
    items = re.findall(r"^\s*\d+\.", checklist_section, flags=re.MULTILINE)
    assert len(items) >= 4


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_has_process_flow_dot_block(skill_path):
    text = skill_path.read_text(encoding="utf-8")
    assert "```dot" in text


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_has_red_flags_section(skill_path):
    text = skill_path.read_text(encoding="utf-8")
    assert "## Red Flags" in text
