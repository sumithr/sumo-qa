# Install

## One line, any host

```bash
python -m pip install sumo-qa && python -m sumo_qa.installer --claude-code
```

Swap `--claude-code` for `--vscode --workspace <path-to-repo>` (VS Code + Copilot), `--jetbrains` (JetBrains AI Assistant), or drop the flag entirely to configure every host detected on this machine. This module-entry command works on Windows, macOS, and Linux, including shells where pip's script directory is not on PATH yet.

On Windows PowerShell, use:

```powershell
py -m pip install sumo-qa; if ($?) { py -m sumo_qa.installer --claude-code }
```

`pip install sumo-qa` creates two script wrappers: `sumo-qa` (the MCP server) and `sumo-qa-install` (the configurator that wires it into your host). The `python -m sumo_qa.installer` form runs the same configurator without depending on the script directory being on PATH. It symlinks skills into `~/.claude/skills/`, writes `claude_desktop_config.json` / `.vscode/mcp.json`, or prints JetBrains UI steps depending on the flag.

Restart your host (or open a fresh chat) once it's done.

## Diagnosing setup with `sumo-qa-doctor`

After install, run:

```bash
sumo-qa-doctor
```

It's the first troubleshooting step for any host-setup or compatibility issue. The command is **read-only** — it never writes to your config files, never re-runs the installer, and never spawns long-lived processes. Each check prints `[OK]`, `[WARN]`, or `[FAIL]` plus a one-line summary, and every failure includes the exact `Fix:` command to run. Exit code is `1` when any check fails, `0` otherwise.

The default run covers ten checks:

1. `python_version` — interpreter + `sumo-qa` package version
2. `install_mode` — wheel vs editable layout (catches "I edited skills/X but the change isn't visible")
3. `binary_discoverable` — `sumo-qa` on PATH or `python -m sumo_qa` fallback
4. `mcp_handshake` — JSON-RPC `initialize` handshake against the running server
5. `tools_list_complete` — all 14 `REQUIRED_TOOL_NAMES` advertised
6. `claude_code_config` — Claude Code's `claude_desktop_config.json` parseable, points at a resolvable binary
7. `claude_desktop_config` — Claude Desktop's separate config path (macOS / Windows / Linux variations)
8. `vscode_workspace_config` — `<workspace>/.vscode/mcp.json` parseable, resolvable
9. `vscode_user_misleading` — WARN when `~/.vscode/mcp.json` exists (VS Code never reads it; common gotcha)
10. `jetbrains_detection` — detects installed JetBrains IDEs and prints the manual UI-add steps

### Flags

```bash
sumo-qa-doctor --host claude-code            # only Claude Code checks
sumo-qa-doctor --host claude-desktop         # only Claude Desktop checks
sumo-qa-doctor --host vscode                 # only VS Code checks
sumo-qa-doctor --host jetbrains              # only JetBrains detection
sumo-qa-doctor --workspace /path/to/repo     # VS Code workspace root override
sumo-qa-doctor --json                        # machine-parseable output
```

### `--json` shape (internal until sumo-qa 1.0)

The JSON document looks like:

```json
{
  "schema_version": "0",
  "summary": {"ok": 9, "warn": 0, "fail": 1},
  "checks": [
    {
      "check_id": "vscode_workspace_config",
      "status": "FAIL",
      "summary": "/path/.vscode/mcp.json points at a binary that does not resolve",
      "fix": "Run `sumo-qa-install --vscode --workspace /path` to refresh the binary path.",
      "details": {"config_path": "/path/.vscode/mcp.json", "stale_command": "/usr/local/bin/sumo-qa"}
    }
  ]
}
```

`schema_version` is `"0"` to signal this contract is **subject to change before sumo-qa 1.0**. Do not build long-lived integrations against it before then. The intent of `--json` today is to make doctor output paste-able into automation and bug reports, not to power scripted decisions.

## Other MCP-capable hosts

For hosts beyond Claude Code, VS Code + Copilot, and JetBrains (which `sumo-qa-install` handles directly), the `sumo-qa` binary you get from `pip install sumo-qa` exposes a standard stdio MCP server. To wire it into any other MCP-capable host, follow that host's own MCP-server setup documentation and point it at the absolute path of `sumo-qa` on your machine (run `which sumo-qa` or `where sumo-qa` on Windows to find it).

We haven't verified those host-specific paths end-to-end ourselves, so we don't ship per-host instructions — but the underlying server is a vanilla MCP stdio server and should work wherever MCP works.

## Plugin-format install (Claude Code / Codex)

For hosts that consume the `.claude-plugin/` / `.codex-plugin/` manifest formats, `sumo-qa` ships first-class plugin folders that wire everything (skills, hooks, MCP server) in one command — no `pip install` required:

```bash
# Claude Code
claude plugin install sumithr/sumo-qa

# OpenAI Codex
/plugins install sumithr/sumo-qa
```

Both folders are generated from a single canonical source (`pyproject.toml`'s `[tool.sumo-qa.plugin]` overlay) and validated in CI against the published Claude Code JSON Schema plus an MCP `initialize` handshake for Codex. See [host-adapters.md](host-adapters.md) for the architecture.

The `pip install` path remains the primary distribution channel for Claude Desktop, VS Code, and JetBrains — those hosts don't consume plugin manifests.

## Per-host flags

When you only want to configure one host (or you're scripting per-host install):

```bash
python -m sumo_qa.installer --claude-code             # Claude Code only
python -m sumo_qa.installer --claude-desktop          # Claude Desktop app only
python -m sumo_qa.installer --vscode                  # VS Code: writes <cwd>/.vscode/mcp.json
python -m sumo_qa.installer --vscode --workspace /path/to/repo
python -m sumo_qa.installer --jetbrains               # prints Settings UI steps
python -m sumo_qa.installer --vscode --skip-mcp-install   # skip MCP binary lookup (faster re-runs)
```

`python -m sumo_qa.installer --help` for the full list.

## Updating

```bash
python -m pip install --upgrade sumo-qa     # refresh server + bundled skills/knowledge
python -m sumo_qa.installer                 # refresh symlinks + host configs (Claude Code, VS Code, ...)
# Restart Claude Code / open a fresh chat — the SessionStart hook re-injects new content.
```

What each step refreshes:

| What changed in the new version | What picks it up |
|---|---|
| `sumo-qa` binary, MCP tools, bundled standards/knowledge/skills in site-packages | `pip install --upgrade` |
| Symlinks in `~/.claude/skills/`, `claude_desktop_config.json`, `.vscode/mcp.json` | re-running `python -m sumo_qa.installer` |
| Skill content the agent reads each turn | next chat session (the SessionStart hook re-fires) |

You only strictly need to re-run `python -m sumo_qa.installer` when **new** skills are added or a host's MCP config schema changes; routine content updates flow through the existing symlinks automatically.

## Per-host detail

### Claude Code

`python -m sumo_qa.installer --claude-code` does three things:

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

Note: `python -m sumo_qa.installer --claude-code` also writes a `claude_desktop_config.json`, but to `~/.config/claude/` (lowercase) — a path Claude Desktop does **not** read. That write is kept for backward compatibility. The `--claude-desktop` flag is the authoritative path for Claude Desktop users.

### JetBrains AI Assistant + Junie

JetBrains' MCP plugin in IDEA 2026.1 has an undocumented internal flow we can't reliably hit by writing the XML config externally — entries written that way show up disabled with `LazyStandaloneCoroutine cancelled` in the UI. The supported path is the Settings UI.

`python -m sumo_qa.installer --jetbrains` prints:

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

`python -m sumo_qa.installer --vscode --workspace /path/to/repo` writes `<repo>/.vscode/mcp.json` using VS Code's native schema:

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
| Claude Code shows only some skills | Earlier wrapper-symlink install left stale top-level dirs | `python -m sumo_qa.installer --claude-code` cleans up and re-symlinks at the right granularity |
| `sumo-qa-install` says "VS Code skipped: not a workspace" | Ran from `$HOME` or a directory without `.git`/`.vscode`/project marker | Re-run with `--workspace /path/to/repo`, or cd into a workspace first |
| `sumo-qa-install` is not recognized on Windows | pip installed the script wrapper into a Scripts directory that PowerShell has not added to PATH | Use the module entrypoint: `py -m pip install sumo-qa; if ($?) { py -m sumo_qa.installer --claude-code }` |
| `python3 install.py` opens Windows Store / "command not found" | Either no `python3` on this Windows machine (Windows ships only a Store stub) or no install.py on disk (pip-only install never had it) | Use the module entrypoint: `py -m pip install sumo-qa; if ($?) { py -m sumo_qa.installer --claude-code }` |
| Copilot says "I don't have access to those tools" with mini model | Mini/fast model can't reliably call MCP tools | Switch to Claude Sonnet 4.5 or GPT-5 full in Copilot's model picker |

## Install from a local clone

Use this flow when you want to **edit skills, knowledge catalogues, or standards packs in place** — your team's own QA standards, custom techniques, extra change rules — and have the host pick the edits up immediately, with no env vars and no reinstall step. Common cases:

- A team fork that bakes in your org's standards pack and change rules
- Trying a custom skill on a branch without publishing it
- Extending the canonical knowledge catalogues (techniques, principles) with team-specific entries
- Working on sumo-qa itself

### What "editable" gets you

An editable install (`pip install -e .`) leaves the package files at the repo root and adds a `.pth` pointer to the venv's `site-packages`. Two side-effects make live editing work end-to-end:

| What you edit in the clone | How it reaches the host | Reinstall needed? |
|---|---|---|
| `skills/<name>/SKILL.md` (existing skill) | `sumo-qa-install` symlinks `~/.claude/skills/<name>` → `<repo>/skills/<name>`. Claude Code re-reads the file on every invocation. | No |
| `knowledge/*.md` (classifications, approaches, principles, techniques) | The bundled `_data/knowledge/` is **only created when a wheel is built**, not in editable installs. The loader's `_knowledge_dir()` falls through to `<repo>/knowledge/`. | No |
| `standards/packs/*.yml` / `*.yaml` | Same fall-through: `_standards_dir()` returns `<repo>/standards/packs/`. The MCP server reads from disk on each `sumo_qa_load_standards` call. | No |
| `standards/rules/change_rules.yaml` | Same — `_rules_path()` resolves to the repo file. | No |
| `knowledge/test_data/<domain>/<record>.yml` | The test-data catalogue scans the repo directory (or `QA_TEST_DATA_PATH` if set). | No |
| **New** `skills/<new-name>/SKILL.md` | Symlink doesn't exist yet under `~/.claude/skills/`. Re-run `sumo-qa-install`. | `sumo-qa-install` only |
| `src/sumo_qa/*.py` | Editable install → already live. Restart the host so it spawns a fresh MCP server process. | Restart host |
| `pyproject.toml` (dependency / script entry change) | `pip install -e .` to refresh the venv's metadata. | `pip install -e .` |

### Prerequisites

- **Python 3.10+** (`python3 --version`)
- **git**
- The `claude` CLI on PATH if you want Claude Code's MCP registry written automatically. Optional — skill symlinks work without it.

### Steps

```bash
git clone https://github.com/sumithr/sumo-qa.git
cd sumo-qa

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e .                    # editable, no dev extras
python -m sumo_qa.installer --claude-code     # or omit the flag for every detected host
```

Two things to know about that installer step:

1. It runs with the activated venv's `sumo-qa` first on PATH, so the absolute path it writes into Claude Code's MCP registry / `claude_desktop_config.json` / `.vscode/mcp.json` is `<repo>/.venv/bin/sumo-qa`. That binary, when invoked, runs the editable install → reads `<repo>/skills/`, `<repo>/knowledge/`, `<repo>/standards/` live.
2. Skills get symlinked **per skill** into `~/.claude/skills/<name>` pointing at `<repo>/skills/<name>`. Editing a SKILL.md needs no further action; the host re-reads it on next invocation.

Restart the host (or open a fresh chat) once the installer is done.

### Verify the clone is wired live, not a stale PyPI install

In a fresh host session, ask:

> load the QA classifications

The text returned should match `<repo>/knowledge/classifications.md` byte-for-byte. To confirm the clone is what the host is actually reading, add one classification to that file — say, a placeholder line under the existing list — save, restart the host, and ask again. The new line should appear in the output.

Quick sanity check from the shell:

```bash
readlink ~/.claude/skills/sumo-qa-deciding-approach
# Expect: <repo>/skills/sumo-qa-deciding-approach
#   NOT: ~/.local/share/uv/tools/sumo-qa/lib/.../_data/skills/...

.venv/bin/python -c "from sumo_qa.knowledge_loaders import _knowledge_dir, _standards_dir; print(_knowledge_dir()); print(_standards_dir())"
# Expect both to point inside <repo>, not a site-packages _data directory.
```

If `readlink` points at `~/.local/share/uv/tools/...` you've got a PyPI / `uv tool install` copy winning the PATH race. Re-activate the venv and re-run `python -m sumo_qa.installer` from inside it.

### Adding your team's standards pack

Full schema reference and a recipe for swapping ISTQB out for a different body of QA practice: [CONTENT-FORMATS.md](CONTENT-FORMATS.md). Run `sumo-qa-validate` (or wait for the pre-commit hook) to confirm a new pack parses and your `change_rules.yaml` entry stays inside the closed `suggested_test_types` enum.

1. Drop a new YAML file into `standards/packs/` (sibling of the existing `istqb_v1.yml`, `qa_shift_left_v1.yml`):

   ```yaml
   # standards/packs/my_team_v1.yml
   pack: my_team_v1
   description: Internal QA standards for <team>
   # Optional metadata filter: makes this pack returned only for matching classifications.
   # Omit to make the pack always-loaded.
   applies_to_classifications: [api_contract_change, business_logic_change]
   standards:
     - id: my-team-1
       statement: Every public endpoint must have a contract test pinned to the OpenAPI schema.
     - id: my-team-2
       statement: PII never appears in logs at INFO level or below.
   ```

2. In the host: *"load the QA standards"*. The output should include `# my_team_v1.yml` followed by your YAML.

The loader takes **every** `*.yml` / `*.yaml` file in `standards/packs/` — there's no registry to update. Same for `change_rules.yaml` (a single file under `standards/rules/`); edit in place to add team-specific change-class rules.

### Adding to the knowledge catalogues

`knowledge/techniques.md`, `knowledge/principles.md`, `knowledge/approaches.md`, `knowledge/classifications.md` are plain markdown the host LLM reads verbatim — the skills tell it to "pick from this catalogue". To extend:

- **New test design technique** → append an entry to `knowledge/techniques.md` matching the existing entries' shape (name, when-to-use, worked example). The TDD and strengthening skills will then consider it.
- **New change classification** → append to `knowledge/classifications.md`. The `sumo-qa-deciding-approach` skill picks from whatever this file says, no code change needed.

Don't add `_data/` directories — they are only created by Hatch when building a wheel, and adding them by hand will shadow the live repo files.

### Adding a new skill

```
skills/
  my-team-perf-review/
    SKILL.md          # follow the structure tested by tests/test_skill_conformance.py
```

Then:

```bash
python -m sumo_qa.installer --claude-code   # only needed to create the new ~/.claude/skills/my-team-perf-review symlink
```

The MCP server picks up `skills/*/SKILL.md` automatically on its next startup (host restart).

### Updating from upstream

```bash
git pull
# Re-run install only if pyproject.toml or new skills/ entries arrived:
python -m pip install -e .          # only if dependencies or src/ changed
python -m sumo_qa.installer         # only if new skills/<name>/ directories arrived
```

Routine knowledge / standards / SKILL.md edits from upstream require neither.

### Switching between a clone and the PyPI install

The installer picks the invocation in this order:

1. **`sumo-qa` script on PATH** — whichever venv currently has it wins, so activating a different venv changes which sumo-qa each host invokes.
2. **No script on PATH** — falls back to `<sys.executable> -m sumo_qa`, i.e. the interpreter you ran the installer with. So even when pip's script directory isn't exported (Microsoft-Store Python on Windows, `--user` installs on Linux without `~/.local/bin` on PATH), every host still gets a working command pointing at the right Python.

To switch:

```bash
# Clone wins (live edits):
source <repo>/.venv/bin/activate
python -m sumo_qa.installer

# Back to a different venv's install:
deactivate
source ~/other-venv/bin/activate     # or whichever env you want
python -m sumo_qa.installer
```

Restart the host after either switch.

### Caveats

- Don't commit your team's private standards / rules to a public fork of sumo-qa upstream. Either fork into a private repo or keep team packs on a long-lived local branch.
- The bundled `_data/` directory only appears in built wheels. If you ever see `<repo>/src/sumo_qa/_data/` after running editable commands, something built a wheel inside the source tree — delete it; otherwise the loaders will read from it instead of `<repo>/knowledge/` and `<repo>/standards/`.
- `QA_KNOWLEDGE_PATH`, `QA_STANDARDS_PATH`, `QA_RULES_PATH`, `QA_TEST_DATA_PATH` env vars always win over the resolution chain. Useful if you want to point a single host at a *different* team-standards directory while leaving the clone's defaults alone. See [CONFIGURATION.md](CONFIGURATION.md).

## Manual install (no `sumo-qa-install`)

If you're not running `sumo-qa-install` for any reason, two options for the MCP server command:

```bash
# Option A — pip wrapper on PATH
python -m pip install sumo-qa
which sumo-qa     # or `where sumo-qa` on Windows
```

```bash
# Option B — module form (no PATH dependency, works in any venv where
# `import sumo_qa` succeeds)
python -m pip install sumo-qa
python -c "import sys; print(sys.executable, '-m sumo_qa')"
```

For Option A, paste the absolute path into each host's MCP config as the `command` field. For Option B, set `command` to the Python interpreter and `args` to `["-m", "sumo_qa"]`. Use Option B on Microsoft-Store Python (Windows) or `pip install --user` (Linux) when the pip Scripts directory isn't exported. Schema details per host: "Per-host detail" above.
