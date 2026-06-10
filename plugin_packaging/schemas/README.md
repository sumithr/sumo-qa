# Vendored host schemas

These JSON Schemas are vendored, not fetched at CI time, so the drift checks
work offline and the version we validate against is pinned to the commit.

- `claude-code-plugin-manifest.json` — fetched 2026-05-20 from
  https://json.schemastore.org/claude-code-plugin-manifest.json
  Used to validate `.claude-plugin/plugin.json`.
- `claude-code-marketplace.json` — fetched 2026-06-10 from
  https://json.schemastore.org/claude-code-marketplace.json
  Used to validate `.claude-plugin/marketplace.json` (the catalog read by
  `/plugin marketplace add`).
- `codex-hooks.json` — fetched 2026-05-20 from
  https://www.schemastore.org/codex-hooks.json
  Used to validate `hooks/hooks-codex.json`. Codex itself does not publish
  a plugin-manifest schema; the manifest is smoke-tested via the MCP
  handshake (see install-smoke.yml).

Refresh: re-run the curls above and inspect the diff. Bump after every
schema-store catalog change to the upstream files.
