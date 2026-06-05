# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Token-budget guard for the QA-artifact export (issue #148, acceptance
criterion: "Token-budget tests prove the export capability does not increase
default skill payload size").

The export capability is a NEW MCP tool plus three Python modules. Crucially it
is NOT wired into any skill's default flow: markdown prose stays the human-facing
output, and export only happens on an explicit user request via
``sumo_qa_export_test_cases``. The thing that would grow the per-activation skill
payload is a ``skills/*/SKILL.md`` body — so the load-bearing proof that export
did not grow that payload is:

1. No ``skills/*/SKILL.md`` mentions the export tool / export capability — the
   default skill bodies are untouched by this feature, so each skill's
   activation token cost is identical to before the export tool existed.
2. The export Python modules carry no SKILL.md content (they are server-side
   plumbing the host calls on demand, never loaded into the model context as a
   skill body).

The numeric per-skill ceilings in ``test_skill_md_token_budget.py`` already gate
absolute SKILL.md size; this test pins the export-specific invariant (export adds
ZERO to any skill body) so a future change that wires export into a skill flow
fails here and forces a deliberate budget decision.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).parent.parent / "skills"
SKILL_PATHS = sorted(SKILLS_DIR.glob("*/SKILL.md"))

# Tokens that would indicate a skill body started routing through the export
# capability (and therefore grew the default skill payload). The tool name is the
# precise signal; the phrasings catch a prose reference that hasn't named the tool
# yet.
_EXPORT_MARKERS = (
    "sumo_qa_export_test_cases",
    "export_test_cases",
    "export the test cases",
    "export qa artifacts",
)


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_no_skill_body_references_the_export_capability(skill_path):
    """Every default skill body must be free of the export capability, proving
    the export tool did not grow any per-activation skill payload."""
    text = skill_path.read_text(encoding="utf-8").lower()
    hits = [marker for marker in _EXPORT_MARKERS if marker in text]
    assert not hits, (
        f"{skill_path.parent.name}/SKILL.md references the export capability "
        f"({hits}); the export tool is opt-in and must not be wired into a "
        f"default skill flow without a deliberate token-budget decision in "
        f"test_skill_md_token_budget.py."
    )


def test_export_modules_carry_no_skill_frontmatter():
    """The export modules are server-side plumbing, never a skill body. They must
    not carry SKILL.md frontmatter (the thing the host loads into context)."""
    src = Path(__file__).parent.parent / "src" / "sumo_qa"
    frontmatter = re.compile(r"\A---\s*\nname:", re.MULTILINE)
    for name in ("export_models.py", "export_format.py", "export_validation.py"):
        body = (src / name).read_text(encoding="utf-8")
        assert not frontmatter.match(body), f"{name} unexpectedly carries skill frontmatter"
