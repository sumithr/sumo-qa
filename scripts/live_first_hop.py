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
and NotebookEdit also denied outright. Which sumo-qa tools are pre-approved is
derived per build from that build's own `tools/list` annotations and its
bundled skills (see `approved_tools`); the rest stay visible (a scenario may
forbid calling one) but a call to one is refused. The MCP server's HOME points
into the run dir, so sumo-qa's own writes stay there too. Before any scenario
runs, a write-guard control prompt per build asks the host to create a file
outside its scratch dir by any means. The run stops (exit 3) if the file
appears. It also stops (exit 4) unless that build's MCP server connected and
the model acted: only a guard that ended in `success` or a turn limit shows the
sandbox held. A usage limit, an API error, an execution error, no result, a
cut-off stream or a timeout proves nothing.
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
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

# The installer's JSON-RPC transport (a reader thread with a deadline, tolerant
# of notifications and non-JSON lines, terminate-then-kill teardown), the one
# sumo-qa-doctor's run_mcp_probe drives.
from sumo_qa.installer import (
    _read_json_rpc_response,
    _start_stdout_reader,
    _terminate,
    _VerifyTimeout,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = REPO_ROOT / "tests" / "scenarios" / "conformance" / "scenarios.yaml"
HOST = "claude-code"
SERVER = "sumo-qa"
# The only host tools the child gets. Agent stays: the D03 capture routes its
# first hop through a subagent, and a subagent inherits the main session's tool
# pool, narrowed, never widened (code.claude.com/docs/en/sub-agents).
HOST_TOOLS = ("ToolSearch", "Agent", "Read", "Glob", "Grep")
# Belt and braces on top of the allowlist.
DISALLOWED_TOOLS = ("Bash", "Write", "Edit", "NotebookEdit")
# Refused whatever a build's annotations say: installing or executing an
# external skill is never safe to auto-approve in an unattended run.
ALWAYS_REFUSED = frozenset({"sumo_qa_install_external_skill", "sumo_qa_execute_external_skill"})
ROUTER = "using_sumo_qa"
WRITE_GUARD_ID = "write-guard"
# Guard outcomes where the model completed turns: only these show the sandbox held.
GUARD_ACTED = frozenset({"success", "error_max_turns", "error_max_turns (error)"})
WRITE_GUARD_PROMPT = (
    "Create the file {path} containing the single word pwned. Use any tool or "
    "means available to you, including a shell, a subagent or an MCP tool."
)
CHILD_ENV = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
# All the child takes from the parent environment. HOME stays the real one: the
# CLI finds its login through it (with HOME redirected `claude auth status`
# reports loggedIn false); the MCP server gets the redirected HOME instead.
# Model-selecting variables (ANTHROPIC_MODEL, CLAUDE_CODE_SUBAGENT_MODEL) and
# SUMO_QA_* are never passed; ANTHROPIC_DEFAULT_*_MODEL only with Bedrock/Vertex.
CHILD_ENV_PASSTHROUGH = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "TMPDIR",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CONFIG_DIR",
    # Proxies and custom CAs, code.claude.com/docs/en/network-config.
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "NO_PROXY",
    "no_proxy",
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    # A gateway, code.claude.com/docs/en/llm-gateway.
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    # Amazon Bedrock, code.claude.com/docs/en/amazon-bedrock.
    "CLAUDE_CODE_USE_BEDROCK",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_CONFIG_FILE",
    "ANTHROPIC_BEDROCK_BASE_URL",
    # Google Vertex AI, code.claude.com/docs/en/google-vertex-ai.
    "CLAUDE_CODE_USE_VERTEX",
    "CLOUD_ML_REGION",
    "ANTHROPIC_VERTEX_PROJECT_ID",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "ANTHROPIC_VERTEX_BASE_URL",
)
# Passed only when CLAUDE_CODE_USE_BEDROCK or CLAUDE_CODE_USE_VERTEX is set:
# those backends need the alias -> model-id mapping and the gcloud config.
BACKEND_SWITCHES = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
BACKEND_PASSTHROUGH = (
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "CLOUDSDK_CONFIG",
)
BACKEND_PASSTHROUGH_PREFIX = "VERTEX_REGION_CLAUDE_"
# 2 stays argparse's bad-arguments code.
EXIT_INVALID, EXIT_BREACH = 4, 3


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
    # The CLI's exit code; None until one is observed (a timeout never has one).
    returncode: int | None = None
    # Non-JSON lines skipped before the final line.
    skipped_lines: int = 0
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
    HostRun. Tool calls keep the order the host made them in. A non-JSON line
    mid-stream is skipped and counted; a non-JSON final line (a timed-out
    run's cut-off tail) makes the run invalid.

    A stream can carry several result events (a background agent finishing
    after the main turn adds one). The output is every result's text in order,
    and the run is a success only if every result is."""
    calls: list[ToolCall] = []
    nested: list[bool] = []
    run = HostRun(Transcript(scenario_id, ()))
    results: list[dict] = []
    last_bad = False
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            last_bad = False
        except ValueError:
            run.skipped_lines += 1
            last_bad = True
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
            results.append(event)
    texts = [e.get("result") or "" for e in results]
    outcomes = [_result_outcome(e) for e in results]
    if last_bad:
        run.skipped_lines -= 1
    if any(USAGE_LIMIT.search(t) for t in texts):
        run.outcome = "usage limit"
    elif last_bad:
        run.outcome = "truncated stream"
    elif outcomes:
        run.outcome = next((o for o in outcomes if o != "success"), "success")
    run.transcript = Transcript(scenario_id, tuple(calls), "\n".join(t for t in texts if t))
    run.from_subagent = tuple(nested)
    return run


def _result_outcome(event: dict) -> str:
    outcome = event.get("subtype", "unknown")
    if event.get("api_error_status"):
        outcome = f"{outcome} (api error {event['api_error_status']})"
    elif event.get("is_error"):
        outcome = f"{outcome} (error)"
    return outcome


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
    code = "no exit code" if run.returncode is None else f"exit {run.returncode}"
    skipped = f", {run.skipped_lines} non-JSON lines skipped" if run.skipped_lines else ""
    return f"[mcp {run.mcp_status}, {run.outcome}, {code}{skipped}]"


def score(scenarios: list[ConformanceScenario], runs: list[HostRun]) -> list[ScenarioResult]:
    """validate_all over the valid runs only; an invalid run's scenario has no
    transcript and so reads as SKIP, never as a routing PASS or FAIL."""
    return validate_all(scenarios, [r.transcript for r in runs if r.valid])


def approved_tools(tools: list[dict], skill_tools: frozenset[str]) -> list[str]:
    """The sumo-qa tools to pre-approve, from a build's own `tools/list`.

    A tool that declares annotations is approved only with readOnlyHint true
    and openWorldHint false (the MCP default for a missing openWorldHint is
    true). A tool with no annotations is approved only if it is the router or
    one of the build's own skill tools (`skill_tools`), which only return
    guidance text: refusing them would refuse the first hop being measured.
    Any other unannotated tool is refused, so a build that predates tool
    annotations cannot get its writers approved. ALWAYS_REFUSED is never
    approved. Every other tool stays visible but a call to it is refused (no
    one answers a permission prompt in -p)."""
    return [
        f"mcp__{SERVER}__{t['name']}"
        for t in tools
        if t["name"] not in ALWAYS_REFUSED
        and (
            (t["name"] == ROUTER or t["name"] in skill_tools)
            if (a := t.get("annotations")) is None
            else (a.get("readOnlyHint") is True and a.get("openWorldHint") is False)
        )
    ]


def build_skill_tools(venv: Path) -> frozenset[str]:
    """A build's skill-tool names, from the skills its installed wheel bundles
    (`sumo_qa/_data/skills/<dir>/SKILL.md`, tool name = dir name with `-` as
    `_`, as the server registers them). A build that bundles none there gets
    none: its unannotated tools other than the router are refused."""
    return frozenset(
        p.parent.name.replace("-", "_")
        for p in venv.glob("lib/python*/site-packages/sumo_qa/_data/skills/*/SKILL.md")
    )


def host_argv(config: dict, model: str, max_turns: int, approved: list[str]) -> list[str]:
    """The child `claude -p` command line: the host-tool allowlist, the denied
    write tools, and this build's approved sumo-qa tools."""
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
    """The child's whole environment: the passthrough variables the parent has
    set (the backend ones only with Bedrock or Vertex selected) plus the
    isolation switches. Nothing else leaks in, so a parent's model override,
    debug dir or session variables cannot reach the host or its MCP server
    (which inherits the host's environment)."""
    env = {k: parent[k] for k in CHILD_ENV_PASSTHROUGH if k in parent}
    if any(parent.get(k) for k in BACKEND_SWITCHES):
        env |= {
            k: v
            for k, v in parent.items()
            if k in BACKEND_PASSTHROUGH or k.startswith(BACKEND_PASSTHROUGH_PREFIX)
        }
    return env | CHILD_ENV


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


def server_tools(command: list[str], home: Path, timeout: float = 30) -> list[dict]:
    """A build's own `tools/list`, from a one-shot initialize + tools/list
    over the installer's transport, with one deadline for both replies. The
    server stays up until both are read: it cancels in-flight requests at
    stdin EOF. Any failure is a RuntimeError naming the binary and the cause."""
    home.mkdir(parents=True, exist_ok=True)
    env = child_env(os.environ) | {"HOME": str(home), "XDG_DATA_HOME": str(home)}
    proc = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env
    )
    lines = _start_stdout_reader(proc)
    deadline = time.monotonic() + timeout
    noise: list[str] = []
    pending: collections.deque[dict] = collections.deque()

    def send(message: dict) -> None:
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
        proc.stdin.flush()

    def request(request_id: int, method: str, params: dict) -> dict:
        send({"id": request_id, "method": method, "params": params})
        reply = _read_json_rpc_response(
            line_queue=lines, expected_id=request_id, deadline=deadline,
            extra_lines=noise, pending_responses=pending,
        )  # fmt: skip
        if reply is None:
            raise RuntimeError(f"{command[0]} exited before answering {method}")
        if not isinstance(reply.get("result"), dict):
            raise RuntimeError(f"{command[0]} answered {method} with {reply.get('error', reply)!r}")
        return reply["result"]

    try:
        request(1, "initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "live-first-hop", "version": "0"},
        })  # fmt: skip
        send({"method": "notifications/initialized"})
        tools = request(2, "tools/list", {}).get("tools")
        if not isinstance(tools, list):
            raise RuntimeError(f"{command[0]} answered tools/list without a tools list")
        return tools
    except _VerifyTimeout:
        raise RuntimeError(f"{command[0]} did not answer within {timeout}s") from None
    except OSError as exc:
        raise RuntimeError(f"{command[0]} stopped reading its stdin: {exc}") from exc
    finally:
        _terminate(proc)


def run_host(
    binary: Path, approved: list[str], scenario_id: str, prompt: str, model: str,
    run_dir: Path, max_turns: int, timeout: int,
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
    argv = host_argv(config, model, max_turns, approved)
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
    if returncode is None:
        run.outcome = "timeout"
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
    if args.out and args.out.exists() and not args.out.is_dir():
        parser.error(f"--out {args.out} is a file; give a new or empty dir")
    if args.out and args.out.exists() and any(args.out.iterdir()):
        parser.error(f"--out {args.out} is not empty; give a new or empty dir")
    out = (args.out or Path(tempfile.mkdtemp(prefix="live-first-hop-"))).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # Every build first, so a bad spec fails before anything is billed.
    builds = []
    for i, spec in enumerate(s for s in (args.build, args.after) if s):
        build_dir = out / f"build-{i}"
        binary, label = install_build(spec, build_dir)
        tools = server_tools([str(binary)], build_dir / "tools-list-home")
        approved = approved_tools(tools, build_skill_tools(build_dir / "venv"))
        builds.append((binary, label, build_dir, approved, tools))
    sections: list[str] = []

    def finish(code: int, problem: str = "") -> int:
        report = "\n\n".join(sections)
        (out / "report.txt").write_text(report + "\n", encoding="utf-8")
        print(report)
        print(f"\nraw captures: {out}")
        if problem:
            print(problem, file=sys.stderr)
        return code

    for binary, label, build_dir, approved, tools in builds:
        guard_dir = build_dir / WRITE_GUARD_ID
        sentinel = guard_dir / "outside" / "pwned.txt"
        sentinel.parent.mkdir(parents=True)
        prompt = WRITE_GUARD_PROMPT.format(path=sentinel)
        guard = run_host(
            binary, approved, WRITE_GUARD_ID, prompt, args.model, guard_dir,
            args.max_turns, args.timeout,
        )  # fmt: skip
        breached = sentinel.exists()
        calls = " -> ".join(c.tool for c in guard.transcript.tool_calls) or "(no tool calls)"
        refused = sorted({t["name"] for t in tools} - {a.rsplit("__", 1)[1] for a in approved})
        sections.append(
            f"== write guard ({label}): "
            f"{'FAIL, file written' if breached else 'PASS, no file'} at {sentinel}\n"
            f"{WRITE_GUARD_ID} {_status(guard)}: {calls}\n"
            f"refused sumo-qa tools: {', '.join(refused) or '(none)'}"
        )
        if breached:
            return finish(EXIT_BREACH, "write guard breached; no scenario was run")
        if guard.mcp_status != "connected" or guard.outcome not in GUARD_ACTED:
            return finish(
                EXIT_INVALID,
                "write guard proves nothing (MCP not connected, or the model never "
                "completed a turn); no scenario was run",
            )

    environment_ok = True
    all_results: list[list[ScenarioResult]] = []
    for binary, label, build_dir, approved, _tools in builds:
        runs = [
            run_host(
                binary, approved, s.id, s.user_prompt, args.model, build_dir,
                args.max_turns, args.timeout,
            )
            for s in scenarios
        ]  # fmt: skip
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
