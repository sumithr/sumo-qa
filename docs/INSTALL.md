# Install

## One-line (recommended)

```bash
python install.py
```

Runs on Windows, macOS, and Linux. Does:

1. Installs `sumo-qa-mcp` via `uv tool install`
2. Symlinks `skills/` into `~/.claude/skills/sumo-qa/` if Claude Code is detected (copies on Windows without developer mode)
3. Prints the MCP config snippet to paste into your host

If `uv` isn't installed, the script tells you how to install it for your OS.

## AI agent setup

If you're running an AI agent (Claude Code, Copilot CLI, etc.) in this repo, just point it at [AGENTS.md](../AGENTS.md). It walks through the per-host setup, detects which host it's in, runs what it can with its existing tools, and hands off steps it can't do (e.g. IntelliJ Settings UI) to you.

## Manual (per host)

### Claude Code

```bash
ln -sfn "$(pwd)/skills" ~/.claude/skills/sumo-qa   # macOS / Linux
# Windows (PowerShell, developer mode on):
# New-Item -ItemType SymbolicLink -Path "$env:USERPROFILE\.claude\skills\sumo-qa" -Target "$(Get-Location)\skills"
```

Add to `~/.config/claude/claude_desktop_config.json` (macOS/Linux) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "sumo-qa": { "command": "sumo-qa-mcp" }
  }
}
```

### IntelliJ AI Assistant

Settings → Tools → AI Assistant → Model Context Protocol → Add server with command `sumo-qa-mcp`. Skills auto-register as MCP prompts at startup.

### VS Code + GitHub Copilot

Edit `.vscode/mcp.json`:

```json
{
  "mcpServers": {
    "sumo-qa": { "command": "sumo-qa-mcp" }
  }
}
```

`.github/copilot-instructions.md` already tells Copilot to fetch the sumo-qa prompts.

## Verify

Ask your host to call `sumo_qa_load_classifications()`. If the response contains the 10 canonical classification names, you're done.
