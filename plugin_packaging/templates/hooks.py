# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Renders hooks/hooks.json (Claude Code shape) and hooks/hooks-codex.json.

Both files come from the same [[tool.sumo-qa.plugin.hooks]] overlay.
Shapes differ: Claude Code uses ${CLAUDE_PLUGIN_ROOT} substitution and
accepts `async`; Codex's published hooks schema is matcher-group-shaped
without `async`.
"""

from __future__ import annotations

from collections import defaultdict

from plugin_packaging.canonical import CanonicalPlugin


def _command_claude_code(script: str) -> str:
    return f'"${{CLAUDE_PLUGIN_ROOT}}/hooks/run-hook.cmd" {script}'


def _command_codex(script: str) -> str:
    # Codex uses repo-relative paths; ${CLAUDE_PLUGIN_ROOT} is Claude-only.
    return f"./hooks/run-hook.cmd {script}"


def render_claude_code(plugin: CanonicalPlugin) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for hook in plugin.hooks:
        grouped[hook.event].append(
            {
                "matcher": hook.trigger,
                "hooks": [
                    {
                        "type": "command",
                        "command": _command_claude_code(hook.script),
                        "async": False,
                    }
                ],
            }
        )
    return {"hooks": dict(grouped)}


def render_codex(plugin: CanonicalPlugin) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for hook in plugin.hooks:
        grouped[hook.event].append(
            {
                "matcher": hook.trigger,
                "hooks": [
                    {
                        "type": "command",
                        "command": _command_codex(hook.script),
                    }
                ],
            }
        )
    return {"hooks": dict(grouped)}
