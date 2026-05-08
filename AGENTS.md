# AGENTS.md — sumo-qa setup

If you are an AI agent in a code editor, follow these steps to set up
sumo-qa for the host you're running in. Do what you can with your
existing tools (bash, edit, write); explicitly hand off to the user
when you hit a step that needs UI clicks or admin permissions.

## Step 1 — detect your host

| Cue | Host |
|---|---|
| You have a `Skill` tool and `~/.claude/` exists | Claude Code |
| You're in a JetBrains IDE with MCP support but no `Skill` tool | IntelliJ AI Assistant |
| You're in VS Code with GitHub Copilot and MCP support | VS Code + Copilot |

## Step 2 — install the MCP server (host-agnostic)

```bash
uv tool install --from . sumo-qa-mcp
sumo-qa-mcp --help
```

If `uv` isn't installed:

- macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows: `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`

## Step 3 — register the MCP and load skills

### Claude Code

1. Symlink skills:

   - macOS / Linux:
     ```bash
     ln -sfn "$(pwd)/skills" ~/.claude/skills/sumo-qa
     ```
   - Windows (PowerShell, developer mode on):
     ```powershell
     New-Item -ItemType SymbolicLink -Path "$env:USERPROFILE\.claude\skills\sumo-qa" -Target "$(Get-Location)\skills"
     ```

2. Add MCP server. Edit:

   - macOS / Linux: `~/.config/claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

   Add:
   ```json
   {
     "mcpServers": {
       "sumo-qa": { "command": "sumo-qa-mcp" }
     }
   }
   ```

### IntelliJ AI Assistant

The agent typically cannot edit IntelliJ Settings programmatically. Hand
off to the user with these exact steps:

1. Open Settings (Cmd/Ctrl + ,)
2. Tools → AI Assistant → Model Context Protocol
3. Add server: command = `sumo-qa-mcp`
4. Skills are auto-exposed as MCP prompts. Invoke by name in AI Assistant chat.

### VS Code + Copilot

1. Edit `.vscode/mcp.json` in the workspace (or VS Code MCP config). Add:
   ```json
   {
     "mcpServers": {
       "sumo-qa": { "command": "sumo-qa-mcp" }
     }
   }
   ```

2. Skills are auto-exposed as MCP prompts. The repo's
   `.github/copilot-instructions.md` already tells Copilot to use them.

## Step 4 — verify

Ask the host to call `sumo_qa_load_classifications()`. If the response
contains the 10 canonical classification names (api_contract_change,
business_logic_change, security_change, ...), setup is complete.

If verification fails, check:
- `sumo-qa-mcp` is on PATH (`which sumo-qa-mcp` / `where sumo-qa-mcp`)
- The host's MCP config is syntactically valid
- The host has been restarted since the config edit

## What you can do, what you must ask the user for

| You CAN | You MUST ASK |
|---|---|
| Run `uv tool install` | Edits to user-level config files outside the workspace (claude_desktop_config.json, IntelliJ Settings UI) |
| Create symlinks (with developer mode on Windows) | Steps requiring sudo or admin elevation |
| Edit `.vscode/mcp.json` in the workspace | Steps requiring restarting the host |
| Run the verification step | |
