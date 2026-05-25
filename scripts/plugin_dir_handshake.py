#!/usr/bin/env python3
# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Drive an MCP handshake against the server declared in a plugin's `.mcp.json`.

Used by the `plugin-dir handshake` job in .github/workflows/install-smoke.yml
to prove the generated plugin manifests (`.claude-plugin/`, `.codex-plugin/`)
expose a working MCP server when read by their host's plugin loader.

Critical contract (same as scripts/uvx_smoke_handshake.py — PR #141):
stdin stays open until the id==2 (tools/list) response has been read off
stdout. Closing stdin earlier triggers the mcp library's cancel-in-flight-
handlers branch (mcp/server/lowlevel/server.py:685-690), losing the id==2
response on Linux's epoll scheduler. PR #141 fixed the uvx-spawn smoke;
this script fixes the second smoke that used the same broken pattern.

Reuses `run_handshake` from scripts/uvx_smoke_handshake.py so the contract
has one source of truth and the existing regression test
(tests/test_uvx_smoke_handshake.py) keeps protecting it.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_HANDSHAKE_SCRIPT = _SCRIPTS_DIR / "uvx_smoke_handshake.py"

# Load uvx_smoke_handshake.py as a module — scripts/ is not a package, so a
# normal import doesn't work. Register in sys.modules BEFORE exec_module so
# @dataclass decoration inside the module can resolve its containing module.
_MODULE_NAME = "_uvx_smoke_handshake_for_plugin_dir"
_spec = importlib.util.spec_from_file_location(_MODULE_NAME, _HANDSHAKE_SCRIPT)
assert _spec is not None and _spec.loader is not None, (
    f"failed to load handshake module from {_HANDSHAKE_SCRIPT}"
)
_handshake_mod = importlib.util.module_from_spec(_spec)
sys.modules[_MODULE_NAME] = _handshake_mod
_spec.loader.exec_module(_handshake_mod)
run_handshake = _handshake_mod.run_handshake
_dump_diagnostic = _handshake_mod._dump_diagnostic


def _discover_adapters(root: Path) -> list[Path]:
    """Return every plugin-adapter directory under `root` (sorted, stable order).

    Convention: an adapter is any directory whose name matches `.*-plugin` and
    which contains a `plugin.json` file. Catches `.claude-plugin`,
    `.codex-plugin`, and any future host adapter the canonical generator
    emits without requiring a CI matrix edit.
    """
    return sorted(p for p in root.glob(".*-plugin") if (p / "plugin.json").is_file())


def _handshake_one(adapter: Path, mcp_path: Path, deadline_secs: float, tool_prefix: str) -> bool:
    """Drive the MCP handshake for one adapter. Returns True on success."""
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    try:
        server_name, entry = next(iter(mcp["mcpServers"].items()))
    except (KeyError, StopIteration):
        sys.stderr.write(f"error: no mcpServers entry in {mcp_path}\n")
        return False

    # Substitute ${CLAUDE_PLUGIN_ROOT} with cwd (matches what Claude Code
    # does at runtime per https://code.claude.com/docs/en/mcp#plugin-provided-mcp-servers).
    # `os.path.expandvars` reads `os.environ`, so set there before expansion.
    os.environ["CLAUDE_PLUGIN_ROOT"] = os.path.abspath(".")
    cmd_args = [os.path.expandvars(a) if isinstance(a, str) else a for a in entry.get("args", [])]
    cmd = [os.path.expandvars(entry["command"]), *cmd_args]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    result = run_handshake(cmd, deadline_secs=deadline_secs, env=env, tool_prefix=tool_prefix)

    if result.success:
        print(f"{adapter}: MCP handshake OK (server={server_name}, {result.tool_count} tools)")
        return True

    sys.stderr.write(f"{adapter}: MCP handshake FAILED (server={server_name})\n")
    _dump_diagnostic(result)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--adapter",
        default=None,
        help=(
            "Plugin adapter directory to smoke (e.g. .claude-plugin). "
            "If omitted, auto-discover every `.*-plugin/` directory under cwd "
            "that contains a plugin.json and smoke each one. The auto-discover "
            "path is what makes this future-proof: a new host adapter added to "
            "plugin_packaging/plugin_generator.py is automatically picked up "
            "by CI with no workflow edit."
        ),
    )
    parser.add_argument(
        "--mcp-json",
        default=".mcp.json",
        help="Path to .mcp.json (default: .mcp.json in cwd)",
    )
    parser.add_argument("--deadline-secs", type=float, default=20.0)
    parser.add_argument("--tool-prefix", default="sumo_qa_")
    args = parser.parse_args(argv)

    mcp_path = Path(args.mcp_json)
    if not mcp_path.is_file():
        sys.stderr.write(f"error: {mcp_path} not found\n")
        return 2

    if args.adapter is not None:
        adapters = [Path(args.adapter)]
        for a in adapters:
            if not (a / "plugin.json").is_file():
                sys.stderr.write(f"error: {a / 'plugin.json'} not found\n")
                return 2
    else:
        adapters = _discover_adapters(Path("."))
        if not adapters:
            sys.stderr.write(
                "error: no `.*-plugin/` directories with plugin.json found under cwd. "
                "Run `python -m plugin_packaging.plugin_generator sync` to regenerate, "
                "or pass --adapter explicitly.\n"
            )
            return 2
        print(f"Auto-discovered {len(adapters)} adapter(s): {', '.join(str(a) for a in adapters)}")

    failures = 0
    for adapter in adapters:
        if not _handshake_one(adapter, mcp_path, args.deadline_secs, args.tool_prefix):
            failures += 1

    if failures:
        sys.stderr.write(f"\n{failures} of {len(adapters)} adapter(s) failed handshake\n")
        return 1
    print(f"\nAll {len(adapters)} adapter(s) passed handshake")
    return 0


if __name__ == "__main__":  # pragma: no cover -- main guard
    sys.exit(main())
