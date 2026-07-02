# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Deterministic cross-model conformance validator (issue #214).

Proves the transcript validator (src/sumo_qa/conformance.py) scores captured
host/tool-call transcripts against the machine-readable fixtures WITHOUT a live
LLM call, and that it FAILS a bad transcript on each of the four contract axes
the acceptance criteria name: missing required tool call, wrong skill routing,
forbidden tool call, and forbidden output claim.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sumo_qa.conformance import (
    ConformanceScenario,
    ScenarioResult,
    ToolCall,
    Transcript,
    ViolationKind,
    format_report,
    load_scenarios,
    transcript_from_debug_dir,
    validate_all,
    validate_transcript,
)
from sumo_qa.debug_capture import maybe_capture
from sumo_qa.server import build_mcp_server

_FIXTURE = Path(__file__).parent / "scenarios" / "conformance" / "scenarios.yaml"
_SCENARIOS_DIR = Path(__file__).parent / "scenarios"

# The five scenario families the AC explicitly requires to be represented.
_REQUIRED_FAMILIES = {
    "S02-review-before-merge",
    "S03-regression-first",
    "S07-find-test-data",
    "S10-no-tests-needed",
    "TS15-capabilities",
}


@pytest.fixture(scope="module")
def scenarios() -> list[ConformanceScenario]:
    return load_scenarios(_FIXTURE)


def _known_entry_skills(scenarios: list[ConformanceScenario]) -> frozenset[str]:
    return frozenset(s.expected_entry_skill for s in scenarios if s.expected_entry_skill)


def _good_transcript(s: ConformanceScenario) -> Transcript:
    """A transcript that satisfies every clause of the scenario's contract."""
    calls: list[ToolCall] = []
    if s.expected_entry_skill:
        calls.append(ToolCall(s.expected_entry_skill))
    calls.extend(ToolCall(t) for t in s.required_tool_calls)
    output = " ".join(s.required_output_markers) + " ...clean senior-QA output..."
    return Transcript(scenario_id=s.id, tool_calls=tuple(calls), output_text=output)


# --------------------------------------------------------------------------- #
# Fixture integrity                                                           #
# --------------------------------------------------------------------------- #
def test_fixture_has_at_least_eight_deterministic_scenarios(scenarios) -> None:
    deterministic = [s for s in scenarios if s.deterministic]
    assert len(deterministic) >= 8, (
        f"AC requires >=8 deterministic scenarios; got {len(deterministic)}"
    )


def test_fixture_represents_the_required_five_families(scenarios) -> None:
    ids = {s.id for s in scenarios}
    missing = _REQUIRED_FAMILIES - ids
    assert not missing, f"required scenario families missing from the fixture: {sorted(missing)}"


def test_fixture_ids_are_unique(scenarios) -> None:
    ids = [s.id for s in scenarios]
    assert len(ids) == len(set(ids))


def test_fixture_only_references_registered_tools(scenarios) -> None:
    """Every tool name a fixture pins must be a real registered MCP tool.

    Ties the fixtures to the live tool surface so a tool rename fails here
    rather than letting a stale contract pass vacuously (non-goal: no duplicate
    source of truth that drifts from the registered surface)."""
    registered = set(build_mcp_server()._tool_manager._tools)
    for s in scenarios:
        referenced = set(s.required_tool_calls) | set(s.forbidden_tool_calls)
        if s.expected_entry_skill:
            referenced.add(s.expected_entry_skill)
        unknown = referenced - registered
        assert not unknown, f"{s.id} references unregistered tools: {sorted(unknown)}"


def test_fixture_source_headings_resolve_in_their_catalogue(scenarios) -> None:
    """Each row's source_heading must still appear in its catalogue doc.

    Anti-drift guard: if a SCENARIOS.md / TOOL-SELECTION.md heading is renamed,
    the fixture row seeded from it must be re-pointed in the same change."""
    cache: dict[str, str] = {}
    for s in scenarios:
        text = cache.get(s.source_doc)
        if text is None:
            text = (_SCENARIOS_DIR / s.source_doc).read_text(encoding="utf-8")
            cache[s.source_doc] = text
        assert s.source_heading in text, (
            f"{s.id}: source_heading {s.source_heading!r} no longer resolves in "
            f"{s.source_doc}; re-point the fixture row at the renamed heading."
        )


# --------------------------------------------------------------------------- #
# Parsing edge cases                                                          #
# --------------------------------------------------------------------------- #
def test_load_scenarios_rejects_unknown_mode(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "scenarios:\n"
        "  - id: X\n"
        "    source_doc: SCENARIOS.md\n"
        "    source_heading: h\n"
        "    user_prompt: p\n"
        "    mode: sometimes\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="mode"):
        load_scenarios(bad)


def test_load_scenarios_rejects_duplicate_ids(tmp_path) -> None:
    dup = tmp_path / "dup.yaml"
    dup.write_text(
        "scenarios:\n"
        "  - id: X\n"
        "    source_doc: SCENARIOS.md\n"
        "    source_heading: h\n"
        "    user_prompt: p\n"
        "    mode: deterministic\n"
        "  - id: X\n"
        "    source_doc: SCENARIOS.md\n"
        "    source_heading: h\n"
        "    user_prompt: p\n"
        "    mode: deterministic\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        load_scenarios(dup)


# --------------------------------------------------------------------------- #
# Good-path: every deterministic scenario passes on a compliant transcript    #
# --------------------------------------------------------------------------- #
def test_every_deterministic_scenario_passes_a_compliant_transcript(scenarios) -> None:
    known = _known_entry_skills(scenarios)
    for s in scenarios:
        if not s.deterministic:
            continue
        result = validate_transcript(s, _good_transcript(s), known)
        assert result.passed, f"{s.id} unexpectedly failed: {result.violations}"


def test_router_prefixed_transcript_still_routes_cleanly(scenarios) -> None:
    """A destination-skill transcript legitimately prefixed by the router/decider
    passes (router tools before the entry skill are not a mis-route)."""
    known = _known_entry_skills(scenarios)
    s = next(s for s in scenarios if s.id == "S02-review-before-merge")
    transcript = Transcript(
        scenario_id=s.id,
        tool_calls=(
            ToolCall("sumo_qa_deciding_approach"),
            ToolCall("sumo_qa_reviewing_before_merge"),
            ToolCall("sumo_qa_load_classifications"),
            ToolCall("sumo_qa_load_rules"),
        ),
        output_text="scope + verdict, no leaked taxonomy",
    )
    assert validate_transcript(s, transcript, known).passed


# --------------------------------------------------------------------------- #
# Bad-path: one synthetic bad transcript per contract axis (AC #3, #6)        #
# --------------------------------------------------------------------------- #
def _kinds(result: ScenarioResult) -> set[ViolationKind]:
    return {v.kind for v in result.violations}


def test_catches_missing_required_tool_call(scenarios) -> None:
    known = _known_entry_skills(scenarios)
    s = next(s for s in scenarios if s.id == "S02-review-before-merge")
    # Routed correctly, but never loaded the classifications/rules catalogues.
    bad = Transcript(s.id, (ToolCall("sumo_qa_reviewing_before_merge"),), "verdict")
    result = validate_transcript(s, bad, known)
    assert not result.passed
    assert ViolationKind.MISSING_REQUIRED_TOOL in _kinds(result)


def test_catches_wrong_skill_routing_absent_expected(scenarios) -> None:
    known = _known_entry_skills(scenarios)
    s = next(s for s in scenarios if s.id == "S02-review-before-merge")
    # Routed to prep, never to review.
    bad = Transcript(s.id, (ToolCall("sumo_qa_preparing_for_work"),), "")
    result = validate_transcript(s, bad, known)
    assert ViolationKind.WRONG_SKILL_ROUTING in _kinds(result)


def test_catches_wrong_skill_routing_wrong_destination_first(scenarios) -> None:
    known = _known_entry_skills(scenarios)
    s = next(s for s in scenarios if s.id == "S02-review-before-merge")
    # A different destination skill fires before the expected one.
    bad = Transcript(
        s.id,
        (
            ToolCall("sumo_qa_preparing_for_work"),
            ToolCall("sumo_qa_reviewing_before_merge"),
            ToolCall("sumo_qa_load_classifications"),
            ToolCall("sumo_qa_load_rules"),
        ),
        "",
    )
    result = validate_transcript(s, bad, known)
    assert ViolationKind.WRONG_SKILL_ROUTING in _kinds(result)


def test_catches_forbidden_tool_call(scenarios) -> None:
    known = _known_entry_skills(scenarios)
    s = next(s for s in scenarios if s.id == "S07-find-test-data")
    # Silently registered a known-good entry on a plain find.
    bad = Transcript(
        s.id,
        (
            ToolCall("sumo_qa_finding_test_data"),
            ToolCall("sumo_qa_find_test_data"),
            ToolCall("sumo_qa_register_known_good_test_data"),
        ),
        "found a fresh entry",
    )
    result = validate_transcript(s, bad, known)
    assert ViolationKind.FORBIDDEN_TOOL_CALLED in _kinds(result)


def test_catches_forbidden_output_claim(scenarios) -> None:
    known = _known_entry_skills(scenarios)
    s = next(s for s in scenarios if s.id == "S10-no-tests-needed")
    # Leaks the internal taxonomy label verbatim into the user-facing output.
    bad = Transcript(
        s.id,
        (ToolCall("sumo_qa_deciding_approach"),),
        "Classification: docs_change, Approach: no-tests-recommended",
    )
    result = validate_transcript(s, bad, known)
    assert ViolationKind.FORBIDDEN_OUTPUT_MARKER in _kinds(result)


def test_catches_missing_required_output_marker() -> None:
    """The validator also flags an absent required output marker (ad-hoc
    scenario — no fixture row pins one, but the axis must work)."""
    s = ConformanceScenario(
        id="AD-HOC",
        source_doc="SCENARIOS.md",
        source_heading="x",
        user_prompt="p",
        mode="deterministic",
        required_output_markers=("SAFE TO MERGE",),
    )
    bad = Transcript(s.id, (), "no verdict here")
    result = validate_transcript(s, bad, frozenset())
    assert ViolationKind.MISSING_OUTPUT_MARKER in _kinds(result)


# --------------------------------------------------------------------------- #
# Provider-backed scenarios are deferred, not scored                          #
# --------------------------------------------------------------------------- #
def test_provider_backed_scenario_is_skipped(scenarios) -> None:
    s = next(s for s in scenarios if s.id == "S08-strategising-quality")
    assert not s.deterministic
    # Even a blatantly non-compliant transcript is not scored deterministically.
    result = validate_transcript(s, Transcript(s.id, (), ""), frozenset())
    assert result.skipped and not result.violations


# --------------------------------------------------------------------------- #
# Batch validation + compact report                                          #
# --------------------------------------------------------------------------- #
def test_validate_all_and_report(scenarios) -> None:
    # Provide a good transcript for one scenario, a bad one for another, none
    # for a third (deterministic, no transcript -> skipped) and let the
    # provider-backed one defer.
    review = next(s for s in scenarios if s.id == "S02-review-before-merge")
    caps = next(s for s in scenarios if s.id == "TS15-capabilities")
    transcripts = [
        _good_transcript(caps),  # PASS
        Transcript(review.id, (ToolCall("sumo_qa_reviewing_before_merge"),), ""),  # FAIL
    ]
    results = validate_all(scenarios, transcripts)
    by_id = {r.scenario_id: r for r in results}
    assert by_id["TS15-capabilities"].passed
    assert not by_id["S02-review-before-merge"].passed
    assert by_id["S08-strategising-quality"].skipped  # provider-backed
    assert by_id["S03-regression-first"].skipped  # deterministic, no transcript

    report = format_report(results)
    assert "PASS TS15-capabilities" in report
    assert "FAIL S02-review-before-merge" in report
    assert "SKIP S08-strategising-quality" in report
    assert "missing_required_tool" in report
    # Summary line reflects the mix.
    assert "passed" in report and "failed" in report and "skipped" in report


# --------------------------------------------------------------------------- #
# Bridge from the SUMO_QA_DEBUG_DIR capture format to a scored transcript     #
# --------------------------------------------------------------------------- #
def test_transcript_from_debug_dir_validates_a_captured_run(
    scenarios, tmp_path, monkeypatch
) -> None:
    """A run captured by debug_capture.maybe_capture reconstructs into a
    transcript the validator can score (the manual test-plan step)."""
    monkeypatch.setenv("SUMO_QA_DEBUG_DIR", str(tmp_path))
    maybe_capture(tool="sumo_qa_capabilities", args={"q": "what can you do"}, output={"ok": True})

    caps = next(s for s in scenarios if s.id == "TS15-capabilities")
    transcript = transcript_from_debug_dir(
        tmp_path, scenario_id=caps.id, output_text="review changes, regression-first fix, ..."
    )
    assert any(tc.tool == "sumo_qa_capabilities" for tc in transcript.tool_calls)
    result = validate_transcript(caps, transcript, _known_entry_skills(scenarios))
    assert result.passed


def test_transcript_from_debug_dir_parses_all_run_dir_shapes(tmp_path, monkeypatch) -> None:
    """Collision-suffixed, missing-input, and non-timestamped dirs all parse;
    stray files in the debug dir are ignored."""
    # Two same-timestamp captures -> the second gets a "-1" collision suffix.
    fixed_ts = "20260702-120000"
    monkeypatch.setenv("SUMO_QA_DEBUG_DIR", str(tmp_path))
    monkeypatch.setattr(time, "strftime", lambda _fmt: fixed_ts)
    maybe_capture(tool="sumo_qa_load_rules", args={"classification": "docs_change"}, output={})
    maybe_capture(tool="sumo_qa_load_rules", args={"classification": "docs_change"}, output={})

    # A run dir with no input.json -> args default to {}.
    (tmp_path / "20260702-130000-sumo_qa_load_principles").mkdir()
    # A non-timestamped dir name -> falls back to the whole name as the tool.
    (tmp_path / "malformeddir").mkdir()
    # A stray file at the top level is not a run dir and must be ignored.
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")

    transcript = transcript_from_debug_dir(tmp_path, scenario_id="probe")
    tools = sorted(tc.tool for tc in transcript.tool_calls)
    # Collision suffix stripped -> two identical load_rules names.
    assert tools.count("sumo_qa_load_rules") == 2
    assert "sumo_qa_load_principles" in tools
    assert "malformeddir" in tools
    assert "notes.txt" not in tools
    # The missing-input dir carries empty args; a real capture carries its args.
    load_rules = [tc for tc in transcript.tool_calls if tc.tool == "sumo_qa_load_rules"]
    assert all(tc.args == {"classification": "docs_change"} for tc in load_rules)
    principles = next(tc for tc in transcript.tool_calls if tc.tool == "sumo_qa_load_principles")
    assert principles.args == {}
