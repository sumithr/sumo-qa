# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The canonical first-hop contract is one rule across every entry surface (#247).

Every surface that tells a host how to enter sumo-qa must carry
`FIRST_HOP_RULE` verbatim, so the
server instructions, Copilot instructions, entry-skill body, SessionStart
compact bootstrap, trigger fixture, and conformance fixture cannot assert incompatible rules. Tool-name validity of
the instruction surfaces is pinned in tests/test_server.py. Text presence is a
drift guard, not proof that a model follows the rule; that proof is the
conformance validator plus captured live-host runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sumo_qa.first_hop import CLARIFY_AFTER_ROUTING, FIRST_HOP_RULE
from sumo_qa.server import build_mcp_server

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Files that must carry the rule verbatim. Server instructions are checked
# separately because they live on the built server, not on disk.
_RULE_FILES = {
    "copilot-instructions": _REPO_ROOT / ".github" / "copilot-instructions.md",
    "entry-skill": _REPO_ROOT / "skills" / "using-sumo-qa" / "SKILL.md",
    "session-bootstrap": _REPO_ROOT / "hooks" / "compact-bootstrap.md",
    "trigger-fixture": _REPO_ROOT / "tests" / "fixtures" / "skill_triggers.yaml",
    "conformance-fixture": _REPO_ROOT / "tests" / "scenarios" / "conformance" / "scenarios.yaml",
}


def _normalise(text: str) -> str:
    """Collapse wrapping and YAML/Markdown comment prefixes so a rule wrapped
    across comment lines still compares equal to the one-line constant."""
    lines = (line.strip().lstrip("#").strip() for line in text.splitlines())
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _server_instructions() -> str:
    return getattr(build_mcp_server(), "instructions", "") or ""


def test_normalise_joins_wrapped_comment_lines() -> None:
    wrapped = "# First hop: every\n#   QA-shaped   request\n"
    assert _normalise(wrapped) == "First hop: every QA-shaped request"


@pytest.mark.parametrize("surface", sorted(_RULE_FILES))
def test_rule_file_carries_the_first_hop_rule_verbatim(surface: str) -> None:
    text = _RULE_FILES[surface].read_text(encoding="utf-8")
    assert _normalise(FIRST_HOP_RULE) in _normalise(text), (
        f"{surface} ({_RULE_FILES[surface].relative_to(_REPO_ROOT)}) does not carry "
        f"sumo_qa.first_hop.FIRST_HOP_RULE verbatim; every entry surface must state "
        f"the same first-hop rule."
    )


def test_server_instructions_carry_the_first_hop_rule_verbatim() -> None:
    assert _normalise(FIRST_HOP_RULE) in _normalise(_server_instructions())


@pytest.mark.parametrize("surface", ["server-instructions", "copilot-instructions"])
def test_pre_routing_surface_defers_clarifying_questions_to_the_routed_skill(surface: str) -> None:
    """Hosts read these surfaces BEFORE any skill body, so the clarify-after-
    routing clause must live here: on the weakest candidate an underspecified
    ask ("write the failing tests first") was answered with a clarifying
    question and no sumo-qa call at all."""
    if surface == "server-instructions":
        text = _server_instructions()
    else:
        text = _RULE_FILES[surface].read_text(encoding="utf-8")
    assert _normalise(CLARIFY_AFTER_ROUTING) in _normalise(text)
