#!/usr/bin/env python3
# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Mock MCP server that faithfully reproduces the cancel-on-EOF behaviour.

The real mcp library (mcp.server.lowlevel.Server.run) deliberately cancels
in-flight handlers when stdin EOF is read — see the explicit
"Transport closed: cancel in-flight handlers" branch in
mcp/server/lowlevel/server.py:685-690. On Linux's epoll scheduler the cancel
can win the race against a tools/list handler's stdout write, dropping the
id==2 response entirely (PR #141 CI diagnostic confirmed this).

This mock replays that race deterministically so a unit test can pin the
smoke harness's stdin-handling contract:

  1. Read init → reply immediately (id==1).
  2. Read notifications/initialized → silent.
  3. Read tools/list → start a "handler" thread that sleeps 300ms then writes
     id==2. If stdin EOF arrives during the sleep, the handler is cancelled
     and id==2 is NEVER written.
  4. Read EOF → cancel any in-flight handler, exit.

The 300ms delay forces the race. A correct smoke client keeps stdin open
until the id==2 response has been observed on stdout; an incorrect client
(e.g. subprocess.communicate which closes stdin after writing the payload)
hits step 4 before step 3 completes — the bug.
"""

from __future__ import annotations

import json
import sys
import threading
import time

DELAY_BEFORE_TOOLS_RESPONSE = 0.3

cancel_event = threading.Event()


def write(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def slow_tools_response() -> None:
    """Simulate the mcp library's async handler: takes 300ms, cancellable on EOF."""
    deadline = time.monotonic() + DELAY_BEFORE_TOOLS_RESPONSE
    while time.monotonic() < deadline:
        if cancel_event.is_set():
            return  # cancelled by stdin EOF — mirrors lowlevel.Server.run finally branch
        time.sleep(0.01)
    write(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {"name": "sumo_qa_load_classifications", "description": "stub"},
                    {"name": "sumo_qa_load_approaches", "description": "stub"},
                ]
            },
        }
    )


def main() -> int:
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        if method == "initialize":
            write(
                {
                    "jsonrpc": "2.0",
                    "id": msg.get("id", 1),
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {"name": "mock-mcp", "version": "0"},
                    },
                }
            )
        elif method == "tools/list":
            threading.Thread(target=slow_tools_response, daemon=True).start()
        # notifications (no `id`) get no response by JSON-RPC contract.

    # stdin EOF: signal any in-flight handler to abort, mirror mcp library behaviour.
    cancel_event.set()
    # Give the handler thread a brief moment to observe the flag before we exit.
    time.sleep(0.05)
    return 0


if __name__ == "__main__":
    sys.exit(main())
