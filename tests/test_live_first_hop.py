# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The live-host first-hop harness's offline half (issue #732).

`scripts/live_first_hop.py` turns `claude -p` stream-json into a conformance
transcript and assembles the report. The fixtures are real captures from the
harness's own run (claude-code 2.1.287, claude-haiku-4-5, D0x/DC0x set), never
invented ones: an invented stream validates the parser against an assumption
of the host's output, not the real contract. Where a test cuts or edits a
capture it says so and why. The captures' local paths and UUIDs (session,
message and task ids) are anonymised: user-identifying path prefixes become
`/tmp/live-first-hop/run/` and `/tmp/claude/`, and every UUID a placeholder
mapped one-to-one across the files; the event structure is unedited. No test
here runs the host: the billed side is replaced by stand-ins for
`install_build` and `subprocess.run`.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import subprocess
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
# A fake build's binary; compared as str(), so the separators are the platform's.
_BINARY = Path("/bin/sumo-qa")
SCENARIOS = {s.id: s for s in load_scenarios(harness.SCENARIOS)}
D03 = "D03-dev-framed-edge-cases"
D04 = "D04-dev-framed-failing-tests-first"
DC03 = "DC03-dev-naming"


def _run(fixture: str, scenario_id: str):
    """A capture parsed as a run that exited 0, as run_host records it."""
    text = (FIXTURES / f"{fixture}.jsonl").read_text(encoding="utf-8")
    run = harness.parse_stream(text, scenario_id)
    run.returncode = 0
    return run


def _with_result(fixture: str, **changes) -> str:
    """A real capture with only its result event edited. No real quota-stop or
    turn-limit capture exists, so these outcomes are written onto a real run."""
    lines = []
    for line in (FIXTURES / f"{fixture}.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("type") == "result":
            line = json.dumps({**event, **changes})
        lines.append(line)
    return "\n".join(lines)


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
        f"{D03} [mcp connected, success, exit 0]: ToolSearch -> Agent -> sub:ToolSearch -> "
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


def _guard_build_tools() -> list[dict]:
    """A build's tools/list with the real served names (the committed tools/list
    snapshot), not the capture's own pool, so a mismatch between the names the
    server serves and the names the CLI's pool lists fails the guard tests. The
    router unannotated, every other one a declared writer."""
    snapshot = REPO_ROOT / "tests" / "fixtures" / "mcp_tools_list_snapshot.json"
    names = json.loads(snapshot.read_text(encoding="utf-8"))["required_tools"]
    return [_tool(n) if n == "using_sumo_qa" else _tool(n, readOnlyHint=False) for n in names]


def _with_pools(*pools: list[str]) -> str:
    """The real guard capture with its init event repeated once per pool, each
    copy's `tools` replaced by that pool. Edited: no real capture has a second
    init event or a short pool."""
    first, *rest = (FIXTURES / "write-guard.jsonl").read_text(encoding="utf-8").splitlines()
    init = json.loads(first)
    return "\n".join([*(json.dumps({**init, "tools": pool}) for pool in pools), *rest])


def test_the_sandboxed_guard_captures_pool_is_exactly_the_allowlist_and_its_build():
    run = _run("write-guard", harness.WRITE_GUARD_ID)

    assert [t for t in run.tool_pool if not t.startswith("mcp__")] == [
        "Task",
        "Glob",
        "Grep",
        "Read",
        "ToolSearch",
    ]
    assert harness.missing_tools(run) == []
    assert harness.unexpected_tools(run, _guard_build_tools()) == []
    # A tool the build does not serve is not part of the sandbox either.
    assert harness.unexpected_tools(run, _guard_build_tools()[1:]) == [
        f"mcp__sumo-qa__{_guard_build_tools()[0]['name']}"
    ]


@pytest.mark.parametrize("required", harness.REQUIRED_POOL)
def test_a_pool_without_a_required_tool_names_it_missing(required):
    full = _run("write-guard", harness.WRITE_GUARD_ID).tool_pool
    run = harness.parse_stream(
        _with_pools([t for t in full if t != required]), harness.WRITE_GUARD_ID
    )

    assert harness.missing_tools(run) == [required]


def test_an_empty_pool_is_missing_every_required_tool():
    run = harness.parse_stream(_with_pools([]), harness.WRITE_GUARD_ID)

    assert harness.missing_tools(run) == list(harness.REQUIRED_POOL)
    assert harness.unexpected_tools(run, _guard_build_tools()) == []


def test_the_pool_is_the_union_of_every_init_event():
    full = _run("write-guard", harness.WRITE_GUARD_ID).tool_pool
    run = harness.parse_stream(_with_pools(list(full), ["Bash"]), harness.WRITE_GUARD_ID)

    assert run.tool_pool == (*full, "Bash")
    assert harness.unexpected_tools(run, _guard_build_tools()) == ["Bash"]


def test_a_name_repeated_inside_one_init_event_is_pooled_once():
    run = harness.parse_stream(_with_pools(["Read", "Read", "Grep"]), harness.WRITE_GUARD_ID)

    assert run.tool_pool == ("Read", "Grep")


def test_the_captures_carry_no_local_user_paths():
    for capture in FIXTURES.glob("*.jsonl"):
        text = capture.read_text(encoding="utf-8")
        assert not re.search(r"/Users/|/private/|/var/folders/|claude-\d+/", text), capture.name


def test_agent_named_as_itself_is_inside_the_sandbox():
    full = _run("write-guard", harness.WRITE_GUARD_ID).tool_pool
    pool = ["Agent" if t == "Task" else t for t in full]
    run = harness.parse_stream(_with_pools(pool), harness.WRITE_GUARD_ID)

    assert harness.missing_tools(run) == []
    assert harness.unexpected_tools(run, _guard_build_tools()) == []


def _with_statuses(*statuses: str | None) -> str:
    """The real guard capture with its init event repeated once per status,
    each copy listing sumo-qa with that status (None: not listed). Edited: no
    real capture has a second init event."""
    first, *rest = (FIXTURES / "write-guard.jsonl").read_text(encoding="utf-8").splitlines()
    init = json.loads(first)
    others = [s for s in init["mcp_servers"] if s.get("name") != harness.SERVER]
    inits = [
        {
            **init,
            "mcp_servers": others
            + ([] if st is None else [{"name": harness.SERVER, "status": st}]),
        }
        for st in statuses
    ]
    return "\n".join([*(json.dumps(i) for i in inits), *rest])


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (("connected", None), "connected"),
        (("connected", "failed"), "failed"),
        (("failed", "connected"), "connected"),
        ((None,), "absent"),
    ],
)
def test_the_mcp_status_is_the_last_init_event_that_lists_sumo_qa(statuses, expected):
    run = harness.parse_stream(_with_statuses(*statuses), harness.WRITE_GUARD_ID)

    assert run.started
    assert run.mcp_status == expected


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
    assert f"{D04} [mcp connected, success, exit 0]: " + " -> ".join(["ToolSearch"] * 9) in lines
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


# --------------------------------------------------------------------------- #
# Invalid runs are never scored                                               #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("changes", "outcome"),
    [
        ({"result": "Claude AI usage limit reached|1789400000"}, "usage limit"),
        ({"subtype": "error_max_turns", "is_error": True}, "error_max_turns (error)"),
        ({"subtype": "error_during_execution", "is_error": True}, "error_during_execution (error)"),
        ({"is_error": True}, "success (error)"),
    ],
)
def test_a_run_that_did_not_end_in_success_is_invalid_and_never_scored(changes, outcome):
    run = harness.parse_stream(_with_result("main-DC03-no-tool-calls", **changes), DC03)

    [result] = harness.score([SCENARIOS[DC03]], [run], frozenset())

    assert (run.outcome, run.valid) == (outcome, False)
    assert result.skipped
    assert "not scored (invalid run): DC03-dev-naming" in harness.render_build("b", [run], [result])


def _with_extra_result(fixture: str, first: dict) -> str:
    """Edited: a real capture with one more result event, `first`, put just
    before its own. No real multi-result capture exists; a background agent
    finishing after the main turn produces this shape."""
    lines = (FIXTURES / f"{fixture}.jsonl").read_text(encoding="utf-8").splitlines()
    result = json.loads(lines[-1])
    return "\n".join([*lines[:-1], json.dumps({**result, **first}), lines[-1]])


def test_a_failed_result_followed_by_a_success_is_invalid_and_keeps_both_texts():
    text = _with_extra_result(
        "main-DC03-no-tool-calls",
        {
            "subtype": "error_max_turns",
            "is_error": True,
            "result": "Classification: business_logic_change",
        },
    )

    run = harness.parse_stream(text, DC03)
    final = json.loads(text.splitlines()[-1])["result"]

    assert (run.outcome, run.valid) == ("error_max_turns (error)", False)
    assert run.transcript.output_text == f"Classification: business_logic_change\n{final}"


def test_a_usage_limit_in_any_result_marks_the_run():
    text = _with_extra_result(
        "main-DC03-no-tool-calls", {"result": "Claude AI usage limit reached|1789400000"}
    )

    assert harness.parse_stream(text, DC03).outcome == "usage limit"


def test_two_successful_results_are_a_success():
    text = _with_extra_result(
        "main-DC03-no-tool-calls", {"result": "The background agent finished."}
    )
    run = harness.parse_stream(text, DC03)
    run.returncode = 0

    assert (run.outcome, run.valid) == ("success", True)


def test_a_mis_route_is_judged_by_the_scored_builds_own_skills():
    # A route to a skill this checkout bundles but the scored build does not is
    # not a mis-route for that build, and the other way round.
    s01 = SCENARIOS["S01-preparing-for-work"]
    calls = ("using_sumo_qa", "sumo_qa_measuring_coverage", "sumo_qa_preparing_for_work")
    run = harness.HostRun(
        harness.Transcript(s01.id, tuple(harness.ToolCall(c, {}) for c in calls)),
        mcp_status="connected",
        outcome="success",
        returncode=0,
    )

    def routing(skills):
        [result] = harness.score([s01], [run], skills)
        return [v.detail for v in result.violations if v.kind.value == "wrong_skill_routing"]

    [checkout] = validate_all([s01], [run.transcript])
    assert "sumo_qa_measuring_coverage" in str(checkout.violations)
    assert routing(frozenset({"using_sumo_qa"})) == []
    assert routing(frozenset({"sumo_qa_measuring_coverage"})) == [
        "routed to 'sumo_qa_measuring_coverage' before the expected entry skill "
        "'sumo_qa_preparing_for_work'"
    ]


def test_a_non_json_line_mid_stream_is_counted_not_fatal():
    # Edited: a real capture with a non-JSON line put after its first event.
    lines = (FIXTURES / "main-DC03-no-tool-calls.jsonl").read_text(encoding="utf-8").splitlines()
    run = harness.parse_stream("\n".join([lines[0], "not json", *lines[1:]]), DC03)
    run.returncode = 0

    assert (run.outcome, run.valid, run.skipped_lines) == ("success", True, 1)
    assert "[mcp connected, success, exit 0, 1 non-JSON lines skipped]" == harness._status(run)


def test_a_run_with_no_observed_exit_code_is_invalid():
    text = (FIXTURES / "main-DC03-no-tool-calls.jsonl").read_text(encoding="utf-8")
    run = harness.parse_stream(text, DC03)

    assert (run.outcome, run.returncode, run.valid) == ("success", None, False)


def test_a_stream_with_no_result_event_is_invalid():
    # Cut: the real capture minus its last line, the result event.
    text = (FIXTURES / "main-DC03-no-tool-calls.jsonl").read_text(encoding="utf-8")
    run = harness.parse_stream("\n".join(text.splitlines()[:-1]), DC03)

    assert (run.outcome, run.valid) == ("no result", False)


def test_the_usage_limit_pattern_is_the_promptfoo_providers_own():
    provider = REPO_ROOT / "tests" / "evals" / "promptfoo" / "providers" / "claude_cli.py"

    assert harness.USAGE_LIMIT.pattern in provider.read_text(encoding="utf-8")


def test_a_timed_out_stream_cut_mid_character_parses_and_is_invalid():
    # Cut: a timeout returns partial stdout. This capture is cut one byte into a
    # three-byte em dash, so the last line is both undecodable and not JSON.
    raw = (FIXTURES / "main-D03-routed-through-subagents.jsonl").read_bytes()
    cut = raw.index("\u2014".encode()) + 1

    text = harness.decode(raw[:cut])
    run = harness.parse_stream(text, D03)

    assert text.endswith("\ufffd")
    assert (run.outcome, run.valid, run.skipped_lines) == ("truncated stream", False, 0)
    assert _tools(run)[:2] == ["ToolSearch", "Agent"]


def test_a_usage_limit_outranks_a_cut_off_final_line():
    # Edited: a real capture whose result is a quota stop, then a cut-off line.
    text = _with_result("write-guard", result="Claude AI usage limit reached|1789400000")

    run = harness.parse_stream(text + '\n{"type": "assist', harness.WRITE_GUARD_ID)

    assert (run.outcome, run.skipped_lines) == ("usage limit", 0)


def test_an_api_error_is_named_apart_from_a_turn_limit():
    run = harness.parse_stream(
        _with_result("write-guard", subtype="error_max_turns", is_error=True, api_error_status=529),
        harness.WRITE_GUARD_ID,
    )

    assert run.outcome == "error_max_turns (api error 529)"


# --------------------------------------------------------------------------- #
# The child's sandbox: tool allowlist and environment                         #
# --------------------------------------------------------------------------- #
def _flag(argv: list[str], name: str) -> list[str]:
    """The values after `name`, up to the next flag."""
    start = argv.index(name) + 1
    end = next((i for i in range(start, len(argv)) if argv[i].startswith("--")), len(argv))
    return argv[start:end]


def test_the_child_gets_only_the_allowlisted_host_tools_and_no_write_tools():
    argv = harness.host_argv({"mcpServers": {}}, "haiku", 15, ["mcp__sumo-qa__using_sumo_qa"])

    assert _flag(argv, "--allowedTools") == ["mcp__sumo-qa__using_sumo_qa"]
    assert _flag(argv, "--tools") == ["ToolSearch,Agent,Read,Glob,Grep"]
    assert _flag(argv, "--disallowedTools") == ["Bash", "Write", "Edit", "NotebookEdit"]
    assert _flag(argv, "--permission-mode") == ["default"]


def _tool(name, **annotations):
    return {"name": name, "annotations": annotations or None}


SKILL_TOOLS = frozenset({"sumo_qa_deciding_approach"})


@pytest.mark.parametrize(
    ("tool", "approved"),
    [
        (_tool("reader", readOnlyHint=True, openWorldHint=False), True),
        # A missing openWorldHint defaults to true in the MCP spec.
        (_tool("reader_no_world_hint", readOnlyHint=True), False),
        (_tool("using_sumo_qa"), True),
        (_tool("sumo_qa_deciding_approach"), True),
        # An unannotated tool that is neither the router nor a skill of this build,
        # as every writer is on a build that predates tool annotations.
        (_tool("sumo_qa_register_known_good_test_data"), False),
        (_tool("writer", readOnlyHint=False, openWorldHint=False), False),
        (_tool("downloader", readOnlyHint=True, openWorldHint=True), False),
        (_tool("unmarked_reader", openWorldHint=False), False),
    ],
)
def test_approval_follows_each_tools_own_annotations(tool, approved):
    assert harness.approved_tools([tool], SKILL_TOOLS) == (
        [f"mcp__sumo-qa__{tool['name']}"] if approved else []
    )


@pytest.mark.parametrize("name", sorted(harness.ALWAYS_REFUSED))
def test_installing_or_executing_an_external_skill_is_refused_whatever_its_annotations(name):
    skills = frozenset({name})
    assert (
        harness.approved_tools([_tool(name, readOnlyHint=True, openWorldHint=False)], skills) == []
    )
    assert harness.approved_tools([_tool(name)], skills) == []


def test_a_builds_skill_tools_come_from_the_skills_its_wheel_bundles(tmp_path):
    skills = tmp_path / "lib" / "python3.12" / "site-packages" / "sumo_qa" / "_data" / "skills"
    for name in ("using-sumo-qa", "sumo-qa-deciding-approach"):
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text("---\n---\n")
    (skills / "not-a-skill").mkdir()

    assert harness.build_skill_tools(tmp_path) == {"using_sumo_qa", "sumo_qa_deciding_approach"}
    assert harness.build_skill_tools(tmp_path / "missing") == frozenset()


def test_this_checkouts_served_annotations_approve_the_router_and_refuse_writers():
    # In-process: a spawned `python -m sumo_qa` would bypass mutmut's trampoline.
    from sumo_qa.server import build_mcp_server
    from sumo_qa.skill_prompts import _skills_dir

    tools = [
        t.model_dump(by_alias=True, exclude_none=True)
        for t in asyncio.run(build_mcp_server().list_tools())
    ]
    skills = frozenset(p.parent.name.replace("-", "_") for p in _skills_dir().glob("*/SKILL.md"))
    approved = {a.removeprefix("mcp__sumo-qa__") for a in harness.approved_tools(tools, skills)}
    writers = {t["name"] for t in tools if t.get("annotations", {}).get("readOnlyHint") is False}

    assert {
        "using_sumo_qa",
        "sumo_qa_deciding_approach",
        "sumo_qa_load_classifications",
    } <= approved
    assert writers and writers.isdisjoint(approved)
    assert {
        "sumo_qa_install_external_skill",
        "sumo_qa_execute_external_skill",
        "sumo_qa_search_external_skills",
    }.isdisjoint(approved)


# A stand-in server: answers initialize and tools/list over stdio, one line at a
# time, with a log line and a notification before each reply.
_FAKE_SERVER = """
import json, sys
for line in sys.stdin:
    m = json.loads(line)
    print("starting up", flush=True)
    print(json.dumps({"jsonrpc": "2.0", "method": "notifications/message"}), flush=True)
    if m.get("id") == 1:
        print(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}), flush=True)
    elif m.get("id") == 2:
        tools = [{"name": "using_sumo_qa"}]
        print(json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": tools}}), flush=True)
"""


def test_a_builds_tools_list_is_read_over_stdio(tmp_path):
    tools = harness.server_tools([sys.executable, "-c", _FAKE_SERVER], tmp_path / "home")

    assert tools == [{"name": "using_sumo_qa"}]


def test_a_server_that_exits_before_answering_is_an_error(tmp_path):
    # Reads the request first, so the write never races the exit.
    server = [sys.executable, "-c", "import sys; sys.stdin.readline()"]

    with pytest.raises(RuntimeError, match=r"python\S* exited before answering initialize"):
        harness.server_tools(server, tmp_path)


def test_a_stalled_server_times_out_and_is_killed(tmp_path, monkeypatch):
    started = []
    popen = subprocess.Popen

    def spy(*args, **kwargs):
        started.append(popen(*args, **kwargs))
        return started[-1]

    monkeypatch.setattr(harness.subprocess, "Popen", spy)
    server = [sys.executable, "-c", "import time; time.sleep(60)"]

    with pytest.raises(RuntimeError, match=r"did not answer within 0.5s"):
        harness.server_tools(server, tmp_path, timeout=0.5)
    assert started[0].poll() is not None


def test_an_error_envelope_names_the_method_and_the_error(tmp_path):
    server = """
import json, sys
m = json.loads(sys.stdin.readline())
print(json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "nope"}}),
      flush=True)
"""
    with pytest.raises(RuntimeError, match=r"answered initialize with .*'nope'"):
        harness.server_tools([sys.executable, "-c", server], tmp_path)


def test_a_failure_names_the_servers_last_output_lines(tmp_path):
    server = """
import sys
sys.stdin.readline()
for i in range(8):
    print(f"log {i}", flush=True)
print("startup note " + "x" * 500, flush=True)
"""
    with pytest.raises(RuntimeError) as exc:
        harness.server_tools([sys.executable, "-c", server], tmp_path)

    message = str(exc.value)
    assert "exited before answering initialize; last output:" in message
    assert "log 7" in message and "startup note" in message
    assert "log 3" not in message
    assert "x" * 201 not in message


def test_a_binary_that_cannot_start_is_an_error_naming_it(tmp_path):
    missing = str(tmp_path / "no-such-sumo-qa")

    with pytest.raises(RuntimeError, match=rf"^{re.escape(missing)} did not start: ") as exc:
        harness.server_tools([missing], tmp_path / "home")

    assert isinstance(exc.value.__cause__, FileNotFoundError)


def test_a_failure_reads_only_the_tail_of_a_long_stderr(tmp_path):
    # Far more stderr than the tail holds; the last lines must survive whole.
    server = (
        "import sys; sys.stdin.readline()\n"
        "for i in range(5000): print(f'noise line {i:05d}', file=sys.stderr)\n"
    )

    with pytest.raises(RuntimeError) as exc:
        harness.server_tools([sys.executable, "-c", server], tmp_path)

    message = str(exc.value)
    assert "'noise line 04999'" in message and "'noise line 04990'" in message
    assert "noise line 04989" not in message


def test_a_stderr_line_longer_than_the_tail_is_kept_truncated(tmp_path):
    server = "import sys; sys.stdin.readline(); sys.stderr.write('x' * 20000 + '\\n')"

    with pytest.raises(RuntimeError) as exc:
        harness.server_tools([sys.executable, "-c", server], tmp_path)

    assert str(exc.value).endswith("; last stderr: ['..." + "x" * 197 + "']")


def test_a_crash_names_the_traceback_the_server_wrote_to_stderr(tmp_path):
    # A real uncaught exception: Python writes its traceback to stderr and exits 1.
    server = "import sys; sys.stdin.readline(); import sumo_qa_no_such_module"

    with pytest.raises(RuntimeError) as exc:
        harness.server_tools([sys.executable, "-c", server], tmp_path)

    message = str(exc.value)
    assert "exited before answering initialize; last stderr:" in message
    assert "Traceback (most recent call last):" in message
    assert "ModuleNotFoundError: No module named 'sumo_qa_no_such_module'" in message
    assert "last output" not in message


def test_a_poisoned_parent_environment_does_not_reach_the_child():
    poison = {
        "CLAUDE_CODE_SUBAGENT_MODEL": "opus",
        "ANTHROPIC_MODEL": "opus",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "opus",
        "VERTEX_REGION_CLAUDE_HAIKU_4_5": "us-east5",
        "CLOUDSDK_CONFIG": "/gcloud",
        "SUMO_QA_DEBUG_DIR": "/elsewhere",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_SESSION_ID": "parent",
        "VIRTUAL_ENV": "/parent/.venv",
    }

    kept = {"PATH": "/bin", "HOME": "/home/u", "SYSTEMROOT": "C:\\Windows"}

    env = harness.child_env({**kept, **poison})

    assert env == {**kept, **harness.CHILD_ENV}


def test_network_and_backend_variables_reach_the_child():
    network = {
        "HTTPS_PROXY": "http://proxy:8080",
        "no_proxy": "localhost",
        "NODE_EXTRA_CA_CERTS": "/ca.pem",
        "CLAUDE_CONFIG_DIR": "/cfg",
        "ANTHROPIC_BASE_URL": "https://gateway",
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "AWS_REGION": "eu-west-2",
        "CLAUDE_CODE_USE_VERTEX": "1",
        "ANTHROPIC_VERTEX_PROJECT_ID": "p",
        "CLOUD_ML_REGION": "global",
        "ANTHROPIC_BEDROCK_BASE_URL": "https://bedrock",
        "ANTHROPIC_VERTEX_BASE_URL": "https://vertex",
        # The AWS credential chain on EKS (web identity, Pod Identity), ECS and EC2.
        "AWS_ROLE_ARN": "arn:aws:iam::1:role/r",
        "AWS_WEB_IDENTITY_TOKEN_FILE": "/var/run/secrets/token",
        "AWS_ROLE_SESSION_NAME": "s",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/v2/credentials/x",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI": "http://169.254.170.23/v1/credentials",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN": "t",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE": "/var/run/secrets/pod-identity/token",
        "AWS_EC2_METADATA_DISABLED": "false",
        "AWS_EC2_METADATA_SERVICE_ENDPOINT": "http://169.254.169.254",
        "AWS_EC2_METADATA_SERVICE_ENDPOINT_MODE": "IPv4",
        "AWS_EC2_METADATA_V1_DISABLED": "true",
        # The backend's alias mapping and gcloud config, passed only with a backend set.
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "us.anthropic.claude-haiku-4-5",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "s",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "o",
        "VERTEX_REGION_CLAUDE_HAIKU_4_5": "us-east5",
        "CLOUDSDK_CONFIG": "/gcloud",
    }

    env = harness.child_env({**network, "ANTHROPIC_MODEL": "opus"})

    assert env == {**network, **harness.CHILD_ENV}


@pytest.mark.parametrize("switch", ["CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"])
@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "On"])
def test_either_backend_switch_alone_passes_the_alias_mapping(switch, value):
    env = harness.child_env({switch: value, "ANTHROPIC_DEFAULT_HAIKU_MODEL": "h"})

    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "h"


@pytest.mark.parametrize("switch", ["CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"])
@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_a_backend_switch_turned_off_keeps_the_model_override_out(switch, value):
    # The CLI reads these as off and uses the first-party API, where an
    # ANTHROPIC_DEFAULT_*_MODEL would override the model under test.
    env = harness.child_env({switch: value, "ANTHROPIC_DEFAULT_HAIKU_MODEL": "opus"})

    assert "ANTHROPIC_DEFAULT_HAIKU_MODEL" not in env


def _fake_cli(monkeypatch, *, stdout=b"", stderr=b"", returncode=0, timeout=False):
    seen = {}

    def run(argv, **kwargs):
        seen.update(kwargs, argv=argv)
        if timeout:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=stdout, stderr=stderr)
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    monkeypatch.setattr(harness.subprocess, "run", run)
    return seen


def test_a_host_run_keeps_stderr_and_reports_its_exit_code(tmp_path, monkeypatch):
    stdout = (FIXTURES / "main-DC03-no-tool-calls.jsonl").read_bytes()
    monkeypatch.setenv("SUMO_QA_DEBUG_DIR", "/elsewhere")
    seen = _fake_cli(monkeypatch, stdout=stdout, stderr=b"warning: x\r\n", returncode=1)

    run = harness.run_host(_BINARY, [], DC03, "p", "haiku", tmp_path, 15, 60)

    assert "SUMO_QA_DEBUG_DIR" not in seen["env"]
    assert (tmp_path / f"{DC03}.stderr").read_bytes() == b"warning: x\r\n"
    assert (tmp_path / f"{DC03}.jsonl").read_bytes() == stdout
    assert (run.returncode, run.valid) == (1, False)
    assert f"{DC03} [mcp connected, success, exit 1]: (no tool calls)" in harness.render_build(
        "b", [run], harness.score([SCENARIOS[DC03]], [run], frozenset())
    )


def test_a_timed_out_host_run_returns_its_partial_stream_as_invalid(tmp_path, monkeypatch):
    # Cut: a timeout returns partial stdout; here the capture minus its result line.
    lines = (FIXTURES / "main-DC03-no-tool-calls.jsonl").read_bytes().splitlines(keepends=True)
    _fake_cli(monkeypatch, stdout=b"".join(lines[:-1]), timeout=True)

    run = harness.run_host(_BINARY, [], DC03, "p", "haiku", tmp_path, 15, 60)

    assert (run.returncode, run.outcome, run.valid) == (None, "timeout", False)
    assert "[mcp connected, timeout, no exit code]" in harness._status(run)


def test_same_named_wheels_get_labels_that_tell_them_apart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(harness, "_run", lambda argv: "")

    labels = [
        harness.install_build(str(Path(d, "sumo_qa-1-py3-none-any.whl")), tmp_path / d / "w")[1]
        for d in ("before", "after")
    ]

    assert labels == [
        str(Path("before", "sumo_qa-1-py3-none-any.whl")),
        str(Path("after", "sumo_qa-1-py3-none-any.whl")),
    ]


def test_an_annotated_tag_resolves_to_its_commit_not_the_tag_object(tmp_path, monkeypatch):
    # A git hook exports GIT_DIR; inherited, it would point git at the real repo.
    for name in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(name)

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", *args],
            capture_output=True, text=True, check=True,
        ).stdout.strip()  # fmt: skip

    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "c")
    git("tag", "-a", "v1", "-m", "annotated")
    monkeypatch.setattr(harness, "REPO_ROOT", tmp_path)

    assert harness.commit_sha("v1") == git("rev-parse", "--short", "HEAD")
    assert harness.commit_sha("v1") != git("rev-parse", "--short", "v1")


# --------------------------------------------------------------------------- #
# main: order of work and exit codes                                          #
# --------------------------------------------------------------------------- #
class _Host:
    """Stands in for install_build, server_tools and run_host; records the
    order of work."""

    def __init__(self, monkeypatch, runs: dict[str, harness.HostRun], breach: bool = False):
        self.log: list[str] = []
        self.runs = runs
        self.breach = breach
        self.install_dirs: list[Path] = []
        monkeypatch.setattr(harness, "install_build", self.install)
        monkeypatch.setattr(harness, "run_host", self.run)
        monkeypatch.setattr(harness, "server_tools", self.tools)

    def install(self, spec, workdir):
        self.log.append(f"install {spec}")
        self.install_dirs.append(workdir)
        workdir.mkdir(parents=True)
        return _BINARY, spec

    def tools(self, command, home):
        self.log.append(f"tools/list {command[0]}")
        return _guard_build_tools()

    def run(self, binary, approved, scenario_id, prompt, model, run_dir, max_turns, timeout):
        assert approved == ["mcp__sumo-qa__using_sumo_qa"]
        self.log.append(f"run {scenario_id}")
        if scenario_id == harness.WRITE_GUARD_ID and self.breach:
            (run_dir.parent / harness.GUARD_SENTINEL).write_text("buy milk")
        return self.runs[scenario_id]


def _guard(**result):
    """The real guard capture, a sandboxed run whose model searched for a write
    tool and delegated to subagents, optionally with its result event edited."""
    run = harness.parse_stream(_with_result("write-guard", **result), harness.WRITE_GUARD_ID)
    run.returncode = 0
    return run


def test_every_build_installs_then_each_guard_runs_before_any_scenario(tmp_path, monkeypatch):
    host = _Host(
        monkeypatch, {harness.WRITE_GUARD_ID: _guard(), DC03: _run("main-DC03-no-tool-calls", DC03)}
    )

    code = harness.main(["a.whl", "b.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert code == 0
    assert host.log == [
        "install a.whl",
        f"tools/list {_BINARY}",
        "install b.whl",
        f"tools/list {_BINARY}",
        f"run {harness.WRITE_GUARD_ID}",
        f"run {harness.WRITE_GUARD_ID}",
        f"run {DC03}",
        f"run {DC03}",
    ]


def test_a_breached_guard_stops_before_any_scenario_with_its_own_exit_code(tmp_path, monkeypatch):
    host = _Host(monkeypatch, {harness.WRITE_GUARD_ID: _guard()}, breach=True)

    code = harness.main(["a.whl", "b.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert code == harness.EXIT_BREACH == 3
    assert host.log[-1] == f"run {harness.WRITE_GUARD_ID}"
    assert host.log.count(f"run {harness.WRITE_GUARD_ID}") == 1


def test_a_guard_whose_mcp_did_not_connect_stops_before_any_scenario(tmp_path, monkeypatch):
    guard = _guard()
    guard.mcp_status = "failed"
    host = _Host(monkeypatch, {harness.WRITE_GUARD_ID: guard})

    code = harness.main(["a.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert code == harness.EXIT_INVALID == 4
    assert host.log[-1] == f"run {harness.WRITE_GUARD_ID}"


def test_a_guard_stopped_before_its_init_event_stops_before_any_scenario(
    tmp_path, monkeypatch, capsys
):
    # Edited: a usage limit before init leaves no init event, so no pool.
    text = _with_result("write-guard", result="Claude AI usage limit reached|1789400000")
    guard = harness.parse_stream("\n".join(text.splitlines()[1:]), harness.WRITE_GUARD_ID)
    assert (guard.started, guard.tool_pool, guard.outcome) == (False, (), "usage limit")
    guard.returncode = 1
    host = _Host(monkeypatch, {harness.WRITE_GUARD_ID: guard})

    code = harness.main(["a.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert code == harness.EXIT_INVALID == 4
    assert host.log[-1] == f"run {harness.WRITE_GUARD_ID}"
    captured = capsys.readouterr()
    assert "NOT PROVEN, no file" in captured.out
    assert (
        "guard run ended before the host started (no init event): usage limit; no scenario was run"
    ) in captured.err


def test_a_guard_that_hit_a_usage_limit_stops_before_any_scenario(tmp_path, monkeypatch, capsys):
    # Edited: the real guard capture, started and connected, with a quota stop
    # as its result.
    guard = _guard(result="Claude AI usage limit reached|1789400000")
    assert (guard.started, guard.mcp_status, guard.outcome) == (True, "connected", "usage limit")
    host = _Host(monkeypatch, {harness.WRITE_GUARD_ID: guard})

    code = harness.main(["a.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert code == harness.EXIT_INVALID == 4
    assert host.log[-1] == f"run {harness.WRITE_GUARD_ID}"
    assert (
        "guard run hit a usage limit (usage limit reached|1789400000); no scenario was run"
    ) in capsys.readouterr().err


def test_a_guard_whose_pool_lacks_the_router_stops(tmp_path, monkeypatch, capsys):
    required = "mcp__sumo-qa__using_sumo_qa"
    full = _guard().tool_pool
    guard = harness.parse_stream(
        _with_pools([t for t in full if t != required]), harness.WRITE_GUARD_ID
    )
    guard.returncode = 0
    host = _Host(monkeypatch, {harness.WRITE_GUARD_ID: guard})

    code = harness.main(["a.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert code == harness.EXIT_INVALID
    assert host.log[-1] == f"run {harness.WRITE_GUARD_ID}"
    assert f"sandbox not proven: host tool pool missing {required};" in capsys.readouterr().err


@pytest.mark.parametrize("dropped", ["ToolSearch", "Read"])
def test_a_guard_whose_pool_lacks_a_host_tool_still_passes(tmp_path, monkeypatch, dropped):
    # Edited: the CLI drops ToolSearch behind a gateway (a non-first-party
    # ANTHROPIC_BASE_URL); a smaller pool is still inside the sandbox.
    guard = harness.parse_stream(
        _with_pools([t for t in _guard().tool_pool if t != dropped]), harness.WRITE_GUARD_ID
    )
    guard.returncode = 0
    host = _Host(
        monkeypatch, {harness.WRITE_GUARD_ID: guard, DC03: _run("main-DC03-no-tool-calls", DC03)}
    )

    code = harness.main(["a.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert code == 0
    assert host.log[-1] == f"run {DC03}"


@pytest.mark.parametrize("is_error", [True, False])
def test_a_guard_that_hit_its_turn_limit_with_the_sandbox_held_still_passes(
    tmp_path, monkeypatch, capsys, is_error
):
    guard = _guard(subtype="error_max_turns", is_error=is_error)
    assert guard.outcome == ("error_max_turns (error)" if is_error else "error_max_turns")
    guard.returncode = 1
    host = _Host(
        monkeypatch, {harness.WRITE_GUARD_ID: guard, DC03: _run("main-DC03-no-tool-calls", DC03)}
    )

    code = harness.main(["a.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert code == 0
    assert host.log[-1] == f"run {DC03}"
    out = capsys.readouterr().out.splitlines()
    assert f"== write guard (a.whl): PASS, no file at {tmp_path / 'o'}" in "\n".join(out)
    assert "host tool pool: Task, Glob, Grep, Read, ToolSearch + 48 sumo-qa tools" in out
    assert "write-guard [mcp connected, error_max_turns" in next(
        line for line in out if line.startswith("write-guard [")
    )
    assert (
        "tool calls (informational): ToolSearch -> ToolSearch -> Agent -> sub:ToolSearch -> "
        "sub:ToolSearch -> sub:Agent -> sub:ToolSearch -> sub:ToolSearch -> sub:ToolSearch"
    ) in "\n".join(out)
    assert next(line for line in out if line.startswith("refused sumo-qa tools: ")).startswith(
        "refused sumo-qa tools: sumo_qa_analyze_diff_impact, "
    )


@pytest.mark.parametrize("injected", ["Bash", "Write", "mcp__other__write_file"])
def test_a_guard_whose_pool_holds_a_tool_outside_the_sandbox_stops(
    tmp_path, monkeypatch, capsys, injected
):
    # Edited: the real guard capture with one write-capable tool added to its
    # init event's tool pool.
    lines = (FIXTURES / "write-guard.jsonl").read_text(encoding="utf-8").splitlines()
    init = json.loads(lines[0])
    init["tools"].append(injected)
    guard = harness.parse_stream("\n".join([json.dumps(init), *lines[1:]]), harness.WRITE_GUARD_ID)
    guard.returncode = 0
    host = _Host(monkeypatch, {harness.WRITE_GUARD_ID: guard})

    code = harness.main(["a.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert code == harness.EXIT_INVALID == 4
    assert host.log[-1] == f"run {harness.WRITE_GUARD_ID}"
    captured = capsys.readouterr()
    assert "NOT PROVEN, no file" in captured.out
    assert "PASS" not in captured.out
    assert f"sandbox not proven: {injected} in the host tool pool" in captured.err


def test_a_quota_stopped_scenario_makes_the_run_invalid_not_a_regression(
    tmp_path, monkeypatch, capsys
):
    stopped = harness.parse_stream(
        _with_result("main-DC03-no-tool-calls", result="Claude AI usage limit reached|1789400000"),
        DC03,
    )
    _Host(monkeypatch, {harness.WRITE_GUARD_ID: _guard(), DC03: stopped})

    code = harness.main(["a.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert code == harness.EXIT_INVALID
    out = capsys.readouterr().out.splitlines()
    assert f"SKIP {DC03} (provider-backed or no transcript)" in out
    assert f"not scored (invalid run): {DC03}" in out


def test_only_matching_no_scenario_errors_before_anything_is_built(tmp_path, monkeypatch):
    host = _Host(monkeypatch, {})

    with pytest.raises(SystemExit) as exc:
        harness.main(["a.whl", "--only", "NOPE", "--out", str(tmp_path / "o")])

    assert exc.value.code == 2
    assert host.log == []


def test_an_invalid_only_regex_is_a_usage_error_before_anything_is_built(
    tmp_path, monkeypatch, capsys
):
    host = _Host(monkeypatch, {})

    with pytest.raises(SystemExit) as exc:
        harness.main(["a.whl", "--only", "D(0", "--out", str(tmp_path / "o")])

    assert exc.value.code == 2
    assert "--only 'D(0' is not a valid regex" in capsys.readouterr().err
    assert host.log == []


def test_a_non_empty_out_dir_is_refused_before_anything_is_built(tmp_path, monkeypatch, capsys):
    (tmp_path / "o").mkdir()
    (tmp_path / "o" / "report.txt").write_text("old")
    host = _Host(monkeypatch, {})

    with pytest.raises(SystemExit):
        harness.main(["a.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert "is not empty" in capsys.readouterr().err
    assert host.log == []


def test_an_out_path_that_is_a_file_is_refused_before_anything_is_built(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "o").write_text("a file")
    host = _Host(monkeypatch, {})

    with pytest.raises(SystemExit) as exc:
        harness.main(["a.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert exc.value.code == 2
    assert "is a file" in capsys.readouterr().err
    assert host.log == []


def test_a_relative_out_dir_is_resolved_before_use(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host = _Host(
        monkeypatch, {harness.WRITE_GUARD_ID: _guard(), DC03: _run("main-DC03-no-tool-calls", DC03)}
    )

    assert harness.main(["a.whl", "--only", DC03, "--out", "run"]) == 0
    assert host.install_dirs == [tmp_path.resolve() / "run" / "build-0"]
