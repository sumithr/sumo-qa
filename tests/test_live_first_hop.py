# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The live-host first-hop harness's offline half (issue #732).

`scripts/live_first_hop.py` turns `claude -p` stream-json into a conformance
transcript and assembles the report. The fixtures are real captures from the
harness's own run (claude-code 2.1.287, claude-haiku-4-5, D0x/DC0x set), never
invented ones: an invented stream validates the parser against an assumption
of the host's output, not the real contract. Where a test cuts or edits a
capture it says so and why. No test here runs the host: the billed side is
replaced by stand-ins for `install_build` and `subprocess.run`.
"""

from __future__ import annotations

import importlib.util
import json
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
SCENARIOS = {s.id: s for s in load_scenarios(harness.SCENARIOS)}
D03 = "D03-dev-framed-edge-cases"
D04 = "D04-dev-framed-failing-tests-first"
DC03 = "DC03-dev-naming"


def _run(fixture: str, scenario_id: str):
    text = (FIXTURES / f"{fixture}.jsonl").read_text(encoding="utf-8")
    return harness.parse_stream(text, scenario_id)


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


def test_the_write_guard_capture_keeps_the_write_attempt_the_host_refused():
    run = _run("write-guard", harness.WRITE_GUARD_ID)
    events = [
        json.loads(line)
        for line in (FIXTURES / "write-guard.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    [use] = [
        block
        for e in events
        if e["type"] == "assistant"
        for block in e["message"]["content"]
        if block.get("type") == "tool_use"
    ]
    [reply] = [
        block
        for e in events
        if e["type"] == "user"
        for block in e["message"]["content"]
        if block.get("tool_use_id") == use["id"]
    ]

    [call] = run.transcript.tool_calls
    assert call.tool == "Write"
    assert call.args["file_path"].endswith("/write-guard/outside/pwned.txt")
    assert reply["is_error"] is True
    assert "No such tool available: Write" in reply["content"]


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

    [result] = harness.score([SCENARIOS[DC03]], [run])

    assert (run.outcome, run.valid) == (outcome, False)
    assert result.skipped
    assert "not scored (invalid run): DC03-dev-naming" in harness.render_build("b", [run], [result])


def test_a_stream_with_no_result_event_is_invalid():
    # Cut: the real capture minus its last line, the result event.
    text = (FIXTURES / "main-DC03-no-tool-calls.jsonl").read_text(encoding="utf-8")
    run = harness.parse_stream("\n".join(text.splitlines()[:-1]), DC03)

    assert (run.outcome, run.valid) == ("no result", False)


def test_the_usage_limit_pattern_is_the_promptfoo_providers_own():
    provider = REPO_ROOT / "tests" / "evals" / "promptfoo" / "providers" / "claude_cli.py"

    assert harness.USAGE_LIMIT.pattern in provider.read_text(encoding="utf-8")
    assert "re.compile" not in Path(harness.__file__).read_text(encoding="utf-8")


def test_a_timed_out_stream_cut_mid_character_parses_and_is_invalid():
    # Cut: a timeout returns partial stdout. This capture is cut one byte into a
    # three-byte em dash, so the last line is both undecodable and not JSON.
    raw = (FIXTURES / "main-D03-routed-through-subagents.jsonl").read_bytes()
    cut = raw.index("\u2014".encode()) + 1

    text = harness.decode(raw[:cut])
    run = harness.parse_stream(text, D03)

    assert text.endswith("\ufffd")
    assert (run.outcome, run.valid) == ("truncated stream", False)
    assert _tools(run)[:2] == ["ToolSearch", "Agent"]


# --------------------------------------------------------------------------- #
# The child's sandbox: tool allowlist and environment                         #
# --------------------------------------------------------------------------- #
def _flag(argv: list[str], name: str) -> list[str]:
    """The values after `name`, up to the next flag."""
    start = argv.index(name) + 1
    end = next((i for i in range(start, len(argv)) if argv[i].startswith("--")), len(argv))
    return argv[start:end]


def test_the_child_gets_only_the_allowlisted_host_tools_and_no_write_tools():
    argv = harness.host_argv({"mcpServers": {}}, "haiku", 15)

    assert _flag(argv, "--tools") == ["ToolSearch,Agent,Read,Glob,Grep"]
    assert _flag(argv, "--disallowedTools") == ["Bash", "Write", "Edit", "NotebookEdit"]
    assert _flag(argv, "--permission-mode") == ["default"]


def test_only_sumo_qa_read_tools_are_pre_approved_and_writers_stay_visible_but_refused():
    approved = _flag(harness.host_argv({"mcpServers": {}}, "haiku", 15), "--allowedTools")
    snapshot = json.loads(harness.TOOLS_SNAPSHOT.read_text(encoding="utf-8"))["required_tools"]

    assert "mcp__sumo-qa" not in approved
    assert {"mcp__sumo-qa__using_sumo_qa", "mcp__sumo-qa__sumo_qa_deciding_approach"} <= set(
        approved
    )
    assert {
        "mcp__sumo-qa__sumo_qa_install_external_skill",
        "mcp__sumo-qa__sumo_qa_execute_external_skill",
    }.isdisjoint(approved)
    assert harness.REFUSED_SUMO_QA_TOOLS <= set(snapshot)
    assert len(approved) == len(snapshot) - len(harness.REFUSED_SUMO_QA_TOOLS)


def test_every_tool_the_server_marks_as_a_writer_is_refused():
    source = (REPO_ROOT / "src" / "sumo_qa" / "server.py").read_text(encoding="utf-8")
    writers = set(re.findall(r"@mcp\.tool\(annotations=_writer_\w+\)\s+def (\w+)", source))

    assert writers
    assert writers <= harness.REFUSED_SUMO_QA_TOOLS


def test_a_poisoned_parent_environment_does_not_reach_the_child():
    poison = {
        "CLAUDE_CODE_SUBAGENT_MODEL": "opus",
        "ANTHROPIC_MODEL": "opus",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "opus",
        "SUMO_QA_DEBUG_DIR": "/elsewhere",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_SESSION_ID": "parent",
        "VIRTUAL_ENV": "/parent/.venv",
    }

    env = harness.child_env({"PATH": "/bin", "HOME": "/home/u", **poison})

    assert env == {"PATH": "/bin", "HOME": "/home/u", **harness.CHILD_ENV}


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
    seen = _fake_cli(monkeypatch, stdout=stdout, stderr=b"warning: x\n", returncode=1)

    run = harness.run_host(Path("/bin/sumo-qa"), DC03, "p", "haiku", tmp_path, 15, 60)

    assert "SUMO_QA_DEBUG_DIR" not in seen["env"]
    assert (tmp_path / f"{DC03}.stderr").read_text(encoding="utf-8") == "warning: x\n"
    assert (tmp_path / f"{DC03}.jsonl").read_bytes() == stdout
    assert (run.returncode, run.valid) == (1, False)
    assert f"{DC03} [mcp connected, success, exit 1]: (no tool calls)" in harness.render_build(
        "b", [run], harness.score([SCENARIOS[DC03]], [run])
    )


def test_a_timed_out_host_run_returns_its_partial_stream_as_invalid(tmp_path, monkeypatch):
    # Cut: a timeout returns partial stdout; here the capture minus its result line.
    lines = (FIXTURES / "main-DC03-no-tool-calls.jsonl").read_bytes().splitlines(keepends=True)
    _fake_cli(monkeypatch, stdout=b"".join(lines[:-1]), timeout=True)

    run = harness.run_host(Path("/bin/sumo-qa"), DC03, "p", "haiku", tmp_path, 15, 60)

    assert (run.returncode, run.outcome, run.valid) == (None, "no result", False)
    assert "[mcp connected, no result, timeout]" in harness._status(run)


# --------------------------------------------------------------------------- #
# main: order of work and exit codes                                          #
# --------------------------------------------------------------------------- #
class _Host:
    """Stands in for install_build and run_host; records the order of work."""

    def __init__(self, monkeypatch, runs: dict[str, harness.HostRun], breach: bool = False):
        self.log: list[str] = []
        self.runs = runs
        self.breach = breach
        self.install_dirs: list[Path] = []
        monkeypatch.setattr(harness, "install_build", self.install)
        monkeypatch.setattr(harness, "run_host", self.run)

    def install(self, spec, workdir):
        self.log.append(f"install {spec}")
        self.install_dirs.append(workdir)
        workdir.mkdir(parents=True)
        return Path("/bin/sumo-qa"), spec

    def run(self, binary, scenario_id, prompt, model, run_dir, max_turns, timeout):
        self.log.append(f"run {scenario_id}")
        if scenario_id == harness.WRITE_GUARD_ID and self.breach:
            (run_dir / "outside" / "pwned.txt").write_text("pwned")
        return self.runs[scenario_id]


def _guard():
    return _run("write-guard", harness.WRITE_GUARD_ID)


def test_every_build_installs_then_each_guard_runs_before_any_scenario(tmp_path, monkeypatch):
    host = _Host(
        monkeypatch, {harness.WRITE_GUARD_ID: _guard(), DC03: _run("main-DC03-no-tool-calls", DC03)}
    )

    code = harness.main(["a.whl", "b.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert code == 0
    assert host.log == [
        "install a.whl",
        "install b.whl",
        f"run {harness.WRITE_GUARD_ID}",
        f"run {harness.WRITE_GUARD_ID}",
        f"run {DC03}",
        f"run {DC03}",
    ]


def test_a_breached_guard_stops_before_any_scenario_with_its_own_exit_code(tmp_path, monkeypatch):
    host = _Host(monkeypatch, {harness.WRITE_GUARD_ID: _guard()}, breach=True)

    code = harness.main(["a.whl", "b.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert code == harness.EXIT_BREACH == 3
    assert host.log == ["install a.whl", "install b.whl", f"run {harness.WRITE_GUARD_ID}"]


def test_a_guard_whose_mcp_did_not_connect_stops_before_any_scenario(tmp_path, monkeypatch):
    guard = _guard()
    guard.mcp_status = "failed"
    host = _Host(monkeypatch, {harness.WRITE_GUARD_ID: guard})

    code = harness.main(["a.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert code == harness.EXIT_INVALID == 2
    assert host.log == ["install a.whl", f"run {harness.WRITE_GUARD_ID}"]


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


def test_a_non_empty_out_dir_is_refused_before_anything_is_built(tmp_path, monkeypatch, capsys):
    (tmp_path / "o").mkdir()
    (tmp_path / "o" / "report.txt").write_text("old")
    host = _Host(monkeypatch, {})

    with pytest.raises(SystemExit):
        harness.main(["a.whl", "--only", DC03, "--out", str(tmp_path / "o")])

    assert "is not empty" in capsys.readouterr().err
    assert host.log == []


def test_a_relative_out_dir_is_resolved_before_use(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    host = _Host(
        monkeypatch, {harness.WRITE_GUARD_ID: _guard(), DC03: _run("main-DC03-no-tool-calls", DC03)}
    )

    assert harness.main(["a.whl", "--only", DC03, "--out", "run"]) == 0
    assert host.install_dirs == [tmp_path.resolve() / "run" / "build-0"]
