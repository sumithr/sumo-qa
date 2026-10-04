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


# ---------------------------------------------------------------------------
# Every launch path resolves the saved profile (#809)
# ---------------------------------------------------------------------------


def _host_entry(config: Path, key: str) -> dict:
    return json.loads(config.read_text(encoding="utf-8"))[key]["sumo-qa"]


def _launch_entries(tmp_path: Path, monkeypatch) -> dict[str, dict]:
    """The ``sumo-qa`` entry each launch path starts the server from, in a
    clean temp HOME. The installer writes the VS Code and Claude Desktop
    entries; the Claude Code and Codex plugins share the shipped ``.mcp.json``,
    whose ``uvx --from <plugin root>`` command needs the network, so it is
    swapped for this interpreter while its ``env`` is kept (a real uvx launch
    is a manual clean-install check). JetBrains and Junie are given the same
    command the installer prints, which is the direct launch."""
    from sumo_qa import installer

    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    (workspace / ".git").mkdir(parents=True)
    desktop_config = installer._claude_desktop_config_path(home, "Linux")
    desktop_config.parent.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    direct = installer.McpCommand(command=sys.executable, args=["-m", "sumo_qa"])
    installer._setup_vscode_copilot(direct, workspace)
    installer._setup_claude_desktop(direct, "Linux")
    plugin = _host_entry(REPO_ROOT / ".mcp.json", "mcpServers")
    return {
        "direct CLI / JetBrains / Junie": direct.to_config_entry(),
        "installer VS Code": _host_entry(workspace / ".vscode" / "mcp.json", "servers"),
        "installer Claude Desktop": _host_entry(desktop_config, "mcpServers"),
        "Claude Code / Codex plugin": {**direct.to_config_entry(), "env": plugin.get("env", {})},
    }


def _launch_and_discover(entry: dict, cwd: Path) -> tuple[set[str], dict]:
    """Start the server as a host would from ``entry`` and return its
    ``tools/list`` names and its ``sumo_qa_capabilities`` result."""
    src_path = str(REPO_ROOT / "src")
    proc = subprocess.Popen(
        [entry["command"], *entry.get("args", [])],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,
        cwd=str(cwd),
        env={**os.environ, "PYTHONPATH": src_path, **entry.get("env", {})},
        text=True,
    )
    try:
        recv = _receiver(_start_stdout_reader(proc))
        _send(proc, _INITIALIZE_REQUEST)
        recv(1)
        _send(proc, _INITIALIZED_NOTIFICATION)
        _send(proc, _TOOLS_LIST_REQUEST)
        names = {t["name"] for t in recv(2)["result"]["tools"]}
        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "sumo_qa_capabilities", "arguments": {}},
            },
        )
        capabilities = json.loads(recv(3)["result"]["content"][0]["text"])
        return names, capabilities
    finally:
        _terminate(proc)


def test_every_launch_path_serves_the_saved_profile_across_a_restart(tmp_path, monkeypatch):
    """With ``core`` saved (what ``sumo-qa-install --profile core`` writes) and
    no profile in any entry, every launch path serves ``core``: its
    capability discovery reports ``core`` and its ``tools/list`` is exactly the
    core tool set. A second launch (a host restart) serves the same."""
    from sumo_qa.paths import mcp_profile_path
    from sumo_qa.tool_registry import PROFILE_ENV, profile_tool_names

    mcp_profile_path().parent.mkdir(parents=True)
    mcp_profile_path().write_text("core\n", encoding="utf-8")
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    for path, entry in _launch_entries(tmp_path, monkeypatch).items():
        assert PROFILE_ENV not in entry.get("env", {}), path
        for launch in ("first launch", "after restart"):
            names, capabilities = _launch_and_discover(entry, tmp_path)
            assert capabilities["active_profile"] == "core", (path, launch)
            assert names == profile_tool_names("core"), (path, launch)
