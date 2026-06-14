# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Deterministic, host-neutral pytest harness for natural-language trigger routing.

The host LLM picks a sumo-qa skill tool from its MCP `description` alone — no
other signal is exposed. This harness pins the trigger-phrase contract for
each of the 16 skill tools so a future description rewording that drops a
user-natural phrase fails CI rather than silently mis-routing the host.

The fixture (`tests/fixtures/skill_triggers.yaml`) is the contract; edit the
fixture (not the test) to extend coverage to a new prompt or skill. A new
skill landing without a fixture row also fails the suite via
`test_every_registered_skill_has_a_trigger_row`.

LLM-judged routing evals live in `tests/evals/promptfoo/` and remain optional
— they need an API key and are not part of CI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from sumo_qa.server import build_mcp_server

_SKILLS_DIR = Path(__file__).parent.parent / "skills"
_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "skill_triggers.yaml"


def _registered_skill_tool_names() -> frozenset[str]:
    """The set of MCP tool names registered for each `skills/<name>/SKILL.md`.

    Derived from the on-disk `skills/` directory rather than hardcoded so a
    new skill landing without trigger coverage trips
    `test_every_registered_skill_has_a_trigger_row` automatically — no
    parallel constant to keep in sync with the server registration logic."""
    return frozenset(
        p.name.replace("-", "_")
        for p in _SKILLS_DIR.iterdir()
        if p.is_dir() and (p / "SKILL.md").is_file()
    )


def _load_fixture() -> dict[str, list[dict[str, Any]]]:
    with _FIXTURE_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "triggers" in data, "fixture missing 'triggers' key"
    assert "non_triggers" in data, "fixture missing 'non_triggers' key"
    return data


_FIXTURE = _load_fixture()


def _registered_tools() -> dict[str, Any]:
    server = build_mcp_server()
    return server._tool_manager._tools


def _ascii_id(prompt: str) -> str:
    """ASCII-sanitise a prompt for use as a pytest parametrize ID.

    Pytest's `_idval` represents non-ASCII characters in collected node IDs
    as `\\u…` escape sequences, but its own CLI nodeid lookup matches against
    the original parametrize ID — the two no longer line up, so selecting a
    test by its full nodeid (as mutmut's stats-collection does via
    `pytest_runtest_logstart` → `pytest.main(...)`) fails with exit code 4
    (CLI usage error / "not found"). Stripping non-ASCII at ID-build time
    keeps the fixture prompts unchanged (they're still the assertion target)
    while making every parametrize ID round-trip cleanly through pytest's
    selector. Em-dash / en-dash collapse to ASCII hyphen so the IDs read
    naturally; anything else non-ASCII is dropped.
    """
    table = str.maketrans({"—": "-", "–": "-"})
    return prompt.translate(table).encode("ascii", "ignore").decode("ascii")


def _trigger_id(row: dict[str, Any]) -> str:
    return f"{row['expected_skill']}::{_ascii_id(row['prompt'])[:40]}"


def _non_trigger_id(row: dict[str, Any]) -> str:
    return f"{row['must_not_match_skill']}::{_ascii_id(row['prompt'])[:40]}"


@pytest.mark.parametrize(
    "row", _FIXTURE["triggers"], ids=[_trigger_id(r) for r in _FIXTURE["triggers"]]
)
def test_trigger_prompt_routes_by_description(row: dict[str, Any]) -> None:
    """Each fixture trigger row must find at least one of its expected phrases
    in the description of the expected skill tool.

    Failure means a description rewording has dropped the user-natural phrase
    the host LLM would use to route this prompt — fix the description (or, if
    the prompt itself is outdated, the fixture row)."""
    tools = _registered_tools()
    expected_skill = row["expected_skill"]
    prompt = row["prompt"]
    expected_phrases = [p.lower() for p in row["expected_phrases"]]

    assert expected_skill in tools, (
        f"prompt={prompt!r}: expected_skill={expected_skill!r} is not registered "
        f"as an MCP tool — fixture is stale or the skill was removed."
    )

    description = (tools[expected_skill].description or "").lower()
    matched = [p for p in expected_phrases if p in description]
    assert matched, (
        f"prompt={prompt!r}: expected_skill={expected_skill!r} description "
        f"contains NONE of expected_phrases={expected_phrases!r}; "
        f"the host LLM will not route this user prompt to this tool by description alone. "
        f"description_first_240={description[:240]!r}"
    )


def test_every_registered_skill_has_a_trigger_row() -> None:
    """Every skill tool registered by the server must appear in the fixture as
    the `expected_skill` of at least one trigger row.

    The set of registered skill tools is derived from `skills/` on disk
    (mirroring the server's registration logic), so a new skill landing
    without a fixture row trips this test automatically. Catches the silent
    drift mode where a new sumo-qa-* skill ships with no trigger-routing
    coverage. Fix by adding a row to `tests/fixtures/skill_triggers.yaml`,
    not by weakening this test."""
    covered = {row["expected_skill"] for row in _FIXTURE["triggers"]}
    missing = _registered_skill_tool_names() - covered
    assert not missing, (
        f"Skill tools without a trigger fixture row: {sorted(missing)}. "
        f"Add a row per skill to tests/fixtures/skill_triggers.yaml."
    )


def test_fixture_only_references_registered_skills() -> None:
    """Every `expected_skill` in the fixture must be a real, registered tool —
    catches typos and stale fixture entries."""
    tools = _registered_tools()
    referenced = {row["expected_skill"] for row in _FIXTURE["triggers"]}
    unknown = referenced - set(tools.keys())
    assert not unknown, (
        f"Fixture references unknown skill tools: {sorted(unknown)}. "
        f"Either the skill was removed or the row name is a typo."
    )


@pytest.mark.parametrize(
    "row",
    _FIXTURE["non_triggers"],
    ids=[_non_trigger_id(r) for r in _FIXTURE["non_triggers"]],
)
def test_non_trigger_prompt_lacks_overlap_with_skill_phrases(
    row: dict[str, Any],
) -> None:
    """Non-trigger control prompts must NOT share trigger phrases with the
    skill they're declared not-to-route-into.

    This is a sanity guard, not a routing oracle: a real LLM might still
    over-match. But if a non-QA prompt contains a verbatim trigger phrase
    from a sumo-qa skill, the fixture phrases are too generic — tighten them."""
    must_not = row["must_not_match_skill"]
    prompt_lower = row["prompt"].lower()

    # Guard: catch typos in must_not_match_skill that would otherwise leave
    # `matching_skill_phrases` empty and let the assertion below pass vacuously.
    trigger_skills = {trigger_row["expected_skill"] for trigger_row in _FIXTURE["triggers"]}
    assert must_not in trigger_skills, (
        f"non-trigger row references must_not_match_skill={must_not!r}, but that skill "
        f"has no trigger row in the fixture; the overlap check would pass vacuously. "
        f"Fix the typo or add a trigger row for that skill first."
    )

    # Collect all expected phrases declared for the must-not-match skill.
    matching_skill_phrases = [
        p.lower()
        for trigger_row in _FIXTURE["triggers"]
        if trigger_row["expected_skill"] == must_not
        for p in trigger_row["expected_phrases"]
    ]
    overlap = [p for p in matching_skill_phrases if p in prompt_lower]
    assert not overlap, (
        f"non-trigger prompt={row['prompt']!r} contains trigger phrases "
        f"{overlap!r} declared for skill {must_not!r}; "
        f"fixture phrases are too generic — make them more specific to the skill's intent."
    )
