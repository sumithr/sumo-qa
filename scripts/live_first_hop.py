#!/usr/bin/env python3
# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Live-host first-hop harness: score real host tool selection (issue #732).

Runs each deterministic conformance scenario's `user_prompt` through a real
host (`claude -p`) that has only the sumo-qa MCP server of a named build
attached, turns the host's stream-json into a conformance `Transcript`, and
scores it with `validate_all` / `format_report` from `sumo_qa.conformance`.
Give two builds for a before/after comparison on the same prompts.

Manual, never in PR CI: every prompt is a billed host run. See
tests/scenarios/CONFORMANCE.md "Running it" for usage and cost.

Each build is clean-installed from a wheel into its own temp venv (a git ref is
archived and built first). The child host runs in a throwaway cwd with
`--strict-mcp-config`, no settings sources (so no user hooks or plugins), no
skills, no CLAUDE.md or auto-memory, and `--disallowedTools Bash Write Edit
NotebookEdit` (`--allowedTools` alone does not stop those) plus the host tools
that act outside the cwd (cron, remote triggers, worktrees). The MCP server's
HOME points into the run dir, so sumo-qa's own writes stay there too. A write
guard control prompt asks the host to create a file outside its scratch dir and
fails the run if the file appears.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sumo_qa.conformance import (
    ConformanceScenario,
    ScenarioResult,
    ToolCall,
    Transcript,
    format_report,
    load_scenarios,
    validate_all,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = REPO_ROOT / "tests" / "scenarios" / "conformance" / "scenarios.yaml"
HOST = "claude-code"
SERVER = "sumo-qa"
DISALLOWED_TOOLS = (
    "Bash",
    "Write",
    "Edit",
    "NotebookEdit",
    "CronCreate",
    "CronDelete",
    "RemoteTrigger",
    "ScheduleWakeup",
    "EnterWorktree",
)
WRITE_GUARD_ID = "write-guard"
WRITE_GUARD_PROMPT = "Create the file {path} containing the single word pwned."
CHILD_ENV = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}


@dataclass
class HostRun:
    """One prompt's host run: what the host reported about itself, plus the
    transcript the validator scores."""

    transcript: Transcript
    host_version: str = "unknown"
    model: str = "unknown"
    mcp_status: str = "absent"
    outcome: str = "no result"
    # One flag per transcript call: True when a subagent made it. The validator
    # scores every call alike; the report marks these so a delegated first hop
    # is visible.
    from_subagent: tuple[bool, ...] = ()


def normalise_tool_name(name: str) -> str:
    """`mcp__<server>__<tool>` -> `<tool>`; host tools keep their own name."""
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) == 3:
            return parts[2]
    return name


def parse_stream(text: str, scenario_id: str) -> HostRun:
    """Turn `claude -p --output-format stream-json --verbose` stdout into a
    HostRun. Tool calls keep the order the host made them in."""
    calls: list[ToolCall] = []
    nested: list[bool] = []
    run = HostRun(Transcript(scenario_id, ()))
    output = ""
    for line in text.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            run.host_version = event.get("claude_code_version", "unknown")
            run.model = event.get("model", "unknown")
            servers = {s.get("name"): s.get("status") for s in event.get("mcp_servers", [])}
            run.mcp_status = servers.get(SERVER) or "absent"
        elif kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    calls.append(
                        ToolCall(normalise_tool_name(block["name"]), block.get("input") or {})
                    )
                    nested.append(event.get("parent_tool_use_id") is not None)
        elif kind == "result":
            run.outcome = event.get("subtype", "unknown")
            output = event.get("result") or ""
    run.transcript = Transcript(scenario_id, tuple(calls), output)
    run.from_subagent = tuple(nested)
    return run


def render_build(label: str, runs: list[HostRun], results: list[ScenarioResult]) -> str:
    """One build's report: host identity, the ordered tool calls per prompt,
    then the validator's PASS/FAIL/SKIP table."""
    hosts = sorted({f"{HOST} {r.host_version}" for r in runs}) or [f"{HOST} unknown"]
    models = sorted({r.model for r in runs}) or ["unknown"]
    lines = [f"== build: {label}", f"host: {', '.join(hosts)}", f"model: {', '.join(models)}"]
    for run in runs:
        calls = " -> ".join(
            f"sub:{c.tool}" if sub else c.tool
            for c, sub in zip(run.transcript.tool_calls, run.from_subagent, strict=True)
        )
        calls = calls or "(no tool calls)"
        lines.append(f"{run.transcript.scenario_id} [mcp {run.mcp_status}, {run.outcome}]: {calls}")
    lines += ["", format_report(results)]
    return "\n".join(lines)


def render_comparison(before: list[ScenarioResult], after: list[ScenarioResult]) -> str:
    """Per-scenario verdict before -> after, for the same prompts."""
    after_by_id = {r.scenario_id: r for r in after}
    lines = ["== before -> after"]
    for result in before:
        lines.append(
            f"{result.scenario_id}: {_verdict(result)} -> "
            f"{_verdict(after_by_id.get(result.scenario_id))}"
        )
    return "\n".join(lines)


def _verdict(result: ScenarioResult | None) -> str:
    if result is None or result.skipped:
        return "SKIP"
    return "PASS" if result.passed else "FAIL"


def select_scenarios(path: Path, only: str | None) -> list[ConformanceScenario]:
    """Every deterministic scenario with a prompt, narrowed by an id regex."""
    return [
        s
        for s in load_scenarios(path)
        if s.deterministic and s.user_prompt and (only is None or re.match(only, s.id))
    ]


# --------------------------------------------------------------------------- #
# Live side: builds and host runs (not unit-tested; this is the billed part)  #
# --------------------------------------------------------------------------- #
def install_build(spec: str, workdir: Path) -> tuple[Path, str]:
    """Clean-install a build (a `.whl` path or a git ref) into its own venv.
    Returns the `sumo-qa` binary and a label naming the build."""
    workdir.mkdir(parents=True)
    if spec.endswith(".whl"):
        wheel, label = Path(spec).resolve(), Path(spec).name
    else:
        sha = _run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", spec]).strip()
        src = workdir / "src"
        src.mkdir()
        archive = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "archive", spec], capture_output=True, check=True
        ).stdout
        subprocess.run(["tar", "-x", "-C", str(src)], input=archive, check=True)
        _run(["uv", "build", "--wheel", "--out-dir", str(workdir / "dist"), str(src)])
        wheel, label = next((workdir / "dist").glob("*.whl")), f"{spec} ({sha})"
    _run(["uv", "venv", "--quiet", str(workdir / "venv")])
    _run(
        [
            "uv",
            "pip",
            "install",
            "--quiet",
            "--python",
            str(workdir / "venv/bin/python"),
            str(wheel),
        ]
    )
    return workdir / "venv" / "bin" / "sumo-qa", label


def run_host(binary: Path, prompt: str, model: str, cwd: Path, max_turns: int, timeout: int) -> str:
    """One `claude -p` run with only this build's sumo-qa attached. Returns
    the raw stream-json stdout (partial on timeout)."""
    cwd.mkdir(parents=True)
    server_home = cwd.parent / f"{cwd.name}-server-home"
    server_home.mkdir()
    config = {
        "mcpServers": {
            SERVER: {
                "command": str(binary),
                "args": [],
                "env": {"HOME": str(server_home), "XDG_DATA_HOME": str(server_home)},
            }
        }
    }
    argv = [
        "claude", "-p",
        "--model", model,
        "--output-format", "stream-json", "--verbose",
        "--strict-mcp-config", "--mcp-config", json.dumps(config),
        "--setting-sources", "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--max-turns", str(max_turns),
        "--allowedTools", f"mcp__{SERVER}",
        "--disallowedTools", *DISALLOWED_TOOLS,
    ]  # fmt: skip
    env = {**os.environ, **CHILD_ENV}
    try:
        done = subprocess.run(
            argv, input=prompt, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
        )
        return done.stdout
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        return out.decode() if isinstance(out, bytes) else out


def _run(argv: list[str]) -> str:
    # stderr is left on the terminal so a failed build or install says why.
    return subprocess.run(argv, stdout=subprocess.PIPE, text=True, check=True).stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("build", help="build to score: a git ref or a .whl path")
    parser.add_argument("after", nargs="?", help="second build for a before/after comparison")
    parser.add_argument(
        "--model", default="haiku", help="host model (default: haiku, the weakest candidate)"
    )
    parser.add_argument("--only", help="regex on scenario ids, e.g. 'DC?0' for the D0x/DC0x set")
    parser.add_argument("--out", type=Path, help="run dir for venvs, cwds and raw captures")
    parser.add_argument("--max-turns", type=int, default=15)
    parser.add_argument("--timeout", type=int, default=600, help="seconds per host run")
    args = parser.parse_args(argv)

    out = args.out or Path(tempfile.mkdtemp(prefix="live-first-hop-"))
    scenarios = select_scenarios(SCENARIOS, args.only)
    sections: list[str] = []
    all_results: list[list[ScenarioResult]] = []
    environment_ok = True
    first_binary: Path | None = None
    for index, spec in enumerate(s for s in (args.build, args.after) if s):
        build_dir = out / f"build-{index}"
        binary, label = install_build(spec, build_dir)
        first_binary = first_binary or binary
        runs = []
        for scenario in scenarios:
            stdout = run_host(
                binary, scenario.user_prompt, args.model, build_dir / "cwd" / scenario.id,
                args.max_turns, args.timeout,
            )  # fmt: skip
            (build_dir / f"{scenario.id}.jsonl").write_text(stdout, encoding="utf-8")
            run = parse_stream(stdout, scenario.id)
            environment_ok &= run.mcp_status == "connected"
            runs.append(run)
        results = validate_all(scenarios, [r.transcript for r in runs])
        all_results.append(results)
        sections.append(render_build(label, runs, results))
    if len(all_results) == 2:
        sections.append(render_comparison(*all_results))

    assert first_binary is not None
    guard_dir = out / "write-guard"
    sentinel = guard_dir / "outside" / "pwned.txt"
    sentinel.parent.mkdir(parents=True)
    stdout = run_host(
        first_binary, WRITE_GUARD_PROMPT.format(path=sentinel), args.model, guard_dir / "cwd",
        args.max_turns, args.timeout,
    )  # fmt: skip
    (guard_dir / "write-guard.jsonl").write_text(stdout, encoding="utf-8")
    guard = parse_stream(stdout, WRITE_GUARD_ID)
    breached = sentinel.exists()
    calls = " -> ".join(c.tool for c in guard.transcript.tool_calls) or "(no tool calls)"
    sections.append(
        f"== write guard: {'FAIL, file written' if breached else 'PASS, no file'} at {sentinel}\n"
        f"{WRITE_GUARD_ID} [mcp {guard.mcp_status}, {guard.outcome}]: {calls}"
    )
    report = "\n\n".join(sections)
    (out / "report.txt").write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\nraw captures: {out}")
    if breached:
        return 1
    if not environment_ok:
        print(
            "sumo-qa MCP server did not connect on every run; scores are not valid", file=sys.stderr
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
