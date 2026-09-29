# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""First-hop enforcement in the conformance validator (issue #247).

`sumo_qa.conformance` enforces `sumo_qa.first_hop.FIRST_HOP_RULE` on every
routed scenario: the first sumo-qa call is `using_sumo_qa`, then
`sumo_qa_deciding_approach`, then the expected skill. These tests pin the
four development-framed prompts, their non-QA controls, and each illegal
transition (no hop at all, a catalogue before the router, direct specialist
entry, a skipped or late decider).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sumo_qa.conformance import (
    ConformanceScenario,
    ScenarioResult,
    ToolCall,
    Transcript,
    ViolationKind,
    load_scenarios,
    validate_transcript,
)

_FIXTURE = Path(__file__).parent / "scenarios" / "conformance" / "scenarios.yaml"


@pytest.fixture(scope="module")
def scenarios() -> list[ConformanceScenario]:
    return load_scenarios(_FIXTURE)


def _kinds(result: ScenarioResult) -> set[ViolationKind]:
    return {v.kind for v in result.violations}


# --------------------------------------------------------------------------- #
# Canonical first hop (#247): router, then decider, then the routed skill     #
# --------------------------------------------------------------------------- #
# The four development-framed prompts #247 requires, verbatim.
_DEV_FRAMED_PROMPTS = {
    "I'm adding sumo_qa_analyze_diff_impact. How should I test it?",
    "I'm implementing a retry worker. What tests do I need for it?",
    "I'm changing the parser. How do I cover the edge cases?",
    "I'm building this endpoint. Write the failing tests first.",
}


def _first_hop_kinds(result: ScenarioResult) -> list[str]:
    return [v.detail for v in result.violations if v.kind is ViolationKind.FIRST_HOP_VIOLATION]


def test_fixture_carries_every_dev_framed_prompt_as_a_router_first_scenario(scenarios) -> None:
    routed = {
        s.user_prompt: s
        for s in scenarios
        if s.deterministic and s.expected_entry_skill == "using_sumo_qa"
    }
    missing = _DEV_FRAMED_PROMPTS - set(routed)
    assert not missing, f"dev-framed prompts without a router-first scenario: {sorted(missing)}"
    for prompt in _DEV_FRAMED_PROMPTS:
        assert "sumo_qa_deciding_approach" in routed[prompt].required_tool_calls


def test_fixture_carries_non_qa_development_controls(scenarios) -> None:
    """Adjacent development asks with no testing intent must forbid the router."""
    controls = [
        s
        for s in scenarios
        if s.deterministic
        and s.expected_entry_skill is None
        and "using_sumo_qa" in s.forbidden_tool_calls
        and s.id.startswith("DC")
    ]
    assert len(controls) >= 3, f"need >=3 non-QA development controls; got {len(controls)}"
    for control in controls:
        assert "sumo_qa_deciding_approach" in control.forbidden_tool_calls
        bypass = Transcript(control.id, (), "Here is the implementation.")
        assert validate_transcript(control, bypass).passed
        routed = Transcript(control.id, (ToolCall("using_sumo_qa"),), "")
        assert ViolationKind.FORBIDDEN_TOOL_CALLED in _kinds(validate_transcript(control, routed))


def test_dev_framed_answer_without_any_first_hop_fails(scenarios) -> None:
    """The original VS Code failure: QA advice for a dev-framed prompt with no
    sumo-qa workflow call at all."""
    for s in scenarios:
        if s.user_prompt not in _DEV_FRAMED_PROMPTS:
            continue
        bypass = Transcript(s.id, (), "You should add unit tests for the happy path and errors.")
        result = validate_transcript(s, bypass)
        assert not result.passed
        assert _first_hop_kinds(result), f"{s.id}: no first-hop violation on a bypass"


def test_catalogue_call_before_the_router_fails_first_hop(scenarios) -> None:
    """Loading a catalogue before `using_sumo_qa` is QA work before the first
    hop, even when the router fires afterwards."""
    s = next(s for s in scenarios if s.user_prompt in _DEV_FRAMED_PROMPTS)
    transcript = Transcript(
        s.id,
        (
            ToolCall("sumo_qa_load_techniques"),
            ToolCall("using_sumo_qa"),
            ToolCall("sumo_qa_deciding_approach"),
        ),
        "",
    )
    details = _first_hop_kinds(validate_transcript(s, transcript))
    assert details and "sumo_qa_load_techniques" in details[0]


def test_direct_specialist_entry_fails_first_hop(scenarios) -> None:
    """A specialist entered without the router chain (the direct-entry shape
    the pre-#247 fixtures accepted) is now a first-hop violation."""
    s = next(s for s in scenarios if s.id == "S02-review-before-merge")
    direct = Transcript(
        s.id,
        (
            ToolCall("sumo_qa_reviewing_before_merge"),
            ToolCall("sumo_qa_load_classifications"),
            ToolCall("sumo_qa_load_rules"),
        ),
        "verdict",
    )
    result = validate_transcript(s, direct)
    assert not result.passed
    assert _first_hop_kinds(result)


def test_router_without_decider_fails_first_hop(scenarios) -> None:
    """The router's mandatory handoff is the decider; skipping it to reach the
    specialist breaks the chain."""
    s = next(s for s in scenarios if s.id == "S02-review-before-merge")
    skipped = Transcript(
        s.id,
        (
            ToolCall("using_sumo_qa"),
            ToolCall("sumo_qa_reviewing_before_merge"),
            ToolCall("sumo_qa_load_classifications"),
            ToolCall("sumo_qa_load_rules"),
        ),
        "verdict",
    )
    details = _first_hop_kinds(validate_transcript(s, skipped))
    assert details and "sumo_qa_deciding_approach" in details[0]


def test_decider_after_the_specialist_fails_first_hop(scenarios) -> None:
    s = next(s for s in scenarios if s.id == "S02-review-before-merge")
    late = Transcript(
        s.id,
        (
            ToolCall("using_sumo_qa"),
            ToolCall("sumo_qa_reviewing_before_merge"),
            ToolCall("sumo_qa_deciding_approach"),
            ToolCall("sumo_qa_reviewing_before_merge"),
            ToolCall("sumo_qa_load_classifications"),
            ToolCall("sumo_qa_load_rules"),
        ),
        "verdict",
    )
    # A second specialist call after the decider does not repair the order the
    # specialist FIRST fired in.
    details = _first_hop_kinds(validate_transcript(s, late))
    assert details and "sumo_qa_reviewing_before_merge" in details[0]


def test_router_without_decider_fails_for_a_router_scenario(scenarios) -> None:
    """Even when the expected skill is the router itself, the decider must follow."""
    s = next(s for s in scenarios if s.id == "S11-router-invocation")
    only_router = Transcript(s.id, (ToolCall("using_sumo_qa"),), "")
    assert _first_hop_kinds(validate_transcript(s, only_router))


def test_unrouted_scenario_is_exempt_from_first_hop(scenarios) -> None:
    """Pure tool-selection scenarios (no expected entry skill) are not QA
    requests; the first-hop rule does not apply to them."""
    s = next(s for s in scenarios if s.id == "TS15-capabilities")
    result = validate_transcript(s, Transcript(s.id, (ToolCall("sumo_qa_capabilities"),), ""))
    assert result.passed
