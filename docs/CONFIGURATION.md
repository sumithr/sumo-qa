# Configuration

All optional. Defaults work out of the box after `pip install sumo-qa && sumo-qa-install`.

| Env var | Default | Purpose |
|---|---|---|
| `QA_STANDARDS_PATH` | bundled `_data/standards/packs` / repo `standards/packs` | Override the team's loaded standards packs |
| `QA_RULES_PATH` | bundled `_data/standards/rules/change_rules.yaml` / repo `standards/rules/change_rules.yaml` | Override the team's loaded change rules |
| `QA_TEST_DATA_PATH` | `knowledge/test_data` (cwd) | Override the known-good test data catalogue. **No samples ship in the wheel** — the catalogue is empty on a fresh install; populate it per your team's domains. |
| `QA_KNOWLEDGE_PATH` | bundled `_data/knowledge` / repo `knowledge` | Override the canonical knowledge catalogues (classifications, approaches, principles, techniques) |
| `SUMO_QA_DEBUG_DIR` | unset | Directory to capture per-tool-call args + output as JSON for debugging / grading |

These env vars are the lowest-level override and always win. For a no-clone way
to add custom content, see [Adding custom knowledge without cloning the
repo](#adding-custom-knowledge-without-cloning-the-repo) below — it inserts
ingested project/global packs as middle tiers between the env vars and the
bundled defaults.

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

PyPI users can add or replace QA knowledge/standards/rules at runtime — no
clone, fork, or hand-authored env-var tree required. Hand a native file (or a
directory of them) to the ingestion tool and it validates, normalizes, and
writes the content into a user-writable pack.

**Two scopes** (the tool asks which to use, mirroring `sumo-qa-install`):

- **`project`** → `<cwd>/.sumo-qa/` — applies to the current repo only.
- **`global`** → `$XDG_DATA_HOME/sumo-qa/` (else `~/.local/share/sumo-qa/`;
  `%LOCALAPPDATA%\sumo-qa\` on Windows) — applies to every repo.

**Precedence** (highest wins, resolved per knowledge file):

```
explicit env var  >  project pack  >  global pack  >  bundled defaults  >  repo root
```

So `QA_KNOWLEDGE_PATH` etc. still win over everything (the low-level override
mechanism is unchanged), and a pack containing only `principles.md` overrides
just principles — the other catalogues fall through to the bundled defaults.

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
— so you can export your team's existing tree and ingest it as-is. Scanning is
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
routes you to a dedicated converter skill: discover one via skill-discovery
(`find-skills` / `sumo_qa_search_external_skills`, e.g. a `pdf-to-markdown`
skill), convert the source to markdown in one shot, then re-ingest the result
with an explicit `--type` / `content_type`. Don't transcribe the source by hand.

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
