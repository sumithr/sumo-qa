# Install

## One line, any host

```bash
pip install sumo-qa && sumo-qa-install
```

`sumo-qa-install` with no flag configures every host detected on this machine. Target a single host with `--claude-code`, `--vscode --workspace <path-to-repo>` (VS Code + Copilot), or `--jetbrains` (JetBrains AI Assistant).

On Windows PowerShell, use (`&&` isn't a valid separator in Windows PowerShell, and pip's script directory is often off PATH, so use the module form):

```powershell
py -m pip install sumo-qa; if ($?) { py -m sumo_qa.installer }
```

`pip install sumo-qa` creates two script wrappers: `sumo-qa` (the MCP server when run with no arguments; also the home of the product commands `sumo-qa analyze` / `sumo-qa status`) and `sumo-qa-install` (the configurator that wires it into your host). It symlinks skills into `~/.claude/skills/`, writes `claude_desktop_config.json` / `.vscode/mcp.json`, or prints JetBrains UI steps depending on the flag. If `sumo-qa-install` isn't on your PATH (e.g. `pip install --user`, or Microsoft-Store Python on Windows), the PATH-proof equivalent is `python -m pip install sumo-qa && python -m sumo_qa.installer` — the same configurator run through the interpreter directly.

Restart your host (or open a fresh chat) once it's done.

## One-command wrapper (`install.sh` / `install.ps1`)

Prefer a single command that installs, configures, and verifies in one shot? The repo ships thin wrappers that route to the same canonical steps above — `python -m pip install sumo-qa`, then `python -m sumo_qa.installer`, then `sumo-qa-doctor`. The wrappers add no install logic of their own; they exist so a first-time user runs one command instead of learning the pip / installer / doctor split. They never bypass the installer's validation.

```bash
# macOS / Linux — clone or download the repo, then from its root:
./install.sh                       # install every detected host, then run the doctor
./install.sh --host claude-code    # one verified host (claude-code | vscode | jetbrains)
./install.sh --update              # pip --upgrade + re-run installer + doctor
./install.sh --doctor              # read-only doctor only (no install)
./install.sh --uninstall           # ownership-aware uninstall (see below); add --host to scope it
./install.sh --print-plan          # show the exact commands it would run, run nothing
```

```powershell
# Windows PowerShell — from the repo root:
.\install.ps1                      # install every detected host, then run the doctor
.\install.ps1 -Host vscode         # one verified host
.\install.ps1 -Update              # upgrade + re-run installer + doctor
.\install.ps1 -Doctor              # read-only doctor only
.\install.ps1 -Uninstall           # ownership-aware uninstall (see below); add -Host to scope it
.\install.ps1 -PrintPlan           # show the exact commands it would run, run nothing
```

Safety: the wrappers never use `sudo`/admin escalation, never delete your `.sumo-qa/` repo artifacts, and never remove a host config entry they can't prove they own. On any failure they print the exact command that failed plus the next safe manual command, and re-running is always safe.

Verified in CI: the `install-smoke` workflow runs `install.sh --print-plan` on Linux/macOS/Windows and `install.ps1 -PrintPlan` on Windows, asserting the wrapper routes to the canonical pip + installer + doctor commands (and rejects unverified hosts) on every push and PR. `--uninstall` routes to the installer's ownership-aware removal — see [Uninstall](#uninstall) below.

The per-host installer flags (`python -m sumo_qa.installer --vscode`, etc.) remain fully supported for users who don't want the wrapper — see [Per-host flags](#per-host-flags).

## Diagnosing setup with `sumo-qa-doctor`

After install, run:

```bash
sumo-qa-doctor
```

It's the first troubleshooting step for any host-setup or compatibility issue. The command is **read-only** — it never writes to your config files, never re-runs the installer, and never spawns long-lived processes. Each check prints `[OK]`, `[WARN]`, or `[FAIL]` plus a one-line summary, and every failure includes the exact `Fix:` command to run. Exit code is `1` when any check fails, `0` otherwise.

### How doctor is delivered (and what to do when it isn't on PATH)

`pip install sumo-qa` registers three console scripts — `sumo-qa`, `sumo-qa-install`, and `sumo-qa-doctor` — all in the same wheel. If `pip install` succeeded for the server, the doctor is already installed alongside it. No separate step.

If the `sumo-qa-doctor` script is **not on PATH** (Microsoft-Store Python on Windows, `pip install --user` on Linux without `~/.local/bin` exported, some corporate-managed Python installs), the module-form is the PATH-proof fallback:

```bash
python -m sumo_qa.doctor
```

This runs the same code through the interpreter directly — no wrapper script required. It mirrors the same fallback `sumo-qa-install` uses when the Scripts dir isn't on PATH. If `python -m sumo_qa.doctor` also can't find the package, the failure is at the pip / Python level (not a sumo-qa issue) — `python -m pip show sumo-qa` will tell you whether the package is installed at all.

The default run covers thirteen checks:

1. `python_version` — interpreter + `sumo-qa` package version
2. `install_mode` — wheel vs editable layout (catches "I edited skills/X but the change isn't visible")
3. `binary_discoverable` — `sumo-qa` on PATH or `python -m sumo_qa` fallback
4. `uvx_available` — `uvx` (Astral's package runner) on PATH; required for the plugin install path; FAIL with canonical install command when missing
5. `mcp_handshake` — JSON-RPC `initialize` handshake against the running server
6. `tools_list_complete` — all 16 `REQUIRED_TOOL_NAMES` advertised
7. `claude_code_config` — Claude Code's `claude_desktop_config.json` parseable, points at a resolvable binary
8. `claude_code_plugin` — detects whether sumo-qa is installed via `claude plugin install` (reads `~/.claude/plugins/installed_plugins.json`); cross-checked with `claude_code_config` so a plugin-install user doesn't get a false FAIL on the pip-install config check. The plugin install is self-contained — its `.mcp.json` invokes `uvx --from ${CLAUDE_PLUGIN_ROOT} sumo-qa` ([Anthropic's canonical pattern](https://code.claude.com/docs/en/mcp#plugin-provided-mcp-servers)) so doctor's `mcp_handshake` + `tools_list_complete` checks pass via the same uvx-bootstrapped wheel
9. `claude_desktop_config` — Claude Desktop's separate config path (macOS / Windows / Linux variations); WARN on macOS when the configured command lives in a source-checkout venv (`.venv`/`venv`/`env`/`.tox`/`.nox`) the Claude.app sandbox cannot launch from. With `--host claude-desktop`, the handshake probes the exact command stored in `claude_desktop_config.json`, not just `shutil.which("sumo-qa")` — so a divergence between the configured path and the current PATH is surfaced rather than masked.
10. `codex_plugin` — detects whether sumo-qa is installed via Codex's `/plugins install` (reads `~/.codex/config.toml` for the `[plugins."sumo-qa@<marketplace>"]` section and validates the plugin cache at `~/.codex/plugins/cache/<marketplace>/sumo-qa/`)
11. `vscode_workspace_config` — `<workspace>/.vscode/mcp.json` parseable, resolvable
12. `vscode_user_misleading` — WARN when `~/.vscode/mcp.json` exists (VS Code never reads it; common gotcha)
13. `jetbrains_detection` — detects installed JetBrains IDEs and prints the manual UI-add steps

### Dual install paths

sumo-qa supports two install flows; doctor covers both:

- **pip install** (canonical) — `pip install sumo-qa && sumo-qa-install` writes per-host JSON configs (`claude_desktop_config.json`, `.vscode/mcp.json`) and symlinks skills into `~/.claude/skills/`. The host-config checks (`claude_code_config`, `claude_desktop_config`, `vscode_workspace_config`) validate this path.
- **plugin install** — `claude plugin install` registers via Claude Code's plugin manager (recorded in `~/.claude/plugins/installed_plugins.json`); `/plugins install` does the equivalent in Codex (recorded in `~/.codex/config.toml`). The `claude_code_plugin` and `codex_plugin` checks validate these paths.

A user can install via either flow (or both — they're additive, not mutually exclusive). Doctor checks each path independently and only FAILs when an active install is genuinely broken.

### Defence-in-depth against host schema changes

Host vendors (Anthropic, OpenAI) own the storage layouts doctor inspects. If a future release renames a file, changes a section key, or adds new shape variations, the storage-probe checks (`claude_code_plugin`, `codex_plugin`, the host-config checks) **fall through to OK with a "couldn't determine install state" disclosure** rather than FAILing — schema drift never produces false failures. The canonical "is it actually working" answer comes from `mcp_handshake` and `tools_list_complete`, which exercise the live JSON-RPC surface directly. As long as those pass, sumo-qa is functionally healthy regardless of what the storage probes can or can't recognise.

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

**Cursor, OpenCode, and Gemini CLI are explicitly not yet verified** — we haven't run those host-specific paths end-to-end ourselves, so we don't ship per-host instructions for them (or for any other unlisted MCP host). The underlying server is a vanilla MCP stdio server and should work wherever MCP works.

## Plugin-format install (Claude Code / Codex)

For hosts that consume the `.claude-plugin/` / `.codex-plugin/` manifest formats, `sumo-qa` ships first-class plugin folders that wire everything (skills, hooks, MCP server, doctor) in one command — no `pip install sumo-qa` step required.

### Prerequisite: `uv`

The plugin install path requires `uv` (Astral's package runner) on PATH. The plugin's `.mcp.json` invokes `uvx` with `--from ${CLAUDE_PLUGIN_ROOT}` — [Anthropic's canonical substitution for plugin-bundled MCP servers](https://code.claude.com/docs/en/mcp#plugin-provided-mcp-servers). At runtime Claude Code expands `${CLAUDE_PLUGIN_ROOT}` to the plugin's source directory (the local checkout for `claude --plugin-dir <repo>`, the marketplace cache for `claude plugin install`), and uvx builds + caches the Python package from there. Without it, the MCP server cannot launch and `sumo_qa_*` tools fail silently.

Install `uv` once via [Astral's official installer](https://docs.astral.sh/uv/getting-started/installation/) (one line, no Python prerequisite — `uv` ships its own Python toolchain):

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Homebrew
brew install uv
```

After install, `uv --version` should print ≥0.4 and `uvx --version` should resolve. uv caches downloaded wheels under `~/.cache/uv/`, so first MCP-server spawn after `claude plugin install` takes ~5-20s; subsequent spawns are instant.

> **Important:** the installer appends a PATH update to your shell rc (`~/.zshrc` or `~/.bashrc`). That only takes effect in **new** shells — the terminal you ran the installer in does not have the updated PATH until you `source ~/.zshrc` (or open a fresh tab). Claude Code locks its environment at process launch, so if you install uv with Claude Code already running, you must `/quit`, open a fresh terminal where `which uvx` resolves, and relaunch — `/reload-plugins` is not enough.

### Install commands

**Session-scoped local-dev (Claude Code):**

```bash
git clone https://github.com/sumithr/sumo-qa.git
claude --plugin-dir /path/to/sumo-qa
```

Every `claude` invocation needs the `--plugin-dir` flag — plain `claude` (no flag) starts a session with no sumo-qa loaded. `/reload-plugins` picks up edits inside the session. See [Anthropic's documented local-dev mode](https://code.claude.com/docs/en/plugins#test-your-plugins-locally) for the underlying mechanism.

**Persistent marketplace install (Claude Code):**

```text
/plugin marketplace add sumithr/sumo-qa
/plugin install sumo-qa@sumo-qa
```

Claude Code clones this repo, reads `.claude-plugin/marketplace.json`, and installs the single plugin it lists (the repo root itself). The plugin's `.mcp.json` resolves the MCP server via `uvx --from ${CLAUDE_PLUGIN_ROOT} sumo-qa` against the marketplace cache, so `uv` must be on PATH (see [Prerequisite: `uv`](#prerequisite-uv)).

> **Verification status (honest):** `.claude-plugin/marketplace.json` is generated from the canonical source, passes the published [marketplace JSON Schema](https://json.schemastore.org/claude-code-marketplace.json) in CI, and is covered by the drift gate. The **live** `marketplace add` → `install` round-trip — managed clone, `${CLAUDE_PLUGIN_ROOT}` resolution, MCP handshake, and a skill route inside a real Claude Code session — has **not yet been verified end-to-end** at the time of writing. Until that confirmation is recorded, prefer the `pip install sumo-qa && sumo-qa-install` flow above for a guaranteed-working persistent install. The `--plugin-dir` and pip/uvx paths are unaffected and remain green in CI.

**Roadmap / not yet verified:**

- **Official Anthropic plugin directory submission — deferred.** The canonical metadata, assets, and a schema-valid `marketplace.json` are in place, so sumo-qa is self-hostable as a marketplace (`/plugin marketplace add sumithr/sumo-qa`) without any external listing. Submission to Anthropic's curated/official directory is intentionally deferred: it requires an external review step outside this repo's control and adds no capability over the self-hosted marketplace for users who have the repo slug. Revisit once the live end-to-end install above is verified and a stable tagged release is published. (Recorded per issue #382; #84 already scoped external submission out.)
- OpenAI Codex plugin install (`/plugins install ...`) is not yet verified — the `.codex-plugin/` manifest exists but the install + MCP-server-launch flow hasn't been confirmed end-to-end. Treat as TBD.

### Doctor for plugin-install users

When the sumo-qa plugin is enabled in a Claude Code session, the plugin's `bin/sumo-qa-doctor` wrapper is on the Bash tool's PATH (per Anthropic's [documented `bin/` mechanism](https://code.claude.com/docs/en/plugins-reference#plugin-directory-structure)). Inside Claude Code, just type:

```
!sumo-qa-doctor
!sumo-qa-doctor --json
!sumo-qa-doctor --host claude-code
```

The wrapper resolves its own plugin folder and delegates to `uvx --from <plugin-root> sumo-qa-doctor` — no `pip install sumo-qa` needed, no `--from <long-path>` boilerplate.

For direct invocation outside Claude Code (e.g. from a regular shell), use `uvx` against the plugin's source directory:

```bash
# claude --plugin-dir <path> local-dev session
uvx --from /path/to/sumo-qa sumo-qa-doctor

# marketplace install (cache lives under ~/.claude/plugins/cache/...)
uvx --from "$HOME/.claude/plugins/cache/<marketplace>/sumo-qa/<version>" sumo-qa-doctor
```

uvx builds the wheel from that directory (cached after the first call) and runs the `sumo-qa-doctor` entry point. Doctor's `claude_code_plugin` check reports whether the plugin install is correctly registered, and `mcp_handshake` confirms the uvx-spawned MCP server actually responds — together they prove the plugin install is fully functional, not just registered.

### Architecture

Both plugin folders (`.claude-plugin/`, `.codex-plugin/`) are generated from a single canonical source (`pyproject.toml`'s `[tool.sumo-qa.plugin]` overlay) and validated in CI against the published Claude Code JSON Schema plus an MCP `initialize` handshake for Codex. See [host-adapters.md](host-adapters.md) for the architecture.

The `pip install` path remains the primary distribution channel for Claude Desktop, VS Code, and JetBrains — those hosts don't consume plugin manifests. The two install paths are additive — a user can have both wired and doctor reports each independently.

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
pip install --upgrade sumo-qa     # refresh server + bundled skills/knowledge
sumo-qa-install                   # refresh symlinks + host configs (Claude Code, VS Code, ...)
# Restart Claude Code / open a fresh chat — the SessionStart hook re-injects new content.
```

What each step refreshes:

| What changed in the new version | What picks it up |
|---|---|
| `sumo-qa` binary, MCP tools, bundled standards/knowledge/skills in site-packages | `pip install --upgrade` |
| Symlinks in `~/.claude/skills/`, `claude_desktop_config.json`, `.vscode/mcp.json` | re-running `sumo-qa-install` |
| Skill content the agent reads each turn | next chat session (the SessionStart hook re-fires) |

You only strictly need to re-run `sumo-qa-install` when **new** skills are added or a host's MCP config schema changes; routine content updates flow through the existing symlinks automatically.

## Uninstall

`install.sh --uninstall` (and `install.ps1 -Uninstall`) run an **ownership-aware uninstall**: they delegate to `python -m sumo_qa.installer --uninstall`, which removes only what the installer wrote and proves ownership before touching anything —

- the `sumo-qa` key under `mcpServers` / `servers` in each host config (every *other* server entry is left untouched);
- the sumo-qa skill symlinks under `~/.claude/skills/` — only a symlink, or a directory whose `SKILL.md` still matches the shipped skill, so a skill you customised is never deleted;
- the Claude Code MCP registration, via `claude mcp remove sumo-qa -s user`.

JetBrains is the exception: nothing was written programmatically (its MCP plugin requires a Settings-UI add), so the uninstall prints the one manual removal step. No `sudo`, no deletion of your `.sumo-qa/` repo artifacts. Scope it to one host with `--host` / `-Host` (e.g. `./install.sh --uninstall --host vscode`).

This removes the host *configuration*; the pip package stays installed. Run `pip uninstall sumo-qa` as well if you also want to remove the package and its console scripts. Prefer to do every step by hand? The equivalent manual commands:

**Package (all hosts):**

```bash
pip uninstall sumo-qa
```

Removes the package and its console scripts (`sumo-qa`, `sumo-qa-install`, `sumo-qa-doctor`, `sumo-qa-validate`, `sumo-qa-ingest`).

**Claude Code:**

```bash
# De-register the MCP server
claude mcp remove sumo-qa -s user

# Remove the sumo-qa skills from ~/.claude/skills — symlinks on macOS/Linux,
# or real directories on Windows where the installer fell back to copying.
# Every sumo-qa skill name contains "sumo-qa", so this matches all of them
# and nothing else.
rm -rf ~/.claude/skills/*sumo-qa*
```

On Windows PowerShell (covers both the symlink and the copied-directory fallback):

```powershell
claude mcp remove sumo-qa -s user
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "$HOME\.claude\skills\*sumo-qa*"
```

Then delete the `"sumo-qa"` key under `mcpServers` in `~/.config/claude/claude_desktop_config.json` (leave any other servers in place).

**Claude Desktop:**

Delete the `"sumo-qa"` key under `mcpServers` in the app's config (keep other servers):

| OS | Config file |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

**VS Code + Copilot:**

In each workspace you configured, delete the `"sumo-qa"` key under `servers` in `<workspace>/.vscode/mcp.json`.

**JetBrains AI Assistant + Junie:**

`sumo-qa-install` only printed setup steps for JetBrains (it never wrote config), so remove it through the UI: **Settings → Tools → AI Assistant → Model Context Protocol**, select `sumo-qa`, remove. For Junie, delete `~/.junie/mcp/sumo-qa.json` if you created it.

Restart any host you changed.

## Per-host detail

### Claude Code

`python -m sumo_qa.installer --claude-code` does three things:

1. Symlinks each `skills/<name>/` directory (either from the bundled `sumo_qa/_data/skills/` after `pip install`, or from the repo `skills/` in dev mode) into `~/.claude/skills/<name>/` so Claude Code's native skill loader picks them up as top-level skills. Earlier versions used a wrapper symlink (`~/.claude/skills/sumo-qa/`) — that was wrong because Claude Code doesn't recurse. Each skill is now its own top-level entry.
2. Registers the MCP server with Claude Code via `claude mcp add sumo-qa <abs-binary-path> -s user`. This is what makes the MCP tools (`sumo_qa_load_classifications`, `sumo_qa_find_test_data`, etc.) actually surface inside Claude Code sessions — without this step, only the skill files are visible in the slash menu, not the underscored MCP tools. Idempotent (any existing `sumo-qa` entry is removed first). Skipped silently if the `claude` CLI isn't on PATH.
3. Writes the MCP server entry into `claude_desktop_config.json` (at `~/.config/claude/` on macOS/Linux, `%APPDATA%\Claude\` on Windows). This file is for Claude Desktop, not Claude Code (which uses the `claude mcp` registry from step 2). Kept so a parallel Claude Desktop install picks up sumo-qa for free.

After install: restart Claude Code. Type `/` and start typing `sumo-qa-`:

- **Skills appear with hyphens** (`/sumo-qa-deciding-approach`, `/sumo-qa-creating-test-plan`, …) — Claude Code's native skill loader picks these up from `~/.claude/skills/<skill>/`.
- **MCP tools appear with underscores** (`/sumo_qa_load_classifications`, `/sumo_qa_find_test_data`, …) — registered through the MCP server. Because the skills are *also* registered through MCP, you'll typically see both hyphen and underscore variants for each skill in the slash menu. They call the same SKILL.md content and behave identically.

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
2. **On macOS only** — refuses to write a command that lives in a source-checkout venv (`.venv`/`venv`/`env`/`.tox`/`.nox`). The Claude.app sandbox cannot read those locations (the same Privacy & Security wall that blocks Desktop / Documents / Downloads / iCloud paths), so a config pointing there would crash the MCP at app launch with `PermissionError: '…/.venv/pyvenv.cfg'`. If a stable install (pipx, pyenv-managed pip, Homebrew) is also on `PATH`, the installer prefers it. If only the source-checkout venv is available, the installer prints the safer install options and exits non-zero **before** touching `claude_desktop_config.json`.
3. If the config file exists, reads it and merges the `sumo-qa` key into `mcpServers` — existing entries (e.g. `obsidian`, `github`) are preserved unchanged. If the existing JSON is invalid, it is not touched and an error is printed instead.
4. If the config file does not exist but the parent directory does, creates it with just the `sumo-qa` entry.

After install: **quit and reopen Claude Desktop** (or restart the relevant Cowork session). The `sumo-qa` MCP tools will appear in the tools panel.

`sumo-qa-doctor --host claude-desktop` mirrors the safety check: it probes the exact command stored in `claude_desktop_config.json` (not just whatever `shutil.which("sumo-qa")` finds on the current shell's `PATH`) and reports `WARN` when that command is in a source-checkout venv on macOS — so a config that looks healthy from the terminal but won't launch from the app is surfaced rather than silently passed.

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
4. Click the **tools / hammer icon** — `sumo-qa` should be listed with its tools underneath

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

You should get the canonical change-classification names back.

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

Two clone-install flows exist; pick by what you want to do.

| Flow | Use when | Pointer |
| --- | --- | --- |
| **Wheel from clone** (matches canonical PyPI install) | You want to **try this version** of the code without publishing to PyPI — e.g. validate a feature branch, smoke-test changes against your real host configs, or share a build with a teammate via `pip install /path/to/their/checkout`. | [Wheel from clone](#wheel-from-clone-matches-canonical-pypi-install) |
| **Editable install** (live-edit workflow) | You want to **edit skills, knowledge catalogues, or standards packs in place** and have the host pick the edits up immediately, with no reinstall step. Closest to working on the project itself. | [Editable install (live-edit workflow)](#editable-install-live-edit-workflow) |

### Wheel from clone (matches canonical PyPI install)

The canonical user install is `pip install sumo-qa && python -m sumo_qa.installer`. Installing from a local clone is the same flow with `pip install .` substituted for `pip install sumo-qa` — pip builds a wheel from the local `pyproject.toml` and installs it just like a PyPI release would, no tags or version bumps required.

The repo ships a helper script that wraps both steps + a post-install `sumo-qa-doctor` smoke:

```bash
git clone https://github.com/sumithr/sumo-qa.git
cd sumo-qa
python scripts/dev_install.py
```

What the script does, in order:

1. `python -m pip install --upgrade --force-reinstall <repo>` against the active interpreter (override with `--python /path/to/python`). The `--force-reinstall` step bypasses pip's "already satisfied" short-circuit when the version string hasn't bumped, so a branch with the same `version =` in `pyproject.toml` as your installed copy still overwrites the wheel.
2. `python -m sumo_qa.installer` (default: configure every detected host). Pass through any host flag the installer understands — e.g. `--claude-code`, `--vscode --workspace .`, `--jetbrains`, `--claude-desktop`, `--skip-mcp-install`.
3. `python -m sumo_qa.doctor` so you can see the result of the install (`[OK]`/`[WARN]`/`[FAIL]` per check, with `Fix:` commands for failures). Skip with `--no-doctor`.

Common invocations:

```bash
python scripts/dev_install.py                          # full canonical flow
python scripts/dev_install.py --claude-code            # only Claude Code host
python scripts/dev_install.py --vscode --workspace .   # only VS Code, this workspace
python scripts/dev_install.py --skip-installer         # just refresh the wheel
python scripts/dev_install.py --python /usr/local/bin/python3.12  # target a specific interpreter
python scripts/dev_install.py --help                   # full flag matrix
```

Reversal: `python -m pip install --upgrade sumo-qa==<previous-version>` restores the PyPI build.

If you'd rather run the steps manually (no script), the same two commands work directly:

```bash
python -m pip install --upgrade --force-reinstall .
python -m sumo_qa.installer --claude-code   # or your host flag of choice
```

#### Test the Claude Code plugin install path

The pip flow above exercises the `sumo-qa-install` (host-config) path. To validate the **Claude Code plugin** install path from a local checkout — the install vector that runs THIS branch's code rather than the published repo (the [marketplace install](#install-commands) always pulls the repo's default branch) — use Claude Code's [`--plugin-dir` flag](https://code.claude.com/docs/en/plugins#test-your-plugins-locally):

```bash
claude --plugin-dir /path/to/sumo-qa
```

Claude Code loads the plugin directly from the directory — no marketplace add, no install step. The plugin's `.mcp.json` uses `${CLAUDE_PLUGIN_ROOT}` substitution (per Anthropic's [canonical pattern](https://code.claude.com/docs/en/mcp#plugin-provided-mcp-servers)) so `uvx --from ${CLAUDE_PLUGIN_ROOT} sumo-qa` resolves to the local checkout — you're running THIS branch's code, not whatever's on the default branch of the public repo. Run `/reload-plugins` inside Claude Code to pick up edits without restarting.

Verify the install with doctor (also via uvx, no pip install needed):

```bash
uvx --from /path/to/sumo-qa sumo-qa-doctor
```

The pip install and plugin install paths are additive, not mutually exclusive — a user can have both at once, and doctor reports each independently.

### Editable install (live-edit workflow)

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

1. It runs with the activated venv's `sumo-qa` first on PATH, so the absolute path it writes into Claude Code's MCP registry / `.vscode/mcp.json` is `<repo>/.venv/bin/sumo-qa`. That binary, when invoked, runs the editable install → reads `<repo>/skills/`, `<repo>/knowledge/`, `<repo>/standards/` live. Claude Code and VS Code launch from the user's shell, so the `.venv` path resolves fine for them.
2. **macOS Claude Desktop is the exception.** Its sandbox can't read repo-`.venv` paths, so the installer refuses to write a `claude_desktop_config.json` entry pointing at `<repo>/.venv/bin/sumo-qa` and exits non-zero (see the [Claude Desktop section](#claude-desktop-macos-app-incl-cowork) above). To wire Claude Desktop from an editable checkout, install a stable companion (`pipx install sumo-qa`, or a pyenv / Homebrew install) first, then re-run `sumo-qa-install --claude-desktop` — the installer skips past the `.venv` candidate and uses the stable one for Claude Desktop while still using `.venv` for the other hosts. Editable dev for the *server* still works — restart Claude Desktop after each MCP server change.
3. Skills get symlinked **per skill** into `~/.claude/skills/<name>` pointing at `<repo>/skills/<name>`. Editing a SKILL.md needs no further action; the host re-reads it on next invocation.

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
- PyPI users who don't want to clone at all can add custom knowledge/standards/rules at runtime via the `sumo-qa-ingest` command (or the `sumo_qa_ingest_knowledge_pack` MCP tool — *"add this to the knowledge base"*). It writes a validated pack into `<cwd>/.sumo-qa` (project) or the XDG data dir (global); precedence is env var > project > global > bundled > repo. See [Adding custom knowledge without cloning the repo](CONFIGURATION.md#adding-custom-knowledge-without-cloning-the-repo).

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
