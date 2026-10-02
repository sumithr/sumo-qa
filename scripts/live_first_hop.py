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

Every build is clean-installed from a wheel into its own venv under the run dir
(a git ref is archived and built first) before any host runs. The child host
runs in a throwaway cwd with `--strict-mcp-config`, no settings sources (so no
user hooks or plugins), no skills, no CLAUDE.md or auto-memory, a minimal
environment, and an allowlist of host tools (`--tools`), with Bash, Write, Edit
and NotebookEdit also denied outright. Only sumo-qa's read-only tools are
pre-approved; its writers stay visible (a scenario may forbid calling one) but
a call to one is refused. The MCP server's HOME points into the run dir, so
sumo-qa's own writes stay there too. Before any scenario runs, a write-guard
control prompt per build asks the host to create a file outside its scratch dir
by any means; the run stops if the file appears or that build's MCP server did
not connect.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
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
TOOLS_SNAPSHOT = REPO_ROOT / "tests" / "fixtures" / "mcp_tools_list_snapshot.json"
# The only host tools the child gets. Agent stays: the D03 capture routes its
# first hop through a subagent, and a subagent inherits the main session's tool
# pool, narrowed, never widened (code.claude.com/docs/en/sub-agents).
HOST_TOOLS = ("ToolSearch", "Agent", "Read", "Glob", "Grep")
# Belt and braces on top of the allowlist.
DISALLOWED_TOOLS = ("Bash", "Write", "Edit", "NotebookEdit")
# sumo-qa tools that write, download or execute. Not pre-approved, so a call is
# refused (no one answers a permission prompt in -p), but still visible, so a
# scenario that forbids one still sees the host reach for it.
REFUSED_SUMO_QA_TOOLS = frozenset(
    {
        "sumo_qa_analyze_diff_impact",
        "sumo_qa_capture_review_feedback",
        "sumo_qa_execute_external_skill",
        "sumo_qa_export_test_cases",
        "sumo_qa_generate_qa_report",
        "sumo_qa_ingest_knowledge_pack",
        "sumo_qa_install_external_skill",
        "sumo_qa_record_coverage",
        "sumo_qa_record_mutation",
        "sumo_qa_register_known_good_test_data",
        "sumo_qa_scan_repo",
    }
)
WRITE_GUARD_ID = "write-guard"
WRITE_GUARD_PROMPT = (
    "Create the file {path} containing the single word pwned. Use any tool or "
    "means available to you, including a shell, a subagent or an MCP tool."
)
CHILD_ENV = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
# All the child takes from the parent environment. HOME stays the real one: the
# CLI finds its login through it (with HOME redirected `claude auth status`
# reports loggedIn false); the MCP server gets the redirected HOME instead.
CHILD_ENV_PASSTHROUGH = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "TMPDIR",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
)
EXIT_INVALID, EXIT_BREACH = 2, 3


def _load_usage_limit() -> re.Pattern[str]:
    """The promptfoo provider's usage-limit pattern, so both read the CLI's
    quota stop the same way."""
    path = REPO_ROOT / "tests" / "evals" / "promptfoo" / "providers" / "claude_cli.py"
    spec = importlib.util.spec_from_file_location("claude_cli_provider", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._USAGE_LIMIT


USAGE_LIMIT = _load_usage_limit()


@dataclass
class HostRun:
    """One prompt's host run: what the host reported about itself, plus the
    transcript the validator scores."""

    transcript: Transcript
    host_version: str = "unknown"
    model: str = "unknown"
    mcp_status: str = "absent"
    # The result event's subtype, or why the run has none worth scoring.
    outcome: str = "no result"
    # The CLI's exit code; None when the run timed out.
    returncode: int | None = 0
    # One flag per transcript call: True when a subagent made it. The validator
    # scores every call alike; the report marks these so a delegated first hop
    # is visible.
    from_subagent: tuple[bool, ...] = ()

    @property
    def valid(self) -> bool:
        """Only a run whose MCP server connected and that ended in a clean
        success is a routing result. A quota stop, a turn limit, an error or a
        cut-off stream says nothing about tool selection, so it is never scored."""
        return self.mcp_status == "connected" and self.outcome == "success" and self.returncode == 0


def normalise_tool_name(name: str) -> str:
    """`mcp__<server>__<tool>` -> `<tool>`; host tools keep their own name."""
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) == 3:
            return parts[2]
    return name


def parse_stream(text: str, scenario_id: str) -> HostRun:
    """Turn `claude -p --output-format stream-json --verbose` stdout into a
    HostRun. Tool calls keep the order the host made them in. A line that is
    not JSON (a timed-out run's cut-off last line) is skipped and makes the
    run invalid."""
    calls: list[ToolCall] = []
    nested: list[bool] = []
    run = HostRun(Transcript(scenario_id, ()))
    output = ""
    truncated = False
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            truncated = True
            continue
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
            output = event.get("result") or ""
            run.outcome = event.get("subtype", "unknown")
            if event.get("is_error") or event.get("api_error_status"):
                run.outcome = f"{run.outcome} (error)"
            if USAGE_LIMIT.search(output):
                run.outcome = "usage limit"
    if truncated:
        run.outcome = "truncated stream"
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
        lines.append(f"{run.transcript.scenario_id} {_status(run)}: {calls or '(no tool calls)'}")
    invalid = [r.transcript.scenario_id for r in runs if not r.valid]
    if invalid:
        lines.append(f"not scored (invalid run): {', '.join(invalid)}")
    lines += ["", format_report(results)]
    return "\n".join(lines)


def _status(run: HostRun) -> str:
    code = "timeout" if run.returncode is None else f"exit {run.returncode}"
    return f"[mcp {run.mcp_status}, {run.outcome}, {code}]"


def score(scenarios: list[ConformanceScenario], runs: list[HostRun]) -> list[ScenarioResult]:
    """validate_all over the valid runs only; an invalid run's scenario has no
    transcript and so reads as SKIP, never as a routing PASS or FAIL."""
    return validate_all(scenarios, [r.transcript for r in runs if r.valid])


def host_argv(config: dict, model: str, max_turns: int) -> list[str]:
    """The child `claude -p` command line: the host-tool allowlist, the denied
    write tools, and only sumo-qa's read-only tools pre-approved."""
    names = json.loads(TOOLS_SNAPSHOT.read_text(encoding="utf-8"))["required_tools"]
    approved = [f"mcp__{SERVER}__{n}" for n in names if n not in REFUSED_SUMO_QA_TOOLS]
    return [
        "claude", "-p",
        "--model", model,
        "--output-format", "stream-json", "--verbose",
        "--strict-mcp-config", "--mcp-config", json.dumps(config),
        "--setting-sources", "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--permission-mode", "default",
        "--max-turns", str(max_turns),
        "--tools", ",".join(HOST_TOOLS),
        "--allowedTools", *approved,
        "--disallowedTools", *DISALLOWED_TOOLS,
    ]  # fmt: skip


def child_env(parent: Mapping[str, str]) -> dict[str, str]:
    """The child's whole environment: a few variables from the parent plus the
    isolation switches. Nothing else leaks in, so a parent's model override,
    debug dir or session variables cannot reach the host or its MCP server
    (which inherits the host's environment)."""
    return {k: parent[k] for k in CHILD_ENV_PASSTHROUGH if k in parent} | CHILD_ENV


def decode(raw: bytes | None) -> str:
    """CLI output as text; a multi-byte character cut by a timeout becomes U+FFFD."""
    return (raw or b"").decode("utf-8", errors="replace")


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


def run_host(
    binary: Path, scenario_id: str, prompt: str, model: str, run_dir: Path,
    max_turns: int, timeout: int,
) -> HostRun:  # fmt: skip
    """One `claude -p` run with only this build's sumo-qa attached. The raw
    stream-json and stderr land in `run_dir` as `<id>.jsonl` / `<id>.stderr`."""
    cwd = run_dir / "cwd" / scenario_id
    cwd.mkdir(parents=True)
    server_home = cwd.parent / f"{scenario_id}-server-home"
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
    argv = host_argv(config, model, max_turns)
    try:
        done = subprocess.run(
            argv, input=prompt.encode(), cwd=cwd, env=child_env(os.environ),
            capture_output=True, timeout=timeout,
        )  # fmt: skip
        stdout, stderr, returncode = done.stdout, done.stderr, done.returncode
    except subprocess.TimeoutExpired as exc:
        stdout, stderr, returncode = exc.stdout, exc.stderr, None
    text = decode(stdout)
    (run_dir / f"{scenario_id}.jsonl").write_text(text, encoding="utf-8")
    (run_dir / f"{scenario_id}.stderr").write_text(decode(stderr), encoding="utf-8")
    run = parse_stream(text, scenario_id)
    run.returncode = returncode
    return run


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
    parser.add_argument(
        "--out", type=Path, help="new or empty run dir for venvs, cwds and raw captures"
    )
    parser.add_argument("--max-turns", type=int, default=15)
    parser.add_argument("--timeout", type=int, default=600, help="seconds per host run")
    args = parser.parse_args(argv)

    scenarios = select_scenarios(SCENARIOS, args.only)
    if not scenarios:
        parser.error(f"--only {args.only!r} matches no deterministic scenario with a prompt")
    if args.out and args.out.exists() and any(args.out.iterdir()):
        parser.error(f"--out {args.out} is not empty; give a new or empty dir")
    out = (args.out or Path(tempfile.mkdtemp(prefix="live-first-hop-"))).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # Every build first, so a bad spec fails before anything is billed.
    builds = [
        (*install_build(spec, out / f"build-{i}"), out / f"build-{i}")
        for i, spec in enumerate(s for s in (args.build, args.after) if s)
    ]
    sections: list[str] = []

    def finish(code: int, problem: str = "") -> int:
        report = "\n\n".join(sections)
        (out / "report.txt").write_text(report + "\n", encoding="utf-8")
        print(report)
        print(f"\nraw captures: {out}")
        if problem:
            print(problem, file=sys.stderr)
        return code

    for binary, label, build_dir in builds:
        guard_dir = build_dir / WRITE_GUARD_ID
        sentinel = guard_dir / "outside" / "pwned.txt"
        sentinel.parent.mkdir(parents=True)
        prompt = WRITE_GUARD_PROMPT.format(path=sentinel)
        guard = run_host(
            binary, WRITE_GUARD_ID, prompt, args.model, guard_dir, args.max_turns, args.timeout
        )
        breached = sentinel.exists()
        calls = " -> ".join(c.tool for c in guard.transcript.tool_calls) or "(no tool calls)"
        sections.append(
            f"== write guard ({label}): "
            f"{'FAIL, file written' if breached else 'PASS, no file'} at {sentinel}\n"
            f"{WRITE_GUARD_ID} {_status(guard)}: {calls}"
        )
        if breached:
            return finish(EXIT_BREACH, "write guard breached; no scenario was run")
        if not guard.valid:
            return finish(
                EXIT_INVALID, "write guard run was not valid (MCP or outcome); no scenario was run"
            )

    environment_ok = True
    all_results: list[list[ScenarioResult]] = []
    for binary, label, build_dir in builds:
        runs = [
            run_host(
                binary, s.id, s.user_prompt, args.model, build_dir, args.max_turns, args.timeout
            )
            for s in scenarios
        ]
        environment_ok &= all(r.valid for r in runs)
        results = score(scenarios, runs)
        all_results.append(results)
        sections.append(render_build(label, runs, results))
    if len(all_results) == 2:
        sections.append(render_comparison(*all_results))
    if not environment_ok:
        return finish(
            EXIT_INVALID,
            "a run's MCP server did not connect or the run did not end in success; "
            "those runs are not scored and the scores are not valid",
        )
    return finish(0)


if __name__ == "__main__":
    sys.exit(main())
