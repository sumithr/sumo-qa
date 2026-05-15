# Install

## One line, any host

```bash
pip install sumo-qa && sumo-qa-install --claude-code
```

Swap `--claude-code` for `--vscode --workspace <path-to-repo>` (VS Code + Copilot), `--jetbrains` (JetBrains AI Assistant), or drop the flag entirely to configure every host detected on this machine. Works identically on Windows / macOS / Linux — `pip` generates `.exe` wrappers on Windows, so no `python3` invocation involved.

`pip install sumo-qa` puts both binaries on PATH: `sumo-qa` (the MCP server) and `sumo-qa-install` (the configurator that wires it into your host). The chained `sumo-qa-install` step then symlinks skills into `~/.claude/skills/`, writes `claude_desktop_config.json` / `.vscode/mcp.json`, or prints JetBrains UI steps — depending on the flag.

Restart your host (or open a fresh chat) once it's done.

## Other MCP-capable hosts

For hosts beyond Claude Code, VS Code + Copilot, and JetBrains (which `sumo-qa-install` handles directly), the `sumo-qa` binary you get from `pip install sumo-qa` exposes a standard stdio MCP server. To wire it into any other MCP-capable host, follow that host's own MCP-server setup documentation and point it at the absolute path of `sumo-qa` on your machine (run `which sumo-qa` or `where sumo-qa` on Windows to find it).

We haven't verified those host-specific paths end-to-end ourselves, so we don't ship per-host instructions — but the underlying server is a vanilla MCP stdio server and should work wherever MCP works.

## Per-host flags

When you only want to configure one host (or you're scripting per-host install):

```bash
sumo-qa-install --claude-code             # Claude Code only
sumo-qa-install --claude-desktop          # Claude Desktop app only
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
| Symlinks in `~/.claude/skills/`, `claude_desktop_config.json`, `.vscode/mcp.json` | re-running `sumo-qa-install` |
| Skill content the agent reads each turn | next chat session (the SessionStart hook re-fires) |

You only strictly need to re-run `sumo-qa-install` when **new** skills are added or a host's MCP config schema changes; routine content updates flow through the existing symlinks automatically.

## Per-host detail

### Claude Code

`sumo-qa-install --claude-code` does three things:

1. Symlinks each `skills/<name>/` directory (either from the bundled `sumo_qa/_data/skills/` after `pip install`, or from the repo `skills/` in dev mode) into `~/.claude/skills/<name>/` so Claude Code's native skill loader picks them up as top-level skills. Earlier versions used a wrapper symlink (`~/.claude/skills/sumo-qa/`) — that was wrong because Claude Code doesn't recurse. Each skill is now its own top-level entry.
2. Registers the MCP server with Claude Code via `claude mcp add sumo-qa <abs-binary-path> -s user`. This is what makes the MCP tools (`sumo_qa_load_classifications`, `sumo_qa_find_test_data`, etc.) actually surface inside Claude Code sessions — without this step, only the skill files are visible in the slash menu, not the underscored MCP tools. Idempotent (any existing `sumo-qa` entry is removed first). Skipped silently if the `claude` CLI isn't on PATH.
3. Writes the MCP server entry into `claude_desktop_config.json` (at `~/.config/claude/` on macOS/Linux, `%APPDATA%\Claude\` on Windows). This file is for Claude Desktop, not Claude Code (which uses the `claude mcp` registry from step 2). Kept so a parallel Claude Desktop install picks up sumo-qa for free.

After install: restart Claude Code. Type `/` and start typing `sumo-qa-`:

- **14 skills appear with hyphens** (`/sumo-qa-deciding-approach`, `/sumo-qa-creating-test-plan`, …) — Claude Code's native skill loader picks these up from `~/.claude/skills/<skill>/`.
- **MCP tools appear with underscores** (`/sumo_qa_load_classifications`, `/sumo_qa_find_test_data`, …) — registered through the MCP server. Because the 14 skills are *also* registered through MCP, you'll typically see both hyphen and underscore variants for each skill in the slash menu. They call the same SKILL.md content and behave identically.

Natural language always works too — ask *"review my changes"* or *"load the QA classifications"* and Claude Code routes by tool description. Use whichever style you prefer.

### Claude Desktop (macOS app, incl. Cowork)

`sumo-qa-install --claude-desktop` writes the sumo-qa MCP entry into the config file that the **Claude Desktop app** reads — the macOS `Claude.app` (and its Windows/Linux equivalents). This is the same app that powers Cowork mode, which has full code capabilities and runs agent tasks in the background.

The config path is **different** from the one Claude Code uses:

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` (uppercase `Claude`) |

The installer:

1. Checks whether the parent directory exists. If not, Claude Desktop is assumed not to be installed and the step is skipped (not an error).
2. If the config file exists, reads it and merges the `sumo-qa` key into `mcpServers` — existing entries (e.g. `obsidian`, `github`) are preserved unchanged. If the existing JSON is invalid, it is not touched and an error is printed instead.
3. If the config file does not exist but the parent directory does, creates it with just the `sumo-qa` entry.

After install: **quit and reopen Claude Desktop** (or restart the relevant Cowork session). The `sumo-qa` MCP tools will appear in the tools panel.

Note: `sumo-qa-install --claude-code` also writes a `claude_desktop_config.json`, but to `~/.config/claude/` (lowercase) — a path Claude Desktop does **not** read. That write is kept for backward compatibility. The `--claude-desktop` flag is the authoritative path for Claude Desktop users.

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

Add once; persists across restarts. After it's added, every MCP entry — `/sumo_qa_deciding_approach`, `/sumo_qa_load_classifications`, etc. — appears in AI Assistant chat's slash menu.

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
4. Click the **tools / hammer icon** — `sumo-qa` should be listed with the 25 tools underneath

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
