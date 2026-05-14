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
