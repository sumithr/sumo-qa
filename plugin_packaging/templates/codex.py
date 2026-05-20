# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Renders .codex-plugin/plugin.json for OpenAI Codex.

Reference: https://developers.openai.com/codex/plugins/build
No published JSON Schema — required fields (name/version/description)
come from the docs page. Validation falls back to MCP-handshake smoke.
"""

from __future__ import annotations

from plugin_packaging.canonical import CanonicalPlugin


def render(plugin: CanonicalPlugin) -> dict:
    return {
        "name": plugin.name,
        "version": plugin.version,
        "description": plugin.description,
        "author": plugin.author,
        "homepage": plugin.homepage,
        "repository": plugin.repository,
        "license": plugin.license,
        "keywords": list(plugin.keywords),
        "skills": "./skills/",
        "mcpServers": "./.mcp.json",
        "hooks": "./hooks/hooks-codex.json",
    }
