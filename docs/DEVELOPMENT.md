# Development

Local dev guide for sumo-qa.

## Prerequisites

- **Python 3.10 or newer** (no upper cap; see `pyproject.toml`'s `requires-python`)
- **Node.js 20.20+ or 22.22+** — only needed if you run the LLM eval harness (`tests/evals/promptfoo/`). Promptfoo is a Node CLI; we pin it as a local devDependency in `package.json`. Skip this if you don't touch evals.

Python tooling: pick whichever installer you already use — `pip`, `uv`, `pipx`, conda. Examples below use `pip` because it ships with every Python install; `uv` users can swap in equivalent commands.

Node tooling: `nvm` (or any Node version manager) handles the version requirement cleanly. `nvm use 24` works.

## Setup

```bash
git clone <repo>
cd sumo-qa
python -m venv .venv                                # any venv tool works; uv users: `uv venv`
source .venv/bin/activate                           # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"                   # installs the package + pytest, ruff, pre-commit
pre-commit install --install-hooks                  # ruff + hygiene hooks on every commit
pre-commit install --hook-type pre-push             # full pytest suite on every push
```

If you already use [uv](https://docs.astral.sh/uv/), the equivalent setup is:

```bash
uv sync --all-extras
uv run pre-commit install --install-hooks
uv run pre-commit install --hook-type pre-push
```

### Eval harness (Node-only — skip if you don't touch evals)

```bash
nvm use 24             # or any Node 20.20+ / 22.22+ install
npm install            # installs promptfoo from package.json
npm run eval           # runs the TDD skill eval (needs OPENAI_API_KEY)
```

See [`tests/evals/promptfoo/README.md`](../tests/evals/promptfoo/README.md) for full eval usage + cost notes.

To put `sumo-qa` on your PATH for ad-hoc use (optional):

```bash
pip install -e .                  # editable install in the active venv, or
uv tool install --from . sumo-qa  # installs into uv's tool dir
```

## Local verification — automatic via git hooks

The repo uses [pre-commit](https://pre-commit.com/) to enforce the same checks CI runs.
Once installed (above), you get them for free on every `git commit` / `git push`:

| Trigger | What runs | Speed | Why |
|---|---|---|---|
| `git commit` | `ruff check --fix`, `ruff format`, trailing-whitespace / EOL / YAML / TOML / JSON / merge-conflict / large-file hooks | ~1s | Auto-fixes 95% of CI lint failures before the commit lands. |
| `git push` | full `pytest -q` suite | ~2s after first run | Stops broken commits reaching the remote. |

The pytest hook runs in pre-commit's own isolated venv (managed by the framework via `additional_dependencies: [".[dev]"]`), so it's not coupled to whichever `python` happens to be on your PATH. The first `git push` after install will be slower (~30s) while pre-commit builds the venv; subsequent pushes reuse it.

**On-demand runs** (without committing/pushing):

```bash
pre-commit run --all-files                          # ruff + hygiene
pre-commit run --all-files --hook-stage pre-push    # pytest
```

**Skipping hooks** (rare): `git commit --no-verify` or `git push --no-verify`. CI will still catch anything you skipped — use this only for genuine emergencies.

Hooks are pinned in `.pre-commit-config.yaml` and mirror `.github/workflows/lint.yml` + `.github/workflows/test.yml`, so passing the hooks locally guarantees CI passes.

## Test suite

```bash
pytest        # or `uv run pytest`
```

The full suite covers:

- `test_knowledge_loaders.py` — 7 catalogue loaders return canonical entries
- `test_skill_conformance.py` — every `skills/*/SKILL.md` has the required structure
- `test_skill_prompts.py` — every skill registers as an MCP tool (function name is historical; tools, not prompts)
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

Picks up server.py changes. For skill edits, no reinstall needed — Claude Code reads each
`~/.claude/skills/<name>/` directory via the per-skill symlinks `sumo-qa-install` set up
(no wrapper directory; Claude Code doesn't recurse), and the MCP server reads
`skills/*/SKILL.md` fresh on each tool invocation.
