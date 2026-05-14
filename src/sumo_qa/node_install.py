# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Detect and run the native package manager to install Node.

This module is separate from `qaskills.py` because its responsibility is
different: `qaskills.py` shells to `npx @qaskills/cli`; `node_install.py`
shells to the user's OS package manager (`brew` / `winget` / `apt-get`
/ `dnf`) to install Node when it's missing. The `sumo-qa-suggesting-
external-skill` chains them: if `qaskills.is_available()` returns False,
the skill calls `detect_installer()` and offers the result to the user.

Sudo policy: this module never calls `sudo`. If the detected installer
requires elevation (Linux `apt-get` / `dnf`), `install()` refuses and
returns a result with the exact command the user can run manually.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass

_INSTALL_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class NodeInstaller:
    name: str
    command: tuple[str, ...]
    needs_sudo: bool


@dataclass(frozen=True)
class InstallResult:
    installed: bool
    reason: str = ""
    stdout: str = ""
    stderr: str = ""


def detect_installer() -> NodeInstaller | None:
    """Pick the best Node installer for the current OS.

    Returns None if the OS is unsupported or no recognised package
    manager is on PATH. Callers should treat None as "fall back to
    showing the user a download link".
    """
    platform = sys.platform
    if platform == "darwin":
        if shutil.which("brew"):
            return NodeInstaller(name="brew", command=("brew", "install", "node"), needs_sudo=False)
        return None
    if platform == "win32":
        if shutil.which("winget"):
            return NodeInstaller(
                name="winget", command=("winget", "install", "OpenJS.NodeJS"), needs_sudo=False
            )
        return None
    if platform.startswith("linux"):
        if shutil.which("apt-get"):
            return NodeInstaller(
                name="apt-get",
                command=("apt-get", "install", "-y", "nodejs", "npm"),
                needs_sudo=True,
            )
        if shutil.which("dnf"):
            return NodeInstaller(
                name="dnf",
                command=("dnf", "install", "-y", "nodejs", "npm"),
                needs_sudo=True,
            )
        return None
    return None


def install(installer: NodeInstaller) -> InstallResult:
    """Run the installer's command. Refuses to elevate.

    When `installer.needs_sudo` is True, returns a clean InstallResult
    with the verbatim command the user can run themselves. We never
    call `sudo` from an MCP server — the security/UX tradeoffs aren't
    worth it for this trial.
    """
    if installer.needs_sudo:
        cmd_str = " ".join(installer.command)
        return InstallResult(
            installed=False,
            reason=(
                f"This installer requires sudo. Run it yourself: `sudo {cmd_str}`. "
                "Sumo QA will not elevate automatically."
            ),
        )
    result = subprocess.run(
        list(installer.command),
        capture_output=True,
        text=True,
        timeout=_INSTALL_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        return InstallResult(
            installed=False,
            reason=f"{installer.name} install failed (exit {result.returncode}): {result.stderr.strip()}",
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return InstallResult(installed=True, stdout=result.stdout, stderr=result.stderr)
