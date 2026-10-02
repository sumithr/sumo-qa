# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The live-host first-hop harness's offline half (issue #732).

`scripts/live_first_hop.py` turns `claude -p` stream-json into a conformance
transcript and assembles the report. The fixtures are real captures from the
harness's own run (claude-code 2.1.287, claude-haiku-4-5, D0x/DC0x set), never
invented ones: an invented stream validates the parser against an assumption
of the host's output, not the real contract. No test here runs the host.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from sumo_qa.conformance import load_scenarios, validate_all

REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "live_first_hop", REPO_ROOT / "scripts" / "live_first_hop.py"
)
harness = importlib.util.module_from_spec(_spec)
# Registered before exec: @dataclass resolves the module's annotations through sys.modules.
sys.modules[_spec.name] = harness
_spec.loader.exec_module(harness)

FIXTURES = Path(__file__).parent / "fixtures" / "live_first_hop"
SCENARIOS = {s.id: s for s in load_scenarios(harness.SCENARIOS)}
D03 = "D03-dev-framed-edge-cases"
D04 = "D04-dev-framed-failing-tests-first"
DC03 = "DC03-dev-naming"


def _run(fixture: str, scenario_id: str):
    text = (FIXTURES / f"{fixture}.jsonl").read_text(encoding="utf-8")
    return harness.parse_stream(text, scenario_id)


def _tools(run) -> list[str]:
    return [call.tool for call in run.transcript.tool_calls]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("mcp__sumo-qa__using_sumo_qa", "using_sumo_qa"),
        ("mcp__sumo-qa__sumo_qa_deciding_approach", "sumo_qa_deciding_approach"),
        ("ToolSearch", "ToolSearch"),
        ("mcp__no-tool-part", "mcp__no-tool-part"),
    ],
)
def test_host_namespaced_names_lose_only_the_server_prefix(name, expected):
    assert harness.normalise_tool_name(name) == expected


def test_a_capture_yields_every_call_in_host_order_with_bare_sumo_qa_names():
    run = _run("main-D03-routed-through-subagents", D03)

    assert _tools(run) == [
        "ToolSearch",
        "Agent",
        "ToolSearch",
        "using_sumo_qa",
        "sumo_qa_deciding_approach",
        "SendMessage",
        "Agent",
        "ToolSearch",
        "ToolSearch",
        "using_sumo_qa",
        "sumo_qa_deciding_approach",
        "ToolSearch",
        "sumo_qa_load_classifications",
        "sumo_qa_load_approaches",
    ]
    assert run.transcript.output_text.startswith("The QA framework needs one detail:")


def test_the_host_identity_comes_from_the_init_and_result_events():
    run = _run("main-D03-routed-through-subagents", D03)

    assert (run.host_version, run.model, run.mcp_status, run.outcome) == (
        "2.1.287",
        "claude-haiku-4-5-20251001",
        "connected",
        "success",
    )


def test_calls_a_subagent_made_are_marked_in_the_report():
    run = _run("main-D03-routed-through-subagents", D03)

    report = harness.render_build(
        "origin/main", [run], validate_all([SCENARIOS[D03]], [run.transcript])
    )

    assert (
        f"{D03} [mcp connected, success]: ToolSearch -> Agent -> sub:ToolSearch -> "
        "sub:using_sumo_qa -> sub:sumo_qa_deciding_approach -> SendMessage -> Agent -> "
        "sub:ToolSearch -> sub:ToolSearch -> sub:using_sumo_qa -> "
        "sub:sumo_qa_deciding_approach -> sub:ToolSearch -> "
        "sub:sumo_qa_load_classifications -> sub:sumo_qa_load_approaches"
    ) in report.splitlines()


def test_a_toolsearch_loop_that_never_calls_the_router_fails_the_first_hop():
    run = _run("branch-D04-toolsearch-loop", D04)

    [result] = validate_all([SCENARIOS[D04]], [run.transcript])

    assert _tools(run) == ["ToolSearch"] * 9
    assert "first_hop_violation" in {v.kind.value for v in result.violations}


def test_a_control_answered_without_tools_passes():
    run = _run("main-DC03-no-tool-calls", DC03)

    [result] = validate_all([SCENARIOS[DC03]], [run.transcript])

    assert run.transcript.tool_calls == ()
    assert result.passed


def test_the_write_guard_capture_keeps_the_refused_write_attempt():
    run = _run("write-guard", harness.WRITE_GUARD_ID)

    [call] = run.transcript.tool_calls
    assert call.tool == "Write"
    assert call.args["file_path"].endswith("/write-guard/outside/pwned.txt")


def test_a_build_report_names_host_model_calls_and_the_validator_table():
    runs = [
        _run("main-D03-routed-through-subagents", D03),
        _run("branch-D04-toolsearch-loop", D04),
    ]
    results = validate_all([SCENARIOS[D03], SCENARIOS[D04]], [r.transcript for r in runs])

    lines = harness.render_build("branch.whl", runs, results).splitlines()

    assert lines[:3] == [
        "== build: branch.whl",
        "host: claude-code 2.1.287",
        "model: claude-haiku-4-5-20251001",
    ]
    assert f"{D04} [mcp connected, success]: " + " -> ".join(["ToolSearch"] * 9) in lines
    assert f"PASS {D03}" in lines
    assert f"FAIL {D04}" in lines
    assert lines[-1] == "1 passed, 1 failed, 0 skipped"


def test_the_comparison_reads_each_scenario_before_then_after():
    d03 = _run("main-D03-routed-through-subagents", D03)
    d04 = _run("branch-D04-toolsearch-loop", D04)
    scenarios = [SCENARIOS[D03], SCENARIOS[D04]]
    before = validate_all(
        scenarios, [d03.transcript, harness.Transcript(D04, d03.transcript.tool_calls)]
    )
    after = validate_all(scenarios, [d04.transcript])

    assert harness.render_comparison(before, after).splitlines() == [
        "== before -> after",
        f"{D03}: PASS -> SKIP",
        f"{D04}: PASS -> FAIL",
    ]


def test_selection_keeps_deterministic_prompts_narrowed_by_id_regex():
    narrowed = harness.select_scenarios(harness.SCENARIOS, "DC?0")
    everything = harness.select_scenarios(harness.SCENARIOS, None)

    assert [s.id for s in narrowed] == [
        "D01-dev-framed-how-to-test",
        "D02-dev-framed-what-tests",
        "D03-dev-framed-edge-cases",
        "D04-dev-framed-failing-tests-first",
        "DC01-dev-implementation-only",
        "DC02-dev-logging",
        "DC03-dev-naming",
        "DC04-dev-formatting",
    ]
    assert [s.id for s in everything] == [
        s.id for s in SCENARIOS.values() if s.deterministic and s.user_prompt
    ]
    assert "S08-strategising-quality" not in {s.id for s in everything}
