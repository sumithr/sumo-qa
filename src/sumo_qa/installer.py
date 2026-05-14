# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""sumo-qa installer.

Shipped as the `sumo-qa-install` console script (exposed via [project.scripts]
in pyproject.toml). After `pip install sumo-qa`, both `sumo-qa` (the MCP
server) and `sumo-qa-install` (this) land on PATH automatically — on Windows
pip generates `.exe` wrappers, so users don't fight `python` vs `python3` vs
`py`.

What this script does:

- Locates the `sumo-qa` MCP binary. If pip already put it on PATH (the
  common case), uses that path directly — does NOT invoke uv. Falls back
  to `uv tool install` only when the binary is not yet on PATH.
- Claude Code: symlinks skills/ into ~/.claude/skills/sumo-qa and writes
  the MCP server entry into claude_desktop_config.json.
- VS Code + Copilot: writes .vscode/mcp.json in the current workspace.
- IntelliJ AI Assistant: detects the latest installation and prints the
  exact Settings-UI fields to fill in (with the absolute binary path).
  The JetBrains MCP plugin's options XML schema isn't publicly documented
  and varies by IntelliJ version, so we don't write the XML directly to
  avoid corrupting user configs.

Idempotent. Re-run to refresh after updates. Runs on Windows, macOS, Linux.

Requires Python 3.10+ (enforced by [project.requires-python] in pyproject).
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 10):
    sys.stderr.write(
        "sumo-qa-install requires Python 3.10+ (you have "
        f"{sys.version_info.major}.{sys.version_info.minor}).\n"
    )
    sys.exit(1)

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

# Mode detection: are we running from inside an installed wheel
# (sumo_qa/_data/skills/ bundled next to this module) or from a git
# clone / editable install (skills/ live at the repo root)?
#
# Hatch's [tool.hatch.build.targets.wheel.force-include] copies skills/
# into sumo_qa/_data/skills/ in built wheels but NOT in editable installs
# (`pip install -e .`), so editable-mode contributors transparently get
# the git-clone branch and pick up live edits to skills/.
_MODULE_DIR = Path(__file__).resolve().parent
_BUNDLED_SKILLS = _MODULE_DIR / "_data" / "skills"

if _BUNDLED_SKILLS.is_dir():
    # Installed-wheel mode. Skills come from the bundled data; the MCP
    # binary is already on PATH (pip put us here), so uv tool install
    # should pull from PyPI by name rather than from a local path.
    REPO_ROOT = _MODULE_DIR  # unused in this mode; kept defined for type-checking
    SKILLS_SRC = _BUNDLED_SKILLS
    _UV_INSTALL_FROM: list[str] = []  # `uv tool install sumo-qa` (no --from)
else:
    # Git-clone / editable-install mode. installer.py lives at
    # <repo>/src/sumo_qa/installer.py, so the repo root is two parents
    # above the module directory: src/sumo_qa → src → <repo>.
    REPO_ROOT = _MODULE_DIR.parent.parent
    if not (REPO_ROOT / "pyproject.toml").is_file():
        sys.stderr.write(
            "sumo-qa-install: could not locate bundled skills or a repo "
            "root. If you installed via pip, please file an issue with your "
            "Python and pip versions; if you're running from a clone, "
            "ensure the standard repo layout.\n"
        )
        sys.exit(1)
    SKILLS_SRC = REPO_ROOT / "skills"
    _UV_INSTALL_FROM = ["--from", str(REPO_ROOT)]


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
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Install sumo-qa MCP for one or more hosts. With no host flags, "
            "configures every supported host found on this machine."
        ),
    )
    parser.add_argument(
        "--claude-code",
        action="store_true",
        help="Configure Claude Code only (symlink skills + write claude_desktop_config.json).",
    )
    parser.add_argument(
        "--vscode",
        action="store_true",
        help=(
            "Configure VS Code + Copilot only. Writes .vscode/mcp.json in the "
            "current workspace (or use --workspace to point elsewhere)."
        ),
    )
    parser.add_argument(
        "--jetbrains",
        action="store_true",
        help="Print JetBrains setup instructions only.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help=(
            "VS Code workspace path. Defaults to the current directory. "
            "Required if CWD is your home directory (VS Code won't read "
            "~/.vscode/mcp.json — that's not a workspace)."
        ),
    )
    parser.add_argument(
        "--skip-mcp-install",
        action="store_true",
        help="Don't reinstall the MCP binary via uv (assume it's already installed).",
    )
    args = parser.parse_args()

    # If no host flag is set, default to all.
    explicit_hosts = bool(args.claude_code or args.vscode or args.jetbrains)
    do_claude = args.claude_code or not explicit_hosts
    do_vscode = args.vscode or not explicit_hosts
    do_jetbrains = args.jetbrains or not explicit_hosts

    system = platform.system()
    print(f"sumo-qa installer  (OS: {system})")
    hosts_str = ", ".join(
        h
        for h, do in [
            ("Claude Code", do_claude),
            ("VS Code", do_vscode),
            ("JetBrains", do_jetbrains),
        ]
        if do
    )
    print(f"Configuring: {hosts_str}\n")

    if args.skip_mcp_install:
        binary = shutil.which("sumo-qa")
        mcp_path = Path(binary).resolve() if binary else None
        if mcp_path is None:
            print("ERROR: --skip-mcp-install was set but sumo-qa is not on PATH.")
            return 1
        print(f"MCP binary (existing): {mcp_path}\n")
    else:
        mcp_path = _install_mcp_binary()
        if mcp_path is None:
            return 1
        print(f"\nMCP binary: {mcp_path}\n")

    workspace = args.workspace.resolve() if args.workspace else Path.cwd()

    results: list[HostResult] = []
    if do_claude:
        results.append(_setup_claude_code(mcp_path, system))
    if do_vscode:
        results.append(_setup_vscode_copilot(mcp_path, workspace))
    if do_jetbrains:
        results.append(_setup_intellij(mcp_path, system))

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
    # Fast path: if the user already has `sumo-qa` on PATH — because they
    # installed sumo-qa via pip / pipx / uv tool / their own venv — we don't
    # need to install it a second time. Use the path they already have.
    existing = shutil.which("sumo-qa")
    if existing is not None:
        resolved = Path(existing).resolve()
        print(f"Using existing sumo-qa binary at {resolved}")
        return resolved

    # Fall back to uv tool install. This branch is mostly for users who
    # somehow ran sumo-qa-install without pip-installing sumo-qa first
    # (e.g. from a fresh clone with a dev environment that doesn't add
    # console scripts to PATH).
    print("sumo-qa not on PATH. Installing the MCP server via uv...")
    if shutil.which("uv") is None:
        print("  ERROR: uv is not installed and sumo-qa is not on PATH.")
        print("  The simplest fix is to install sumo-qa via pip (no uv needed):")
        print("    pip install --upgrade sumo-qa")
        print("  Or, if you prefer uv, install it first:")
        print("    macOS / Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh")
        print('    Windows (PS):   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"')
        print("  Then re-run: sumo-qa-install")
        return None
    try:
        subprocess.run(
            ["uv", "tool", "install", *_UV_INSTALL_FROM, "sumo-qa", "--reinstall"],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"  ERROR: uv tool install failed ({exc.returncode})")
        return None
    binary = shutil.which("sumo-qa")
    if binary is None:
        # Fall back to the conventional uv tool bin dir.
        for candidate in [
            Path.home() / ".local" / "bin" / "sumo-qa",
            Path.home() / ".local" / "share" / "uv" / "tools" / "sumo-qa" / "bin" / "sumo-qa",
        ]:
            if candidate.is_file():
                return candidate.resolve()
        print("  ERROR: uv install succeeded but sumo-qa is not on PATH and")
        print("  not at any conventional uv tool location. Restart your shell")
        print("  and re-run sumo-qa-install.")
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

    # 1. Symlink each skill directory individually at the TOP LEVEL of
    #    ~/.claude/skills/.
    #
    #    Why per-skill, not a wrapper: Claude Code reads skills at
    #    ~/.claude/skills/<name>/SKILL.md. It does NOT recurse into
    #    subdirectories. So a wrapper like ~/.claude/skills/sumo-qa/qa-*
    #    is invisible to Claude Code's discovery; only top-level names
    #    surface in the slash menu.
    #
    #    Also clean up: previous install.py versions used the wrapper and
    #    earlier versions left stale copies at the top level. This pass
    #    removes both so the user ends with one fresh symlink per skill
    #    directory found under SKILLS_SRC.
    skills_dir = claude_home / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    symlink_msg = _install_claude_code_skills_per_dir(skills_dir, system)

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
    r.message = f"{symlink_msg}; wrote {config_path}"
    return r


def _install_claude_code_skills_per_dir(skills_dir: Path, system: str) -> str:
    """Symlink each skills/<name>/ directory individually at the top level of
    ~/.claude/skills/. Cleans up the legacy wrapper (sumo-qa/) and any stale
    top-level copies left by earlier install.py versions.

    Claude Code's native skill discovery reads top-level directories only —
    nested subdirectories are invisible. So skills MUST sit directly under
    ~/.claude/skills/ to surface in the slash menu.

    Returns a one-line summary for the install.py output.
    """
    # 1. Cleanup the legacy wrapper.
    wrapper = skills_dir / "sumo-qa"
    if wrapper.is_symlink() or wrapper.is_file():
        wrapper.unlink()
    elif wrapper.is_dir():
        shutil.rmtree(wrapper)

    # 2. Cleanup any stale top-level copies of OUR skills (only the ones in
    #    repo/skills/) — don't touch other unrelated skills the user has
    #    installed (e.g. codex-review, graphify).
    repo_skill_names = {p.name for p in SKILLS_SRC.iterdir() if p.is_dir()}

    cleaned: list[str] = []
    for name in repo_skill_names:
        target = skills_dir / name
        if not (target.exists() or target.is_symlink()):
            continue
        if target.is_symlink():
            target.unlink()
            cleaned.append(name)
            continue
        # Real directory or file — only delete if its content matches our
        # repo version (so we don't accidentally nuke a user-customised one).
        repo_skill = SKILLS_SRC / name / "SKILL.md"
        target_skill = target / "SKILL.md"
        if (
            target.is_dir()
            and repo_skill.is_file()
            and target_skill.is_file()
            and repo_skill.read_text() == target_skill.read_text()
        ):
            shutil.rmtree(target)
            cleaned.append(name)

    # 3. Symlink each skill dir from the repo to the top level.
    linked: list[str] = []
    copied: list[str] = []
    for name in sorted(repo_skill_names):
        src = SKILLS_SRC / name
        if not src.is_dir():
            continue
        target = skills_dir / name
        try:
            target.symlink_to(src, target_is_directory=True)
            linked.append(name)
        except OSError:
            if system == "Windows":
                shutil.copytree(src, target)
                copied.append(name)
            else:
                raise

    parts = []
    if cleaned:
        parts.append(f"cleaned up {len(cleaned)} stale entries")
    parts.append(f"symlinked {len(linked)} skills")
    if copied:
        parts.append(f"copied {len(copied)} (Windows fallback)")
    return "; ".join(parts) + f" under {skills_dir}"


# ----------------------------------------------------------------------
# VS Code + GitHub Copilot
# ----------------------------------------------------------------------


def _setup_vscode_copilot(mcp_path: Path, workspace: Path) -> HostResult:
    r = HostResult("VS Code + Copilot")

    # Refuse to write to the user's home directory. VS Code reads
    # .vscode/mcp.json from the WORKSPACE root, not from $HOME. Writing to
    # ~/.vscode/mcp.json silently does nothing useful.
    if workspace == Path.home():
        r.message = (
            "skipped: refused to write to $HOME/.vscode/mcp.json — VS Code "
            "only reads .vscode/mcp.json from a workspace root, not from "
            "your home directory. Re-run with --workspace <path-to-repo> "
            "from inside a workspace, or use Cmd+Shift+P -> MCP: Add Server "
            "in VS Code to set it user-wide."
        )
        return r

    # Heuristic: a workspace has either a .git dir, an existing .vscode dir,
    # or a recognisable project file. If none, surface a clear skip rather
    # than write to an arbitrary path.
    project_markers = [
        ".git",
        ".vscode",
        "package.json",
        "pyproject.toml",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "Cargo.toml",
        "go.mod",
    ]
    if not any((workspace / marker).exists() for marker in project_markers):
        r.message = (
            f"skipped: {workspace} doesn't look like a workspace (no .git, "
            ".vscode, or project file). Re-run with --workspace <path> from "
            "inside a real project, or use Cmd+Shift+P -> MCP: Add Server "
            "in VS Code to set it user-wide."
        )
        return r

    r.detected = True
    vscode_dir = workspace / ".vscode"
    vscode_dir.mkdir(exist_ok=True)
    config_path = vscode_dir / "mcp.json"

    # VS Code Copilot's MCP config schema:
    #   { "servers": { "<name>": { "type": "stdio", "command": "...", "args": [] } } }
    # Note: this is DIFFERENT from Claude Desktop / Claude Code's schema
    # ({ "mcpServers": { ... } } without a "type" field). VS Code ignores
    # the mcpServers key entirely. We write the VS Code-native format.
    config: dict = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            r.message = (
                f"{config_path} exists but is invalid JSON; not modifying. "
                f'Add manually: "sumo-qa": {{ "type": "stdio", "command": "{mcp_path}" }}'
            )
            return r

    # Strip any legacy mcpServers key from previous install.py runs — VS Code
    # never used it, leaving it as noise is harmful (looks configured when
    # it isn't).
    config.pop("mcpServers", None)

    config.setdefault("servers", {})
    config["servers"]["sumo-qa"] = {
        "type": "stdio",
        "command": str(mcp_path),
        "args": [],
    }
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
    """Print manual setup instructions for JetBrains IDEs.

    History note (left here so future-us doesn't re-walk this path): earlier
    versions of install.py tried to write llm.mcpServers.xml directly to
    pre-register sumo-qa. That worked once, then failed unreliably — IntelliJ
    silently dropped externally-written entries between IDE startup and steady
    state on IDEA 2026.1, leaving entries marked disabled with a generic
    "LazyStandaloneCoroutine was cancelled" error. We could not reverse-
    engineer the JetBrains MCP plugin's internal flow to make external writes
    stick reliably. The Settings UI add does work — that's what we point at.
    """
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

    ide_dirs = sorted(
        (
            p
            for p in jb_root.iterdir()
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
    latest = ide_dirs[0]
    r.message = (
        f"detected {latest.name} (and {len(ide_dirs) - 1} other IDE(s)). "
        "JetBrains MCP plugin requires one-time Settings-UI add."
    )
    r.followup = (
        "      In any JetBrains IDE, open the chat / AI Assistant panel,\n"
        "      then:\n"
        "        Settings -> Tools -> AI Assistant -> Model Context Protocol\n"
        "        Click + Add server, fill in:\n"
        "          Name:    sumo-qa\n"
        f"          Command: {mcp_path}\n"
        "          Arguments / Working directory: leave empty\n"
        "        Apply.\n"
        "\n"
        "      Why manual: external writes to JetBrains' MCP config XML are\n"
        "      not reliably picked up on IDEA 2026.1 (we tried). The UI add\n"
        "      registers it via the supported path and persists across\n"
        "      restarts."
    )
    return r


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
                "clientInfo": {"name": "sumo-qa-install", "version": "1"},
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
