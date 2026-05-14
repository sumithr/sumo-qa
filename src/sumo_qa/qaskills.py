# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Thin subprocess shim around `npx @qaskills/cli`.

This module does the bare minimum the host LLM cannot do for itself:

- runs the CLI and captures stdout/stderr,
- strips ANSI/spinner noise so the LLM sees clean text,
- handles `scope="project"` by moving the post-install directory into
  the project's `.claude/skills/` (the underlying CLI has no project
  flag).

It does NOT parse the CLI's natural-language output into structured
records. The qaskills CLI emits human-readable text designed for an
LLM coding agent to read. Building Python dataclasses around that
output would throw away nuance, break on every CLI cosmetic change,
and put a middleman between the host LLM and the source. We return the
cleaned text and let Claude interpret it.

Structured types live where they belong: `AddResult` (filesystem path
the host LLM can't compute), `InstalledLocation` (on-disk check), and
the `Scope` literal.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_DEFAULT_TIMEOUT_SECONDS = 30
_ADD_TIMEOUT_SECONDS = 180
_CLI = ("npx", "--yes", "@qaskills/cli")

# Matches CSI escape sequences (\x1b[…) and the bare control sequences the
# CLI's spinner library writes between newlines.
_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\[\?\d+[lh]|\[\d+[A-Za-z]")
# Spinner glyphs the CLI uses while a request is in flight. Lines that start
# with one of these are pure animation noise — drop them.
_SPINNER_GLYPHS = "◒◐◓◑◇"


def is_available() -> bool:
    """Return True when `npx` is on PATH (proxy for Node being installed)."""
    return shutil.which("npx") is not None


class QaskillsError(Exception):
    """Base class for qaskills shim errors."""


class NodeNotFoundError(QaskillsError):
    """Raised when `npx` is not on PATH."""


class QaskillsCLIError(QaskillsError):
    """Raised when the qaskills CLI exits non-zero."""


Scope = Literal["global", "project"]
_VALID_SCOPES: tuple[Scope, ...] = ("global", "project")


@dataclass(frozen=True)
class AddResult:
    name: str
    scope: Scope
    installed_at: Path
    cli_output: str


@dataclass(frozen=True)
class InstalledLocation:
    scope: Scope
    path: Path  # absolute path to SKILL.md


def _strip_cli_chrome(text: str) -> str:
    """Strip ANSI escape codes and pure-spinner lines from CLI output.

    Returns text the host LLM can read directly: real content (skill
    entries, descriptions, install commands) is preserved verbatim, but
    terminal control sequences and rotating spinner glyphs are removed.
    """
    no_ansi = _ANSI_PATTERN.sub("", text)
    keep: list[str] = []
    for raw in no_ansi.splitlines():
        line = raw.rstrip()
        if not line:
            keep.append(line)
            continue
        stripped = line.lstrip()
        if stripped and stripped[0] in _SPINNER_GLYPHS:
            continue
        keep.append(line)
    return "\n".join(keep).strip("\n")


def _run(args: Sequence[str], *, timeout: int = _DEFAULT_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    if not is_available():
        raise NodeNotFoundError(
            "qaskills integration requires Node ≥ 18 (`npx` not found on PATH). "
            "Install Node from https://nodejs.org or via `brew install node`."
        )
    return subprocess.run(
        list(_CLI) + list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def search(query: str) -> str:
    """Run `qaskills search <query>` and return cleaned output for the LLM.

    The host LLM reads this text and decides which skill (if any) matches
    the user's intent. We do not parse fields out of it.
    """
    result = _run(("search", query))
    if result.returncode != 0:
        raise QaskillsCLIError(
            f"qaskills CLI search failed (exit {result.returncode}): "
            f"{result.stderr.strip()[:500] or _strip_cli_chrome(result.stdout)[:500]}"
        )
    return _strip_cli_chrome(result.stdout)


def info(name: str) -> str:
    """Run `qaskills info <name>` and return cleaned output for the LLM.

    Returns metadata (version, publisher, score, license, languages,
    frameworks, web URL). The CLI does not expose the SKILL.md body —
    the host LLM reads the installed file directly via its `Read` tool
    after `add()`.
    """
    result = _run(("info", name))
    if result.returncode != 0:
        raise QaskillsCLIError(
            f"qaskills CLI info failed for {name!r} (exit {result.returncode}): "
            f"{result.stderr.strip()[:500] or _strip_cli_chrome(result.stdout)[:500]}"
        )
    return _strip_cli_chrome(result.stdout)


def _global_skill_dir(name: str) -> Path:
    return Path.home() / ".claude" / "skills" / name


def _project_skill_dir(project_root: Path, name: str) -> Path:
    return project_root / ".claude" / "skills" / name


def add(
    name: str,
    scope: Scope,
    *,
    project_root: Path | None = None,
    agent: str = "claude-code",
) -> AddResult:
    """Install a qaskill via the qaskills CLI.

    Global scope: CLI installs into `~/.claude/skills/<name>/` and we
    leave it there.

    Project scope: CLI installs globally, then we *move* the directory
    into `<project_root>/.claude/skills/<name>/`. The CLI has no native
    project flag; this is how we preserve sumo-qa's per-install scope
    choice.
    """
    if scope not in _VALID_SCOPES:
        raise ValueError(f"scope must be one of {_VALID_SCOPES!r}, got {scope!r}")
    if project_root is None:
        project_root = Path.cwd()

    result = _run(("add", name, "-a", agent), timeout=_ADD_TIMEOUT_SECONDS)
    cli_output = _strip_cli_chrome(result.stdout)
    if result.returncode != 0:
        raise QaskillsCLIError(
            f"qaskills CLI add failed for {name!r} (exit {result.returncode}): "
            f"{result.stderr.strip()[:500] or cli_output[:500]}"
        )

    global_path = _global_skill_dir(name)
    if not global_path.is_dir():
        raise QaskillsCLIError(
            f"qaskills CLI add for {name!r} reported success but no skill directory "
            f"appeared at {global_path}. Inspect with `npx qaskills list`."
        )

    if scope == "global":
        return AddResult(name=name, scope="global", installed_at=global_path, cli_output=cli_output)

    project_path = _project_skill_dir(project_root, name)
    if project_path.exists():
        raise QaskillsCLIError(
            f"project-local target {project_path} already exists; "
            "remove it first or pick scope='global'."
        )
    project_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(global_path), str(project_path))
    return AddResult(name=name, scope="project", installed_at=project_path, cli_output=cli_output)


def is_installed_locally(name: str, *, project_root: Path | None = None) -> InstalledLocation | None:
    """Look for an installed qaskill at the well-known on-disk locations.

    Project-local install wins when both exist. Caller passes
    `project_root` (defaults to cwd) so tests don't depend on cwd state.
    """
    if project_root is None:
        project_root = Path.cwd()
    project_path = _project_skill_dir(project_root, name) / "SKILL.md"
    if project_path.is_file():
        return InstalledLocation(scope="project", path=project_path)
    global_path = _global_skill_dir(name) / "SKILL.md"
    if global_path.is_file():
        return InstalledLocation(scope="global", path=global_path)
    return None
