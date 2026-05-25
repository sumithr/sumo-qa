# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Regression test for the install-smoke plugin-dir handshake bug.

The `plugin-dir handshake` job in .github/workflows/install-smoke.yml drove
the MCP handshake via an inline `subprocess.communicate(payload, timeout=20)`
heredoc, which closes stdin immediately after writing the payload. That
triggers the mcp library's cancel-in-flight-handlers branch (see PR #141 /
tests/test_uvx_smoke_handshake.py for the full root-cause writeup) and the
id==2 response is dropped on Linux. PR #141 fixed the uvx-spawn job using
scripts/uvx_smoke_handshake.py but missed this second job, which kept
failing on every push to main.

This test pins the plugin-dir variant of the same contract: read the cmd
from `.mcp.json`, substitute `${CLAUDE_PLUGIN_ROOT}`, drive the handshake,
keep stdin open until id==2 arrives. Uses the same cancel-on-EOF mock
server as the uvx test, in a tmp checkout shaped like a real plugin
(adapter dir with plugin.json + .mcp.json at the root).
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys


def _find_repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "scripts").is_dir():
            return candidate
    raise RuntimeError(f"cannot locate repo root from {here}")


REPO_ROOT = _find_repo_root()
SCRIPT = REPO_ROOT / "scripts" / "plugin_dir_handshake.py"
MOCK_SERVER = REPO_ROOT / "tests" / "fixtures" / "mock_slow_mcp_server.py"


def test_plugin_dir_handshake_passes_against_slow_mock(tmp_path: pathlib.Path) -> None:
    """End-to-end regression: a plugin checkout with a `.mcp.json` pointing at
    the cancel-on-EOF mock server must succeed.

    A correct script keeps stdin open until id==2 is observed; the broken
    `subprocess.communicate` shape triggers the mock's cancel branch and the
    handshake fails. This is the exact failure mode that's been red on main
    since 4df0afa.
    """
    adapter = tmp_path / ".claude-plugin"
    adapter.mkdir()
    (adapter / "plugin.json").write_text('{"name": "sumo-qa"}', encoding="utf-8")
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "sumo-qa": {
                        "command": sys.executable,
                        "args": [str(MOCK_SERVER)],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--adapter", ".claude-plugin"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, (
        f"handshake should pass on cancel-on-EOF mock; got returncode={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "MCP handshake OK" in result.stdout, (
        f"expected success line in stdout; got: {result.stdout!r}"
    )


def test_plugin_dir_handshake_substitutes_claude_plugin_root(tmp_path: pathlib.Path) -> None:
    """The plugin's `.mcp.json` uses `${CLAUDE_PLUGIN_ROOT}` to point at args
    relative to the plugin root. The script must expand that to the cwd (which
    is what Claude Code does at runtime) so the mock server path resolves.
    """
    adapter = tmp_path / ".codex-plugin"
    adapter.mkdir()
    (adapter / "plugin.json").write_text('{"name": "sumo-qa"}', encoding="utf-8")
    # Copy the mock server into the tmp plugin so the path-substitution is
    # the only thing under test.
    mock_in_plugin = tmp_path / "fixtures" / "mock.py"
    mock_in_plugin.parent.mkdir()
    mock_in_plugin.write_text(MOCK_SERVER.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "sumo-qa": {
                        "command": sys.executable,
                        "args": ["${CLAUDE_PLUGIN_ROOT}/fixtures/mock.py"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--adapter", ".codex-plugin"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, (
        f"${{CLAUDE_PLUGIN_ROOT}} substitution failed; got returncode={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
