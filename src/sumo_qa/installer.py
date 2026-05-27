# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""sumo-qa installer.

Shipped as the ``sumo-qa-install`` console script (exposed via
``[project.scripts]`` in pyproject.toml) and as ``python -m sumo_qa.installer``.
The module form is the PATH-proof entry point for shells where pip created
the script wrapper but the Python Scripts directory isn't on PATH (e.g.
Microsoft-Store Python on Windows, ``pip install --user`` on Linux without
``~/.local/bin`` exported).

What this script does:

- Decides how the MCP server should be invoked by hosts: if pip's
  ``sumo-qa`` wrapper is on PATH, uses it; otherwise configures hosts to
  call ``<sys.executable> -m sumo_qa`` directly. Never installs a second
  package manager (no uv fallback) — the installer trusts the interpreter
  that was used to launch it.
- Claude Code: symlinks skills/ into ``~/.claude/skills/``, registers the
  MCP server via ``claude mcp add -s user``, and writes
  ``claude_desktop_config.json`` (the latter is a no-op for Claude Code
  itself but harmless if Claude Desktop is also installed).
- VS Code + Copilot: writes ``.vscode/mcp.json`` in the current workspace.
- IntelliJ AI Assistant: detects the latest installation and prints the
  exact Settings-UI fields to fill in (Command + Arguments). The JetBrains
  MCP plugin's options XML schema isn't publicly documented and varies
  by IntelliJ version, so we don't write the XML directly to avoid
  corrupting user configs.

Idempotent. Re-run to refresh after updates. Runs on Windows, macOS, Linux.

Requires Python 3.10+ (enforced by [project.requires-python] in pyproject).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

if sys.version_info < (
    3,
    10,
):  # pragma: no cover -- defensive exit for Python <3.10 (CI runs 3.10+)
    sys.stderr.write(
        "sumo-qa-install requires Python 3.10+ (you have "
        f"{sys.version_info.major}.{sys.version_info.minor}).\n"
    )
    sys.exit(1)

import collections
import json
import os
import platform
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

from sumo_qa.plugin_metadata import PluginMetadata

# Canonical plugin metadata — loaded once at import time from the bundled
# snapshot at sumo_qa/_data/plugin_metadata.json. Every host-config write
# site (claude_desktop_config.json, .vscode/mcp.json, `claude mcp add`)
# sources the MCP server name and command from here so adding a new host
# never requires a string-literal grep across the installer.
#
# NOT used: console-script wrapper lookups (`shutil.which("sumo-qa")`)
# and banner / error strings that reference the pip-managed
# `[project.scripts]` entry-point name. Those literals govern the script
# pip generates and intentionally stay decoupled from the runtime
# MCP-server identifier.
PLUGIN_METADATA = PluginMetadata.from_bundle()

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

# Canonical sumo-qa tool surface — exactly what the post-install handshake
# expects to find in the MCP's tools/list response. Kept in lock-step with
# the @mcp.tool decorators in src/sumo_qa/server.py; if a tool is added,
# renamed or removed there, update this tuple (and the matching tests).
REQUIRED_TOOL_NAMES: tuple[str, ...] = (
    # Test-data
    "sumo_qa_explain_test_data_requirements",
    "sumo_qa_find_test_data",
    "sumo_qa_validate_test_data",
    "sumo_qa_register_known_good_test_data",
    # Knowledge loaders
    "sumo_qa_load_classifications",
    "sumo_qa_load_approaches",
    "sumo_qa_load_principles",
    "sumo_qa_load_techniques",
    "sumo_qa_load_standards",
    "sumo_qa_load_rules",
    # Capabilities discovery
    "sumo_qa_capabilities",
    # Ingestion
    "sumo_qa_ingest_knowledge_pack",
    # External skills
    "sumo_qa_search_external_skills",
    "sumo_qa_check_external_skill_installed",
    "sumo_qa_install_external_skill",
    "sumo_qa_execute_external_skill",
)

# Truncate stdout/stderr to keep installer output readable when the MCP
# verification fails. 300 chars is enough to surface a Python traceback header
# or the first failing JSON-RPC line without flooding the terminal.
_DUMP_STREAM_CHARS = 300

# Overall budget for the JSON-RPC handshake (initialize + tools/list).
# Mirrors the legacy ``timeout=10`` literal on ``subprocess.run``; expressed
# as a constant so the value is visible at the top of the module instead of
# buried inside the verifier.
_VERIFY_TIMEOUT_SECONDS = 10


def _detect_install_mode(
    module_dir: Path = _MODULE_DIR,
    bundled_skills: Path = _BUNDLED_SKILLS,
) -> tuple[Path, Path]:
    """Return (REPO_ROOT, SKILLS_SRC) for the active install layout.

    Two arms:
    - Wheel mode: bundled skills exist next to this module → use them directly.
    - Editable / git-clone mode: skills live at the repo root two levels above
      the module dir.
    """
    if bundled_skills.is_dir():
        return module_dir, bundled_skills
    repo_root = module_dir.parent.parent
    if not (repo_root / "pyproject.toml").is_file():
        sys.stderr.write(
            "sumo-qa-install: could not locate bundled skills or a repo "
            "root. If you installed via pip, please file an issue with your "
            "Python and pip versions; if you're running from a clone, "
            "ensure the standard repo layout.\n"
        )
        sys.exit(1)
    return repo_root, repo_root / "skills"


REPO_ROOT, SKILLS_SRC = _detect_install_mode()


@dataclass(frozen=True)
class McpCommand:
    """How to invoke the sumo-qa MCP server.

    Two shapes the installer can return:
    - Single binary: ``McpCommand("/usr/local/bin/sumo-qa", [])`` — the
      console-script wrapper pip placed on PATH.
    - Module form: ``McpCommand(sys.executable, ["-m", "sumo_qa"])`` — used
      when the pip Scripts dir isn't on PATH (Microsoft-Store Python on
      Windows, ``pip install --user`` without ``~/.local/bin`` on Linux).
      Works because the installer is currently executing inside an
      interpreter that can ``import sumo_qa``.
    """

    command: str
    args: list[str] = field(default_factory=list)

    def to_config_entry(self, *, include_empty_args: bool = False) -> dict:
        """Return the dict shape MCP host configs expect.

        ``include_empty_args=True`` always emits an ``args`` key (VS Code's
        ``mcp.json`` writers historically wrote ``"args": []``); the Claude
        Code / Claude Desktop writers omit it when empty so existing user
        configs don't pick up a no-op key on re-run.
        """
        if self.args or include_empty_args:
            return {"command": self.command, "args": list(self.args)}
        return {"command": self.command}

    def as_subprocess_argv(self) -> list[str]:
        """Return ``[command, *args]`` for ``subprocess.run`` / Popen."""
        return [self.command, *self.args]

    def display(self) -> str:
        """Human-readable form for log output."""
        if self.args:
            return f"{self.command} {' '.join(self.args)}"
        return self.command


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
        help=(
            "Configure Claude Code only (symlink skills + register MCP server "
            "via `claude mcp add` + write claude_desktop_config.json)."
        ),
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
        "--claude-desktop",
        action="store_true",
        help=(
            "Configure Claude Desktop only (the macOS Claude.app + Windows/Linux "
            "equivalents — including the Cowork code-capable mode). Writes "
            "claude_desktop_config.json to the OS-correct path; merges with any "
            "existing mcpServers entries."
        ),
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
    explicit_hosts = bool(args.claude_code or args.vscode or args.jetbrains or args.claude_desktop)
    do_claude = args.claude_code or not explicit_hosts
    do_vscode = args.vscode or not explicit_hosts
    do_jetbrains = args.jetbrains or not explicit_hosts
    do_claude_desktop = args.claude_desktop or not explicit_hosts

    system = platform.system()
    print(f"sumo-qa installer  (OS: {system})")
    hosts_str = ", ".join(
        h
        for h, do in [
            ("Claude Code", do_claude),
            ("VS Code", do_vscode),
            ("JetBrains", do_jetbrains),
            ("Claude Desktop", do_claude_desktop),
        ]
        if do
    )
    print(f"Configuring: {hosts_str}\n")

    if args.skip_mcp_install:
        binary = shutil.which("sumo-qa")
        mcp_cmd = McpCommand(command=str(Path(binary).resolve()), args=[]) if binary else None
        if mcp_cmd is None:
            print("ERROR: --skip-mcp-install was set but sumo-qa is not on PATH.")
            return 1
        print(f"MCP command (existing): {mcp_cmd.display()}\n")
    else:
        mcp_cmd = _install_mcp_binary()
        print(f"\nMCP command: {mcp_cmd.display()}\n")

    workspace = args.workspace.resolve() if args.workspace else Path.cwd()

    # Claude Desktop on macOS launches from a sandbox that cannot read
    # source-checkout venv paths (issue #181). Resolve a host-safe command
    # for it BEFORE writing any host configs: if no safe candidate exists
    # the installer refuses to mutate claude_desktop_config.json and exits
    # non-zero, even if other hosts would have succeeded.
    cd_cmd: McpCommand | None = None
    cd_refusal: str | None = None
    if do_claude_desktop and system == "Darwin":
        safe_cd = _select_safe_command_for_claude_desktop(system)
        if safe_cd is None:
            # Distinguish "no sumo-qa at all on PATH" from "only project-
            # checkout venvs": the user's next step differs (install vs.
            # reinstall-from-a-different-shell).
            if _iter_sumo_qa_on_path():
                cd_refusal = (
                    "Only project-checkout venv sumo-qa installations were "
                    "found on PATH. macOS Claude Desktop cannot read "
                    "source-checkout .venv paths from its sandbox. Install a "
                    "stable sumo-qa first (`pipx install sumo-qa`, a "
                    "pyenv/asdf-managed install, or via Homebrew), then re-run "
                    "`sumo-qa-install --claude-desktop`."
                )
            else:
                cd_refusal = (
                    "No sumo-qa installation was found on PATH for Claude "
                    "Desktop. Install one first (`pipx install sumo-qa`, a "
                    "pyenv/asdf-managed install, or via Homebrew), then "
                    "re-run `sumo-qa-install --claude-desktop`."
                )
        else:
            cd_cmd = safe_cd

    results: list[HostResult] = []
    if do_claude:
        results.append(_setup_claude_code(mcp_cmd, system))
    if do_vscode:
        results.append(_setup_vscode_copilot(mcp_cmd, workspace))
    if do_jetbrains:
        results.append(_setup_intellij(mcp_cmd, system))
    if do_claude_desktop:
        if cd_refusal is not None:
            refusal = HostResult("Claude Desktop")
            refusal.detected = True
            refusal.message = f"skipped (unsafe install context): {cd_refusal}"
            results.append(refusal)
        else:
            results.append(_setup_claude_desktop(cd_cmd or mcp_cmd, system))

    print("Host setup:")
    for r in results:
        print(r.render())

    print()
    if cd_refusal is not None:
        # Skip the verify subprocess entirely on the refusal path so we
        # never spawn the unsafe binary, even with the verifier's own
        # timeout guard — the install context is already known-broken.
        print("ERROR: refused to configure Claude Desktop.")
        print(cd_refusal)
        return 1
    # When ``cd_cmd`` was selected past an unsafe shadowing binary on
    # PATH, probe the binary Claude Desktop will actually launch — not
    # the first ``shutil.which`` result, which is exactly the unsafe
    # path we steered around. ``cd_cmd`` is a sumo-qa binary too, so
    # verifying it covers the runtime path the other hosts use as well.
    verify_cmd = cd_cmd if cd_cmd is not None else mcp_cmd
    ok = _verify_mcp_responds(verify_cmd)
    print()
    if ok:
        print("Installation complete. Restart any host you just configured.")
        return 0
    print("Installation finished but the MCP did not respond cleanly to a")
    print("JSON-RPC initialize ping. Check that the command is healthy:")
    print(f"  {verify_cmd.display()}")
    return 2


# ----------------------------------------------------------------------
# MCP binary
# ----------------------------------------------------------------------


# Directory-name segments that indicate a Python venv layout local to a
# source checkout: the host that wins PATH resolution lives inside the
# user's project. Claude Desktop on macOS launches from a sandbox that
# cannot read these locations (Desktop / Documents / Downloads / iCloud
# / repo .venv all hit the same Privacy & Security gate). Segment-match,
# not substring-match: ``environment``/``venvs`` are legitimate names that
# must NOT be flagged.
_UNSAFE_VENV_SEGMENTS: frozenset[str] = frozenset({".venv", "venv", "env", ".tox", ".nox"})


def _is_unsafe_for_claude_desktop(path: str, system: str) -> bool:
    """Whether ``path`` is a sumo-qa command the Claude Desktop sandbox
    cannot launch on macOS.

    macOS-scoped per issue #181: the Privacy & Security folder-access
    restriction only fires for the bundled .app launch context. Other OSes
    don't have this restriction, so the predicate is a no-op (returns
    ``False``) off Darwin — the installer keeps the fast path there.
    """
    if system != "Darwin":
        return False
    return any(p in _UNSAFE_VENV_SEGMENTS for p in Path(path).parts)


def _iter_sumo_qa_on_path() -> list[str]:
    """Walk ``$PATH`` and return every directory's ``sumo-qa`` executable.

    ``shutil.which`` only returns the first match, but the issue's
    central failure mode is "the source-checkout venv comes first; the
    safe install comes second". We need to look past the first hit to
    find the safe one, so this is a manual walk in PATH order.

    Returns absolute, resolved paths; de-dupes by resolved path so a
    symlinked directory on PATH doesn't double-count the same binary.
    """
    seen: set[str] = set()
    out: list[str] = []
    for dirname in os.environ.get("PATH", "").split(os.pathsep):
        if not dirname:
            continue
        candidate = Path(dirname) / "sumo-qa"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            resolved = str(candidate.resolve())
            if resolved not in seen:
                seen.add(resolved)
                out.append(resolved)
    return out


def _select_safe_command_for_claude_desktop(system: str) -> McpCommand | None:
    """Pick the first ``sumo-qa`` on ``$PATH`` that the macOS Claude Desktop
    sandbox can launch.

    - On Darwin: skip past any candidate matching the source-checkout venv
      layout (``_is_unsafe_for_claude_desktop``); return the first
      remaining one, or ``None`` if every candidate is unsafe (the caller
      then refuses to mutate ``claude_desktop_config.json``).
    - Off Darwin: the restriction doesn't apply — return the first
      candidate, matching ``_install_mcp_binary``'s fast-path behaviour.

    ``None`` distinguishes "no safe candidate" from "no candidate at all";
    both block writing the config but the caller's error message differs.
    """
    for candidate in _iter_sumo_qa_on_path():
        if not _is_unsafe_for_claude_desktop(candidate, system):
            return McpCommand(command=candidate, args=[])
    return None


def _install_mcp_binary() -> McpCommand:
    """Decide how the host should invoke the sumo-qa MCP server.

    Two-step resolution, no uv recovery:

    1. **Console script on PATH** — pip / pipx / uv-tool / a custom venv all
       generate a ``sumo-qa`` wrapper. If ``shutil.which`` finds it, use it.

    2. **Module form** — fall back to ``<sys.executable> -m sumo_qa``. Safe
       because this function is reached via ``python -m sumo_qa.installer``
       (or via the wrapper script, which itself imports ``sumo_qa``), so the
       current interpreter is proof that ``import sumo_qa`` works. This is
       the path Microsoft-Store Python on Windows always lands in — pip
       successfully installs ``sumo-qa.exe`` into a Scripts dir that is
       never on PATH by default; the previous uv-based fallback surprised
       users with an unrequested second install vector.
    """
    existing = shutil.which("sumo-qa")
    if existing is not None:
        resolved = Path(existing).resolve()
        print(f"Using existing sumo-qa binary at {resolved}")
        return McpCommand(command=str(resolved), args=[])

    invocation = McpCommand(command=sys.executable, args=["-m", "sumo_qa"])
    print(
        f"sumo-qa script not on PATH; using `{invocation.display()}` directly. "
        "(Common when the pip Scripts directory is off PATH, e.g. Microsoft-Store "
        "Python on Windows.)"
    )
    return invocation


# ----------------------------------------------------------------------
# Claude Code
# ----------------------------------------------------------------------


def _setup_claude_code(mcp_cmd: McpCommand, system: str) -> HostResult:
    r = HostResult("Claude Code")
    home = Path.home()

    if system == "Windows":  # pragma: no cover -- platform-conditional Windows branch
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
                f'    "{PLUGIN_METADATA.mcp_server_name}": '
                f"{json.dumps(mcp_cmd.to_config_entry())}"
            )
            return r
    config.setdefault("mcpServers", {})
    config["mcpServers"][PLUGIN_METADATA.mcp_server_name] = mcp_cmd.to_config_entry()
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    # 3. Register with Claude Code's own MCP registry via `claude mcp add`.
    #    Claude Code (the CLI) does NOT read claude_desktop_config.json — it
    #    keeps its own MCP server list managed via the `claude mcp` subcommand.
    #    Without this step the MCP tools (sumo_qa_load_*, etc.) never surface
    #    in a Claude Code session even though the skill files are symlinked.
    mcp_msg = _register_claude_code_mcp(mcp_cmd)

    r.configured = True
    r.config_path = config_path
    r.message = f"{symlink_msg}; wrote {config_path}; {mcp_msg}"
    return r


def _register_claude_code_mcp(mcp_cmd: McpCommand) -> str:
    """Idempotently register sumo-qa as a user-scoped MCP server in Claude Code.

    Removes any existing ``sumo-qa`` entry first (covers the case where a
    previous install registered a stale invocation — e.g. a binary path that
    no longer exists after a venv move), then re-adds. Returns a one-line
    summary for the install output.

    No-ops gracefully when the ``claude`` CLI isn't on PATH — users running
    sumo-qa-install on a machine without Claude Code installed only get the
    skill symlinks, not an error.
    """
    claude = shutil.which("claude")
    if claude is None:
        return "claude CLI not on PATH — skipped MCP-registry registration"
    # Remove first; ignore failure (entry may not exist). Idempotent re-add.
    server_name = PLUGIN_METADATA.mcp_server_name
    subprocess.run(
        [claude, "mcp", "remove", server_name, "-s", "user"],
        capture_output=True,
        check=False,
    )
    # `claude mcp add [options] NAME -- COMMAND [ARGS...]` — `--` terminates
    # option parsing so subprocess flags (e.g. `-m sumo_qa`) reach the MCP
    # server intact rather than being intercepted as claude CLI options.
    add_argv = [
        claude,
        "mcp",
        "add",
        "-s",
        "user",
        server_name,
        "--",
        mcp_cmd.command,
        *mcp_cmd.args,
    ]
    try:
        subprocess.run(add_argv, capture_output=True, check=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip() if exc.stderr else ""
        return f"claude mcp add failed ({exc.returncode}): {stderr or 'no stderr'}"
    return f"registered with claude mcp as `{mcp_cmd.display()}`"


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
            and repo_skill.read_text(encoding="utf-8").replace("\r\n", "\n")
            == target_skill.read_text(encoding="utf-8").replace("\r\n", "\n")
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


def _setup_vscode_copilot(mcp_cmd: McpCommand, workspace: Path) -> HostResult:
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
                f'Add manually: "{PLUGIN_METADATA.mcp_server_name}": {{ "type": "stdio", '
                f"{json.dumps(mcp_cmd.to_config_entry(include_empty_args=True))[1:-1]} }}"
            )
            return r

    # Strip any legacy mcpServers key from previous install.py runs — VS Code
    # never used it, leaving it as noise is harmful (looks configured when
    # it isn't).
    config.pop("mcpServers", None)

    config.setdefault("servers", {})
    config["servers"][PLUGIN_METADATA.mcp_server_name] = {
        "type": "stdio",
        **mcp_cmd.to_config_entry(include_empty_args=True),
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


def _setup_intellij(mcp_cmd: McpCommand, system: str) -> HostResult:
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
    args_line = " ".join(mcp_cmd.args) if mcp_cmd.args else "leave empty"
    r.followup = (
        "      In any JetBrains IDE, open the chat / AI Assistant panel,\n"
        "      then:\n"
        "        Settings -> Tools -> AI Assistant -> Model Context Protocol\n"
        "        Click + Add server, fill in:\n"
        "          Name:    sumo-qa\n"
        f"          Command: {mcp_cmd.command}\n"
        f"          Arguments: {args_line}\n"
        "          Working directory: leave empty\n"
        "        Apply.\n"
        "\n"
        "      Why manual: external writes to JetBrains' MCP config XML are\n"
        "      not reliably picked up on IDEA 2026.1 (we tried). The UI add\n"
        "      registers it via the supported path and persists across\n"
        "      restarts."
    )
    return r


# ----------------------------------------------------------------------
# Claude Desktop (the macOS Claude.app + Windows/Linux equivalents,
# including the Cowork code-capable mode)
# ----------------------------------------------------------------------


def _claude_desktop_config_path(home: Path, system: str) -> Path:
    """Return the OS-correct path to claude_desktop_config.json.

    Critically NOT the same as the path used by `_setup_claude_code`. The real
    Claude Desktop app reads from these locations:
      - macOS:   ~/Library/Application Support/Claude/claude_desktop_config.json
      - Windows: %APPDATA%/Claude/claude_desktop_config.json
      - Linux:   ~/.config/Claude/claude_desktop_config.json   (uppercase Claude)
    """
    if system == "Darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":  # pragma: no cover -- platform-conditional Windows branch
        appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
        return appdata / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"


def _setup_claude_desktop(mcp_cmd: McpCommand, system: str) -> HostResult:
    """Wire sumo-qa into the Claude Desktop app's MCP config.

    Reads the existing claude_desktop_config.json (if any), merges the sumo-qa
    entry into mcpServers (preserving every other server entry), writes back.
    Idempotent on re-run.
    """
    r = HostResult("Claude Desktop")
    home = Path.home()

    # Special-case Windows: APPDATA may not be set. Use it if present, else
    # fall back to the same path-resolution helper which provides a default.
    config_path = _claude_desktop_config_path(home, system)
    config_dir = config_path.parent

    if not config_dir.is_dir():
        r.message = "Claude Desktop not detected on this machine"
        return r

    r.detected = True

    config: dict = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            r.message = (
                f"{config_path} exists but is invalid JSON; not modifying. "
                f"Add manually:\n"
                f'    "{PLUGIN_METADATA.mcp_server_name}": '
                f"{json.dumps(mcp_cmd.to_config_entry())}"
            )
            return r

    server_name = PLUGIN_METADATA.mcp_server_name
    existing_servers = config.get("mcpServers") or {}
    other_servers_count = sum(1 for k in existing_servers if k != server_name)

    config.setdefault("mcpServers", {})
    config["mcpServers"][server_name] = mcp_cmd.to_config_entry()
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    r.configured = True
    r.config_path = config_path
    if other_servers_count > 0:
        r.message = f"wrote {config_path}; merged with {other_servers_count} existing server(s)"
    else:
        r.message = f"wrote {config_path}"
    return r


# ----------------------------------------------------------------------
# Verification
# ----------------------------------------------------------------------


class _VerifyTimeout(Exception):
    """Raised internally when a JSON-RPC response doesn't arrive in time."""


def _verify_mcp_responds(mcp_cmd: McpCommand) -> bool:
    """Drive a JSON-RPC handshake and confirm the expected tool surface.

    Spawns the MCP server with ``subprocess.Popen`` and walks the
    ``initialize`` + ``notifications/initialized`` + ``tools/list`` handshake
    one message at a time, reading each response off stdout BEFORE sending
    the next request. Critically, stdin stays open until both responses have
    been collected — closing stdin signals EOF to FastMCP's async stdio
    transport, which cancels any in-flight ``ListToolsRequest`` work before
    its response reaches stdout. That was the root cause of the ubuntu
    install-smoke flake: ``subprocess.run`` writes all stdin in one shot and
    immediately closes it, racing the server's async response queue.

    Validates:

    1. An ``initialize`` response with ``id=1``, ``jsonrpc='2.0'``, no top-level
       ``error`` envelope, and a ``dict`` ``result``.
    2. A ``tools/list`` response with ``id=2`` whose ``result.tools[*].name``
       set is a superset of ``REQUIRED_TOOL_NAMES``.

    Returns True only when both responses validate cleanly. Failures print a
    WARNING line naming the specific shape that broke, plus truncated
    stdout/stderr so the user has something actionable to debug.
    """
    print("Verifying the MCP responds to initialize and exposes the expected tools...")
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
    initialized_note = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    tools_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

    proc = subprocess.Popen(  # noqa: S603 -- argv comes from a trusted McpCommand
        mcp_cmd.as_subprocess_argv(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # ``stdin=subprocess.PIPE`` guarantees ``proc.stdin`` is a real stream, but
    # typeshed types it as ``IO[str] | None``. Bind + assert once so the writes
    # below type-check without a None-guard on every line.
    stdin = proc.stdin
    assert stdin is not None
    # Spawn the stdout reader thread once per process so both
    # ``_read_json_rpc_response`` calls (id=1 and id=2) share the same queue.
    # Cross-platform timeout falls out of ``queue.get(timeout=...)`` — no
    # platform-branched ``select`` needed.
    line_queue = _start_stdout_reader(proc)
    deadline = time.monotonic() + _VERIFY_TIMEOUT_SECONDS
    init_resp: dict | None = None
    tools_resp: dict | None = None
    extra_stdout: list[str] = []
    # Buffer of parsed JSON-RPC response objects that didn't match the
    # expected id at the time they were read. Shared across both
    # ``_read_json_rpc_response`` calls so a server that batches responses
    # per spec 2.0 §6 (a single line containing
    # ``[{"id":1,...}, {"id":2,...}]``) still resolves id=1 on the first
    # call and id=2 on the second.
    pending_responses: collections.deque[dict] = collections.deque()
    try:
        # Step 1: initialize.
        stdin.write(init_req + "\n")
        stdin.flush()
        init_resp = _read_json_rpc_response(
            line_queue=line_queue,
            expected_id=1,
            deadline=deadline,
            extra_lines=extra_stdout,
            pending_responses=pending_responses,
        )

        # Step 2: notifications/initialized — no response on the wire.
        stdin.write(initialized_note + "\n")
        stdin.flush()

        # Step 3: tools/list.
        stdin.write(tools_req + "\n")
        stdin.flush()
        tools_resp = _read_json_rpc_response(
            line_queue=line_queue,
            expected_id=2,
            deadline=deadline,
            extra_lines=extra_stdout,
            pending_responses=pending_responses,
        )
    except _VerifyTimeout:
        print(f"  WARNING: MCP did not respond within {_VERIFY_TIMEOUT_SECONDS}s (timeout).")
        _dump_proc_streams(proc, extra_lines=extra_stdout)
        _terminate(proc)
        return False
    except BrokenPipeError:  # pragma: no cover -- defensive; server-crash race
        # Server exited mid-handshake (e.g. import error in the MCP package).
        print("  WARNING: MCP closed stdin mid-handshake (server likely crashed on startup).")
        _dump_proc_streams(proc, extra_lines=extra_stdout)
        _terminate(proc)
        return False
    finally:
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except Exception:  # pragma: no cover -- defensive cleanup; noqa: BLE001
            pass

    # --- initialize ----------------------------------------------------------
    if init_resp is None:
        print("  WARNING: MCP did not return an initialize response (no id=1 message).")
        _dump_proc_streams(proc, extra_lines=extra_stdout)
        _terminate(proc)
        return False
    if init_resp.get("jsonrpc") != "2.0":
        print("  WARNING: initialize response missing jsonrpc='2.0'.")
        _dump_proc_streams(proc, extra_lines=extra_stdout)
        _terminate(proc)
        return False
    if "error" in init_resp:
        print(f"  WARNING: initialize returned an error envelope: {init_resp['error']!r}")
        _dump_proc_streams(proc, extra_lines=extra_stdout)
        _terminate(proc)
        return False
    init_result = init_resp.get("result")
    if not isinstance(init_result, dict):
        print(
            "  WARNING: initialize response 'result' is not a dict "
            f"(got {type(init_result).__name__})."
        )
        _dump_proc_streams(proc, extra_lines=extra_stdout)
        _terminate(proc)
        return False

    # --- tools/list ----------------------------------------------------------
    if tools_resp is None:
        print("  WARNING: MCP did not return a tools/list response (no id=2 message).")
        _dump_proc_streams(proc, extra_lines=extra_stdout)
        _terminate(proc)
        return False
    if "error" in tools_resp:
        print(f"  WARNING: tools/list returned an error envelope: {tools_resp['error']!r}")
        _dump_proc_streams(proc, extra_lines=extra_stdout)
        _terminate(proc)
        return False
    tools_result = tools_resp.get("result")
    if not isinstance(tools_result, dict):
        print(
            "  WARNING: tools/list response 'result' is not a dict "
            f"(got {type(tools_result).__name__})."
        )
        _dump_proc_streams(proc, extra_lines=extra_stdout)
        _terminate(proc)
        return False
    tools = tools_result.get("tools", [])
    if not isinstance(tools, list):
        print("  WARNING: tools/list 'result.tools' is not a list.")
        _dump_proc_streams(proc, extra_lines=extra_stdout)
        _terminate(proc)
        return False
    advertised = {t.get("name") for t in tools if isinstance(t, dict)}
    missing = [n for n in REQUIRED_TOOL_NAMES if n not in advertised]
    if missing:
        print(f"  WARNING: tools/list is missing required tools: {missing}")
        _dump_proc_streams(proc, extra_lines=extra_stdout)
        _terminate(proc)
        return False

    _terminate(proc)
    print(f"  MCP responded with {len(advertised)} tools; all required tools present.")
    return True


def _start_stdout_reader(proc: subprocess.Popen) -> queue.Queue:
    """Spawn a daemon thread that pumps each stdout line into a queue.

    Returns the queue. The thread reads via blocking ``readline`` until EOF
    (empty string from ``readline``), at which point it pushes a ``None``
    sentinel so the main thread can distinguish "stalled server" (queue stays
    empty, ``get`` raises ``queue.Empty``) from "server exited" (queue yields
    ``None``).

    Daemon so it doesn't block process exit if the parent forgets to drain.
    Cross-platform: blocking ``readline`` works identically on POSIX and
    Windows, and ``queue.Queue.get(timeout=...)`` honours the timeout on both.
    This is the replacement for the previous platform-branched ``select``
    polling, which silently degraded to a no-timeout blocking ``readline`` on
    Windows.
    """
    q: queue.Queue = queue.Queue()

    def _pump() -> None:
        # ``stdout=subprocess.PIPE`` guarantees a real stream; typeshed types it
        # as ``IO[Any] | None``, so narrow once before the blocking read loop.
        stdout = proc.stdout
        assert stdout is not None
        try:
            for line in iter(stdout.readline, ""):
                q.put(line)
        finally:
            q.put(None)  # EOF sentinel

    t = threading.Thread(target=_pump, daemon=True)
    t.start()
    return q


def _read_json_rpc_response(
    *,
    line_queue: queue.Queue,
    expected_id: int,
    deadline: float,
    extra_lines: list[str],
    pending_responses: collections.deque[dict],
) -> dict | None:
    """Read lines from ``line_queue`` until one parses as a JSON object with
    ``id == expected_id``.

    Returns the parsed dict on success, ``None`` if the reader thread signals
    EOF (the server exited) before the expected response arrives. Raises
    ``_VerifyTimeout`` when ``deadline`` elapses with no matching response.

    Non-matching lines (notifications, malformed JSON, log noise, JSON values
    that aren't objects) are accumulated into ``extra_lines`` so a later
    ``_dump_proc_streams`` call can surface them when verification fails.

    Cross-platform by construction: ``queue.Queue.get(timeout=...)`` honours
    the timeout identically on POSIX and Windows. No ``select`` needed.

    Batched-response support (JSON-RPC 2.0 §6): if a line parses to a JSON
    array, each dict element is treated as if it had arrived on its own
    line. A match for ``expected_id`` returns immediately; the remaining
    dict elements are buffered into ``pending_responses`` so a subsequent
    call (e.g. the second handshake read for id=2) picks them up before
    pulling the next line off ``line_queue``. Non-dict array elements
    (strings, numbers, nested lists) are accumulated into ``extra_lines``
    as noise — JSON-RPC messages are always objects.

    On EOF: pushes the ``None`` sentinel back onto the queue so any subsequent
    read from the same queue also short-circuits to ``None`` instead of
    blocking for the full deadline. The reader thread only puts ``None``
    once; without this re-push, the second handshake read (tools/list) would
    hang waiting for a sentinel that's already been consumed.
    """
    # First, drain any buffered batched responses from the previous call.
    # If one of them carries the expected id, return it without touching
    # the queue at all.
    while pending_responses:
        candidate = pending_responses.popleft()
        if candidate.get("id") == expected_id:
            return candidate
        # Otherwise it's still unmatched — keep it visible to the failure
        # dump so noise isn't silently swallowed.
        extra_lines.append(json.dumps(candidate))

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _VerifyTimeout()
        try:
            line = line_queue.get(timeout=remaining)
        except queue.Empty:
            raise _VerifyTimeout() from None
        if line is None:
            # EOF sentinel — the reader thread saw stdout close. Re-push so
            # any later read on the same queue also yields None immediately,
            # then surface as missing-response.
            line_queue.put(None)
            return None
        stripped = line.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            extra_lines.append(stripped)
            continue
        if isinstance(value, list):
            # Batched response per JSON-RPC 2.0 §6. Process each dict element
            # as if it had arrived on its own line: a match for the expected
            # id returns immediately; remaining dicts buffer for the next
            # call. Non-dict elements (strings, numbers, nested lists) are
            # log noise from the verifier's perspective.
            matched: dict | None = None
            for item in value:
                if not isinstance(item, dict):
                    extra_lines.append(json.dumps(item))
                    continue
                if matched is None and item.get("id") == expected_id:
                    matched = item
                else:
                    pending_responses.append(item)
            if matched is not None:
                return matched
            continue
        if not isinstance(value, dict):
            extra_lines.append(stripped)
            continue
        if value.get("id") == expected_id:
            return value
        # Some other JSON-RPC message (e.g. a server notification). Keep it
        # for the failure dump and continue reading.
        extra_lines.append(stripped)


def _terminate(proc: subprocess.Popen) -> None:
    """Best-effort process teardown.

    Mirrors the cleanup in ``tests/test_e2e_mcp_initialize.py``: close stdin,
    ``terminate()``, wait briefly, ``kill()`` on stragglers. Tolerant of
    already-exited processes and missing pipe handles.
    """
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
    except Exception:  # pragma: no cover -- defensive cleanup; noqa: BLE001
        pass
    try:
        proc.terminate()
    except Exception:  # pragma: no cover -- defensive; already gone; noqa: BLE001
        pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:  # pragma: no cover -- defensive; kill fallback
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # pragma: no cover -- defensive; wait on missing pid; noqa: BLE001
        pass


def _parse_json_rpc_lines(stdout: str) -> list[dict]:
    """Split stdout on newlines and decode each line as a JSON object.

    Defensive against:
    - Empty / whitespace-only lines (skipped).
    - Non-JSON log noise some servers emit alongside JSON-RPC (skipped).
    - JSON values that aren't objects or arrays of objects, e.g. bare
      strings or numbers (skipped) — JSON-RPC messages are always objects,
      so anything else is noise from the verifier's perspective.

    Batched-response support (JSON-RPC 2.0 §6): a line that parses to a
    JSON array is flattened — dict elements are appended to the output in
    order; non-dict elements (nested arrays, strings, numbers) are
    skipped, matching the single-line behaviour.
    """
    out: list[dict] = []
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            out.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    out.append(item)
    return out


def _dump_proc_streams(proc: subprocess.Popen, *, extra_lines: list[str]) -> None:
    """Print truncated stdout/stderr from a live Popen for diagnostics.

    Drains any remaining stderr (non-blocking best-effort) and prints the
    accumulated stdout lines we couldn't match plus any stderr bytes the
    server emitted. Truncated to ``_DUMP_STREAM_CHARS`` to keep the install
    log readable on failure.

    Cross-platform: only reads stderr when the process has exited (so we
    don't block the installer waiting on a stalled server's stderr pipe).
    The previous POSIX-only ``select`` polling has been removed in favour of
    this exit-gated read, which works identically on Windows.
    """
    if extra_lines:
        joined = "\n".join(extra_lines)
        print(f"    stdout: {joined[:_DUMP_STREAM_CHARS]}")
    # Best-effort: only drain stderr once the process has exited so the read
    # is guaranteed not to block.
    stderr_text = ""
    try:
        if proc.stderr is not None and proc.poll() is not None:
            stderr_text = proc.stderr.read() or ""
    except Exception:  # pragma: no cover -- defensive; noqa: BLE001
        pass
    if stderr_text:
        print(f"    stderr: {stderr_text[:_DUMP_STREAM_CHARS]}")


if __name__ == "__main__":  # pragma: no cover -- main guard
    sys.exit(main())
