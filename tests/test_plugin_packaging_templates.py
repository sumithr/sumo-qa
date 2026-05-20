# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for plugin_packaging/templates/*.

Each template is a pure function from CanonicalPlugin to a JSON-
serialisable dict (or markdown text for the docs template). These
tests freeze the SHAPE — schema validation happens in
test_plugin_packaging_schema_validation.py.
"""

from __future__ import annotations

import pytest

from plugin_packaging.canonical import CanonicalPlugin, HookSpec, McpSpec
from plugin_packaging.templates import (
    claude_code,
    codex,
    hooks,
    host_adapters_doc,
    mcp,
)


@pytest.fixture
def plugin() -> CanonicalPlugin:
    return CanonicalPlugin(
        name="sumo-qa",
        version="9.9.9",
        description="d",
        license="Apache-2.0",
        author={"name": "T", "email": "t@t.test"},
        homepage="https://h.test",
        repository="https://r.test",
        display_name="Sumo QA",
        keywords=("qa", "tdd"),
        mcp=McpSpec(server_name="sumo-qa", command="sumo-qa"),
        hooks=(
            HookSpec(
                event="SessionStart",
                script="session-start",
                trigger="startup|clear|compact",
            ),
        ),
    )


def test_mcp_template_shape(plugin):
    out = mcp.render(plugin)
    assert out == {
        "mcpServers": {
            "sumo-qa": {
                "command": "sumo-qa",
                "args": [],
                "type": "stdio",
            }
        }
    }


def test_claude_code_template_required_fields(plugin):
    out = claude_code.render(plugin)
    assert out["$schema"] == "https://json.schemastore.org/claude-code-plugin-manifest.json"
    assert out["name"] == "sumo-qa"
    assert out["version"] == "9.9.9"
    assert out["description"] == "d"
    assert out["author"] == {"name": "T", "email": "t@t.test"}
    assert out["license"] == "Apache-2.0"
    assert out["keywords"] == ["qa", "tdd"]
    assert out["mcpServers"] == "./.mcp.json"
    assert out["hooks"] == "./hooks/hooks.json"


def test_codex_template_required_fields(plugin):
    out = codex.render(plugin)
    # Codex REQUIRES name, version, description (stricter than Claude Code)
    assert out["name"] == "sumo-qa"
    assert out["version"] == "9.9.9"
    assert out["description"] == "d"
    assert out["mcpServers"] == "./.mcp.json"
    assert out["hooks"] == "./hooks/hooks-codex.json"
    assert out["skills"] == "./skills/"


def test_hooks_template_claude_code_shape(plugin):
    out = hooks.render_claude_code(plugin)
    expected_cmd = '"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd" session-start'
    assert out == {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|clear|compact",
                    "hooks": [
                        {
                            "type": "command",
                            "command": expected_cmd,
                            "async": False,
                        }
                    ],
                }
            ]
        }
    }


def test_hooks_template_codex_shape(plugin):
    out = hooks.render_codex(plugin)
    # Codex hooks-schema: matcherGroups array of objects with `matcher` + `hooks`,
    # but no `async` flag (codex schema doesn't define it).
    assert "hooks" in out
    assert "SessionStart" in out["hooks"]
    groups = out["hooks"]["SessionStart"]
    assert isinstance(groups, list) and len(groups) == 1
    assert groups[0]["matcher"] == "startup|clear|compact"
    assert groups[0]["hooks"][0]["type"] == "command"
    assert "async" not in groups[0]["hooks"][0]


def test_host_adapters_doc_lists_both_hosts(plugin):
    text = host_adapters_doc.render(plugin)
    assert "# Host adapters" in text
    assert "Claude Code" in text
    assert "Codex" in text
    assert "https://json.schemastore.org/claude-code-plugin-manifest.json" in text
    # No skill body content leaking in
    assert "## When reviewing code" not in text
