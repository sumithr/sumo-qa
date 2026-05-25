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


def _write_mock_mcp_json(checkout: pathlib.Path, mock_path: pathlib.Path) -> None:
    """Write a `.mcp.json` at `checkout` that points at the cancel-on-EOF mock."""
    (checkout / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "sumo-qa": {
                        "command": sys.executable,
                        "args": [str(mock_path)],
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_auto_discovers_every_adapter_with_plugin_json(tmp_path: pathlib.Path) -> None:
    """Future-proofing: when --adapter is omitted, the script must enumerate
    EVERY `.*-plugin/` directory at cwd that contains plugin.json and smoke
    each one. A new host adapter (e.g. `.cursor-plugin/`) added to
    plugin_packaging must be picked up automatically — no CI matrix edit.
    """
    # Three adapters, mimicking the present + a hypothetical future host.
    for name in (".claude-plugin", ".codex-plugin", ".future-host-plugin"):
        adapter = tmp_path / name
        adapter.mkdir()
        (adapter / "plugin.json").write_text('{"name": "sumo-qa"}', encoding="utf-8")
    _write_mock_mcp_json(tmp_path, MOCK_SERVER)

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],  # no --adapter
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (
        f"auto-discover smoke should pass for every adapter; got returncode={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # Every discovered adapter must show in stdout — the discovery contract.
    for name in (".claude-plugin", ".codex-plugin", ".future-host-plugin"):
        assert name in result.stdout, (
            f"auto-discover dropped {name!r}; got stdout:\n{result.stdout}"
        )
    assert "All 3 adapter(s) passed" in result.stdout


def test_auto_discover_ignores_non_plugin_dirs(tmp_path: pathlib.Path) -> None:
    """Discovery must require BOTH the `.*-plugin` naming AND a plugin.json file.
    A dotted dir without plugin.json (e.g. `.github/`, `.vscode/`) is not an
    adapter and must not be smoked — otherwise dropping a `.github` in the repo
    would break CI.
    """
    # An adapter-shaped dir WITHOUT plugin.json must be silently ignored.
    (tmp_path / ".broken-plugin").mkdir()
    # A non-adapter dir starting with `.` must be ignored.
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "plugin.json").write_text("{}", encoding="utf-8")
    # One real adapter, so discovery doesn't fail-empty.
    adapter = tmp_path / ".claude-plugin"
    adapter.mkdir()
    (adapter / "plugin.json").write_text('{"name": "sumo-qa"}', encoding="utf-8")
    _write_mock_mcp_json(tmp_path, MOCK_SERVER)

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (
        f"discovery should succeed with one real adapter; got returncode={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert ".github" not in result.stdout, (
        f"`.github/` must not be treated as an adapter; got stdout:\n{result.stdout}"
    )
    assert ".broken-plugin" not in result.stdout, (
        f"adapter without plugin.json must be skipped; got stdout:\n{result.stdout}"
    )
    assert "All 1 adapter(s) passed" in result.stdout


def test_auto_discover_fails_clearly_when_no_adapters_present(tmp_path: pathlib.Path) -> None:
    """Empty cwd must fail loudly with an actionable error pointing the user
    at the generator — not silently pass with zero coverage.
    """
    _write_mock_mcp_json(tmp_path, MOCK_SERVER)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "no `.*-plugin/` directories" in result.stderr
    assert "plugin_packaging.plugin_generator sync" in result.stderr


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
