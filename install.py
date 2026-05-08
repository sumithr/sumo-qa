#!/usr/bin/env python3
"""Cross-platform installer for sumo-qa.

Runs on Windows, macOS, and Linux. Installs the MCP server via uv,
symlinks skills/ into Claude Code's skills dir (or copies on Windows
without developer mode), and prints the host-specific config snippet.

Usage:
    python install.py
"""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SKILLS_SRC = REPO_ROOT / "skills"


def main() -> int:
    system = platform.system()
    print(f"sumo-qa installer — detected OS: {system}")

    _install_mcp_server()
    _install_claude_code_skills(system)
    _print_config_instructions(system)
    return 0


def _install_mcp_server() -> None:
    print("\n[1/3] Installing the MCP server via uv...")
    if shutil.which("uv") is None:
        print("ERROR: uv is not installed. Install it first:")
        print("  macOS / Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh")
        print('  Windows (PS):   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"')
        sys.exit(1)
    subprocess.run(
        ["uv", "tool", "install", "--from", str(REPO_ROOT), "sumo-qa-mcp"],
        check=True,
    )
    print("  done.")


def _install_claude_code_skills(system: str) -> None:
    print("\n[2/3] Installing Claude Code skill links...")
    home = Path.home()
    target = home / ".claude" / "skills" / "sumo-qa"
    if not target.parent.exists():
        print(f"  Claude Code config dir not found at {target.parent}; skipping.")
        print(f"  Skills are still available via MCP prompts on every host.")
        return
    if target.exists() or target.is_symlink():
        if target.is_symlink() or target.is_file():
            target.unlink()
        else:
            shutil.rmtree(target)
    try:
        target.symlink_to(SKILLS_SRC, target_is_directory=True)
        print(f"  symlinked {SKILLS_SRC} -> {target}")
    except OSError as exc:
        if system == "Windows":
            shutil.copytree(SKILLS_SRC, target)
            print(
                f"  Windows developer mode off — copied skills to {target}.\n"
                f"  Re-run install.py after editing skills/ to refresh."
            )
        else:
            raise


def _print_config_instructions(system: str) -> None:
    print("\n[3/3] Add this MCP server to your host's config:")
    snippet = json.dumps(
        {"mcpServers": {"sumo-qa": {"command": "sumo-qa-mcp"}}},
        indent=2,
    )
    print("\n" + snippet + "\n")
    print("Per-host config file:")
    if system == "Windows":
        print("  Claude Code:  %APPDATA%\\Claude\\claude_desktop_config.json")
    else:
        print("  Claude Code:  ~/.config/claude/claude_desktop_config.json")
    print("  IntelliJ:     Settings -> Tools -> AI Assistant -> MCP -> Add server")
    print("  VS Code:      .vscode/mcp.json (workspace) or VS Code MCP settings")
    print("\nSee AGENTS.md for the full per-host walkthrough.")


if __name__ == "__main__":
    sys.exit(main())
