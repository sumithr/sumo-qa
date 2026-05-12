# AGENTS.md — sumo-qa setup

If you're an AI agent setting up sumo-qa for the user, follow this exactly. One command for the common case; per-host flags if you only need to wire one host.

## Default: configure every detected host

```bash
pip install sumo-qa
sumo-qa-install
```

`pip install sumo-qa` puts both `sumo-qa` (the MCP server binary) and `sumo-qa-install` (this configurator) on PATH. On Windows, `pip` generates `.exe` wrappers — no `python3` invocation needed.

What `sumo-qa-install` does:

1. Locates the `sumo-qa` MCP binary. If `pip install sumo-qa` already put it on PATH (the common case), uses that path directly — no `uv` invocation. If `sumo-qa` is not on PATH yet, falls back to `uv tool install` and prints `uv` install instructions if `uv` is also missing.
2. **Claude Code** (if `~/.claude/` exists): symlinks each `skills/<name>/` into `~/.claude/skills/<name>/`. Writes `claude_desktop_config.json` with the MCP entry pointing at the absolute binary path.
3. **VS Code + Copilot** (if cwd is a workspace with `.git` / `.vscode` / `package.json` / etc.): writes `.vscode/mcp.json` with the **VS Code-native schema** (`servers` key, `type: stdio`).
4. **JetBrains IDEs** (if JetBrains config dir exists): prints exact Settings UI steps. JetBrains' MCP plugin requires Settings UI registration — external XML writes don't reliably register the runtime coroutine.
5. Verifies the binary responds to JSON-RPC `initialize`.

## Per-host flags

Use these when you only want to configure one host:

```bash
sumo-qa-install --claude-code              # Claude Code only
sumo-qa-install --vscode                   # VS Code workspace (cwd-based)
sumo-qa-install --vscode --workspace /path/to/repo
sumo-qa-install --jetbrains                # Prints JetBrains UI steps only
sumo-qa-install --vscode --skip-mcp-install   # Skip uv reinstall for speed
```

Re-runs are idempotent.

## Updating

```bash
pip install --upgrade sumo-qa     # refresh server + bundled skills/knowledge
sumo-qa-install                   # refresh host symlinks + MCP configs
# Restart the host or open a fresh chat — SessionStart hook re-injects new content
```

You only strictly need the second step when new skills are added or a host's MCP config schema changes; routine content updates flow through the existing symlinks automatically.

## VS Code specifics

- VS Code reads `.vscode/mcp.json` from the **workspace root**, not from `$HOME`. `sumo-qa-install` refuses to write to `~/.vscode/mcp.json` and prints a clear error if you're cd'd into `$HOME`.
- VS Code uses a different MCP schema than Claude Desktop:
  ```json
  { "servers": { "sumo-qa": { "type": "stdio", "command": "...", "args": [] } } }
  ```
  `sumo-qa-install` writes this format. Earlier versions wrote `mcpServers` (the Claude Desktop schema) which VS Code silently ignored. On re-run, the installer strips the stale `mcpServers` key.
- After running `sumo-qa-install`, in VS Code: **Cmd+Shift+P → Developer: Reload Window**. VS Code caches the MCP server list at startup; it doesn't re-read the file mid-session.
- Use **Agent mode** (not Ask, not Edit) in Copilot Chat. Tools require Agent mode.
- Use a capable model — **Claude Sonnet 4.5** or **GPT-5 (full)**. Mini/fast variants don't reliably call MCP tools.

## JetBrains specifics

JetBrains AI Assistant's MCP config (`llm.mcpServers.xml`) is not reliably writable externally on IDEA 2026.1 — the plugin requires its in-process Settings UI to register the runtime coroutine. `sumo-qa-install` prints the exact UI fields (with the absolute binary path):

```
Settings → Tools → AI Assistant → Model Context Protocol → + Add server
  Name:    sumo-qa
  Command: <absolute path printed by sumo-qa-install>
  Args:    (empty)
  Working directory: (empty)
Apply.
```

For **Junie** (JetBrains' agentic coding agent), drop this into `~/.junie/mcp/sumo-qa.json`:

```json
{
  "mcpServers": {
    "sumo-qa": {
      "command": "<absolute path printed by sumo-qa-install>"
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
| Run `pip install sumo-qa` then `sumo-qa-install` (with whatever host flags) | Restart their host application(s) after install |
| Run the verification call | Anything that requires admin / sudo elevation |
| Re-run `sumo-qa-install` to refresh | The JetBrains AI Assistant Settings UI add (it's a clicks-only flow; can't be scripted) |
| Verify Junie's `~/.junie/mcp/sumo-qa.json` file content | |
