# Development

Local dev guide for sumo-qa.

## Prerequisites

- Python 3.10 or newer (no upper cap; see `pyproject.toml`'s `requires-python`)
- [uv](https://docs.astral.sh/uv/) — install via `curl -LsSf https://astral.sh/uv/install.sh | sh` (or PowerShell equivalent on Windows)

## Setup

```bash
git clone <repo>
cd sumo-qa
uv sync --all-extras                                # installs pytest, ruff, pre-commit, etc.
uv run pre-commit install --install-hooks           # ruff + hygiene hooks on every commit
uv run pre-commit install --hook-type pre-push      # full pytest suite on every push
uv tool install --from . sumo-qa --reinstall        # optional: puts `sumo-qa` on PATH
```

For development without installing to the user tool dir, use `uv run`:

```bash
uv run pytest
uv run sumo-qa --help
```

## Local verification — automatic via git hooks

The repo uses [pre-commit](https://pre-commit.com/) to enforce the same checks CI runs.
Once installed (above), you get them for free on every `git commit` / `git push`:

| Trigger | What runs | Why |
|---|---|---|
| `git commit` | `ruff check --fix`, `ruff format`, trailing-whitespace / EOL / YAML / TOML / JSON / merge-conflict / large-file hooks | Fast (~1s). Catches and auto-fixes 95% of CI lint failures before the commit lands. |
| `git push` | full `pytest -q` suite | Slower (~2s on this repo). Stops broken commits reaching the remote. |

You don't need to remember to run `uv run ruff check`, `uv run ruff format --check`, or
`uv run pytest` manually — the hooks do it for you.

**On-demand runs** (without committing/pushing):

```bash
uv run pre-commit run --all-files                       # ruff + hygiene across whole repo
uv run pre-commit run --all-files --hook-stage pre-push # pytest across whole repo
```

**Skipping hooks** (rare): `git commit --no-verify` or `git push --no-verify`. CI will still catch
anything you skipped, so use this only for genuine emergencies.

Hooks are pinned in `.pre-commit-config.yaml`. They mirror `.github/workflows/lint.yml` and
`.github/workflows/test.yml` exactly, so passing locally guarantees CI passes.

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

Feature work goes on a feature branch off `main`. Don't push without explicit
review approval.

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
