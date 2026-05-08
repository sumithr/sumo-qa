# Install

Manual install paths. The recommended path is the one-command installer at the repo root:

```bash
./install.sh
```

That script installs `uv` if needed, isolates the MCP into its own environment with a known-working Python, puts `sumo-qa-mcp` on your PATH, and prints the JSON config block to paste.

If you'd rather not run the script, pick whichever of the following you already have.

## uv (recommended manual path)

`uv` downloads its own Python if needed, sidestepping the "your Python is 3.14 / pydantic-core has no wheel / Rust missing" trap.

```bash
uv tool install /path/to/sumo-qa-mcp
```

## pipx

Requires Python 3.10–3.13 already on PATH.

```bash
pipx install --python python3.12 /path/to/sumo-qa-mcp
```

## Docker

```bash
docker build -t sumo-qa-mcp .
```

Then in your host's MCP config:

```json
{
  "mcpServers": {
    "sumo-qa": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "sumo-qa-mcp"]
    }
  }
}
```

## Where each host wants the JSON

| Host | Path / location |
|---|---|
| Claude Code | `~/.config/claude/claude_desktop_config.json` (`mcpServers`), or `claude mcp add` |
| Cursor | Settings → Tools & Integrations → MCP → Add server |
| Windsurf | Settings → MCP Servers |
| IntelliJ AI Assistant | Settings → Tools → AI Assistant → Model Context Protocol (2025.x+) |
| GitHub Copilot (VS Code) | Settings → Copilot → MCP Servers |

For env-var configuration (custom standards / rules / test data paths), see [docs/CONFIGURATION.md](CONFIGURATION.md).
