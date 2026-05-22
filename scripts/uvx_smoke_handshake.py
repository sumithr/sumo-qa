#!/usr/bin/env python3
# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Spawn an MCP server and drive an initialize + tools/list handshake.

Used by the `plugin install via uvx` job in .github/workflows/install-smoke.yml
to prove `uvx --from $CLAUDE_PLUGIN_ROOT sumo-qa` produces a working JSON-RPC
server on every OS. Extracted from a YAML heredoc so the handshake logic is
importable and unit-testable.

Critical contract: stdin stays open until the id==2 (tools/list) response
has been read off stdout. Closing stdin earlier triggers the mcp library's
cancel-in-flight-handlers branch (mcp/server/lowlevel/server.py:685-690),
which on Linux's epoll scheduler races and beats the tools/list handler's
stdout write — the bug confirmed on PR #141 ubuntu CI.

The unit regression test at tests/test_uvx_smoke_handshake.py pins this
contract using a deterministic mock that mirrors the mcp-library
cancel-on-EOF behaviour.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field


@dataclass
class HandshakeResult:
    """Outcome of one MCP handshake attempt.

    `success` is True iff an id==2 response was observed in stdout and at
    least one tool name started with the required `tool_prefix`. Diagnostics
    are populated regardless so callers can dump full evidence on failure.
    """

    success: bool
    stdout: str
    stderr: str
    id2: dict | None
    tool_count: int
    tool_names: list[str] = field(default_factory=list)


_INIT_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "ci-smoke", "version": "1"},
    },
}
_INITIALIZED_NOTIF = {"jsonrpc": "2.0", "method": "notifications/initialized"}
_TOOLS_LIST_REQUEST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}


def _drain_pipe(pipe, sink_queue: queue.Queue) -> None:
    """Background-thread reader: drain `pipe` line-by-line into `sink_queue`.

    Pushing each line to a queue lets the main thread write to stdin and
    poll for responses without deadlocking on a full OS pipe buffer (default
    16–64KB), and without closing stdin prematurely just to bound the read.
    A `None` sentinel marks end-of-stream.
    """
    try:
        for line in iter(pipe.readline, ""):
            sink_queue.put(line)
    finally:
        sink_queue.put(None)


def run_handshake(
    cmd: list[str],
    deadline_secs: float = 60.0,
    env: dict[str, str] | None = None,
    tool_prefix: str = "sumo_qa_",
) -> HandshakeResult:
    """Spawn `cmd` as an MCP server over stdio, send init + notif + tools/list,
    and return the captured response.

    Stdin stays open until the id==2 response has been observed in stdout
    (or the deadline expires). Only then do we close stdin and reap.
    """
    if env is None:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(  # noqa: S603 -- cmd is caller-controlled
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    stdout_q: queue.Queue = queue.Queue()
    stderr_q: queue.Queue = queue.Queue()
    threading.Thread(target=_drain_pipe, args=(proc.stdout, stdout_q), daemon=True).start()
    threading.Thread(target=_drain_pipe, args=(proc.stderr, stderr_q), daemon=True).start()

    payload = "\n".join(
        json.dumps(m) for m in (_INIT_REQUEST, _INITIALIZED_NOTIF, _TOOLS_LIST_REQUEST)
    )
    try:
        proc.stdin.write(payload + "\n")
        proc.stdin.flush()
    except BrokenPipeError:
        pass  # server died early — diagnostic dump below will show it

    stdout_lines: list[str] = []
    id2: dict | None = None
    deadline = time.monotonic() + deadline_secs
    while time.monotonic() < deadline:
        try:
            line = stdout_q.get(timeout=0.5)
        except queue.Empty:
            if proc.poll() is not None:
                break  # process exited; flush any final lines below
            continue
        if line is None:
            break  # stdout EOF
        stdout_lines.append(line)
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 2:
            id2 = msg
            break

    # NOW close stdin (after id==2 captured, not before). If id==2 never
    # arrived we still close so the server can shut down cleanly.
    try:
        proc.stdin.close()
    except BrokenPipeError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    # Drain any straggler lines off both queues so the diagnostic dump on
    # failure has the complete picture.
    while True:
        try:
            line = stdout_q.get_nowait()
        except queue.Empty:
            break
        if line is None:
            break
        stdout_lines.append(line)

    stderr_lines: list[str] = []
    while True:
        try:
            line = stderr_q.get_nowait()
        except queue.Empty:
            break
        if line is None:
            break
        stderr_lines.append(line)

    stdout = "".join(stdout_lines)
    stderr = "".join(stderr_lines)

    tool_names: list[str] = []
    tool_count = 0
    success = False
    if id2 is not None and "result" in id2:
        tools = id2["result"].get("tools", [])
        tool_count = len(tools)
        tool_names = [t.get("name", "") for t in tools]
        success = any(n.startswith(tool_prefix) for n in tool_names)

    return HandshakeResult(
        success=success,
        stdout=stdout,
        stderr=stderr,
        id2=id2,
        tool_count=tool_count,
        tool_names=tool_names,
    )


def _dump_diagnostic(result: HandshakeResult) -> None:
    """Print a full failure diagnostic to stderr — the thing the previous
    smoke's `(err or "")[-500:]` truncation hid. Classify the failure shape
    so the next reader can act without reproducing the run."""
    sys.stderr.write("=== uvx handshake FAILED ===\n")
    if result.id2 is None:
        sys.stderr.write("-- no id==2 response found in stdout\n")
    elif "result" in result.id2:
        head = result.tool_names[:5]
        ellipsis = "…" if len(result.tool_names) > 5 else ""
        sys.stderr.write(
            f"-- id==2 result present: {result.tool_count} tools, "
            f"none with required prefix. Names: {head}{ellipsis}\n"
        )
    elif "error" in result.id2:
        sys.stderr.write(f"-- id==2 ERROR response: {json.dumps(result.id2['error'])}\n")
    else:
        sys.stderr.write(f"-- id==2 had neither result nor error: {json.dumps(result.id2)}\n")
    sys.stderr.write(f"-- full stdout ({len(result.stdout)} bytes):\n{result.stdout}\n")
    sys.stderr.write(f"-- full stderr ({len(result.stderr)} bytes):\n{result.stderr}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Drive a JSON-RPC handshake against an MCP server and assert sumo_qa_* tools are advertised.",
    )
    parser.add_argument(
        "--plugin-root",
        default=os.environ.get("CLAUDE_PLUGIN_ROOT"),
        help="Source directory passed to `uvx --from <plugin-root>` (default: $CLAUDE_PLUGIN_ROOT)",
    )
    parser.add_argument("--deadline-secs", type=float, default=60.0)
    parser.add_argument("--tool-prefix", default="sumo_qa_")
    args = parser.parse_args(argv)

    if not args.plugin_root:
        sys.stderr.write("error: --plugin-root or $CLAUDE_PLUGIN_ROOT is required\n")
        return 2

    cmd = ["uvx", "--from", args.plugin_root, "sumo-qa"]
    result = run_handshake(cmd, deadline_secs=args.deadline_secs, tool_prefix=args.tool_prefix)

    if result.success:
        print(f"uvx-spawned MCP handshake OK ({result.tool_count} tools)")
        return 0

    _dump_diagnostic(result)
    return 1


if __name__ == "__main__":  # pragma: no cover -- main guard
    sys.exit(main())


if __name__ == "__main__":  # pragma: no cover -- main guard
    sys.exit(main())
