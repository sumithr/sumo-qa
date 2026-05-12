# AGENTS.md — sumo-qa setup

If you're an AI agent setting up sumo-qa for the user, follow this exactly. One command for the common case; per-host flags if you only need to wire one host.

## Default: configure every detected host

```bash
python3 install.py
```

What this does:

1. Installs `sumo-qa-mcp` via `uv` (prints `uv` install instructions if missing).
2. **Claude Code** (if `~/.claude/` exists): symlinks each `skills/<name>/` into `~/.claude/skills/<name>/`. Writes `claude_desktop_config.json` with the MCP entry pointing at the absolute binary path.
3. **VS Code + Copilot** (if cwd is a workspace with `.git` / `.vscode` / `package.json` / etc.): writes `.vscode/mcp.json` with the **VS Code-native schema** (`servers` key, `type: stdio`).
4. **JetBrains IDEs** (if JetBrains config dir exists): prints exact Settings UI steps. JetBrains' MCP plugin requires Settings UI registration — external XML writes don't reliably register the runtime coroutine.
5. Verifies the binary responds to JSON-RPC `initialize`.

## Per-host flags

Use these when you only want to configure one host:

```bash
python3 install.py --claude-code              # Claude Code only
python3 install.py --vscode                   # VS Code workspace (cwd-based)
python3 install.py --vscode --workspace /path/to/repo
python3 install.py --jetbrains                # Prints JetBrains UI steps only
python3 install.py --vscode --skip-mcp-install   # Skip uv reinstall for speed
```

Re-runs are idempotent.

## VS Code specifics

- VS Code reads `.vscode/mcp.json` from the **workspace root**, not from `$HOME`. install.py refuses to write to `~/.vscode/mcp.json` and prints a clear error if you're cd'd into `$HOME`.
- VS Code uses a different MCP schema than Claude Desktop:
  ```json
  { "servers": { "sumo-qa": { "type": "stdio", "command": "...", "args": [] } } }
  ```
  install.py writes this format. Earlier versions wrote `mcpServers` (the Claude Desktop schema) which VS Code silently ignored. If you upgrade install.py and re-run, it strips the stale `mcpServers` key.
- After running install.py, in VS Code: **Cmd+Shift+P → Developer: Reload Window**. VS Code caches the MCP server list at startup; it doesn't re-read the file mid-session.
- Use **Agent mode** (not Ask, not Edit) in Copilot Chat. Tools require Agent mode.
- Use a capable model — **Claude Sonnet 4.5** or **GPT-5 (full)**. Mini/fast variants don't reliably call MCP tools.

## JetBrains specifics

JetBrains AI Assistant's MCP config (`llm.mcpServers.xml`) is not reliably writable externally on IDEA 2026.1 — the plugin requires its in-process Settings UI to register the runtime coroutine. install.py prints the exact UI fields (with the absolute binary path):

```
Settings → Tools → AI Assistant → Model Context Protocol → + Add server
  Name:    sumo-qa
  Command: <absolute path printed by install.py>
  Args:    (empty)
  Working directory: (empty)
Apply.
```

For **Junie** (JetBrains' agentic coding agent), drop this into `~/.junie/mcp/sumo-qa.json`:

```json
{
  "mcpServers": {
    "sumo-qa": {
      "command": "<absolute path printed by install.py>"
    }
  }
}
```

Or per-project at `<repo>/.junie/mcp/sumo-qa.json`. Junie reads MCP configs from those directories on startup.

## Verify

In any host, ask in chat:

```
load the QA classifications
```

You should get 10 canonical names back: api_contract_change, business_logic_change, security_change, performance_change, frontend_change, infrastructure_change, test_change, docs_change, config_change, data_migration. If yes, the MCP is wired correctly.

## After install

The host needs to re-read its MCP config:

- Claude Code: restart the app
- JetBrains IDEs: restart the IDE (or restart the AI Assistant tool window)
- VS Code: **Developer: Reload Window**

## What an AI agent can vs. must ask the user for

| You (the agent) CAN | You MUST ASK the user |
|---|---|
| Run `python3 install.py` (with whatever host flags) | Restart their host application(s) after install |
| Run the verification call | Anything that requires admin / sudo elevation |
| Re-run install.py to refresh | The JetBrains AI Assistant Settings UI add (it's a clicks-only flow; can't be scripted) |
| Verify Junie's `~/.junie/mcp/sumo-qa.json` file content | |
