#!/usr/bin/env python3
"""sumo-qa installer.

Installs the MCP server via uv, then auto-configures every supported host
found on this machine using the absolute path to the binary (so hosts that
don't inherit the user shell PATH still find it).

- Claude Code: symlinks skills/ into ~/.claude/skills/sumo-qa and writes
  the MCP server entry into claude_desktop_config.json.
- VS Code + Copilot: writes .vscode/mcp.json in the current workspace.
- IntelliJ AI Assistant: detects the latest installation and prints the
  exact Settings-UI fields to fill in (with the absolute binary path).
  The JetBrains MCP plugin's options XML schema isn't publicly documented
  and varies by IntelliJ version, so we don't write the XML directly to
  avoid corrupting user configs.

Idempotent. Re-run to refresh after updates. Runs on Windows, macOS, Linux.

Requires Python 3.10+. If you see a SyntaxError around type annotations,
you're running Python 2 (`python` on macOS resolves there by default).
Use `python3 install.py` instead.
"""
from __future__ import annotations

import sys
if sys.version_info < (3, 10):
    sys.stderr.write(
        "install.py requires Python 3.10+ (you have "
        f"{sys.version_info.major}.{sys.version_info.minor}).\n"
        "Run: python3 install.py\n"
    )
    sys.exit(1)

import json
import os
import platform
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
SKILLS_SRC = REPO_ROOT / "skills"


class HostResult:
    """Per-host install outcome."""

    def __init__(self, host: str) -> None:
        self.host = host
        self.detected = False
        self.configured = False
        self.config_path: Path | None = None
        self.message = ""
        self.followup: str = ""

    def render(self) -> str:
        if self.configured:
            mark = "OK"
        elif self.detected:
            mark = "..."
        else:
            mark = "skip"
        line = f"  [{mark}] {self.host}: {self.message}"
        if self.followup:
            line += f"\n{self.followup}"
        return line


def main() -> int:
    system = platform.system()
    print(f"sumo-qa installer  (OS: {system})\n")

    mcp_path = _install_mcp_binary()
    if mcp_path is None:
        return 1
    print(f"\nMCP binary: {mcp_path}\n")

    results = [
        _setup_claude_code(mcp_path, system),
        _setup_vscode_copilot(mcp_path),
        _setup_intellij(mcp_path, system),
    ]

    print("Host setup:")
    for r in results:
        print(r.render())

    print()
    ok = _verify_mcp_responds(mcp_path)
    print()
    if ok:
        print("Installation complete. Restart any host you just configured.")
        return 0
    print("Installation finished but the MCP did not respond cleanly to a")
    print("JSON-RPC initialize ping. Check that the binary is healthy:")
    print(f"  {mcp_path}")
    return 2


# ----------------------------------------------------------------------
# MCP binary
# ----------------------------------------------------------------------

def _install_mcp_binary() -> Path | None:
    print("Installing the MCP server via uv...")
    if shutil.which("uv") is None:
        print("  ERROR: uv is not installed. Install it first:")
        print("    macOS / Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh")
        print('    Windows (PS):   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"')
        print("  Then re-run: python install.py")
        return None
    try:
        subprocess.run(
            ["uv", "tool", "install", "--from", str(REPO_ROOT), "sumo-qa", "--reinstall"],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"  ERROR: uv tool install failed ({exc.returncode})")
        return None
    binary = shutil.which("sumo-qa-mcp")
    if binary is None:
        # Fall back to the conventional uv tool bin dir.
        for candidate in [
            Path.home() / ".local" / "bin" / "sumo-qa-mcp",
            Path.home() / ".local" / "share" / "uv" / "tools" / "sumo-qa" / "bin" / "sumo-qa-mcp",
        ]:
            if candidate.is_file():
                return candidate.resolve()
        print("  ERROR: uv install succeeded but sumo-qa-mcp is not on PATH and")
        print("  not at any conventional uv tool location. Restart your shell")
        print("  and re-run python install.py.")
        return None
    return Path(binary).resolve()


# ----------------------------------------------------------------------
# Claude Code
# ----------------------------------------------------------------------

def _setup_claude_code(mcp_path: Path, system: str) -> HostResult:
    r = HostResult("Claude Code")
    home = Path.home()

    if system == "Windows":
        config_dir = Path(os.environ.get("APPDATA", "")) / "Claude"
    elif system == "Darwin":
        config_dir = home / ".config" / "claude"
    else:
        config_dir = home / ".config" / "claude"

    claude_home = home / ".claude"

    if not (claude_home.exists() or config_dir.exists()):
        r.message = "not detected on this machine"
        return r

    r.detected = True

    # 1. Skills symlink
    skills_target = claude_home / "skills" / "sumo-qa"
    skills_target.parent.mkdir(parents=True, exist_ok=True)
    skills_msg = _install_skills_link(skills_target, system)

    # 2. claude_desktop_config.json
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "claude_desktop_config.json"
    config: dict = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            r.message = (
                f"{config_path} exists but is invalid JSON; not modifying. "
                f"Add manually:\n"
                f'    "sumo-qa": {{ "command": "{mcp_path}" }}'
            )
            return r
    config.setdefault("mcpServers", {})
    config["mcpServers"]["sumo-qa"] = {"command": str(mcp_path)}
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    r.configured = True
    r.config_path = config_path
    r.message = f"{skills_msg}; wrote {config_path}"
    return r


def _install_skills_link(target: Path, system: str) -> str:
    """Symlink (or copy on Windows w/o devmode) skills into the target path."""
    if target.exists() or target.is_symlink():
        if target.is_symlink() or target.is_file():
            target.unlink()
        else:
            shutil.rmtree(target)
    try:
        target.symlink_to(SKILLS_SRC, target_is_directory=True)
        return f"symlinked {target}"
    except OSError:
        if system == "Windows":
            shutil.copytree(SKILLS_SRC, target)
            return (
                f"copied skills to {target} (Windows developer mode off; "
                f"re-run install.py to refresh after edits)"
            )
        raise


# ----------------------------------------------------------------------
# VS Code + GitHub Copilot
# ----------------------------------------------------------------------

def _setup_vscode_copilot(mcp_path: Path) -> HostResult:
    r = HostResult("VS Code + Copilot")
    workspace = Path.cwd()

    # Only write if we look like we're in a workspace (this is the install
    # script's CWD, which the user ran from the repo). Use that workspace's
    # .vscode/ dir. If we're running from the repo root, .vscode/ is the
    # repo's; if we're running from a different workspace, that workspace's.
    if not (workspace / ".git").exists() and not (workspace / ".vscode").exists():
        r.message = (
            f"skipped: no .git or .vscode in {workspace}; not a workspace. "
            "Run install.py from within a workspace to configure it."
        )
        return r

    r.detected = True
    vscode_dir = workspace / ".vscode"
    vscode_dir.mkdir(exist_ok=True)
    config_path = vscode_dir / "mcp.json"

    config: dict = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            r.message = (
                f"{config_path} exists but is invalid JSON; not modifying. "
                f'Add manually: "sumo-qa": {{ "command": "{mcp_path}" }}'
            )
            return r

    config.setdefault("mcpServers", {})
    config["mcpServers"]["sumo-qa"] = {"command": str(mcp_path)}
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    r.configured = True
    r.config_path = config_path
    r.message = f"wrote {config_path}"
    return r


# ----------------------------------------------------------------------
# IntelliJ AI Assistant
# ----------------------------------------------------------------------

_JB_IDE_PREFIXES = (
    "IntelliJIdea",
    "PyCharm",
    "GoLand",
    "WebStorm",
    "RubyMine",
    "PhpStorm",
    "CLion",
    "Rider",
    "DataGrip",
    "AppCode",
    "AndroidStudio",
)


def _setup_intellij(mcp_path: Path, system: str) -> HostResult:
    r = HostResult("JetBrains IDEs")
    home = Path.home()

    if system == "Darwin":
        jb_root = home / "Library" / "Application Support" / "JetBrains"
    elif system == "Windows":
        jb_root = Path(os.environ.get("APPDATA", "")) / "JetBrains"
    else:
        jb_root = home / ".config" / "JetBrains"

    if not jb_root.exists():
        r.message = "not detected (no JetBrains config dir)"
        return r

    # Find every JetBrains IDE installation that has an options/ dir.
    # We write to all of them so any IDE the user opens picks up sumo-qa.
    ide_dirs = sorted(
        (
            p for p in jb_root.iterdir()
            if p.is_dir()
            and any(p.name.startswith(prefix) for prefix in _JB_IDE_PREFIXES)
            and (p / "options").exists()
        ),
        key=lambda p: p.name,
        reverse=True,
    )
    if not ide_dirs:
        r.message = "no JetBrains IDE installation found"
        return r

    r.detected = True
    written: list[str] = []
    for ide_dir in ide_dirs:
        xml_path = ide_dir / "options" / "llm.mcpServers.xml"
        try:
            _write_intellij_mcp_entry(xml_path, mcp_path)
            written.append(ide_dir.name)
        except (ET.ParseError, OSError) as exc:
            # Don't fail the whole install if one IDE config is malformed
            print(f"  ! {ide_dir.name}: {exc}")

    if written:
        r.configured = True
        r.config_path = ide_dirs[0] / "options" / "llm.mcpServers.xml"
        r.message = (
            f"wrote sumo-qa entry to {len(written)} IDE config(s): "
            f"{', '.join(written)}"
        )
        r.followup = (
            "      Restart any open JetBrains IDE so the new MCP entry loads.\n"
            "      Then in AI Assistant chat type /sumo_qa_load_classifications\n"
            "      to verify."
        )
    else:
        r.message = (
            f"detected {len(ide_dirs)} IDE(s) but none could be updated. "
            "Add manually in Settings -> Tools -> AI Assistant -> Model Context Protocol "
            f"with command: {mcp_path}"
        )
    return r


def _write_intellij_mcp_entry(xml_path: Path, mcp_path: Path) -> None:
    """Write or update the sumo-qa MCP entry in JetBrains' llm.mcpServers.xml.

    Schema reverse-engineered from a working install:

        <application>
          <component name="McpApplicationServerCommands" modifiable="true">
            <McpServerCommand sourceId="UserConfigurationSource">
              <option name="allowedToolsNames" />
              <option name="enabled" value="true" />
              <option name="name" value="sumo-qa" />
              <option name="programPath" value="<absolute path>" />
              <option name="arguments" value="" />
              <option name="workingDirectory" value="" />
              <envs />
            </McpServerCommand>
          </component>
        </application>
    """
    if xml_path.exists():
        tree = ET.parse(xml_path)
        root = tree.getroot()
    else:
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        root = ET.Element("application")
        tree = ET.ElementTree(root)

    component = root.find("component[@name='McpApplicationServerCommands']")
    if component is None:
        component = ET.SubElement(
            root,
            "component",
            {"name": "McpApplicationServerCommands", "modifiable": "true"},
        )

    # Look for an existing sumo-qa entry; update it in place if present.
    existing = None
    for cmd in component.findall("McpServerCommand"):
        name_opt = cmd.find("option[@name='name']")
        if name_opt is not None and name_opt.get("value") == "sumo-qa":
            existing = cmd
            break

    if existing is not None:
        # Refresh programPath + ensure enabled. Leave other fields alone so
        # any user tweaks (allowed tool restrictions, env vars) are preserved.
        program_opt = existing.find("option[@name='programPath']")
        if program_opt is None:
            program_opt = ET.SubElement(existing, "option", {"name": "programPath"})
        program_opt.set("value", str(mcp_path))
        enabled_opt = existing.find("option[@name='enabled']")
        if enabled_opt is None:
            enabled_opt = ET.SubElement(existing, "option", {"name": "enabled"})
        enabled_opt.set("value", "true")
    else:
        cmd = ET.SubElement(
            component, "McpServerCommand", {"sourceId": "UserConfigurationSource"}
        )
        ET.SubElement(cmd, "option", {"name": "allowedToolsNames"})
        ET.SubElement(cmd, "option", {"name": "enabled", "value": "true"})
        ET.SubElement(cmd, "option", {"name": "name", "value": "sumo-qa"})
        ET.SubElement(cmd, "option", {"name": "programPath", "value": str(mcp_path)})
        ET.SubElement(cmd, "option", {"name": "arguments", "value": ""})
        ET.SubElement(cmd, "option", {"name": "workingDirectory", "value": ""})
        ET.SubElement(cmd, "envs")

    # Pretty-print with 2-space indent matching JetBrains' own format.
    ET.indent(tree, space="  ", level=0)
    tree.write(xml_path, encoding="UTF-8", xml_declaration=False)


# ----------------------------------------------------------------------
# Verification
# ----------------------------------------------------------------------

def _verify_mcp_responds(mcp_path: Path) -> bool:
    """Send a JSON-RPC initialize and confirm the binary responds."""
    print("Verifying the MCP responds to initialize...")
    init_req = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "install.py", "version": "1"},
            },
        }
    )
    try:
        proc = subprocess.run(
            [str(mcp_path)],
            input=init_req + "\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        print("  WARNING: MCP did not respond within 10s.")
        return False
    if proc.stdout and '"result"' in proc.stdout:
        print("  MCP responded to initialize.")
        return True
    print("  WARNING: MCP did not return a result.")
    if proc.stdout:
        print(f"    stdout: {proc.stdout[:300]}")
    if proc.stderr:
        print(f"    stderr: {proc.stderr[:300]}")
    return False


if __name__ == "__main__":
    sys.exit(main())
