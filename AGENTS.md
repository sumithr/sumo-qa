# AGENTS.md — sumo-qa setup

One command. Idempotent. Works on Claude Code, JetBrains IDEs, and VS Code + Copilot, on Windows, macOS, and Linux.

## Install

```bash
python3 install.py
```

What it does end-to-end:

1. Installs `sumo-qa-mcp` via `uv` (prints `uv` install instructions if missing).
2. **Claude Code** (if `~/.claude/` exists): symlinks `skills/` into `~/.claude/skills/sumo-qa`; writes `claude_desktop_config.json` with the MCP entry pointing at the absolute binary path.
3. **JetBrains IDEs** (any IntelliJ / PyCharm / GoLand / WebStorm / RubyMine / PhpStorm / CLion / Rider / DataGrip / AppCode / Android Studio installation found): writes a `sumo-qa` entry into each IDE's `options/llm.mcpServers.xml` with the absolute binary path. Preserves any existing MCP entries the user already had.
4. **VS Code + Copilot** (if run inside a workspace with `.git` or `.vscode`): writes `.vscode/mcp.json` with the absolute binary path.
5. Verifies the binary responds to a JSON-RPC `initialize` ping.

Re-run any time to refresh.

## After install — restart the host

The host needs to re-read its MCP config:

- Claude Code: restart the app
- JetBrains IDEs: restart the IDE (or just the AI Assistant tool window)
- VS Code: restart the Copilot extension or reload the window

## Verify

In any host, ask it to call `sumo_qa_load_classifications`. Expected response: text containing the 10 canonical classification names (api_contract_change, business_logic_change, security_change, …, data_migration).

## Why absolute paths

JetBrains IDEs and some other hosts launch MCP subprocesses without inheriting your shell PATH. Using `sumo-qa-mcp` as a bare command fails with `LazyStandaloneCoroutine was cancelled` (or similar) because the binary isn't found. `install.py` writes the absolute uv-tool path everywhere, so this never happens.

## What an AI agent can vs. must ask the user for

| You (the agent) CAN | You MUST ASK the user |
|---|---|
| Run `python3 install.py` | Restart their host application(s) after the MCP entries land |
| Run the verification call | Anything that requires admin / sudo elevation |
| Re-run install.py to refresh | — |

There are no remaining manual config-paste steps. Every supported host's MCP entry is written by `install.py`.
