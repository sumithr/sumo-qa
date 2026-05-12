# Installing Sumo QA for OpenCode

## Prerequisites

- [OpenCode.ai](https://opencode.ai) installed
- `uv` (used to install the `sumo-qa` server binary that the skills call). Get it with `curl -LsSf https://astral.sh/uv/install.sh | sh` if you don't have it.

## Installation

Add sumo-qa to the `plugin` array in your `opencode.json` (global or project-level):

```json
{
  "plugin": ["sumo-qa@git+https://github.com/sumithr/sumo-qa.git"]
}
```

Then install the MCP server binary that the skills call into:

```bash
uv tool install --from git+https://github.com/sumithr/sumo-qa.git sumo-qa-mcp
```

Restart OpenCode. The plugin registers all sumo-qa skills.

Verify by asking: *"load the QA classifications"* — you should get 10 names back (api_contract_change, business_logic_change, security_change, performance_change, frontend_change, infrastructure_change, test_change, docs_change, config_change, data_migration).

OpenCode uses its own plugin install. If you also use Claude Code, Cursor, Codex, JetBrains, or VS Code, install sumo-qa separately for each one.

## Usage

Use OpenCode's native `skill` tool:

```
use skill tool to list skills
use skill tool to load sumo-qa/using-sumo-qa
use skill tool to load sumo-qa/qa-deciding-approach
```

Or just describe a QA task in natural language ("plan QA for this story", "review my changes") — OpenCode's skill router picks the right one from the descriptions.

## Updating

```json
{
  "plugin": ["sumo-qa@git+https://github.com/sumithr/sumo-qa.git#v0.1.0"]
}
```

To get the latest commit on `main`, omit the `#tag`. Some OpenCode / Bun versions cache the resolved git dependency — if updates don't appear, clear OpenCode's package cache or reinstall the plugin.

## Tool name mapping

If you're authoring a skill that references Claude Code tool names, OpenCode uses different names for the same tools:

| Claude Code | OpenCode |
|---|---|
| `TodoWrite` | `todowrite` |
| `Read` | `read` |
| `Edit` | `edit` |
| `Write` | `write` |
| `Bash` | `bash` |
| `Skill` | `skill` |
| `Glob` | `glob` |
| `Grep` | `grep` |

The sumo-qa skills are written in tool-name-agnostic prose, so this mapping mostly matters if you fork and extend.

## Troubleshooting

### Plugin not loading
1. Check logs: `opencode run --print-logs "hello" 2>&1 | grep -i sumo-qa`
2. Verify the plugin line in your `opencode.json`
3. Make sure you're running a recent version of OpenCode

### MCP tools not available
Confirm `sumo-qa` is on `PATH`:
```bash
which sumo-qa
```
If not, re-run the `uv tool install` step above.
