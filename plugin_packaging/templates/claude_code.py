# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Renders .claude-plugin/plugin.json for Claude Code.

Schema: https://json.schemastore.org/claude-code-plugin-manifest.json
Reference: https://code.claude.com/docs/en/plugins-reference
"""

from __future__ import annotations

from plugin_packaging.canonical import CanonicalPlugin

_SCHEMA_URL = "https://json.schemastore.org/claude-code-plugin-manifest.json"


def render(plugin: CanonicalPlugin) -> dict:
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
        "hooks": "./hooks/hooks.json",
    }
