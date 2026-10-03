# Configuration

All optional. Defaults work out of the box after `pip install sumo-qa && sumo-qa-install`.

| Env var | Default | Purpose |
|---|---|---|
| `QA_STANDARDS_PATH` | bundled `_data/standards/packs` / repo `standards/packs` | Override the team's loaded standards packs |
| `QA_RULES_PATH` | bundled `_data/standards/rules/change_rules.yaml` / repo `standards/rules/change_rules.yaml` | Override the team's loaded change rules |
| `QA_TEST_DATA_PATH` | `knowledge/test_data` (cwd) | Override the known-good test data catalogue. **No samples ship in the wheel**, the catalogue is empty on a fresh install; populate it per your team's domains. |
| `QA_KNOWLEDGE_PATH` | bundled `_data/knowledge` / repo `knowledge` | Override the canonical knowledge catalogues (classifications, approaches, principles, techniques) |
| `SUMO_QA_DEBUG_DIR` | unset | Directory to capture per-tool-call args + output as JSON for debugging / grading |
| `SUMO_QA_MCP_PROFILE` | `full` | MCP tool profile: `full` (every tool) or `core` (the native QA workflow tools; no specialist tools or external-skill search/check/install/execute tools). See [Tool profiles](#tool-profiles) |

These env vars are the lowest-level override and always win. For a no-clone way
to add custom content, see [Adding custom knowledge without cloning the
repo](#adding-custom-knowledge-without-cloning-the-repo) below, it inserts
ingested project/global packs as middle tiers between the env vars and the
bundled defaults.

## Tool profiles

`SUMO_QA_MCP_PROFILE` picks which tools the server lists, once at startup:

- `full` (default; also when unset or empty): every tool, unchanged.
- `core`: the tools the native QA workflows use: the entry router, every
  workflow skill, the knowledge loaders, the test-data, repo-map, evidence and
  report tools, and `sumo_qa_capabilities`. It leaves out the specialist tools
  (`sumo_qa_load_catalogue_entry`, `sumo_qa_list_skill_manifests`,
  `sumo_qa_export_test_cases`, `sumo_qa_ingest_knowledge_pack`) and the
  external-skill tools. The external-skill workflow's tool,
  `sumo_qa_suggesting_external_skill`, stays in the tool list, but the
  search, check, install and execute tools it drives are absent, so it cannot
  run under `core`: calling it, or loading it through
  `sumo_qa_load_skill_context` or the skill resources, returns one activation
  path instead of the skill:

  ```text
  capability unavailable in core profile
  required group: external
  activate: SUMO_QA_MCP_PROFILE=full
  ```

  A host-local copy of the skill (the `~/.claude/skills` link the installer
  writes for Claude Code) has no server in front of it, so when one of its
  tools cannot be found or called, the skill sends the host to
  `sumo_qa_capabilities` for the same setting.

Any other value stops the server at launch with an error naming the valid
profiles. Each tool's capability group and profile membership live in
`src/sumo_qa/tool_registry.py`.

`sumo_qa_capabilities` reports the active profile, the capability groups it
serves, and each group it leaves out with its open-world flag and the setting
that enables it. Its `workflows` list leaves out any workflow the profile
cannot run.

Set the profile in the host's `sumo-qa` entry `env`. Re-running
`sumo-qa-install` refreshes the entry's `command` and `args` and keeps its
`env` in every host it writes: `claude_desktop_config.json` (Claude Desktop,
and the copy written for Claude Code), `.vscode/mcp.json`, and Claude Code's
own MCP registry (user scope in `~/.claude.json`, or
`$CLAUDE_CONFIG_DIR/.claude.json`). It also keeps `envFile` in
`claude_desktop_config.json` and `.vscode/mcp.json`, but not in Claude Code's
registry: the installer re-registers that entry through `claude mcp add-json`
with the old entry's `env` (string values only), and Claude Code entries
cannot use `envFile`, so the claude CLI drops it. A CLI without `add-json`
gets `claude mcp add -e`, which cannot pass `envFile` or any key other than
`command`, `args` and `env`, so the installer warns naming the keys it drops.
If that registration fails, the installer re-adds the entry it removed; when
the remove itself failed, the old entry is still registered and it says so.
Any other key you added to an entry is removed.

`sumo-qa-doctor --host <host>` probes the entry that host launches, with that
entry's `env`:

| `--host` | Entry probed | Shell `SUMO_QA_MCP_PROFILE` |
|---|---|---|
| `claude-code` | Claude Code's user-scope registry (`$CLAUDE_CONFIG_DIR/.claude.json` when set, else `~/.claude.json`) | kept |
| `claude-desktop` | `claude_desktop_config.json` | dropped |
| `vscode` | `<workspace>/.vscode/mcp.json` `servers` (VS Code ignores `mcpServers`) | kept |
| `codex`, `jetbrains` | none: the `sumo-qa` on `PATH` | kept |

The entry's `env` always wins over the shell. Where the shell's value is
kept, it follows the host:

- Claude Code passes its own process env to stdio servers, so a profile
  exported in the shell that starts `claude` applies when the entry sets none.
  Verified with Claude Code 2.1.287 in a temp HOME: a server registered with
  `claude mcp add -e ENTRY_VAR=...` and started by `claude mcp list` saw both
  `ENTRY_VAR` and the shell's `SUMO_QA_MCP_PROFILE`; with the entry setting
  `SUMO_QA_MCP_PROFILE=full`, the entry's value won over the shell's `core`.
- Claude Desktop is a GUI app and does not see the doctor shell's env, so the
  probe drops the shell's value and only the entry picks the profile.
- VS Code: not verified. Whether its servers see a shell's env depends on
  how VS Code was started (with `code` from that terminal, or from the Dock or
  Start menu), so the probe keeps the shell's value.

A `${...}` in an entry's command, args or env is read the way its host reads
it:

- VS Code: `${workspaceFolder}`, `${userHome}` and `${env:NAME}` are expanded
  as VS Code does, by both the probe and the `vscode_workspace_config` check.
  An entry that still holds another `${...}` (such as `${input:...}`, which VS
  Code prompts for) is a WARN in both: the doctor cannot know the value, so it
  does not launch it. This WARN applies only to VS Code entries.
- Claude Code: `${VAR}` and `${VAR:-default}` are expanded from the doctor's
  env, as Claude Code expands them from its own. Verified with Claude Code
  2.1.287 on a user-scope entry: a set `VAR` (even empty) gives its value, an
  unset one gives the default, and an unset one with no default stays as
  written (Claude Code warns "Missing environment variables" and launches it).
- Claude Desktop: nothing is expanded; the entry launches as written, so a
  `${...}` in its command is a launch FAIL.

An invalid profile is a FAIL; otherwise the probe requires every tool the
launch profile serves. An entry whose command cannot be started (a moved
venv) is a FAIL naming the command and the config file. An entry `env` key
containing `=` cannot be passed to a process: the probe launches without it
and reports a WARN naming it. The doctor does not read `envFile`. With no
`--host`, or when the host has no `sumo-qa` entry, the doctor probes the
`sumo-qa` on `PATH` with its own shell env. The `vscode_workspace_config`
check judges the same `servers` entry as the probe; an entry only under the
legacy `mcpServers` key is a FAIL, since VS Code does not register it.

```json
{
  "mcpServers": {
    "sumo-qa": {
      "command": "sumo-qa",
      "env": { "SUMO_QA_MCP_PROFILE": "core" }
    }
  }
}
```

## Example: custom team standards

```json
{
  "mcpServers": {
    "sumo-qa": {
      "command": "sumo-qa",
      "env": {
        "QA_STANDARDS_PATH": "/abs/path/to/team-standards/packs",
        "QA_RULES_PATH": "/abs/path/to/team-standards/rules/change_rules.yaml",
        "QA_TEST_DATA_PATH": "/abs/path/to/team-test-data"
      }
    }
  }
}
```

## Adding custom knowledge without cloning the repo

PyPI users can add or replace QA knowledge/standards/rules at runtime, no
clone, fork, or hand-authored env-var tree required. Hand a native file (or a
directory of them) to the ingestion tool and it validates, normalizes, and
writes the content into a user-writable pack.

**Two scopes** (the tool asks which to use, mirroring `sumo-qa-install`):

- **`project`** → `<cwd>/.sumo-qa/`: applies to the current repo only.
- **`global`** → `$XDG_DATA_HOME/sumo-qa/` (else `~/.local/share/sumo-qa/`;
  `%LOCALAPPDATA%\sumo-qa\` on Windows): applies to every repo.

**Precedence** (highest wins, resolved per knowledge file):

```
explicit env var  >  project pack  >  global pack  >  bundled defaults  >  repo root
```

So `QA_KNOWLEDGE_PATH` etc. still win over everything (the low-level override
mechanism is unchanged), and a pack containing only `principles.md` overrides
just principles, the other catalogues fall through to the bundled defaults.

**In conversation** (the MCP tool): say *"add this to the knowledge base"* and
the agent calls `sumo_qa_ingest_knowledge_pack(source, scope, content_type)`.

**From the shell** (the console script):

```bash
sumo-qa-ingest principles.md --scope project      # this repo only
sumo-qa-ingest ./team-pack/   --scope global       # a directory, all repos
sumo-qa-ingest converted.md   --type principles    # force the catalogue
```

Accepted native files: `principles.md`, `techniques.md`, `classifications.md`,
`approaches.md`, a standards-pack `*.yaml`, and `change_rules.yaml`. Invalid
content fails with an actionable error and **writes nothing**.

A directory source may be either **flat** (the native files sitting directly in
it) or a **repo-shaped tree** that mirrors the bundled layout
(`knowledge/*.md`, `standards/packs/*.yaml`, `standards/rules/change_rules.yaml`)
- so you can export your team's existing tree and ingest it as-is. Scanning is
limited to those canonical locations (it does not recurse arbitrarily), and
symlinked files or subdirectories are skipped.

### End-to-end (PyPI user)

```bash
pip install sumo-qa && sumo-qa-install --claude-code

# Author a replacement principles catalogue and ingest it for this repo.
printf '# Team principles\n\nWe weight risk-based testing above coverage %%.\n' > principles.md
sumo-qa-ingest principles.md --scope project
# -> ingested 1 file(s) -> /path/to/repo/.sumo-qa
#      - principles: /path/to/repo/.sumo-qa/knowledge/principles.md

# The loader now returns the ingested content:
python -c "from sumo_qa.knowledge_loaders import sumo_qa_load_principles as p; print(p())"
# -> # Team principles ...
```

### Non-native sources (PDF, PPTX, a URL)

The ingest tool is format-strict and does **no** conversion or network fetch.
Hand it a `.pdf`/`.pptx`/URL and it returns an `unsupported_source` result that
routes through the `sumo-qa-suggesting-external-skill` flow: it finds, installs,
and runs a converter skill to turn the source into markdown (the converter owns
any URL fetch), then re-ingests the result with an explicit `--type` /
`content_type`. Don't transcribe the source by hand.

## Review feedback memory

A team can promote a recurring review lesson, *"we always miss timezone
boundaries in billing"*, into an explicit, inspectable, reversible **review
feedback memory** that the planning and review skills consult as an **advisory
hint**. It is deliberately not automatic learning: nothing is saved without an
explicit, user-confirmed capture, and sumo-qa never auto-captures from a review,
prompt, or tool trace.

**Storage reuses the same `project`/`global` pack location as ingestion** (it is
*not* a second hidden tree) under a `feedback/` subdir:

- **`project`** → `<cwd>/.sumo-qa/feedback/review_feedback.yaml`: this repo only.
- **`global`** → the user data dir (`$XDG_DATA_HOME/sumo-qa/feedback/…`, else
  `~/.local/share/sumo-qa/feedback/…`; `%LOCALAPPDATA%\sumo-qa\feedback\…` on
  Windows): every repo.

**Each saved item carries** `scope` (where the lesson applies), `trigger_signal`
(the change shape that should surface it), `recommended_probe` (the QA check to
run), `source_note` (your own short summary of where the lesson came from), and
`last_reviewed` (an ISO-8601 timestamp, defaulted to now).

**Advisory precedence.** Feedback memory is *not* one of the
knowledge/standards/rules loader tiers, so it can never shadow a canonical
catalogue. The skills cite a memory-derived probe **separately** from the
bundled ISTQB principles, techniques, and change-rules, and it **never overrides
a classification or change-rule**. The only way team content gains canonical
authority is the `sumo_qa_ingest_knowledge_pack` path above (a #92 custom pack).

**Sensitive input is rejected, not stored.** A free-text field that looks like a
raw diff hunk, a secret/credential, a code snippet, or a pasted full issue/PR
body fails validation and **nothing is written**, only your own summary is kept.

**In conversation** (the MCP tool): *"remember that we always miss timezone
boundaries in billing"* → the agent calls `sumo_qa_capture_review_feedback`
after confirming with you. *"what review lessons have we saved?"* lists them.

**Inspect and remove** (the console script, capture goes through a host that can
confirm with you, so the CLI exposes only listing and deletion):

```bash
sumo-qa-feedback list                          # all saved lessons (this repo + global), as JSON
sumo-qa-feedback list --scope project          # this repo only
sumo-qa-feedback list --scope global           # cross-repo lessons only
sumo-qa-feedback delete <id> --scope project   # remove a saved lesson by id
```

To wipe a scope entirely, delete its `feedback/review_feedback.yaml` file.

## Optional analysis signals

The semantic-analysis adapter layer (issue #212, see [ARCHITECTURE.md](ARCHITECTURE.md)) reads optional inputs and degrades cleanly when they are absent, so none of them is required for a normal install:

- **Cross-file impacted-symbol reach** needs the repo-map `imports` graph, built by the optional `[treesitter]` extra (`pip install sumo-qa[treesitter]`, owned by #353). Without the extra, changed-symbol extraction and the changed-symbol-to-likely-test mapping still run; only the cross-file reach is skipped, and the result records a `missing_optional_dependency` fallback naming why.
- **Coverage and mutation signals** are read from `.sumo-qa/coverage.json` and `.sumo-qa/mutation.json` when present (the same artifacts the readiness scorecard consumes). An absent file is treated as not-measured, never an error; a present-but-malformed file is surfaced as an `invalid_artifact` fallback instead of being silently dropped.

No optional analysis dependency is required for `sumo-qa` to start.

## Debugging

```json
{
  "mcpServers": {
    "sumo-qa": {
      "command": "sumo-qa",
      "env": {
        "SUMO_QA_DEBUG_DIR": "/tmp/sumo-qa-debug"
      }
    }
  }
}
```

Each tool call writes a JSON file under `SUMO_QA_DEBUG_DIR` capturing the args and output. Useful for grading skill-driven output and reproducing host-side issues.
