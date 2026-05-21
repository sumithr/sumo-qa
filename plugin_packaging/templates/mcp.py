# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Renders the host-neutral .mcp.json — referenced by both adapters."""

from __future__ import annotations

from plugin_packaging.canonical import CanonicalPlugin


def render(plugin: CanonicalPlugin) -> dict:
    entry: dict = {
        "command": plugin.mcp.command,
        "args": list(plugin.mcp.args),
        "type": plugin.mcp.transport,
    }
    # Only include `env` when non-empty so plugins that don't need env
    # vars get the same minimal shape they had before this field existed.
    if plugin.mcp.env:
        entry["env"] = dict(plugin.mcp.env)
    return {
        "mcpServers": {
            plugin.mcp.server_name: entry,
        }
    }
