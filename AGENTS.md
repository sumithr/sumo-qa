# AGENTS.md — sumo-qa setup

If you're an AI agent in a code editor, run the installer. It handles
every supported host on this machine automatically, except the one
IntelliJ step that needs the Settings UI.

## The whole install

```bash
python3 install.py
```

What it does:

1. Installs `sumo-qa-mcp` via `uv` (installs `uv` instructions if missing).
2. For **Claude Code** (if `~/.claude/` exists): symlinks `skills/` into
   `~/.claude/skills/sumo-qa`, writes `claude_desktop_config.json` with the
   absolute path to the binary.
3. For **VS Code + Copilot** (if running inside a `.git`/`.vscode` workspace):
   writes `.vscode/mcp.json` in the workspace with the absolute path.
4. For **IntelliJ AI Assistant** (if a JetBrains config dir exists): prints
   the exact Settings-UI fields to fill in, with the absolute binary path
   pre-filled. The JetBrains MCP plugin doesn't expose a programmable
   config API; this step is unavoidable until JetBrains ships one.
5. Verifies the binary responds to a JSON-RPC `initialize` ping.

Re-run any time. Idempotent.

## The IntelliJ step

After install.py finishes it prints something like:

```
[...] IntelliJ AI Assistant: detected IntelliJIdea2026.1.
      Open IntelliJ -> Settings -> Tools -> AI Assistant ->
      Model Context Protocol -> Add server, with these fields:

        Name:    sumo-qa
        Command: /Users/.../.local/share/uv/tools/sumo-qa/bin/sumo-qa-mcp
        Args:    (empty)

      Apply, then restart the AI Assistant chat panel.
```

Follow that. The absolute path matters — IntelliJ's subprocess launcher
doesn't inherit your shell PATH, so a bare `sumo-qa-mcp` command will fail
to start (LazyStandaloneCoroutine cancelled).

If you already added the MCP with a bare command and it's broken, edit the
existing entry in Settings and replace the Command field with the absolute
path shown by install.py.

## Verify

In any host, ask it to call `sumo_qa_load_classifications`. If you get back
text containing the 10 canonical classification names (api_contract_change,
business_logic_change, security_change, performance_change, frontend_change,
infrastructure_change, test_change, docs_change, config_change,
data_migration), the MCP is wired correctly.

## What an AI agent can vs. must ask the user for

| You (the agent) CAN | You MUST ASK the user |
|---|---|
| Run `python3 install.py` | The IntelliJ Settings-UI step (you can't click into Settings panels programmatically) |
| Run the verification call | Restarting the AI Assistant chat panel after IntelliJ Settings change |
| Re-run install.py to refresh | Editing user-level files outside what install.py already handles |
