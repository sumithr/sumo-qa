# Host adapters

> **Generated file.** Do not hand-edit. Source: `pyproject.toml` `[tool.sumo-qa.plugin]`.
> Regenerate with `python -m plugin_packaging.plugin_generator sync`.

`sumo-qa` ships first-class plugin folders for two hosts today:

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
  content from `<site-packages>/sumo_qa/_data/{skills,hooks,assets}/`.
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

- **Claude Code** — `.claude-plugin/plugin.json` auto-discovers `skills/`,
  `hooks/`, and `.mcp.json`. Loaded today via `claude --plugin-dir <repo>`
  (session-scoped local-dev); persistent marketplace install
  (`claude plugin install …`) is on the roadmap pending marketplace
  publication.
- **Codex** — `.codex-plugin/plugin.json` declares explicit `skills` /
  `mcpServers` / `hooks` paths. The install + MCP-server-launch flow
  hasn't been verified end-to-end yet; treat as TBD until confirmed.

The `pip install sumo-qa && sumo-qa-install` flow is the canonical
persistent install for every host (Claude Code, Claude Desktop, VS Code,
JetBrains). See [INSTALL.md](INSTALL.md).
