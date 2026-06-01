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
python -m pip install -e ".[dev]"                   # installs the package + pytest, ruff, mypy, pre-commit
pre-commit install --install-hooks                  # ruff + hygiene hooks on every commit
pre-commit install --hook-type pre-push             # full pytest suite on every push
```

If you already use [uv](https://docs.astral.sh/uv/), the equivalent setup is:

```bash
uv sync --all-extras
uv run pre-commit install --install-hooks
uv run pre-commit install --hook-type pre-push
```

### Markdown drift gate

Every commit that touches a `.md` file runs [`scripts/check_markdown_links.sh`](../scripts/check_markdown_links.sh) — a thin wrapper that fails the commit if any markdown link or root-level user-facing code-block file ref points at a file that doesn't exist. CI runs the same script across every tracked markdown file on every PR via the `markdown-links` job in [`.github/workflows/lint.yml`](../.github/workflows/lint.yml).

Two layers run in sequence:

1. **`pytest-check-links`** for markdown link syntax (every tracked `.md`). Catches `[label](path/to/file)` after the target file is removed or renamed. Runs across the whole repo with high precision (zero false positives in practice).
2. **`scripts/check_codeblock_file_refs.py`** for inline-code and fenced-code file refs in **root-level user-facing docs only** (`README.md`, `AGENTS.md`, `DEMO.md`, `CHANGELOG.md`). Catches commands like `python scripts/<removed>.py` whose file no longer exists. Narrower scope by design — `docs/*.md` contains lots of illustrative example paths and would generate too many false positives. Gitignored paths (intentional runtime outputs) are skipped automatically via `git check-ignore`.

What the gate does **not** catch (yet):

- Broken section anchors (`#some-heading`). `pytest-check-links` 0.10.1 has a known anchor-detection bug; the gate runs with `--check-anchors` OFF. Revisit when `> 0.10.x` ships.
- Broken external URLs. Skipped intentionally — pre-commit must stay fast and offline.
- GitHub-relative URLs like `../../commit/<sha>` or `../../pull/<n>`. These only resolve on github.com; pattern-skipped in the wrapper.
- Code-block file refs inside `docs/*.md`, `skills/*.md`, `knowledge/*.md`, or `tests/scenarios/**/*.md`. These docs are full of illustrative paths by design; scanning them would flood the gate with false positives.

To run the whole gate manually from the repo root, invoke `scripts/check_markdown_links.sh` with no args to scan every tracked `.md`, or pass explicit paths to limit scope.

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

### Try this branch as a "real user" (without publishing)

The contributor workflow above gives you an **editable** install — perfect for live edits but distinct from what an end-user gets via `pip install sumo-qa` or `claude plugin install sumithr/sumo-qa`. Two helpers cover the two install vectors:

**`scripts/dev_install.py`** — pip-install path (the canonical PyPI flow):

```bash
python scripts/dev_install.py                # full canonical flow: pip install + sumo-qa-install + doctor
python scripts/dev_install.py --claude-code  # only configure Claude Code
python scripts/dev_install.py --skip-installer   # just refresh the wheel
python scripts/dev_install.py --help         # full flag matrix
```

Runs `pip install --upgrade --force-reinstall .` against the active interpreter, then `python -m sumo_qa.installer` (passing through any host flags you provide), then `python -m sumo_qa.doctor`. Bootstraps pip automatically via `ensurepip` when the target venv lacks it (e.g. uv-created venvs). Full write-up: [docs/INSTALL.md#wheel-from-clone-matches-canonical-pypi-install](INSTALL.md#wheel-from-clone-matches-canonical-pypi-install).

**Claude Code plugin path** — use Claude Code's `--plugin-dir` flag (the [official local-dev mechanism](https://code.claude.com/docs/en/plugins#test-your-plugins-locally)):

```bash
claude --plugin-dir /path/to/sumo-qa
```

That loads the plugin directly from the directory — no marketplace, no install step. `/reload-plugins` inside Claude Code picks up edits without restarting. The plugin's `.mcp.json` uses `${CLAUDE_PLUGIN_ROOT}` so `uvx` resolves the local checkout's Python source — `claude --plugin-dir` invocations run THIS branch's code end-to-end (skills + hooks + MCP server tools).

> **`--plugin-dir` is session-scoped, not a persistent install.** The flag must be passed on every `claude` invocation; it isn't recorded anywhere. Plain `claude` (no flag) starts a session with no sumo-qa loaded, even if a previous session had it. Persistent install requires `claude plugin install sumithr/sumo-qa` once the plugin is published to a marketplace — until then, `--plugin-dir` is the only vehicle for local-dev iteration.
>
> Likewise `uv` must be on PATH **before** `claude --plugin-dir` launches: Claude Code captures `PATH` at process start and `/reload-plugins` does not refresh it. If you install uv mid-session, `/quit`, source your shell rc (or open a fresh tab), and relaunch.

For the plugin's own doctor, inside the Claude Code session just type `!sumo-qa-doctor` — the plugin ships a `bin/sumo-qa-doctor` wrapper that's on the Bash tool's PATH while the plugin is enabled (Anthropic's [documented `bin/` mechanism](https://code.claude.com/docs/en/plugins-reference#plugin-directory-structure)). From outside Claude Code:

```bash
uvx --from /path/to/sumo-qa sumo-qa-doctor
```

Reversal: `pip install --upgrade sumo-qa==<previous-version>` restores the PyPI build for the pip path; exit the Claude Code session to drop the `--plugin-dir` plugin.

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

Hooks are pinned in `.pre-commit-config.yaml` and mirror `.github/workflows/lint.yml` + `.github/workflows/test.yml`, so passing the hooks locally clears the ruff and pytest gates. One CI lint gate is intentionally not a hook — `mypy` (see [Type checking](#type-checking)) — to keep `git push` fast; run `python -m mypy` before pushing to clear it too.

## Test suite

```bash
pytest        # or `uv run pytest`
```

The full suite covers:

- `test_knowledge_loaders.py` — 7 catalogue loaders return canonical entries
- `test_skill_conformance.py` — every `skills/*/SKILL.md` has the required structure
- `test_skill_md_description_vs_body.py` — every `skills/*/SKILL.md` frontmatter `description` that names a catalogue (classifications, approaches, principles, techniques, standards, rules) must back it with a `sumo_qa_load_<catalogue>` call in the body — catches description-vs-body drift (the #188 `sumo-qa-deciding-approach` over-claim of `rules` + `standards`). Matches the prefixed call form, not bare `load_<catalogue>` prose mentions of other skills' loads
- `test_skill_prompts.py` — every skill registers as an MCP tool (function name is historical; tools, not prompts)
- `test_phase3_e2e_skill_path.py` — end-to-end smoke through the new surface
- `test_token_weight_regression.py` — per-call and per-flow token budgets (the IntelliJ-SSE regression test)
- `test_server.py` — tool registration
- `test_skill_triggering.py` — deterministic, host-neutral assertion that every skill tool is registered AND that its MCP description contains at least one of the natural-language trigger phrases pinned for the prompts that should route to it (fixture: `tests/fixtures/skill_triggers.yaml`). Phrase presence is a necessary (not sufficient) condition for the host LLM to pick the right tool by description alone; the harness catches the silent regression where a description rewording drops a trigger phrase. Behavioural quality is judged by the optional LLM evals under `tests/evals/promptfoo/`
- `test_tdm.py` — test-data tools
- `test_tools.py` — service factory
- `test_standards.py`, `test_rules.py` — file loading
- `test_debug_capture.py` — `SUMO_QA_DEBUG_DIR` capture

## Type checking

The package ships the PEP 561 marker `src/sumo_qa/py.typed`, so the
`Typing :: Typed` classifier in `pyproject.toml` is real — downstream
type-checkers honour sumo-qa's annotations. `tests/test_wheel_packaging.py`
builds the wheel and asserts the marker is inside it, so a packaging change
that dropped it would fail the suite.

Run the static type checker from the repo root:

```bash
python -m mypy        # or `uv run mypy`
```

Configuration lives in `[tool.mypy]` in `pyproject.toml` (targets Python 3.10,
the lowest supported runtime; checks `src/sumo_qa` only — tests are out of
scope). The `mypy` job in [`.github/workflows/lint.yml`](../.github/workflows/lint.yml)
runs the same command on every PR. The few dynamic surfaces (FastMCP decorator
returns, a Pydantic opt-out attribute) carry narrow `# type: ignore[<code>]`
comments with rationale; `warn_unused_ignores` is on, so a suppression that
stops being needed fails the check until removed.

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
5. Add a trigger row to [`tests/fixtures/skill_triggers.yaml`](../tests/fixtures/skill_triggers.yaml) pinning at least one natural-language prompt to the new skill — [`tests/test_skill_triggering.py`](../tests/test_skill_triggering.py) fails on any registered skill tool that lacks a fixture row, and on any pinned phrase that doesn't appear in the skill's description. Edit the fixture, not the test.
6. **Don't add the skill to a list in the docs** — there isn't one. The docs are kept at capability-altitude (no skill/tool counts or name-lists); `README.md`, `docs/SKILLS.md`, and `docs/TOOLS.md` point to `skills/` for the skills and the host's MCP tool list for the live tool surface. Only a genuine *capability* change (a new kind of workflow, a changed contract) warrants a docs edit.

## Editing plugin packaging (host adapters)

Plugin-format hosts (Claude Code, Codex) consume `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` at the repo root. These folders — along with `.mcp.json`, `hooks/hooks.json`, `hooks/hooks-codex.json`, `docs/host-adapters.md`, and the runtime snapshot at `src/sumo_qa/_data/plugin_metadata.json` — are **generated** from `pyproject.toml`'s `[tool.sumo-qa.plugin]` overlay. Do not hand-edit them.

```bash
# After bumping any plugin metadata in [tool.sumo-qa.plugin]:
python -m plugin_packaging.plugin_generator sync

# Before pushing, the pre-commit drift hook re-runs:
python -m plugin_packaging.plugin_generator check

# Schema correctness (Claude Code manifest + Codex hooks):
python -m plugin_packaging.validate_plugins
```

The `plugin-packaging` CI workflow runs both gates on every PR. If `pyproject.toml`'s plugin overlay changes without a matching `sync`, the drift check fails.

### Adding a new host adapter

1. Add `plugin_packaging/templates/<host>.py` exposing `render(plugin: CanonicalPlugin) -> dict`.
2. Wire it into `plugin_packaging.plugin_generator._build_outputs`.
3. Run `python -m plugin_packaging.plugin_generator sync` and commit the generated folder.
4. If the host publishes a JSON Schema, vendor it under `plugin_packaging/schemas/` and add a `validate_<host>` call to `plugin_packaging/validate_plugins.py`. Otherwise extend the `plugin-dir-handshake` matrix in `.github/workflows/install-smoke.yml`.

See [host-adapters.md](host-adapters.md) for the full architecture rationale.

## Scheduled CI workflows (opt-in, off the PR critical path)

Three workflows run on a weekly schedule (Monday mornings UTC) and on
`workflow_dispatch`, but never on `push` or `pull_request` — so they
exercise external surfaces without becoming required PR checks:

- [`.github/workflows/tdm-freshness.yml`](../.github/workflows/tdm-freshness.yml) — checks every known-good test-data URL still returns 2xx. Opens a `tdm-freshness` issue on failure. (06:00 UTC.)
- [`.github/workflows/external-skills-smoke.yml`](../.github/workflows/external-skills-smoke.yml) — runs `tests/test_external_skills.py::test_search_external_skills_real_cli_smoke` against the real upstream Skills CLI (`npx skills find`). The mocked coverage in `tests/test_external_skills.py` runs on every PR via `test.yml`; this workflow exists so format drift in the upstream Skills CLI surfaces on a low cadence without coupling required CI to npm / network / upstream uptime. (06:00 UTC.)
- [`.github/workflows/upgrade-smoke.yml`](../.github/workflows/upgrade-smoke.yml) — installs **whatever sumo-qa is currently published on PyPI** into a temp HOME, configures Claude Code + VS Code, then upgrades to **this checkout's source** and re-runs the installer against the **same** HOME. This rehearses the real deployment path — *current live release → the build we're about to ship* — so that when this source is eventually published, upgrading onto an existing install is proven not to break. Asserts the re-install-over-existing-state stayed clean: exactly one `sumo-qa` MCP entry per host, no dangling skill symlinks, all five console-script entry points present, and `tools/list` (from the upgraded host config) is still a superset of the committed snapshot. This is the upgrade transition [`install-smoke.yml`](../.github/workflows/install-smoke.yml) can't see — that workflow always starts from a fresh, empty HOME. The baseline defaults to the current latest PyPI release (resolved at runtime); a `workflow_dispatch` input can override it with a specific published version to rehearse a particular upgrade path. There is **no** version-ordering check — the local checkout has no real version until release-please assigns one, so the delta under test is the code, not a version number. First matrix is Linux + macOS (the upgrade-cleanup logic in `installer.py` is OS-independent; Windows clean-install paths are already covered by `install-smoke.yml`). (06:30 UTC.)

### Interpreting an external-skills-smoke run

| Outcome | Meaning | Action |
|---|---|---|
| GREEN, pytest reports `1 passed` | Upstream CLI reachable; the MCP-owned shape contract (keys present, non-empty `raw_output`, ANSI stripped) still holds. | None. |
| RED in the `Verify npx is on PATH` step | `actions/setup-node` regressed or its cache is corrupt. | Bump the action version or pin a different `node-version`. Not an `external_skills.py` bug. |
| RED in the `Run external Skills CLI smoke` step | Genuine MCP-shape regression: the CLI returned, but the wrapper in `sumo_qa.external_skills` dropped a key, leaked an ANSI sequence into `raw_output`, or returned empty text. | Fix in `src/sumo_qa/external_skills.py`; the failing assertions in the test name the broken contract. Do **not** loosen the assertions — they're the only thing standing between us and silent upstream-format coupling. |
| RED in the `Fail if smoke was skipped` step | The test self-skipped via `pytest.skip(...)`. Because the workflow's earlier `Verify npx is on PATH` step rules out `NodeNotFoundError`, the only paths to a skip here are the CLI timing out or the CLI exiting nonzero — both surfaced as `ExternalSkillCLIError`. Skips are deliberately elevated to failures so a permanent silent skip (e.g. the upstream `skills find` command renamed) cannot defeat the workflow's purpose. | Read the `SKIPPED` line in the pytest log (the `-rs` flag prints the reason). A `timed out after Ns` reason is likely transient — re-run the workflow. A `skills CLI exited N` reason is real upstream drift — inspect `npx skills find mypy` locally and adjust `src/sumo_qa/external_skills.py` if the CLI's contract changed. |

To trigger the workflow on demand (e.g. before bumping the
`sumo_qa.external_skills` wrapper): GitHub → Actions →
`external-skills-smoke` → **Run workflow**.

### Interpreting an upgrade-smoke run

| Outcome | Meaning | Action |
|---|---|---|
| GREEN | A real PyPI release installed cleanly into a temp HOME, the source build upgraded over the same HOME, and the post-upgrade host config is duplicate-free with no dangling skill symlinks. | None. |
| RED in `Resolve published baseline` | PyPI was unreachable, or a `workflow_dispatch` `previous_version` override named a version that isn't a published release. | Re-run if PyPI was transiently down; if overriding, pass a version that exists on PyPI (omit the input to use the current latest automatically). |
| RED in `Pre-upgrade install` | The currently-published release no longer installs cleanly on the runner Python (e.g. a dependency it pinned has yanked a compatible wheel). | This is published-release rot in the live version, not a source regression — usually transient or a dependency-pin issue worth a follow-up; it does not block the source under test. |
| RED in `Post-upgrade install` with a duplicate-entry / dangling-symlink failure | A genuine upgrade regression: re-running the installer over an existing HOME left a duplicate `sumo-qa` MCP entry, leaked the legacy `mcpServers` key into VS Code, or left a broken skill symlink. Clean-install CI can't catch this. | Fix the cleanup logic in `installer.py` (`_install_claude_code_skills_per_dir` for symlinks, `_setup_claude_code` / `_setup_vscode_copilot` for the single-entry write). The failure message names the broken assertion. Add a unit case to `tests/test_installer_idempotency.py`. |
| RED in `Post-upgrade entry points` or `tools/list superset contract` | The upgraded build dropped a console-script wrapper or a pinned tool. | Same root cause as the equivalent `install-smoke.yml` failures — fix `pyproject.toml` entry points / the tool registration, regenerate the snapshot with `scripts/regen_tools_list_snapshot.py` only if the removal is deliberate. |
| `::warning` "Skill-pack drift" annotation (still GREEN) | A skill present in the previous release is absent (removed/renamed) in source. Not a failure — a legitimate release decision — but surfaced so it can't ship silently. | Confirm the removal is intended and call it out in the release notes. |

To trigger on demand (e.g. before a release, or to validate an
installer change): GitHub → Actions → `upgrade-smoke` → **Run workflow**.
By default it upgrades from the current latest PyPI release; optionally set
`previous_version` to rehearse the upgrade from a specific published version.

## Staging a candidate to the private staging repo

Before a production release, a candidate build can be published to the
**private** staging repo [`sumithr/sumo-qa-staging`](https://github.com/sumithr/sumo-qa-staging)
so project collaborators can `pip install` and smoke-test it with the exact
artifact shape end-users consume — entry points, dependency metadata, the MCP
`initialize`/`tools/list` handshake — **without** exposing a dev build on public
PyPI. Because `sumo-qa` is a public repo, TestPyPI / PyPI / public-repo release
assets are all world-readable; a separate **private** repo is what restricts the
candidate to collaborators. This is the
[`.github/workflows/staging-publish.yml`](../.github/workflows/staging-publish.yml)
workflow: it builds the wheel + sdist and creates a GitHub Release (carrying
those artifacts) in the private staging repo.

### How it stays fork-PR-safe

- **Trigger is `workflow_dispatch` only.** There is deliberately no
  `pull_request`, `pull_request_target`, or `push` trigger, so untrusted
  fork-PR code can never start it or reach the publish token, and the ref it
  builds is always one a maintainer (write access required to dispatch)
  selected.
- **Publishing runs in the `staging` GitHub Environment.** Deployment
  protection rules (required reviewers / allowed branches) are configured in
  repo settings, not in the workflow file.
- **Narrow cross-repo token.** The release is created with a fine-grained PAT
  (`STAGING_PUBLISH_TOKEN`) scoped to `contents: write` on `sumo-qa-staging`
  ONLY — never the default `GITHUB_TOKEN` (which cannot write another repo) and
  never a broadly-scoped token. It is only readable by the protected publish
  job.

### One-time maintainer setup (cannot be done from a PR branch)

These are GitHub-side settings an admin configures once; the workflow assumes
they exist:

1. **The private staging repo** `sumithr/sumo-qa-staging` exists (private).
   Grant the project's developers **collaborator** access to it — that
   collaborator list *is* the access-control boundary for staged builds.
2. **Create a fine-grained PAT** with **Repository access → only
   `sumo-qa-staging`** and **Contents: Read and write**, then add it to the
   `sumo-qa` repo as the secret **`STAGING_PUBLISH_TOKEN`** (Settings → Secrets
   and variables → Actions, scoped to the `staging` environment).
3. **Create the `staging` Environment** in `sumo-qa` repo settings
   (Settings → Environments) and add deployment protection — required reviewers
   and/or an allowed-branches rule — so a dispatch still gates on a human before
   it publishes.

### Triggering it and installing the staged build

1. GitHub → **Actions** → `staging-publish` → **Run workflow**. Optionally set
   the `ref` input to a branch, tag, or SHA (defaults to the dispatch ref).
2. The build job rewrites the static `pyproject.toml` version to a unique
   `<version>.dev<run_number>` PEP 440 dev release so each staged build gets its
   own release tag (`v<version>.dev<run_number>`).
3. The run summary prints the package name, the version, the staging repo, the
   release tag, and the exact install command. Collaborators install it in a
   clean virtualenv:

   ```bash
   gh release download v<version>.dev<run_number> \
     --repo sumithr/sumo-qa-staging --pattern '*.whl'
   pip install ./sumo_qa-<version>.dev<run_number>-py3-none-any.whl
   ```

4. Then verify the artifact: `sumo-qa-doctor`, and an MCP `initialize` +
   `tools/list` round-trip (see [docs/INSTALL.md](INSTALL.md)).

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
