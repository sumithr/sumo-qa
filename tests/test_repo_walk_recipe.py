import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPE = REPO_ROOT / "knowledge" / "repo_walk.md"


def test_recipe_file_exists():
    assert RECIPE.is_file(), f"Expected recipe at {RECIPE}"


def test_recipe_has_required_sections_in_order():
    body = RECIPE.read_text(encoding="utf-8")
    sections = re.findall(r"^## .+", body, flags=re.MULTILINE)
    expected = ["## Inventory commands", "## Data shape captured", "## Output template"]
    # Each expected section must appear in the file in the listed order
    indices = [sections.index(s) if s in sections else -1 for s in expected]
    assert all(i >= 0 for i in indices), (
        f"Missing sections: {[s for s, i in zip(expected, indices, strict=False) if i < 0]}"
    )
    assert indices == sorted(indices), f"Sections out of order: {sections}"


def test_each_required_section_has_fenced_code_block():
    body = RECIPE.read_text(encoding="utf-8")
    # Split on H2 headings; check each required section has ``` somewhere before the next H2
    sections = re.split(r"^(## .+)$", body, flags=re.MULTILINE)
    # sections is [preamble, heading1, body1, heading2, body2, ...]
    headings_to_bodies = dict(zip(sections[1::2], sections[2::2], strict=False))
    for required in ["## Inventory commands", "## Data shape captured", "## Output template"]:
        body_chunk = headings_to_bodies.get(required, "")
        assert "```" in body_chunk, f"{required} has no fenced code block"


def test_strategising_skill_references_recipe():
    skill = REPO_ROOT / "skills" / "sumo-qa-strategising" / "SKILL.md"
    body = skill.read_text(encoding="utf-8")
    assert "knowledge/repo_walk.md" in body, (
        "sumo-qa-strategising SKILL.md does not reference the recipe path"
    )
