#!/usr/bin/env python3
# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Spawn an MCP server and drive an initialize + tools/list handshake.

Used by the `plugin install via uvx` job in .github/workflows/install-smoke.yml
to prove uvx --from $CLAUDE_PLUGIN_ROOT sumo-qa produces a working JSON-RPC
server on every OS. Extracted from a YAML heredoc so the handshake logic is
importable and unit-testable.

RED-PHASE STUB — returns a failure result so the regression test in
tests/test_uvx_smoke_handshake.py reaches its assertion. The green-phase
implementation is the contributor's next step.
"""

from __future__ import annotations

import sys
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


def run_handshake(
    cmd: list[str],
    deadline_secs: float = 60.0,
    env: dict[str, str] | None = None,
    tool_prefix: str = "sumo_qa_",
) -> HandshakeResult:
    """Spawn `cmd` as an MCP server over stdio, send init + notif + tools/list,
    and return the captured response.

    The handshake must keep stdin OPEN until the id==2 response has been
    observed in stdout (or the deadline expires). Closing stdin earlier
    triggers the mcp library's cancel-in-flight-handlers branch
    (mcp/server/lowlevel/server.py:685-690), which on Linux's epoll scheduler
    races the tools/list response and loses.
    """
    # Red-phase stub: returns a uniform failure shape so the regression test
    # reaches its assertion. No behaviour — the green-making implementation
    # is the contributor's next step.
    return HandshakeResult(
        success=False,
        stdout="",
        stderr="",
        id2=None,
        tool_count=0,
        tool_names=[],
    )


def main(argv: list[str] | None = None) -> int:
    # Red-phase stub: green-make next.
    return 1


if __name__ == "__main__":  # pragma: no cover -- main guard
    sys.exit(main())
