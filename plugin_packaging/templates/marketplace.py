# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Renders .claude-plugin/marketplace.json for Claude Code.

Schema: https://json.schemastore.org/claude-code-marketplace.json
Reference: https://code.claude.com/docs/en/plugin-marketplaces

This is the catalog Claude Code reads after
`/plugin marketplace add sumithr/sumo-qa`. The repo IS the plugin
(pyproject.toml + src/sumo_qa/ + skills/ + .claude-plugin/plugin.json all
live at the repo root), so the marketplace lists a single plugin whose
`source` is the marketplace root itself ("./"). Listing metadata
propagates from the canonical `[tool.sumo-qa.plugin]` overlay only — no
field is hand-typed here.
"""

from __future__ import annotations

from plugin_packaging.canonical import CanonicalPlugin

_SCHEMA_URL = "https://json.schemastore.org/claude-code-marketplace.json"


def render(plugin: CanonicalPlugin) -> dict:
    # The repo root is both the marketplace root and the plugin root, so the
    # marketplace-root-relative source is "./" (the schema's relative-path
    # form requires the leading "./").
    entry: dict = {
        "name": plugin.name,
        "source": "./",
        # The listing description prefers the issue-#84 marketplace short
        # copy; falls back to the [project] description so the listing is
        # never blank.
        "description": plugin.short_description or plugin.description,
        "version": plugin.version,
        "author": plugin.author,
        "homepage": plugin.homepage,
        "repository": plugin.repository,
        "license": plugin.license,
        "keywords": list(plugin.keywords),
        "category": plugin.category,
    }
    return {
        "$schema": _SCHEMA_URL,
        "name": plugin.name,
        "owner": plugin.author,
        "plugins": [entry],
    }
