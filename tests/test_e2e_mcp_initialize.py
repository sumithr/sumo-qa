# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""End-to-end tests: spawn the real MCP server and drive it over JSON-RPC.

We use ``sys.executable -m sumo_qa`` (Option B) rather than looking up
the ``sumo-qa`` console-script binary on PATH.  This is more portable: it works
in any venv-based CI environment and during local ``python -m pytest`` without
requiring a separate ``pip install`` step to register the entry-point.

Note: ``python -m sumo_qa.server`` does NOT work because ``server.py`` has no
``if __name__ == "__main__"`` guard — the module defines ``main()`` but never
calls it when run directly. The top-level package (``-m sumo_qa``) routes
through ``__main__.py`` which calls ``main()`` correctly.
"""

# mutmut-subprocess-spawning: spawns a fresh Python interpreter that imports the
# sumo_qa package (``-m sumo_qa``, transitively importing the mutated modules),
# so it MUST be excluded from the mutmut gate via
# [tool.mutmut].pytest_add_cli_args in pyproject.toml — otherwise it crashes the
# trampoline (KeyError: 'MUTANT_UNDER_TEST') and silently disarms the gate. The
# tests/test_mutmut_subprocess_exclusions.py guard enforces this marker↔ignore
# pairing loudly at PR time. See docs/DEVELOPMENT.md § Mutation testing.

import collections
import json
import os
import queue
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from sumo_qa import server as sumo_server
from sumo_qa.installer import (
    _read_json_rpc_response,
    _start_stdout_reader,
    _terminate,
    _VerifyTimeout,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}

_INITIALIZED_NOTIFICATION = {
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
}

_TOOLS_LIST_REQUEST = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {},
}


def _spawn_mcp() -> subprocess.Popen:
    # Prepend src/ to PYTHONPATH so the spawned interpreter can `import sumo_qa`
    # even when sumo-qa isn't pip-installed in the active venv. Without this,
    # `pytest --cov` works when the project is editable-installed,
    # but the pre-commit-hooks isolated venv (which only installs the deps
    # listed in additional_dependencies, not the project itself) fails with
    # `No module named sumo_qa`.
    src_path = str(REPO_ROOT / "src")
    existing = os.environ.get("PYTHONPATH", "")
    pythonpath = f"{src_path}{os.pathsep}{existing}" if existing else src_path
    return subprocess.Popen(
        [sys.executable, "-m", "sumo_qa"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        # Inherited, not piped: an undrained pipe can deadlock the server, and
        # pytest's fd capture shows a crashing server's traceback on failure.
        stderr=None,
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": pythonpath},
        text=True,
    )


def _send(proc: subprocess.Popen, request: dict) -> None:
    """Write a JSON-RPC message to the server's stdin (fire-and-forget)."""
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()


_DEADLINE_SECONDS = 60


def _receiver(lines: queue.Queue) -> Callable[[int], dict]:
    """A reader of the server's JSON-RPC responses by id. Every read shares
    one absolute deadline, so a stalled server fails the test after 60s in
    total instead of hanging the worker, and any stdout line that is not the
    awaited response (a stray ``print()``) fails the test."""
    deadline = time.monotonic() + _DEADLINE_SECONDS
    pending: collections.deque[dict] = collections.deque()

    def recv(expected_id: int) -> dict:
        extra_lines: list[str] = []
        try:
            response = _read_json_rpc_response(
                line_queue=lines,
                expected_id=expected_id,
                deadline=deadline,
                extra_lines=extra_lines,
                pending_responses=pending,
            )
        except _VerifyTimeout:
            pytest.fail(
                f"the MCP server did not answer request id={expected_id} "
                f"within the test's {_DEADLINE_SECONDS}s deadline"
            )
        assert response is not None, "the MCP server exited before responding"
        assert extra_lines == [], f"non-protocol lines on the server's stdout: {extra_lines!r}"
        return response

    return recv


def _expected_tool_count() -> int:
    """Derive the expected tool count directly from the live server registry.

    This avoids hardcoding a magic constant so the test stays correct when
    tools are added or removed in future.
    """
    mcp = sumo_server.build_mcp_server()
    return len(mcp._tool_manager._tools)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_proc():
    """Spawn the MCP server with a response reader and guarantee it is
    terminated after the test."""
    proc = _spawn_mcp()
    try:
        yield proc, _receiver(_start_stdout_reader(proc))
    finally:
        _terminate(proc)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_mcp_initialize_returns_server_name(mcp_proc):
    """The server responds to JSON-RPC ``initialize`` with serverInfo.name == 'sumo-qa'."""
    proc, recv = mcp_proc
    _send(proc, _INITIALIZE_REQUEST)
    response = recv(1)

    assert response.get("jsonrpc") == "2.0"
    result = response.get("result", {})
    server_info = result.get("serverInfo", {})
    assert server_info.get("name") == "sumo-qa", (
        f"Expected serverInfo.name == 'sumo-qa', got: {server_info!r}"
    )


def test_mcp_tools_list_count_matches_registry(mcp_proc):
    """The ``tools/list`` response returns exactly the same number of tools
    as are registered via ``build_mcp_server()``."""
    # Complete the handshake before sending tools/list.
    proc, recv = mcp_proc
    _send(proc, _INITIALIZE_REQUEST)
    recv(1)  # consume the initialize result

    _send(proc, _INITIALIZED_NOTIFICATION)
    # notifications/initialized has no response; go straight to tools/list.

    _send(proc, _TOOLS_LIST_REQUEST)
    response = recv(2)

    assert response.get("jsonrpc") == "2.0"
    tools = response.get("result", {}).get("tools", [])
    expected = _expected_tool_count()
    assert len(tools) == expected, f"Expected {expected} tools from tools/list, got {len(tools)}"
