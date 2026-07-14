# Configuration

All optional. Defaults work out of the box after `pip install sumo-qa && sumo-qa-install`.

| Env var | Default | Purpose |
|---|---|---|
| `QA_STANDARDS_PATH` | bundled `_data/standards/packs` / repo `standards/packs` | Override the team's loaded standards packs |
| `QA_RULES_PATH` | bundled `_data/standards/rules/change_rules.yaml` / repo `standards/rules/change_rules.yaml` | Override the team's loaded change rules |
| `QA_TEST_DATA_PATH` | `knowledge/test_data` (cwd) | Override the known-good test data catalogue. **No samples ship in the wheel**, the catalogue is empty on a fresh install; populate it per your team's domains. |
| `QA_KNOWLEDGE_PATH` | bundled `_data/knowledge` / repo `knowledge` | Override the canonical knowledge catalogues (classifications, approaches, principles, techniques) |
| `SUMO_QA_DEBUG_DIR` | unset | Directory to capture per-tool-call args + output as JSON for debugging / grading |
| `SUMO_QA_OUTPUT_PROFILE` | `default` | Output verbosity/strictness profile for served skill bodies: `concise`, `default`, or `strict` (see [Output verbosity and strictness profiles](#output-verbosity-and-strictness-profiles)). An unrecognised value falls back to `default`. |

These env vars are the lowest-level override and always win. For a no-clone way
to add custom content, see [Adding custom knowledge without cloning the
repo](#adding-custom-knowledge-without-cloning-the-repo) below, it inserts
ingested project/global packs as middle tiers between the env vars and the
bundled defaults.

## Output verbosity and strictness profiles

`SUMO_QA_OUTPUT_PROFILE` tunes how much ceremony wraps the skill guidance
sumo-qa serves, so a small docs-only or test-only edit does not feel like a
full QA audit while security, API, migration, and release-gate work still gets
strict handling. It is a serve-time overlay on the single skill-serving path,
so no skill file is edited and the canonical `SKILL.md` content stays readable
and host-neutral.

| Value | Effect |
|---|---|
| `concise` | Shortest useful answer AND leanest tool path: one focused risk/test summary, findings over framing, no formal section headers or evidence tables unless the skill marks them mandatory; load only what the skill's gates require, skip supplementary loads and sweeps, never re-load content already in context (#528). |
| `default` | Current behaviour. The skill body is served byte-for-byte, unchanged. |
| `strict` | Full ceremony: each gate stated explicitly, evidence as a table, every named risk mapped to its test, and an explicit residual-risk section. |

Profiles shape ceremony and the tool path, not the session price. Measured
end-to-end with a real headless agent (#528, 2026-07-14): `concise` does not
reduce total session tokens, because session cost is dominated by the mandatory
QA flow's tool traffic and per-turn context, which no serve-time overlay can
shrink. Pick `concise` for decisive, low-ceremony output on small changes, not
for cost savings.

An unrecognised value (a typo, an unknown name) falls back predictably to
`default` rather than failing, so a misconfigured host can never break serving
or silently drop a gate.

**Never optional, at any profile.** A profile tunes how much prose wraps the
work, never whether the mandatory gates hold. Whatever the profile, the served
overlay restates that the skill's Iron Law and any HARD-GATE, evidence for
every claim, explicit user confirmation before writing files or installing
anything, and every mandatory test or safety gate the skill names are always
kept. Concise mode shortens low-risk output; it does not drop a gate on
high-risk work. Strict mode adds structure to the skill body only; it does not
touch the `sumo_qa_load_*` catalogue payloads, so it cannot bloat them.

```json
{
  "mcpServers": {
    "sumo-qa": {
      "command": "sumo-qa",
      "env": {
        "SUMO_QA_OUTPUT_PROFILE": "concise"
      }
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
