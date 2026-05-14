# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Subprocess shim around `npx @qaskills/cli`.

This module shells out to the qaskills.sh CLI to discover, inspect,
and install skills. It is pure I/O — no MCP wiring lives here. The
MCP tool surface in `server.py` adapts these functions into MCP tools.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal


def is_available() -> bool:
    """Return True when `npx` is on PATH (proxy for Node being installed).

    The qaskills CLI is invoked as `npx @qaskills/cli <subcommand>`; if
    `npx` is missing there is no way to call it.
    """
    return shutil.which("npx") is not None


_DEFAULT_TIMEOUT_SECONDS = 30
_CLI = ("npx", "--yes", "@qaskills/cli")


class QaskillsError(Exception):
    """Base class for qaskills shim errors."""


class NodeNotFoundError(QaskillsError):
    """Raised when `npx` is not on PATH."""


class QaskillsCLIError(QaskillsError):
    """Raised when `npx @qaskills/cli` exits non-zero or emits unparseable output."""


@dataclass(frozen=True)
class QaskillMatch:
    name: str
    publisher: str
    score: int
    description: str


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


def search(query: str) -> list[QaskillMatch]:
    """Return parsed candidate matches for the query."""
    result = _run(("search", query, "--json"))
    if result.returncode != 0:
        raise QaskillsCLIError(
            f"qaskills CLI search failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise QaskillsCLIError(
            f"qaskills CLI returned non-JSON output for search: {result.stdout[:200]!r}"
        ) from exc
    return [
        QaskillMatch(
            name=item["name"],
            publisher=item["publisher"],
            score=int(item.get("score", 0)),
            description=item.get("description", ""),
        )
        for item in raw
    ]


@dataclass(frozen=True)
class QaskillInfo:
    name: str
    publisher: str
    score: int
    description: str
    skill_md: str
    mcp_servers: tuple[str, ...]


def info(name: str) -> QaskillInfo:
    """Return full skill record (publisher, score, raw SKILL.md, MCP refs)."""
    result = _run(("info", name, "--json"))
    if result.returncode != 0:
        raise QaskillsCLIError(
            f"qaskills CLI info failed for {name!r} (exit {result.returncode}): {result.stderr.strip()}"
        )
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise QaskillsCLIError(
            f"qaskills CLI returned non-JSON output for info: {result.stdout[:200]!r}"
        ) from exc
    return QaskillInfo(
        name=raw["name"],
        publisher=raw["publisher"],
        score=int(raw.get("score", 0)),
        description=raw.get("description", ""),
        skill_md=raw.get("skill_md", ""),
        mcp_servers=tuple(raw.get("mcp_servers") or ()),
    )


Scope = Literal["global", "project"]
_VALID_SCOPES: tuple[Scope, ...] = ("global", "project")
_ADD_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class AddResult:
    name: str
    scope: Scope
    installed_at: str


def add(name: str, scope: Scope) -> AddResult:
    """Install a qaskill. Scope picks between global and project install."""
    if scope not in _VALID_SCOPES:
        raise ValueError(f"scope must be one of {_VALID_SCOPES!r}, got {scope!r}")
    extra = ("--project",) if scope == "project" else ()
    result = _run(("add", name, *extra, "--json"), timeout=_ADD_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise QaskillsCLIError(
            f"qaskills CLI add failed for {name!r} (exit {result.returncode}): {result.stderr.strip()}"
        )
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise QaskillsCLIError(
            f"qaskills CLI returned non-JSON output for add: {result.stdout[:200]!r}"
        ) from exc
    return AddResult(name=name, scope=scope, installed_at=raw["installed_at"])
