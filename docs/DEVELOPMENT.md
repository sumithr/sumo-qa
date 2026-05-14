# Development

Local dev guide for sumo-qa.

## Prerequisites

- Python 3.10 or newer (no upper cap; see `pyproject.toml`'s `requires-python`)

That's it. Pick whichever installer you already use — `pip`, `uv`, `pipx`, conda. Examples below use `pip` because it ships with every Python install; `uv` users can swap in equivalent commands.

## Setup

```bash
git clone <repo>
cd sumo-qa
python -m venv .venv                                # any venv tool works; uv users: `uv venv`
source .venv/bin/activate                           # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"                   # installs the package + pytest, ruff, pre-commit
pre-commit install --install-hooks                  # ruff + hygiene hooks on every commit
```

If you already use [uv](https://docs.astral.sh/uv/), the equivalent setup is:

```bash
uv sync --all-extras
uv run pre-commit install --install-hooks
```

To put `sumo-qa` on your PATH for ad-hoc use (optional):

```bash
pip install -e .                  # editable install in the active venv, or
uv tool install --from . sumo-qa  # installs into uv's tool dir
```

## Local verification — automatic via git hooks

The repo uses [pre-commit](https://pre-commit.com/) to enforce the same lint/format checks CI runs.
Once installed (above), every `git commit` runs `ruff check --fix`, `ruff format`, and basic file-hygiene hooks (trailing whitespace, EOL, YAML / TOML / JSON validity, merge-conflict markers, large-file guard) against the staged files automatically. Takes ~1 second and auto-fixes 95% of CI lint failures before the commit lands.

**On-demand run** (without committing):

```bash
pre-commit run --all-files
```

**Skipping hooks** (rare): `git commit --no-verify`. CI will still catch anything you skipped, so use this only for genuine emergencies.

Hooks are pinned in `.pre-commit-config.yaml` and mirror `.github/workflows/lint.yml` exactly, so passing the hooks locally guarantees the lint CI job passes.

**Tests:** the full pytest suite runs in CI on every push (Ubuntu + macOS × Python 3.10–3.14). It deliberately does *not* run as a local pre-push hook — that would couple every push to whichever `python` happens to be first on your PATH (system vs. pyenv vs. venv) and break in mixed environments. Run tests yourself with `pytest` (or `uv run pytest`) when you want a fast local sanity check.

## Test suite

```bash
pytest        # or `uv run pytest`
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
pip install -e .                              # if you're using a plain venv
# or
uv tool install --from . sumo-qa --reinstall  # if you're using uv's tool dir
```

Picks up server.py changes. For skill edits, no reinstall needed — Claude Code reads
`~/.claude/skills/sumo-qa/` via the symlink that `sumo-qa-install` set up, and the MCP server
reads `skills/*/SKILL.md` fresh on each prompt request.
