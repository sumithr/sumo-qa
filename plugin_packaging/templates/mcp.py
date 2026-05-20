# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Renders the host-neutral .mcp.json — referenced by both adapters."""

from __future__ import annotations

from plugin_packaging.canonical import CanonicalPlugin


def render(plugin: CanonicalPlugin) -> dict:
    return {
        "mcpServers": {
            plugin.mcp.server_name: {
                "command": plugin.mcp.command,
                "args": list(plugin.mcp.args),
                "type": plugin.mcp.transport,
            }
        }
    }
