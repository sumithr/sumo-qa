# Install

There are two install paths depending on which host you're using:

- **Native-plugin path** — Claude Code, Cursor, Codex, OpenCode (one-line install per host).
- **`sumo-qa-install` path** — JetBrains AI Assistant, Junie, VS Code + Copilot (or batch-install across hosts). Requires `pip install sumo-qa` first; that puts both `sumo-qa` (the MCP server binary) and `sumo-qa-install` (the configurator) on your PATH. On Windows, pip generates `.exe` wrappers automatically — no `python` vs `python3` vs `py` to deal with.

## Native-plugin install (Claude Code, Cursor, Codex, OpenCode)

These hosts have plugin systems that read `.claude-plugin/`, `.cursor-plugin/`, `.codex-plugin/`, `.opencode/` directly from the repo — no `sumo-qa-install` needed.

### Claude Code

```text
/plugin marketplace add sumithr/sumo-qa
/plugin install sumo-qa@sumo-qa-dev
```

This installs the skills, registers the SessionStart hook (auto-injects the `using-sumo-qa` router on every conversation), and you're done. To also get the MCP tools (knowledge loaders + test-data tools), install the server binary:

```bash
uv tool install --from git+https://github.com/sumithr/sumo-qa.git sumo-qa
```

Then add it to `claude_desktop_config.json` (or let `sumo-qa-install --claude-code` do it).

### Cursor

```text
/add-plugin sumo-qa
```

Or add to `.cursor/plugins.json`. The plugin declares `"skills": "./skills/"` and `"hooks": "./hooks/hooks-cursor.json"` so Cursor picks up both automatically.

### Codex

Install from the Codex plugin marketplace — search for "Sumo QA". The plugin ships an `interface` block (display name, default prompts, etc.) so it shows up correctly in the Codex UI.

### OpenCode

See [`.opencode/INSTALL.md`](../.opencode/INSTALL.md) — add `"sumo-qa@git+https://github.com/sumithr/sumo-qa.git"` to your `opencode.json` plugin array. Includes a Claude-Code-to-OpenCode tool-name mapping table for skill authors.

## `sumo-qa-install` path (JetBrains, VS Code + Copilot, batch installs)

```bash
pip install sumo-qa
sumo-qa-install
```

Configures every supported host detected on this machine. Runs on Windows, macOS, and Linux — no `python` invocation; `pip` generates the right wrapper (`sumo-qa-install.exe` on Windows).

## Per-host flags

When you only want to configure one host (or you're scripting per-host install):

```bash
sumo-qa-install --claude-code             # Claude Code only
sumo-qa-install --vscode                  # VS Code: writes <cwd>/.vscode/mcp.json
sumo-qa-install --vscode --workspace /path/to/repo
sumo-qa-install --jetbrains               # prints Settings UI steps
sumo-qa-install --vscode --skip-mcp-install   # skip uv reinstall (faster re-runs)
```

`sumo-qa-install --help` for the full list.

## Updating

```bash
pip install --upgrade sumo-qa     # refresh server + bundled skills/knowledge
sumo-qa-install                   # refresh symlinks + host configs (Claude Code, VS Code, …)
# Restart Claude Code / open a fresh chat — the SessionStart hook re-injects new content.
```

What each step refreshes:

| What changed in the new version | What picks it up |
|---|---|
| `sumo-qa` binary, MCP tools, bundled standards/knowledge/skills in site-packages | `pip install --upgrade` |
| Symlinks in `~/.claude/skills/`, `.cursor/plugins.json`, `claude_desktop_config.json`, `.vscode/mcp.json` | re-running `sumo-qa-install` |
| Skill content the agent reads each turn | next chat session (the SessionStart hook re-fires) |

You only strictly need to re-run `sumo-qa-install` when **new** skills are added or a host's MCP config schema changes; routine content updates flow through the existing symlinks automatically.

## Per-host detail

### Claude Code

`sumo-qa-install --claude-code` does two things:

1. Symlinks each `skills/<name>/` directory (either from the bundled `sumo_qa/_data/skills/` after `pip install`, or from the repo `skills/` in dev mode) into `~/.claude/skills/<name>/` so Claude Code's native skill loader picks them up as top-level skills. Earlier versions used a wrapper symlink (`~/.claude/skills/sumo-qa/`) — that was wrong because Claude Code doesn't recurse. Each skill is now its own top-level entry.
2. Writes the MCP server entry into `claude_desktop_config.json` (at `~/.config/claude/` on macOS/Linux, `%APPDATA%\Claude\` on Windows) with the absolute binary path.

After install: restart Claude Code. Type `/qa-` in chat — you should see the 13 skills in autocomplete.

**MCP tools are NOT slash-invocable in Claude Code.** Only skill files (the 10 `qa-*` and `using-sumo-qa`, `sumo-qa-strategising`) show up in the `/` menu. To call an MCP tool, ask in natural language (*"load the QA classifications"*) and Claude Code's AI picks it up by description.

### JetBrains AI Assistant + Junie

JetBrains' MCP plugin in IDEA 2026.1 has an undocumented internal flow we can't reliably hit by writing the XML config externally — entries written that way show up disabled with `LazyStandaloneCoroutine cancelled` in the UI. The supported path is the Settings UI.

`sumo-qa-install --jetbrains` prints:

```
Settings → Tools → AI Assistant → Model Context Protocol → + Add server
  Name:    sumo-qa
  Command: /abs/path/to/sumo-qa
  Args:    (empty)
  Working directory: (empty)
Apply.
```

Add once; persists across restarts. After it's added, every MCP entry — `/qa_deciding_approach`, `/sumo_qa_load_classifications`, etc. — appears in AI Assistant chat's slash menu.

**Junie** (JetBrains' agentic coding agent, separate from AI Assistant) reads MCP configs from JSON files in `~/.junie/mcp/` (global) or `<repo>/.junie/mcp/` (per-project). Create one named `sumo-qa.json`:

```json
{
  "mcpServers": {
    "sumo-qa": {
      "command": "/abs/path/to/sumo-qa"
    }
  }
}
```

(Use the absolute path that `sumo-qa-install` prints. Note: Junie uses the `mcpServers` schema, NOT VS Code's `servers` schema.)

### VS Code + GitHub Copilot

`sumo-qa-install --vscode --workspace /path/to/repo` writes `<repo>/.vscode/mcp.json` using VS Code's native schema:

```json
{
  "servers": {
    "sumo-qa": {
      "type": "stdio",
      "command": "/abs/path/to/sumo-qa",
      "args": []
    }
  }
}
```

This is DIFFERENT from the schema Claude Desktop / Junie use (which is `{ "mcpServers": { ... } }` without a `type` field). VS Code only reads the `servers` key.

After install:

1. **Cmd+Shift+P → Developer: Reload Window** (VS Code caches the MCP server list at startup)
2. In Copilot Chat: switch to **Agent mode** (not Ask, not Edit)
3. Switch model to **Claude Sonnet 4.5** or **GPT-5 full** (mini models can't reliably call MCP tools)
4. Click the **tools / hammer icon** — `sumo-qa` should be listed with the 24 tools underneath

Invocation: natural language only — Copilot's slash menu doesn't route to MCP tools. Ask *"load the QA classifications"* and Copilot will call the right tool by description.

### User-level VS Code install (any workspace)

If you want sumo-qa available in every workspace VS Code opens, use VS Code's user settings instead of a workspace file:

1. Cmd+Shift+P → **MCP: Add Server**
2. Pick **Command (stdio)**
3. Server ID: `sumo-qa`
4. Command: the absolute path `sumo-qa-install` printed
5. Save in **User settings** (not Workspace)

## Verify

In any host, ask:

```
load the QA classifications
```

You should get 10 names back: api_contract_change, business_logic_change, security_change, performance_change, frontend_change, infrastructure_change, test_change, docs_change, config_change, data_migration.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "no tools available" in Copilot Chat | VS Code reloaded with old schema or no MCP entry visible | Cmd+Shift+P → Developer: Reload Window; verify `.vscode/mcp.json` has `"servers"` key (not `"mcpServers"`) |
| "LazyStandaloneCoroutine was cancelled" in JetBrains MCP list | External XML write didn't register the runtime coroutine | Remove the entry; re-add via Settings UI with absolute path |
| Claude Code shows only some skills | Earlier wrapper-symlink install left stale top-level dirs | `sumo-qa-install --claude-code` cleans up and re-symlinks at the right granularity |
| "Unknown command: /sumo_qa_load_classifications" in Claude Code | MCP tools aren't slash-invocable in Claude Code by design | Use natural language ("load the QA classifications") instead, OR use `/qa-*` skill names (hyphens) for the 13 skills |
| `sumo-qa-install` says "VS Code skipped: not a workspace" | Ran from `$HOME` or a directory without `.git`/`.vscode`/project marker | Re-run with `--workspace /path/to/repo`, or cd into a workspace first |
| `python3 install.py` opens Windows Store / "command not found" | Either no `python3` on this Windows machine (Windows ships only a Store stub) or no install.py on disk (pip-only install never had it) | Use the console-script entry instead: `pip install sumo-qa` then `sumo-qa-install`. Avoids the `python3` shell-stub issue entirely. |
| Copilot says "I don't have access to those tools" with mini model | Mini/fast model can't reliably call MCP tools | Switch to Claude Sonnet 4.5 or GPT-5 full in Copilot's model picker |

## Manual install (no `sumo-qa-install`)

If you're not running `sumo-qa-install` for any reason, the binary path you need everywhere is:

```bash
uv tool install --from . sumo-qa --reinstall
which sumo-qa   # or: ls ~/.local/share/uv/tools/sumo-qa/bin/sumo-qa
```

Then paste that absolute path into each host's MCP config in the schema appropriate to that host (see "Per-host detail" above).
