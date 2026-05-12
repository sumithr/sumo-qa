# Development

Local dev guide for sumo-qa.

## Prerequisites

- Python 3.10 or newer (no upper cap; see `pyproject.toml`'s `requires-python`)
- [uv](https://docs.astral.sh/uv/) — install via `curl -LsSf https://astral.sh/uv/install.sh | sh` (or PowerShell equivalent on Windows)

## Setup

```bash
git clone <repo>
cd sumo-qa
uv tool install --from . sumo-qa --reinstall
```

For development without installing to the user tool dir, use `uv run`:

```bash
uv run pytest
uv run sumo-qa --help
```

## Test suite

```bash
uv run pytest
```

The full suite covers:

- `test_knowledge_loaders.py` — 7 catalogue loaders return canonical entries
- `test_skill_conformance.py` — every `skills/*/SKILL.md` has the required structure
- `test_skill_prompts.py` — every skill registers as an MCP prompt
- `test_phase3_e2e_skill_path.py` — end-to-end smoke through the new surface
- `test_token_weight_regression.py` — per-call and per-flow token budgets (the IntelliJ-SSE regression test)
- `test_server.py` — tool registration
- `test_tdm.py` — test-data tools
- `test_tools.py` — service factory
- `test_standards.py`, `test_rules.py` — file loading
- `test_debug_capture.py` — `SUMO_QA_DEBUG_DIR` capture

## Branch workflow

Feature work goes on a feature branch off `main`. Plans and specs land under
`docs/superpowers/`. Iteration notes go under `docs/superpowers/iteration-runs/`.
Don't push without explicit review approval.

## Editing skills

Plain markdown. Edit `skills/<name>/SKILL.md`. Conformance tests catch structural
drift (Iron Law section, Checklist ≥4 items, graphviz dot block, Red Flags table).

## Editing knowledge catalogues

Plain markdown under `knowledge/`. The LLM picks from what these files say.
Adding a new technique, classification, or specialty tool = editing one file.

## Adding a new skill

1. Create `skills/<new-name>/SKILL.md` following the template in `docs/SKILLS.md`.
2. `register_skills_as_prompts` (server startup) picks it up automatically.
3. Conformance tests parametrise over `skills/*/SKILL.md` — they run on the new skill too.
4. If the skill is meant to auto-trigger in Claude Code, the frontmatter `description` is what the host LLM uses to route.

## Reinstalling locally

```bash
uv tool install --from . sumo-qa --reinstall
```

Picks up server.py changes. For skill edits, no reinstall needed — Claude Code reads
`~/.claude/skills/sumo-qa/` via the symlink that `sumo-qa-install` set up, and the MCP server
reads `skills/*/SKILL.md` fresh on each prompt request.
