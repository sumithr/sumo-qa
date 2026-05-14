# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Subprocess shim around `npx @qaskills/cli`.

This module shells out to the qaskills.sh CLI to discover, inspect,
and install skills. It is pure I/O — no MCP wiring lives here. The
MCP tool surface in `server.py` adapts these functions into MCP tools.
"""
from __future__ import annotations

import shutil


def is_available() -> bool:
    """Return True when `npx` is on PATH (proxy for Node being installed).

    The qaskills CLI is invoked as `npx @qaskills/cli <subcommand>`; if
    `npx` is missing there is no way to call it.
    """
    return shutil.which("npx") is not None
