# Phase 3 — Mutation Baseline + TDM Freshness QA Plan

> **For agentic execution:** Use `sumo-qa-executing-qa-rollout` to dispatch this plan task-by-task with two-stage review. Tasks use checkbox (`- [ ]`) syntax for tracking. Tasks marked `[parallel]` can be dispatched concurrently after their `blocks` dependency completes; `[sequential]` tasks must run alone.

**Strategy reference:** [`docs/qa-strategy.md`](../../qa-strategy.md). This plan implements Phase 3 (items 7–8) of that strategy.

**Goal:** Establish a mutation-testing baseline on the four parser/decision modules (`knowledge_loaders.py`, `rules.py`, `standards.py`, `tdm_validation.py`) with a CI nightly job + score-floor gate, and add a scheduled TDM URL freshness check that opens issues for non-2xx responses. Per-module survivor strengthening is **deferred to a Phase 3.5 follow-up** — Phase 3's closure is "baseline captured + CI floor at baseline" rather than "score ≥ 75%". Honest about what's achievable in one PR; the Phase 3.5 plan is data-driven on the baseline numbers T2 reveals.

**Branch:** `feat/phase3-mutation-baseline-tdm-freshness` off `main`. One PR into main.

**Approach mix:**
- T1, T3, T4 — infrastructure-change (mutmut config, CI workflows)
- T2 — verify-existing (baseline data capture; the existing test suite is the input — mutmut measures whether it kills mutations, no test changes)

**Files touched:**

New:
- `.github/workflows/mutation.yml` (T3) — nightly mutmut run + score-floor gate
- `.github/workflows/tdm-freshness.yml` (T4) — weekly TDM URL freshness check
- `scripts/check_tdm_freshness.py` (T4) — Python helper invoked by the workflow
- `docs/qa/runs/2026-05-14-phase3-mutation-baseline.md` (T2) — per-module baseline mutation scores (becomes the CI floor)
- `mutmut-baseline.json` (T2) — machine-readable per-module baseline (or commit `.mutmut-cache`; format decided in T2)

Modified:
- `pyproject.toml` (T1) — add `mutmut>=3,<4` to `[project.optional-dependencies].dev`; add `[tool.mutmut]` config block targeting only the 4 parser modules
- `uv.lock` (T1) — auto-regenerated

**Production code:** untouched. **Test code:** untouched (no new tests in Phase 3 — survivor strengthening is Phase 3.5).

**Risks covered (anchored):**
- **R-MUT-DRIFT** — without a baseline + nightly mutmut run, assertion strength can silently degrade as the codebase changes (a refactor that introduces an equivalent class of mutants would otherwise go unnoticed). Captured by T1+T2+T3.
- **R-TDM-STALE** — known-good test-data entries in `knowledge/test_data/<domain>/known_good.yaml` reference URLs that may rot over time. Validators currently don't call downstream APIs (per `docs/TOOLS.md`). Captured by T4.

**Phase 3 closure gate:** mutmut runs cleanly + per-module baseline recorded + CI fails on score drop below baseline + TDM freshness workflow scheduled and has run at least once. The 75% per-module mutation-score target from the strategy moves to a Phase 3.5 follow-up if baseline is below.

---

### Task 1 — Install + configure mutmut `[parallel]`

**Approach:** infrastructure-change
**Risk covered:** prerequisite for T2 (mutmut must be installed + configured before baseline run)
**Blocks:** T2

**Files:**
- Edit: `pyproject.toml` — add `"mutmut>=3,<4"` to `[project.optional-dependencies].dev`. Add a new `[tool.mutmut]` section configuring mutmut to target only the 4 parser modules.

**Recommended `[tool.mutmut]` config:**

```toml
[tool.mutmut]
paths_to_mutate = "src/sumo_qa/knowledge_loaders.py,src/sumo_qa/rules.py,src/sumo_qa/standards.py,src/sumo_qa/tdm_validation.py"
runner = "uv run pytest -x -q --no-cov"
tests_dir = "tests/"
# Skip `# pragma: no mutate` lines and `if TYPE_CHECKING:` blocks via mutmut defaults.
```

Notes for the implementer:
- The `--no-cov` flag is critical: mutmut already wraps pytest, so the project's `--cov-fail-under=100` addopts would fail every mutation run (mutated code reduces coverage). `--no-cov` bypasses the gate; coverage is enforced by the regular `tests` workflow, not the mutation workflow.
- `-x` (stop after first failure) speeds mutmut significantly — one failure is enough to kill a mutant.
- Targeting only the 4 modules keeps the run tractable. Other modules (installer, server, tdm_*) aren't included in this Phase 3 baseline.

**Done when:**
- `uv run mutmut --help` works (mutmut installed).
- `uv run mutmut run --paths-to-mutate=src/sumo_qa/rules.py 2>&1 | head -20` produces a sensible early output (no config errors). Don't wait for it to complete; just confirm it starts.
- `uv run pytest -q` still passes at 100% coverage (the new dep + config didn't break anything).
- `uv run ruff check . && uv run ruff format --check .` clean.

- [ ] Step 1: Read `pyproject.toml` to find the right insertion points (the `dev` extras list + a sensible spot for `[tool.mutmut]`).
- [ ] Step 2: Add `"mutmut>=3,<4"` to `dev` extras. Match neighbour formatting.
- [ ] Step 3: Add `[tool.mutmut]` section with the config above (or as close as the latest mutmut version supports — verify the option names against `mutmut --help` output).
- [ ] Step 4: `uv sync --all-extras` to install mutmut.
- [ ] Step 5: Verify `uv run mutmut --help` works.
- [ ] Step 6: Sanity-check: `uv run mutmut run --paths-to-mutate=src/sumo_qa/rules.py 2>&1 | head -30` — should start mutating without crashing on config. Kill it after a few seconds if it doesn't finish; you don't need a full run here.
- [ ] Step 7: `uv run pytest -q` still green at 100% coverage; ruff clean.

**Done when:** mutmut installed + configured; `mutmut --help` works; existing suite still green.

---

### Task 2 — Generate baseline mutation report `[sequential]`

**Approach:** verify-existing (mutmut measures the existing suite's assertion strength; no production or test changes)
**Risk covered:** R-MUT-DRIFT (provides the snapshot CI will gate against in T3)
**Blocked by:** T1
**Blocks:** T3

**Files:**
- Create: `docs/qa/runs/2026-05-14-phase3-mutation-baseline.md` — per-module mutation scores + survivor counts + commentary on which modules are above/below 75%
- Create: `mutmut-baseline.json` (or equivalent — see Step 3 below) — machine-readable per-module baseline T3 will read

**Done when:**
- `uv run mutmut run` has been run end-to-end against all 4 target modules (will take some time — 5-30 minutes depending on mutmut count).
- Per-module mutation score (killed / total) is recorded in the baseline doc.
- `mutmut-baseline.json` (or equivalent format mutmut emits) is committed so T3's CI workflow can compare against it.
- `uv run pytest -q` still green at 100% coverage (mutmut shouldn't have changed anything; sanity check).
- `uv run ruff check . && uv run ruff format --check .` clean.

- [ ] Step 1: `uv run mutmut run` (or `uv run mutmut run --paths-to-mutate=src/sumo_qa/knowledge_loaders.py,src/sumo_qa/rules.py,src/sumo_qa/standards.py,src/sumo_qa/tdm_validation.py` if the config block doesn't pick up). Wait for completion. May take 10-30 minutes; that's expected.
- [ ] Step 2: `uv run mutmut results` — capture the summary. Per-module breakdown via `uv run mutmut results --module <module>` if supported, OR `uv run mutmut show all` and parse per-file.
- [ ] Step 3: Convert the results into machine-readable form. Mutmut's cache is in `.mutmut-cache/` (SQLite) by default — that's not great for CI. Generate a JSON snapshot via `uv run mutmut results --json > mutmut-baseline.json` if supported, OR write a small inline Python script that reads the cache and emits `{module: {killed: N, total: N, score: 0.XX}}` JSON. Commit the JSON.
- [ ] Step 4: Write `docs/qa/runs/2026-05-14-phase3-mutation-baseline.md` with: per-module table (Module / Total mutants / Killed / Survived / Score / Above 75% threshold?), commentary on which modules need Phase 3.5 strengthening, link back to the strategy.
- [ ] Step 5: Re-run `uv run pytest -q` + ruff to confirm nothing regressed.

**Done when:** baseline doc + JSON committed; per-module scores recorded; suite + lint still green.

---

### Task 3 — Mutmut nightly CI workflow + score-floor gate `[sequential]`

**Approach:** infrastructure-change
**Risk covered:** R-MUT-DRIFT (CI catches assertion-strength regressions over time)
**Blocked by:** T2 (needs the baseline JSON to know what floor to enforce)

**Files:**
- Create: `.github/workflows/mutation.yml`

**Done when:**
- The workflow runs on a nightly cron (e.g. `0 5 * * *` — 05:00 UTC) and on manual `workflow_dispatch`.
- It does NOT run on every push (mutmut is too slow for per-push CI).
- It runs `uv run mutmut run` against the 4 target modules.
- It compares the new score against `mutmut-baseline.json` and FAILS the workflow if any module's score drops below its baseline.
- It uploads the mutation-cache as an artifact for debugging if it fails.
- A first manual `workflow_dispatch` run completes without false-failure.

- [ ] Step 1: Read the existing `.github/workflows/test.yml` for the shape conventions (uv setup, Python install, sync deps).
- [ ] Step 2: Write `.github/workflows/mutation.yml` with: `name: mutation`, `on: schedule + workflow_dispatch`, single `runs-on: ubuntu-latest` job. Steps: checkout → install uv → setup Python 3.13 → `uv sync --all-extras` → `uv run mutmut run` → compare against `mutmut-baseline.json` with a small inline Python check that fails the job if any module's score dropped.
- [ ] Step 3: Push the branch; trigger a manual `workflow_dispatch` run via `gh workflow run mutation.yml`. Wait for completion.
- [ ] Step 4: Confirm the run completes and produces no false failures (the score should match the baseline since T2's data IS the baseline).
- [ ] Step 5: If the run reveals an issue (mutmut behaves differently in CI vs local — e.g. nondeterministic mutation IDs), surface it; don't paper over.

**Done when:** workflow file exists; manual run completes successfully; no false failures.

---

### Task 4 — TDM URL freshness scheduled GHA `[parallel]`

**Approach:** infrastructure-change + new helper script
**Risk covered:** R-TDM-STALE
**Blocked by:** none (independent of mutmut chain)

**Files:**
- Create: `scripts/check_tdm_freshness.py` — Python script that walks `knowledge/test_data/*/known_good.yaml`, extracts every URL field, HEAD-requests each, and exits non-zero if any returns non-2xx (with detail printed).
- Create: `.github/workflows/tdm-freshness.yml` — weekly cron (e.g. Monday 06:00 UTC) + `workflow_dispatch`. Runs the script. On non-zero exit, opens a GitHub issue tagged `tdm-freshness` with the failing URLs.

**Done when:**
- `uv run python scripts/check_tdm_freshness.py` works locally and exits 0 if all known-good URLs are reachable (or honestly reports which ones aren't — accept that some may fail today; that's the whole point of the check).
- The workflow file is well-formed YAML.
- A manual `workflow_dispatch` run completes (success or fails-then-opens-issue both count).
- `uv run pytest -q` still green at 100% coverage; ruff clean.

- [ ] Step 1: Read 1-2 existing `knowledge/test_data/<domain>/known_good.yaml` files to understand the schema. Find the URL field name(s).
- [ ] Step 2: Write `scripts/check_tdm_freshness.py`. Use only stdlib if possible (`urllib.request`) to avoid adding `requests` as a runtime dep. Walk the test-data dir, extract URLs, HEAD each, collect non-2xx results, print a summary, exit 0 or non-zero accordingly.
- [ ] Step 3: Run locally: `uv run python scripts/check_tdm_freshness.py`. Capture output.
- [ ] Step 4: Write `.github/workflows/tdm-freshness.yml`. Include `permissions: { issues: write, contents: read }` so the workflow can open issues. On non-zero exit from the script, use `gh issue create --label tdm-freshness --title "TDM URL freshness: N entries non-2xx" --body "..."` (or the `actions/github-script` action).
- [ ] Step 5: Push the branch; trigger `workflow_dispatch` via `gh workflow run tdm-freshness.yml`. Wait for completion.
- [ ] Step 6: Confirm the run either passes (all URLs OK) or fails AND opens an issue. Either is acceptable evidence of "the workflow works".

**Done when:** script + workflow exist; manual run completes; if URLs failed, the issue was opened.

---

## Phase 3 closure gate

All 4 tasks complete + branch in this state:

- `uv run pytest -q` exits 0; suite count unchanged from main (no new tests in Phase 3 — strengthening is Phase 3.5 work).
- `uv run pytest --cov=src/sumo_qa --cov-fail-under=100` exits 0 (coverage gate holds).
- `uv run ruff check . && uv run ruff format --check .` clean.
- `uv run mutmut --help` works (mutmut installed + configured).
- `mutmut-baseline.json` committed with per-module survivor counts.
- `docs/qa/runs/2026-05-14-phase3-mutation-baseline.md` records the baseline + commentary.
- `.github/workflows/mutation.yml` exists; one manual `workflow_dispatch` has completed.
- `.github/workflows/tdm-freshness.yml` exists; one manual `workflow_dispatch` has completed.

When all of the above hold, the PR is ready for review. After merge, route to `sumo-qa-finishing-qa-work` to capture evidence + draft the PR description + write `docs/qa/runs/2026-05-14-phase3-mutation-baseline-tdm-freshness.md`.

**Phase 3.5 follow-up** *(separate plan, only if needed)*: if T2's baseline shows any module with mutation score < 75%, plan an interactive `sumo-qa-strengthening-tests` session per affected module to triage survivors (suppress equivalents, write strengthening tests for real ones) until each module clears 75%. The CI floor in T3 ratchets up as strengthening lands.
