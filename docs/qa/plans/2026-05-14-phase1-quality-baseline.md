# Phase 1 — Quality Baseline QA Plan

> **For agentic execution:** Use `sumo-qa-executing-qa-rollout` to dispatch this plan task-by-task with two-stage review. Tasks use checkbox (`- [ ]`) syntax for tracking. Tasks marked `[parallel]` can be dispatched concurrently after their `blocks` dependency completes; `[sequential]` tasks must run alone.

**Strategy reference:** [`docs/qa-strategy.md`](../../qa-strategy.md). This plan implements Phase 1 of that strategy.

**Goal:** Land a clean code base, lift `installer.py` from 14% to 100% statement coverage with a strict pragma policy, harden CI with cross-OS + coverage-floor + SAST, document the repo-walk recipe, and add an end-to-end MCP smoke test — all on `feat/qaskills-integration-trial` as one PR.

**Branch:** All tasks land on `feat/qaskills-integration-trial`. The PR into `main` includes the install-fix (already on the branch as uncommitted edits to `installer.py`, the new `tests/test_installer_claude_code_mcp.py`, and `docs/INSTALL.md`), plus the strategy doc itself, plus all 12 Phase 1 deliverables.

**Approach mix:**
- T1 — verify-existing (mechanical deletion verified by full suite)
- T2 — coverage-first-then-refactor + docs-change (rewrite skill content; conformance test pins behaviour)
- T3–T6 — strengthen-test-coverage (raise-coverage on `installer.py`; production code unchanged)
- T7, T8, T12 — infrastructure-change (CI YAML edits)
- T9 — docs-change + tdd-scaffold (new knowledge file + new structural test + skill edit)
- T10 — tdd-scaffold (new e2e test for existing behaviour)
- T11 — docs-change (new policy doc)

**Files touched (full list):**

Deletes (T1):
- `src/sumo_qa/qaskills.py`, `src/sumo_qa/node_install.py`
- `tests/test_qaskills_shim.py`, `tests/test_qaskills_local_check.py`, `tests/test_qaskills_server_tools.py`, `tests/test_node_install.py`
- `tests/fixtures/qaskills_search_playwright.txt`, `tests/fixtures/qaskills_info_playwright_e2e.txt`

Edits:
- `src/sumo_qa/server.py` (T1: drop import + `_register_qaskills_tools` + its call)
- `tests/test_server.py` (T1: drop qaskills tool name assertions)
- `skills/sumo-qa-suggesting-external-skill/SKILL.md` (T2: rewrite to find-skills/skills.sh Bash flow)
- `tests/test_qa_suggesting_external_skill_conformance.py` (T2: re-target conformance assertions)
- `skills/sumo-qa-deciding-approach/SKILL.md` (T2: clean qaskills fallback paragraph)
- `README.md` (T2: rewrite "qaskills.sh integration" section + tool count)
- `docs/INSTALL.md` (T2: tool count claim if mentioned)
- `docs/TOOLS.md` (T2: tool count + external-skill section)
- `docs/ARCHITECTURE.md` (T2: tool count if mentioned)
- `.github/workflows/test.yml` (T7: add `windows-latest`; T12: add `--cov-fail-under=100`)
- `skills/sumo-qa-strategising/SKILL.md` (T9: extend step 1 to ref `knowledge/repo_walk.md`)
- `pyproject.toml` (T12: pytest addopts if coverage gate lives there instead of in workflow)

New files:
- `tests/test_installer_vscode.py` (T3)
- `tests/test_installer_jetbrains.py` (T4)
- `tests/test_installer_idempotency.py` (T5)
- `tests/test_installer_mcp_binary.py` (T6)
- `.github/workflows/codeql.yml` (T8)
- `knowledge/repo_walk.md` (T9)
- `tests/test_repo_walk_recipe.py` (T9)
- `tests/test_e2e_mcp_initialize.py` (T10)
- `docs/COVERAGE.md` (T11)

**Risks covered (anchored):**
- **R-DEAD** — `src/sumo_qa/qaskills.py`, `src/sumo_qa/node_install.py` and ~660 LOC of supporting tests are unused after the prior pivot to Bash-driven SKILL.md. They confuse maintainers, inflate coverage denominators inaccurately, and the qaskills MCP tool registrations in `server.py:336-` shadow what the new design promises.
- **R-EXTSKILL** — `skills/sumo-qa-suggesting-external-skill/SKILL.md` references the qaskills CLI + MCP tools deleted in T1; without rewriting it, sumo-qa would route users into a broken external-skill flow.
- **R-INSTALLER** — `installer.py` is at 14% coverage (237 of 276 stmts untested). The Claude Code MCP-registry gap fixed in this branch is the prototype bug; analogous gaps almost certainly exist in `_setup_vscode_copilot` (line 446), `_setup_intellij` (line 544), and `_install_mcp_binary` (line 218).
- **R-WIN** — README claims Windows is supported; CI has only `ubuntu-latest` + `macos-latest`. Windows-only path-handling bugs would slip through.
- **R-COVDRIFT** — without a coverage floor in CI, any future installer.py-style 14%-coverage module can land silently.
- **R-SEC** — no SAST or supply-chain alerting despite shipping a binary to PyPI.
- **R-SKILLDRIFT** — skill ↔ MCP tool ↔ knowledge file references are checked only by humans; T2's deletion + rewrite is a one-time fix, not a guard.
- **R-RECIPEDRIFT** — `sumo-qa-strategising` runs gather inventory by per-Claude-session judgment, not a fixed recipe; future runs may collect different data and reach different conclusions on the same repo state.
- **R-MCPSTART** — no test proves the published `sumo-qa` binary actually responds to JSON-RPC initialize; `installer._verify_mcp_responds` is a one-shot install check, not a permanent guard.
- **R-PRAGMASPAM** — adopting `--cov-fail-under=100` without a pragma policy invites `# pragma: no cover` to spread as a dumping ground.

---

### Task 1 — Dead-code purge `[sequential]`

**Approach:** verify-existing
**Risk covered:** R-DEAD
**Blocks:** T2, T3, T4, T5, T6, T7, T8, T9, T10, T11, T12 (suite must be green and tool surface stable before any other Phase 1 task touches things)

**Files:**
- Delete: `src/sumo_qa/qaskills.py`, `src/sumo_qa/node_install.py`, `tests/test_qaskills_shim.py`, `tests/test_qaskills_local_check.py`, `tests/test_qaskills_server_tools.py`, `tests/test_node_install.py`, `tests/fixtures/qaskills_search_playwright.txt`, `tests/fixtures/qaskills_info_playwright_e2e.txt`
- Edit: `src/sumo_qa/server.py` (remove `from sumo_qa import node_install, qaskills` import line; remove the `_register_qaskills_tools` function; remove its call site; remove `_HINT_QASKILLS_CLI` constant)
- Edit: `tests/test_server.py` (remove qaskills tool name assertions; the registered tool count drops by 8)

- [ ] Step 1: Read `src/sumo_qa/server.py` lines 1-60 + the `_register_qaskills_tools` function block (line 336 onwards) to confirm removal scope.
- [ ] Step 2: Delete the 8 files listed above.
- [ ] Step 3: Edit `server.py` — drop the import + the `_register_qaskills_tools` function definition + its call + the `_HINT_QASKILLS_CLI` constant.
- [ ] Step 4: Edit `tests/test_server.py` — drop any assertions naming the 8 deleted qaskills tools (`sumo_qa_search_external_skills`, `sumo_qa_get_external_skill_info`, `sumo_qa_install_external_skill`, `sumo_qa_check_external_skill_installed`, `sumo_qa_load_external_skills_registry`, `sumo_qa_check_node_available`, `sumo_qa_install_node`, `sumo_qa_detect_node_installer`); update any expected tool count.
- [ ] Step 5: Run `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`. Surface output verbatim.

**Done when:** `git grep -E "qaskills|node_install|sumo_qa_(search|install|check|detect|get|load)_external|sumo_qa_(check|install)_node"` returns zero matches under `src/` and `tests/`; full suite green; lint clean.

---

### Task 2 — Rewrite `sumo-qa-suggesting-external-skill` SKILL.md to find-skills flow `[sequential]`

**Approach:** coverage-first-then-refactor (skill content rewrite, conformance test pins)
**Risk covered:** R-EXTSKILL
**Blocked by:** T1
**Blocks:** none — independent of T3–T11 once T1 lands

**Files:**
- Edit: `skills/sumo-qa-suggesting-external-skill/SKILL.md` — rewrite to drive the [find-skills](https://github.com/vercel-labs/skills) meta-skill via Bash, gating install on `[y/N]`. No companion MCP tools (sumo-qa stays one MCP server). Reference [skills.sh](https://www.skills.sh/) as the registry.
- Edit: `tests/test_qa_suggesting_external_skill_conformance.py` — drop `test_skill_gates_on_trusted_publishers` (no publisher-trust gate any more); add `test_skill_targets_skills_sh_registry`, `test_skill_documents_find_skills_install_command_verbatim` (asserts `github.com/vercel-labs/skills` and `--skill find-skills`), `test_skill_gates_find_skills_install_on_user_confirmation`, `test_skill_explicitly_rejects_companion_python_shims`.
- Edit: `skills/sumo-qa-deciding-approach/SKILL.md` — rewrite the "qaskills.sh fallback" paragraph to reference skills.sh / find-skills with no qaskills mention.
- Edit: `README.md` — rewrite the `## qaskills.sh integration` section to describe the find-skills/skills.sh Bash flow and the design rationale (single MCP server, no CLI-wrapper companions). Update tool count to **25** (was 33).
- Edit: `docs/INSTALL.md` — change "33 tools" → "25 tools" wherever it appears.
- Edit: `docs/TOOLS.md` — change "33 entry points" → "25 entry points"; replace the `## qaskills / Node-install tools (8)` section with `## External-skill discovery (no MCP entry points)` explaining the Bash-driven design.
- Edit: `docs/ARCHITECTURE.md` — change "33 tools" → "25 tools" if it appears; add a note about external-skill discovery being SKILL-driven.

- [ ] Step 1: Read the current `skills/sumo-qa-suggesting-external-skill/SKILL.md` to preserve the Iron-Law / Red-Flags structure shape.
- [ ] Step 2: Verify with one `npx --yes skills add --help` (or web-search if uncertain) that `https://github.com/vercel-labs/skills` is current and the `--skill find-skills -a claude-code -y` flag set hasn't drifted. Cite the exact install command verbatim in the SKILL.
- [ ] Step 3: Rewrite SKILL.md: Iron Law (no install without `[y/N]`), step 2 Node availability check via `which npx`, step 4 install find-skills via `npx --yes skills add https://github.com/vercel-labs/skills --skill find-skills -a claude-code -y`, step 5 hand off to find-skills via the Skill tool.
- [ ] Step 4: Update conformance tests per the file list above.
- [ ] Step 5: Update `sumo-qa-deciding-approach/SKILL.md` fallback paragraph + README + INSTALL + TOOLS + ARCHITECTURE per file list.
- [ ] Step 6: Run `uv run pytest -q` — must be green.
- [ ] Step 7: `git grep -E "qaskills|@qaskills/cli"` — must return zero matches under `skills/`, `docs/`, `README.md` (matches in `docs/superpowers/specs/` historical files are acceptable).

**Done when:** SKILL.md drives the find-skills flow with no qaskills CLI references; conformance suite green; tool count is "25" everywhere a count appears in shipped docs.

---

### Task 3 — VS Code installer tests `[parallel]`

**Approach:** strengthen-test-coverage
**Risk covered:** R-INSTALLER (VS Code branch)
**Blocked by:** T1

**Files:**
- Create: `tests/test_installer_vscode.py`
- Touch: none (production stays unchanged)

- [ ] Step 1: Read `src/sumo_qa/installer.py:446-543` (the `_setup_vscode_copilot` function body) and `tests/test_installer_claude_code_mcp.py` to copy the mock + `tmp_path` pattern.
- [ ] Step 2: Write tests covering: (a) `not detected on this machine` when no `.vscode/` and no `.git/` exists in workspace, (b) `--workspace` flag honoured over CWD, (c) writes `<workspace>/.vscode/mcp.json` with the `servers` schema (NOT `mcpServers`), (d) preserves any existing keys in `mcp.json`, (e) JSON parse failure on existing file produces a graceful error message including the absolute path.
- [ ] Step 3: Run `uv run pytest tests/test_installer_vscode.py -v`. Surface output.
- [ ] Step 4: Run `uv run pytest --cov=src/sumo_qa.installer --cov-report=term-missing -q` and confirm `_setup_vscode_copilot` lines are now covered.

**Done when:** ≥ 5 tests in the new file; all pass; `_setup_vscode_copilot` shows zero "missing" lines in the coverage report (exclusions captured via `# pragma: no cover` only for platform-specific branches per `docs/COVERAGE.md`).

---

### Task 4 — JetBrains installer tests `[parallel]`

**Approach:** strengthen-test-coverage
**Risk covered:** R-INSTALLER (JetBrains branch)
**Blocked by:** T1

**Files:**
- Create: `tests/test_installer_jetbrains.py`
- Touch: none

- [ ] Step 1: Read `src/sumo_qa/installer.py:544-613` (`_setup_intellij`) and pattern-match against `test_installer_claude_code_mcp.py`.
- [ ] Step 2: Write tests covering: (a) prints the Settings-UI fields with the correct absolute binary path, (b) prints the Junie JSON snippet with the `mcpServers` schema (NOT `servers` — Junie uses Claude Desktop's schema), (c) handles missing JetBrains install detection gracefully (no crash, returns informational HostResult), (d) detects across `~/Library/Application Support/JetBrains/` (Darwin), `%APPDATA%/JetBrains/` (Windows), `~/.config/JetBrains/` (Linux).
- [ ] Step 3: Run `uv run pytest tests/test_installer_jetbrains.py -v`. Surface output.
- [ ] Step 4: Verify `_setup_intellij` is fully covered.

**Done when:** ≥ 4 tests; all pass; `_setup_intellij` zero "missing" lines.

---

### Task 5 — Installer idempotency tests `[parallel]`

**Approach:** strengthen-test-coverage
**Risk covered:** R-INSTALLER (re-run safety)
**Blocked by:** T1

**Files:**
- Create: `tests/test_installer_idempotency.py`
- Touch: none

- [ ] Step 1: Re-read `_setup_claude_code` (line 271), `_register_claude_code_mcp` (line 337), `_install_claude_code_skills_per_dir` (line 369).
- [ ] Step 2: Write tests covering: (a) running `_setup_claude_code` twice in a row leaves `claude_desktop_config.json` with exactly one `sumo-qa` entry (not two), (b) `_register_claude_code_mcp` runs `claude mcp remove` then `claude mcp add` on every invocation (already covered for happy path in `test_installer_claude_code_mcp.py:test_register_runs_remove_then_add_with_user_scope`; add: re-run after success — second invocation behaves identically and returns a fresh "registered" message), (c) `_install_claude_code_skills_per_dir` cleans up the legacy wrapper symlink + stale top-level entries on every run, (d) running the full installer twice doesn't accumulate broken symlinks.
- [ ] Step 3: Run `uv run pytest tests/test_installer_idempotency.py -v`.

**Done when:** ≥ 4 tests; all pass; the existing `test_installer_claude_code_mcp.py` is not duplicated (these tests are *additional* idempotency-shape coverage).

---

### Task 6 — Path-detection tests for `_install_mcp_binary` `[parallel]`

**Approach:** strengthen-test-coverage
**Risk covered:** R-INSTALLER (binary discovery)
**Blocked by:** T1

**Files:**
- Create: `tests/test_installer_mcp_binary.py`
- Touch: none

- [ ] Step 1: Read `src/sumo_qa/installer.py:218-269` (`_install_mcp_binary`) — fast-path (binary on PATH), uv-fallback path, conventional-bin fallback (~/.local/bin, ~/.local/share/uv/tools/), missing-uv error path.
- [ ] Step 2: Write tests covering: (a) returns the resolved Path immediately when `shutil.which("sumo-qa")` returns a non-None path, (b) falls back to `uv tool install` when `which` returns None, (c) returns None and prints the "uv is not installed" hint when neither `sumo-qa` nor `uv` is on PATH, (d) returns the conventional `~/.local/bin/sumo-qa` path when uv install succeeds but `which` still misses, (e) returns None when uv install fails (subprocess raises CalledProcessError).
- [ ] Step 3: Run `uv run pytest tests/test_installer_mcp_binary.py -v`.

**Done when:** ≥ 5 tests; all pass; `_install_mcp_binary` zero "missing" lines (or only documented-pragma exclusions).

---

### Task 7 — Add `windows-latest` to test matrix `[parallel]`

**Approach:** infrastructure-change
**Risk covered:** R-WIN
**Blocked by:** T1

**Files:**
- Edit: `.github/workflows/test.yml`

- [ ] Step 1: Read `.github/workflows/test.yml:13-17` (the matrix block).
- [ ] Step 2: Change `os: [ubuntu-latest, macos-latest]` to `os: [ubuntu-latest, macos-latest, windows-latest]`.
- [ ] Step 3: Push the branch, observe the next CI run. If Windows-specific failures appear (likely candidates: path-separator assumptions, `shutil.which` returning `.exe`, `Path.home()` behaviour) — fix them in the production code (NOT the test) and re-push.
- [ ] Step 4: Confirm matrix shows 3 OS × 5 Python = 15 jobs; all green.

**Done when:** matrix expanded; all 15 jobs green on the next CI run.

---

### Task 8 — CodeQL workflow `[parallel]`

**Approach:** infrastructure-change
**Risk covered:** R-SEC
**Blocked by:** T1

**Files:**
- Create: `.github/workflows/codeql.yml`

- [ ] Step 1: Reference the GitHub-published CodeQL starter for Python.
- [ ] Step 2: Write the workflow with: language=`python`, triggers=`push` to feat/* + main + `pull_request` against main + scheduled `cron: '0 6 * * 1'` (weekly Monday 06:00 UTC), and the default `security-extended,security-and-quality` query suite.
- [ ] Step 3: Push; observe one full CodeQL run completes.
- [ ] Step 4: Triage any high-severity findings. Either fix or document a SARIF dismissal with rationale in the PR description.

**Done when:** workflow file exists; one full run has completed; zero "high" findings (or all triaged with documented rationale).

---

### Task 9 — Repo-walk recipe `[parallel]`

**Approach:** docs-change + tdd-scaffold
**Risk covered:** R-RECIPEDRIFT
**Blocked by:** T1

**Files:**
- Create: `knowledge/repo_walk.md` (the fixed inventory recipe)
- Create: `tests/test_repo_walk_recipe.py` (structural assertions)
- Edit: `skills/sumo-qa-strategising/SKILL.md` (extend step 1 of the Checklist to reference the recipe)

- [ ] Step 1: Write `knowledge/repo_walk.md` with sections: `## Inventory commands` (the exact `find`, `wc -l`, `pytest --co`, `pytest --cov` invocations to run), `## Data shape captured` (a table listing what to gather: top-level dirs, languages detected, test framework, CI matrix axes, pre-commit hook list, top-N coverage gaps), `## Output template` (the markdown table format for `## Inventory` in a strategy doc).
- [ ] Step 2: Write `tests/test_repo_walk_recipe.py` asserting: file exists at `knowledge/repo_walk.md`, contains the three required H2 sections, contains at least one fenced code block per section (so the commands are copy-paste runnable).
- [ ] Step 3: Edit `skills/sumo-qa-strategising/SKILL.md` step 1 of the Checklist: append "Use the recipe in `knowledge/repo_walk.md` to ensure consistent inventory data across runs."
- [ ] Step 4: Run `uv run pytest tests/test_repo_walk_recipe.py -v`.

**Done when:** all three files in their final shape; test green; strategising skill references the recipe by path.

---

### Task 10 — End-to-end MCP initialize test `[parallel]`

**Approach:** tdd-scaffold
**Risk covered:** R-MCPSTART
**Blocked by:** T1

**Files:**
- Create: `tests/test_e2e_mcp_initialize.py`
- Touch: none

- [ ] Step 1: Read `src/sumo_qa/installer.py:614-651` (`_verify_mcp_responds`) for the JSON-RPC initialize-handshake pattern to copy.
- [ ] Step 2: Read `src/sumo_qa/server.py` to count the registered tools (after T1's deletion). Capture this number as the expected count.
- [ ] Step 3: Write a test that: (a) spawns `sumo-qa` via `subprocess.Popen` with stdin/stdout pipes (or via `python -m sumo_qa.server` if the binary may not be on PATH in CI), (b) sends a JSON-RPC `initialize` request, asserts the response has `serverInfo.name == "sumo-qa"`, (c) sends `tools/list`, asserts the response includes the expected number of tools, (d) sends a graceful `shutdown` and waits for the process to exit cleanly (≤ 5s timeout).
- [ ] Step 4: Run `uv run pytest tests/test_e2e_mcp_initialize.py -v`. Test must complete in ≤ 5s.

**Done when:** test passes locally; survives a `pytest -q` run in the full suite without flake.

---

### Task 11 — `docs/COVERAGE.md` policy doc `[parallel]`

**Approach:** docs-change
**Risk covered:** R-PRAGMASPAM
**Blocked by:** T1

**Files:**
- Create: `docs/COVERAGE.md`

- [ ] Step 1: Write `docs/COVERAGE.md` with sections: `## Floor` (100% statement coverage enforced via `pytest --cov-fail-under=100`), `## Allowed pragmas` (defensive `sys.exit(1)` after Python-version / type-of-environment guards; platform-conditional branches that can't run on the current OS — one targeted pragma per branch, never wholesale; `if __name__ == "__main__":` guards), `## Disallowed pragmas` (covering up untested logic, suppressing flaky tests, "I'll come back to this later"), `## How to add a pragma` (PR description must justify per the allowed list; reviewer must agree), `## Running coverage locally` (`uv run pytest --cov=src/sumo_qa --cov-report=term-missing`), `## Lowering the floor` (requires a strategy document amendment + maintainer sign-off).
- [ ] Step 2: Add a line to `README.md` under `## Docs` linking `docs/COVERAGE.md`.

**Done when:** file exists with the sections above; linked from `README.md`.

---

### Task 12 — `--cov-fail-under=100` + verify clean `[sequential]`

**Approach:** infrastructure-change
**Risk covered:** R-COVDRIFT
**Blocked by:** T1, T2, T3, T4, T5, T6 (must run after the installer tests have actually lifted coverage)

**Files:**
- Edit: `.github/workflows/test.yml` (add `--cov-fail-under=100` and `--cov=src/sumo_qa` to the pytest invocation)
- Edit: `pyproject.toml` (or `pytest.ini`) — optional: bake the same args into `[tool.pytest.ini_options].addopts` so local runs match CI

- [ ] Step 1: Run `uv run pytest --cov=src/sumo_qa --cov-report=term-missing -q` locally.
- [ ] Step 2: For each remaining "missing" line: (a) write a test if it's reachable; (b) add `# pragma: no cover` with a brief inline comment justifying per `docs/COVERAGE.md` if it's a documented exception.
- [ ] Step 3: Re-run with `--cov-fail-under=100`. Confirm green.
- [ ] Step 4: Add `--cov=src/sumo_qa --cov-fail-under=100` to the pytest invocation in `.github/workflows/test.yml:34`.
- [ ] Step 5: Push; confirm all 15 CI jobs green.

**Done when:** local `uv run pytest --cov=src/sumo_qa --cov-fail-under=100` exits 0; CI matrix all green; every `# pragma: no cover` in the codebase has an inline comment matching one of the allowed cases in `docs/COVERAGE.md`.

---

## Phase 1 closure gate

All 12 tasks complete + branch in this state:

- `git grep -E "qaskills|@qaskills/cli"` returns zero matches under `src/`, `tests/`, `skills/`, `docs/` (excluding `docs/qa-strategy.md` and `docs/superpowers/`).
- `installer.py` shows ≥ 95% line coverage with documented pragmas, OR full 100%.
- `.github/workflows/test.yml` matrix is 3 OS × 5 Python = 15 jobs.
- `.github/workflows/codeql.yml` exists and one run has completed.
- `pytest --cov-fail-under=100` passes locally and in CI.
- `tests/test_e2e_mcp_initialize.py` is in the suite and passes.
- `knowledge/repo_walk.md`, `docs/COVERAGE.md`, `docs/qa-strategy.md` all on disk.
- `claude mcp list` after `pip install --upgrade sumo-qa && sumo-qa-install --claude-code` shows sumo-qa connected.

When all of the above hold, the PR is ready for review. After merge, route to `sumo-qa-finishing-qa-work` to capture evidence + draft the PR description + write the run summary at `docs/qa/runs/2026-05-14-phase1-quality-baseline.md`.
