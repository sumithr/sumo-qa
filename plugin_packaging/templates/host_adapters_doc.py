# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Renders docs/host-adapters.md — the user-facing reference for which
hosts sumo-qa supports as native plugins and how each adapter is wired.

This file is GENERATED. Do not hand-edit; bump the canonical source
in pyproject.toml and re-run plugin_packaging.plugin_generator sync.
"""

from __future__ import annotations

from plugin_packaging.canonical import CanonicalPlugin

_TEMPLATE = """# Host adapters

> **Generated file.** Do not hand-edit. Source: `pyproject.toml` `[tool.sumo-qa.plugin]`.
> Regenerate with `python -m plugin_packaging.plugin_generator sync`.

`{name}` ships first-class plugin folders for two hosts today:

| Host | Manifest | Published JSON Schema | Validation in CI |
| --- | --- | --- | --- |
| Claude Code | `.claude-plugin/plugin.json` | https://json.schemastore.org/claude-code-plugin-manifest.json | Schema validation against vendored copy |
| OpenAI Codex | `.codex-plugin/plugin.json` | _none published_ | MCP `initialize` handshake smoke |

Both adapters share `.mcp.json`, `skills/`, and `assets/`. Hook files
diverge by schema (`hooks/hooks.json` for Claude Code, `hooks/hooks-codex.json`
for Codex) but are generated from the same `[[tool.sumo-qa.plugin.hooks]]`
overlay in `pyproject.toml`.

## Architecture

The canonical source is `pyproject.toml`:

- Shared metadata (`name`, `version`, `description`, `license`,
  `author`, `homepage`, `repository`) flows from `[project]` and
  `[project.urls]`. It is not duplicated.
- Plugin-specific overlay lives under `[tool.sumo-qa.plugin]`.

The generator (`python -m plugin_packaging.plugin_generator sync`)
reads this canonical source, emits every committed plugin folder, and
writes a SHA256 sidecar at `plugin_packaging/generated/manifest.json`.
CI runs `python -m plugin_packaging.plugin_generator check` on every PR
— if any emitted file drifts from the canonical source, the gate
fails.

## Wheel-vs-repo path resolution

- `pip install sumo-qa && sumo-qa-install` — installer resolves bundled
  content from `<site-packages>/sumo_qa/_data/{{skills,hooks,assets}}/`.
- `claude plugin install <repo>` / git clone — content lives at repo
  root; plugin manifests use repo-root-relative paths (`./skills/`,
  `./hooks/hooks.json`).

The wheel bundles `skills/`, `hooks/`, and `assets/` via
`[tool.hatch.build.targets.wheel.force-include]` so both layouts work
out of the box.

## Adding a new host

1. Add `plugin_packaging/templates/<host>.py` rendering
   `CanonicalPlugin -> dict`.
2. Wire it into `plugin_packaging/plugin_generator.py`'s sync map.
3. Run `python -m plugin_packaging.plugin_generator sync`.
4. If the host publishes a JSON Schema, vendor it under
   `plugin_packaging/schemas/` and add a validation case to
   `plugin_packaging/validate_plugins.py`. Otherwise, extend the
   install-smoke matrix with a `--plugin-dir`-style MCP handshake.

## Supported adapters

- **Claude Code** — `claude plugin install <this-repo>` reads
  `.claude-plugin/plugin.json` and auto-discovers `skills/`, `hooks/`,
  and `.mcp.json`.
- **Codex** — `/plugins install <this-repo>` reads
  `.codex-plugin/plugin.json` and follows the explicit `skills`/
  `mcpServers`/`hooks` paths.

The `pip install sumo-qa && sumo-qa-install` flow remains the primary
distribution channel for Claude Desktop, VS Code, and JetBrains. See
[INSTALL.md](INSTALL.md).
"""


def render(plugin: CanonicalPlugin) -> str:
    return _TEMPLATE.format(name=plugin.name)
