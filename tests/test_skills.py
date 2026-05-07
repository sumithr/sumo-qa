"""Smoke checks on the QA skill files we ship.

Skills follow superpowers conventions:
  - Live under skills/<skill-name>/SKILL.md
  - Have YAML frontmatter with `name` and `description`
  - Have an Iron Law block
  - Reference at least one qa_* MCP tool concretely
  - Have a Red Flags section
"""
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"

EXPECTED_SKILLS = (
    "using-sumo-qa",
    "sumo-qa-strategising",
    "qa-deciding-approach",
    "qa-implementing-with-tdd",
    "qa-strengthening-tests",
    "qa-reviewing-before-merge",
    "qa-finding-test-data",
)


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_skill_file_exists(skill_name: str) -> None:
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    assert skill_path.is_file(), f"missing skill: {skill_path}"


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_skill_has_frontmatter(skill_name: str) -> None:
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{skill_name}: missing YAML frontmatter"
    end = text.find("\n---\n", 4)
    assert end > 4, f"{skill_name}: malformed frontmatter"
    frontmatter = text[4:end]
    assert "name:" in frontmatter
    assert "description:" in frontmatter
    # Name in frontmatter must match the directory name
    name_line = next(line for line in frontmatter.splitlines() if line.startswith("name:"))
    declared_name = name_line.split(":", 1)[1].strip()
    assert declared_name == skill_name, (
        f"{skill_name}: frontmatter name {declared_name!r} != directory name"
    )


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_skill_has_iron_law_section(skill_name: str) -> None:
    """Each skill states an explicit Iron Law (the discipline it enforces)."""
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8").lower()
    assert "iron law" in text or "the rule" in text, (
        f"{skill_name}: missing 'Iron Law' or 'The Rule' section"
    )


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_skill_has_red_flags_section(skill_name: str) -> None:
    """Red flags is the 'when to STOP and re-route' table.

    The entry skill (using-sumo-qa) and worker skills both have it; only
    skip if a skill is purely informational. We require it for now.
    """
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8").lower()
    assert "red flag" in text, f"{skill_name}: missing 'Red Flags' section"


@pytest.mark.parametrize(
    "skill_name,must_reference_tool",
    [
        ("using-sumo-qa", "sumo_qa_decide_approach"),
        ("sumo-qa-strategising", "sumo_qa_decide_approach"),
        ("qa-deciding-approach", "sumo_qa_decide_approach"),
        ("qa-implementing-with-tdd", "sumo_qa_scaffold_tests"),
        ("qa-strengthening-tests", "sumo_qa_scaffold_tests"),
        ("qa-reviewing-before-merge", "sumo_qa_review_local_change"),
        ("qa-finding-test-data", "sumo_qa_find_test_data"),
    ],
)
def test_skill_references_its_primary_mcp_tool(skill_name: str, must_reference_tool: str) -> None:
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    assert must_reference_tool in text, (
        f"{skill_name}: must reference {must_reference_tool!r} as the concrete MCP action"
    )


def test_entry_skill_routes_to_each_subskill() -> None:
    """The using-sumo-qa entry skill must point at every other skill."""
    entry_text = (SKILLS_DIR / "using-sumo-qa" / "SKILL.md").read_text(encoding="utf-8")
    for sub in EXPECTED_SKILLS:
        if sub == "using-sumo-qa":
            continue
        assert sub in entry_text, f"entry skill does not reference {sub}"


def test_host_agnostic_workflow_doc_exists_and_covers_every_tool() -> None:
    """docs/QA_WORKFLOW.md is the host-agnostic equivalent of the skills.

    Users on Cursor / Copilot / Windsurf / Aider / etc. paste this content
    into their project's agent-instructions file (.cursorrules, AGENTS.md,
    .github/copilot-instructions.md, etc.) to get the same discipline.
    """
    workflow = ROOT / "docs" / "QA_WORKFLOW.md"
    assert workflow.is_file(), f"missing host-agnostic workflow doc at {workflow}"

    text = workflow.read_text(encoding="utf-8")
    # Every primary MCP tool must be referenced so the discipline is complete.
    for tool in (
        "sumo_qa_decide_approach",
        "sumo_qa_scaffold_tests",
        "sumo_qa_review_local_change",
        "sumo_qa_create_test_plan",
        "sumo_qa_find_test_data",
        "sumo_qa_explain_test_data_requirements",
        "sumo_qa_validate_test_data",
        "sumo_qa_register_known_good_test_data",
    ):
        assert tool in text, f"workflow doc does not reference MCP tool {tool!r}"

    # Names of all 7 approaches must all be present so the branching is complete.
    for approach in (
        "tdd-scaffold",
        "regression-first",
        "coverage-first-then-refactor",
        "strengthen-test-coverage",
        "verify-existing",
        "no-tests-recommended",
        "spike-first-then-tests",
    ):
        assert approach in text, f"workflow doc does not reference approach {approach!r}"

    # Hosts table must list at least Claude Code, Cursor, Copilot, Aider so the
    # cross-host coverage is explicit.
    for host in ("Claude Code", "Cursor", "Copilot", "Aider"):
        assert host in text, f"workflow doc does not mention host {host!r}"
