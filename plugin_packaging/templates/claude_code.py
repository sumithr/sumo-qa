# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Renders .claude-plugin/plugin.json for Claude Code.

Schema: https://json.schemastore.org/claude-code-plugin-manifest.json
Reference: https://code.claude.com/docs/en/plugins-reference
"""

from __future__ import annotations

from plugin_packaging.canonical import CanonicalPlugin

_SCHEMA_URL = "https://json.schemastore.org/claude-code-plugin-manifest.json"


def render(plugin: CanonicalPlugin) -> dict:
    # NOTE: Do NOT emit `"hooks": "./hooks/hooks.json"`. Claude Code's plugin
    # loader auto-discovers the standard-path hooks file and rejects a
    # manifest-level pointer to it as a duplicate-load error (visible to the
    # user as "Duplicate hooks file detected" under /plugin → Errors). The
    # `hooks` manifest key is reserved for non-standard hook files; sumo-qa
    # has none.
    return {
        "$schema": _SCHEMA_URL,
        "name": plugin.name,
        "displayName": plugin.display_name,
        "version": plugin.version,
        "description": plugin.description,
        "author": plugin.author,
        "homepage": plugin.homepage,
        "repository": plugin.repository,
        "license": plugin.license,
        "keywords": list(plugin.keywords),
        "mcpServers": "./.mcp.json",
    }
