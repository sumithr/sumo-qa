# Superpowers Restructure — Phase 4 (Heavy-Tool Deletion) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Delete the 6 heavy MCP tools, the 9 legacy `@mcp.prompt` decorators that surfaced them, and all supporting Python that exists only to feed the heavy single-shot path. After Phase 4, the only public MCP tool surface is the 4 test-data tools + 7 knowledge loaders (11 tools total). Only the 10 skill-derived MCP prompts remain.

**Architecture:** This is a deletion phase. No new code, no new tests. The new path (Phase 1 + 2) has been validated automatically (Phase 3 in-session); manual host verification is the user's responsibility post-Phase-4 since the heavy tools no longer exist to fall back to. The branch stays local for review before merging.

**Tech Stack:** None new. Python deletions, test removals, schema cleanups.

**Spec:** [`docs/superpowers/specs/2026-05-08-superpowers-restructure-design.md`](../specs/2026-05-08-superpowers-restructure-design.md)

**Branch:** `feat/superpowers-restructure` (continues from Phase 3, commit `3427efa`).

---

## File Structure

### Deleted

| Path | Reason |
|---|---|
| `src/sumo_qa/prompts.py` | SENIOR_QA_SYSTEM_PROMPT — discipline moves to skill markdown |
| `src/sumo_qa/approach_decision.py` | Deterministic decider |
| `src/sumo_qa/scaffolder.py` | Heavy scaffold tool |
| `src/sumo_qa/render_preview.py` | Rendered structured output |
| `src/sumo_qa/render_cli.py` | `sumo-qa-render` CLI for structured output |
| `src/sumo_qa/rubric.py` | 10-dim grader for structured output |
| `src/sumo_qa/specialty_routing.py` | Knowledge moved to `knowledge/specialty_tools.md` |
| `src/sumo_qa/classification.py` | Knowledge moved to `knowledge/classifications.md` |
| `src/sumo_qa/local_diff.py` | Review skill uses host file tools instead |
| `src/sumo_qa/evaluation.py` | Legacy AI-graded eval against structured output |
| `evaluation/` (entire directory) | Iteration harness for the old structured eval; superseded by skill-driven verification |

### Heavy slim-downs

| Path | Change |
|---|---|
| `src/sumo_qa/server.py` | Drop the 6 heavy tool registrations; drop the 9 legacy `@mcp.prompt` decorators; drop imports of deleted modules; drop `_attach_output_schemas` if it only serves heavy tools |
| `src/sumo_qa/tools.py` | Drop everything except test-data flows (the `qa_explain_test_data_requirements`, etc.) |
| `src/sumo_qa/models.py` | Drop heavy response models (`DecideApproachResponse`, `CreateTestPlanResponse`, etc.); keep only test-data models |
| `src/sumo_qa/llm.py` | Drop `HostSamplingClient` if only used by heavy tools; drop sampling-prompt construction |
| `src/sumo_qa/knowledge.py` | Drop everything except basic markdown reading (if anything is left after Phase 1 loader extraction) |
| `pyproject.toml` | Drop `sumo-qa-eval` and `sumo-qa-render` entry points |

### Tests deleted (heavy-path coverage)

| Path | Reason |
|---|---|
| `tests/test_approach_decision.py` | Tests deleted module |
| `tests/test_classification.py` | Tests deleted module |
| `tests/test_evaluation.py` | Tests deleted module |
| `tests/test_iteration_brief.py` | Tests deleted module |
| `tests/test_llm.py` | Tests deleted/slim module |
| `tests/test_local_diff.py` | Tests deleted module |
| `tests/test_prompts.py` | Tests deleted module |
| `tests/test_render_preview.py` | Tests deleted module |
| `tests/test_repo_scenarios.py` | Tests deleted evaluation harness |
| `tests/test_rubric.py` | Tests deleted module |
| `tests/test_scaffolder.py` | Tests deleted module |
| `tests/test_specialty_routing.py` | Tests deleted module |

### Tests slimmed (mixed coverage)

| Path | Change |
|---|---|
| `tests/test_server.py` | Drop heavy-tool sub-tests (`_HEAVY_QA_TOOL_NAMES` checks, schema/response_format iterations); keep knowledge-loader registration test |
| `tests/test_tools.py` | Drop heavy-flow tests; keep test-data tests |
| `tests/test_skill_prompts.py` | Drop legacy-prompt assertions; keep skill-prompt assertions |
| `tests/test_token_weight_regression.py` | Un-xfail the `test_create_test_plan_flow_stays_under_token_budget` — heavy path is gone so flow total = knowledge-loader sum, which is under budget |
| `tests/test_error_envelope.py` | Drop if it only covers heavy-tool error paths |
| `tests/test_standards.py` | Drop if it only covers structured pack consumption by heavy tools; keep file-loading tests |
| `tests/test_rules.py` | Drop if it only covers structured rule consumption by heavy tools; keep file-loading tests |
| `tests/test_debug_capture.py` | Keep; debug capture is used by knowledge loaders and skills |

### Kept as-is

- `src/sumo_qa/debug_capture.py`
- `src/sumo_qa/knowledge_loaders.py`
- `src/sumo_qa/skill_prompts.py`
- `src/sumo_qa/tdm_*.py` (test-data tools)
- All `knowledge/*.md`
- All `skills/*/SKILL.md`
- `tests/test_knowledge_loaders.py`
- `tests/test_skill_conformance.py`
- `tests/test_phase3_e2e_skill_path.py`
- `tests/test_tdm.py`

---

## Setup

### Task 0: Baseline

- [ ] **Step 0.1: Confirm starting state.**

```bash
git branch --show-current
uv run pytest 2>&1 | tail -3
```

Expected: branch `feat/superpowers-restructure`, 312 passed / 0 skipped / 2 xfailed.

---

## Group A: Strip server.py to the knowledge+test-data surface

### Task 1: Rewrite `server.py` to drop heavy tools + heavy prompts

**Files:**
- Modify: `src/sumo_qa/server.py`

Approach: Take the existing `build_mcp_server()` function and remove every section that registers a heavy tool, a heavy prompt, or imports a heavy module. Keep:

- The 7 knowledge loaders (`_register_knowledge_loaders`)
- The 4 test-data tools (`sumo_qa_explain_test_data_requirements`, etc.)
- `register_skills_as_prompts(mcp)` call
- The MCP server name + main() entry point

Drop:
- Tool registrations for `sumo_qa_decide_approach`, `sumo_qa_prepare_for_work`, `sumo_qa_create_test_plan`, `sumo_qa_review_local_change`, `sumo_qa_scaffold_tests`, `sumo_qa_answer_testing_question`
- All 9 hardcoded `@mcp.prompt` decorators
- Imports of `prompts.py`, `approach_decision.py`, `tools.QAShiftLeftService`, `models.*`, `llm.HostSamplingClient`, `render_preview.render_response`
- `_attach_output_schemas(mcp)` call (and the helper if it only serves heavy tools)
- `_OUTPUT_SCHEMA_MODELS` dict if it only references heavy tools
- `_HINT_*` hint constants that only reference heavy-tool error paths
- `_RESPONSE_FORMAT_FIELD`, `_format_response`, `_slim` references if they only serve heavy tools

- [ ] **Step 1.1: Read the current `src/sumo_qa/server.py` to understand its full shape.**

```bash
wc -l src/sumo_qa/server.py
grep -n "^def \|^class \|@mcp.tool\|@mcp.prompt\|from sumo_qa" src/sumo_qa/server.py
```

- [ ] **Step 1.2: Edit the file. Remove every heavy-tool registration block. Remove every legacy `@mcp.prompt` block. Remove unused imports. The resulting `build_mcp_server()` should be small enough that the file is under 250 lines.**

After editing, verify it imports cleanly:

```bash
uv run python -c "from sumo_qa.server import build_mcp_server; mcp = build_mcp_server(); print('tools:', sorted(mcp._tool_manager._tools.keys())); print('prompts:', sorted(mcp._prompt_manager._prompts.keys()))"
```

Expected: 11 tools (4 test-data + 7 knowledge loaders), 10 prompts (skill-derived).

- [ ] **Step 1.3: Run the test suite.**

```bash
uv run pytest 2>&1 | tail -10
```

Expected: many tests will fail because they reference the now-deleted heavy tools. That's intentional — Task 2 deletes the obsolete tests. For now, the loader-related tests, skill-conformance, skill-prompts, token-weight, phase3-e2e, and tdm tests MUST pass.

If imports break (`ImportError`), fix in `src/sumo_qa/server.py` until the new path imports cleanly.

- [ ] **Step 1.4: Commit (don't worry about other test failures yet — Task 2 handles them).**

```bash
git add src/sumo_qa/server.py
git commit -m "feat(server): remove 6 heavy tool registrations and 9 legacy MCP prompts"
```

---

## Group B: Delete obsolete source modules

### Task 2: Delete the heavy Python modules

**Files:**
- Delete: 11 files listed in the "Deleted" inventory above (excluding `evaluation/`)

- [ ] **Step 2.1: Delete the 9 source files.**

```bash
git rm src/sumo_qa/prompts.py \
       src/sumo_qa/approach_decision.py \
       src/sumo_qa/scaffolder.py \
       src/sumo_qa/render_preview.py \
       src/sumo_qa/render_cli.py \
       src/sumo_qa/rubric.py \
       src/sumo_qa/specialty_routing.py \
       src/sumo_qa/classification.py \
       src/sumo_qa/local_diff.py \
       src/sumo_qa/evaluation.py
```

- [ ] **Step 2.2: Delete the `evaluation/` directory (legacy AI-graded eval harness).**

```bash
git rm -r evaluation/
```

- [ ] **Step 2.3: Verify the MCP server still builds.**

```bash
uv run python -c "from sumo_qa.server import build_mcp_server; build_mcp_server()"
```

If this fails, the previous task missed an import. Fix `src/sumo_qa/server.py`.

- [ ] **Step 2.4: Commit.**

```bash
git commit -m "feat: delete 10 heavy-path source files (prompts/approach_decision/scaffolder/render_preview/render_cli/rubric/specialty_routing/classification/local_diff/evaluation) and the evaluation/ harness"
```

---

## Group C: Slim down hybrid modules

### Task 3: Trim `tools.py` to test-data flows only

**Files:**
- Modify: `src/sumo_qa/tools.py`

- [ ] **Step 3.1: Read the file. Identify which functions/classes only serve heavy tools.**

```bash
wc -l src/sumo_qa/tools.py
grep -n "^def \|^class \|^async def " src/sumo_qa/tools.py
```

- [ ] **Step 3.2: Edit. Keep only:**

- `QAShiftLeftService` class (but slim it to test-data methods only: `qa_explain_test_data_requirements`, `qa_find_test_data`, `qa_validate_test_data`, `qa_register_known_good_test_data`, plus `from_standards_path` factory if it's still needed by anything in `tools.py`)
- The `_slim` helper IF it's still used by the test-data methods (likely not — heavy outputs used `_slim`)
- The test-data-related imports

Drop:
- All `_build_*_sampling_prompt` builders
- The heavy classification/approach inference helpers
- `_apply_host_sampling`
- Heavy-flow methods (`qa_decide_approach`, `qa_create_test_plan`, etc.) and their async wrappers
- Imports that are no longer used

- [ ] **Step 3.3: Verify imports clean.**

```bash
uv run python -c "from sumo_qa.tools import QAShiftLeftService; print('OK')"
```

- [ ] **Step 3.4: Commit.**

```bash
git add src/sumo_qa/tools.py
git commit -m "feat(tools): slim to test-data flows only"
```

---

### Task 4: Trim `models.py` to test-data models

**Files:**
- Modify: `src/sumo_qa/models.py`

- [ ] **Step 4.1: Read the file.**

```bash
cat src/sumo_qa/models.py
```

- [ ] **Step 4.2: Delete the heavy response Pydantic models. Keep only what's imported by the surviving code (likely none — test-data models live in `tdm_models.py`).**

If `models.py` becomes empty or near-empty, delete the file entirely:

```bash
git rm src/sumo_qa/models.py
```

If anything remains, keep it.

- [ ] **Step 4.3: Verify imports clean.**

```bash
uv run python -c "from sumo_qa.server import build_mcp_server; build_mcp_server()"
```

- [ ] **Step 4.4: Commit.**

```bash
git add -A src/sumo_qa/models.py 2>/dev/null || true
git commit -m "feat(models): drop heavy response models (kept test-data models in tdm_models.py)"
```

If `models.py` was deleted, the commit message becomes: `feat(models): delete obsolete heavy response models`.

---

### Task 5: Trim `llm.py` (if anything's left)

**Files:**
- Modify: `src/sumo_qa/llm.py`

- [ ] **Step 5.1: Check what still uses anything in `llm.py`.**

```bash
grep -rn "from sumo_qa.llm\|sumo_qa import llm" src/ tests/
```

- [ ] **Step 5.2: If nothing uses it, delete it.**

```bash
git rm src/sumo_qa/llm.py
git commit -m "feat(llm): delete obsolete LLM sampling client (heavy-path only)"
```

If something still uses it, slim to just that.

---

### Task 6: Trim `knowledge.py` (if anything's left)

**Files:**
- Modify: `src/sumo_qa/knowledge.py`

- [ ] **Step 6.1: Check usage.**

```bash
grep -rn "from sumo_qa.knowledge\|sumo_qa import knowledge\|sumo_qa\.knowledge\." src/ tests/ | grep -v "knowledge_loaders"
```

- [ ] **Step 6.2: If unused or only carries obsolete code, delete it.**

```bash
git rm src/sumo_qa/knowledge.py
git commit -m "feat(knowledge): delete obsolete domain knowledge module"
```

---

## Group D: Delete obsolete tests

### Task 7: Delete tests that target deleted modules

- [ ] **Step 7.1: Delete the obvious ones.**

```bash
git rm tests/test_approach_decision.py \
       tests/test_classification.py \
       tests/test_evaluation.py \
       tests/test_iteration_brief.py \
       tests/test_llm.py \
       tests/test_local_diff.py \
       tests/test_prompts.py \
       tests/test_render_preview.py \
       tests/test_repo_scenarios.py \
       tests/test_rubric.py \
       tests/test_scaffolder.py \
       tests/test_specialty_routing.py
```

If any of these don't exist, that's fine.

- [ ] **Step 7.2: Run tests; check for additional ImportErrors.**

```bash
uv run pytest 2>&1 | tail -20
```

If any remaining test fails on `ImportError` for a deleted module, add it to the deletion list (it was a heavy-only test).

- [ ] **Step 7.3: Commit.**

```bash
git add -A tests/
git commit -m "test: delete tests for the 12 heavy-path source modules removed in Phase 4"
```

---

### Task 8: Slim mixed-coverage tests

**Files:**
- Modify: `tests/test_server.py`
- Modify: `tests/test_tools.py`
- Modify: `tests/test_skill_prompts.py`
- Modify: `tests/test_error_envelope.py`
- Modify: `tests/test_standards.py`
- Modify: `tests/test_rules.py`

For each file: read it, identify heavy-tool-specific tests (look for `_HEAVY_QA_TOOL_NAMES`, `_OUTPUT_SCHEMA_MODELS`, references to `sumo_qa_decide_approach` / `sumo_qa_create_test_plan` / etc.), delete those tests. Keep tests that exercise the surviving code paths (knowledge loaders, test-data tools, file IO).

- [ ] **Step 8.1: Edit each file. Delete heavy-only tests. Update `_HEAVY_QA_TOOL_NAMES` references — if a test uses the constant, either delete the test or replace the constant usage.**

- [ ] **Step 8.2: Run the suite. Confirm it's green.**

```bash
uv run pytest 2>&1 | tail -5
```

Expected: ~100-150 passed (down from 312 because we deleted ~12 test files; plus the slimmed files lose tests). 0 failed, 0 errored. Possibly some skips and the xfails.

If anything fails, the slim was too aggressive — restore deleted tests until green.

- [ ] **Step 8.3: Un-xfail the flow budget test.**

In `tests/test_token_weight_regression.py`, find the `@pytest.mark.xfail` decorator on `test_create_test_plan_flow_stays_under_token_budget` and DELETE the decorator line. The test should now pass (heavy path is gone, flow total is just knowledge loaders).

Run:
```bash
uv run pytest tests/test_token_weight_regression.py -v
```

Expected: 3 passed (was 2 passed + 2 xfailed; now the unfiltered-standards xfail might still apply, and the flow-budget test passes).

Actually re-check: the unfiltered standards xfail stays (Task 12 still deferred). So expected: 3 passed, 1 xfail (unfiltered standards/rules).

- [ ] **Step 8.4: Commit.**

```bash
git add -A tests/
git commit -m "test: slim heavy-tool tests; un-xfail create-test-plan flow budget"
```

---

## Group E: Update pyproject.toml

### Task 9: Remove obsolete entry points

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 9.1: Edit `[project.scripts]`. Remove `sumo-qa-eval = "sumo_qa.evaluation:main"` and `sumo-qa-render = "sumo_qa.render_cli:main"`. Keep `sumo-qa-mcp = "sumo_qa.server:main"`.**

After:
```toml
[project.scripts]
sumo-qa-mcp = "sumo_qa.server:main"
```

- [ ] **Step 9.2: Reinstall to confirm only `sumo-qa-mcp` is exposed.**

```bash
uv tool install --from . sumo-qa --reinstall 2>&1 | tail -5
```

Expected: "Installed 1 executable: sumo-qa-mcp" (was 3).

- [ ] **Step 9.3: Commit.**

```bash
git add pyproject.toml
git commit -m "build: drop obsolete sumo-qa-eval and sumo-qa-render entry points"
```

---

## Group F: Final verification

### Task 10: Phase 4 completion

- [ ] **Step 10.1: Full suite.**

```bash
uv run pytest 2>&1 | tail -3
```

Expected: ~100-150 passed, 0 failed, possibly 1 xfailed (unfiltered standards if Task 12 still deferred).

- [ ] **Step 10.2: Verify MCP server.**

```bash
sumo-qa-mcp --help 2>&1 | head -10
uv run python -c "
from sumo_qa.server import build_mcp_server
mcp = build_mcp_server()
print('tools:', len(mcp._tool_manager._tools))
print('prompts:', len(mcp._prompt_manager._prompts))
print('tools list:', sorted(mcp._tool_manager._tools.keys()))
print('prompts list:', sorted(mcp._prompt_manager._prompts.keys()))
"
```

Expected: 11 tools (4 test-data + 7 loaders), 10 prompts (skill-derived).

- [ ] **Step 10.3: Verify no heavy tools accidentally remain.**

```bash
uv run python -c "
from sumo_qa.server import build_mcp_server
mcp = build_mcp_server()
tools = set(mcp._tool_manager._tools.keys())
heavy = {'sumo_qa_decide_approach', 'sumo_qa_prepare_for_work', 'sumo_qa_create_test_plan', 'sumo_qa_review_local_change', 'sumo_qa_scaffold_tests', 'sumo_qa_answer_testing_question'}
leaked = tools & heavy
assert not leaked, f'Leaked heavy tools: {leaked}'
print('No heavy tools registered. Surface clean.')
"
```

Expected: "No heavy tools registered. Surface clean."

- [ ] **Step 10.4: Write Phase 4 completion doc.**

Create `docs/superpowers/iteration-runs/round-11-phase-4-deletion.md`:

```markdown
# Phase 4 — Heavy-tool deletion (complete)

Branch: `feat/superpowers-restructure`. <N> new commits since Phase 3 completion (`3427efa`).

## What was deleted

Source modules:
- `src/sumo_qa/prompts.py`, `approach_decision.py`, `scaffolder.py`, `render_preview.py`, `render_cli.py`, `rubric.py`, `specialty_routing.py`, `classification.py`, `local_diff.py`, `evaluation.py`
- (Possibly) `src/sumo_qa/models.py`, `llm.py`, `knowledge.py` if fully obsoleted

Directories:
- `evaluation/` (legacy AI-graded harness)

Server registrations:
- 6 heavy tools (decide_approach, prepare_for_work, create_test_plan, review_local_change, scaffold_tests, answer_testing_question)
- 9 legacy `@mcp.prompt` decorators

Tests:
- 12 test files for the deleted modules
- Heavy-flow sub-tests in `test_server.py`, `test_tools.py`, `test_skill_prompts.py`, `test_error_envelope.py`, `test_standards.py`, `test_rules.py`

Entry points:
- `sumo-qa-eval` and `sumo-qa-render` from `pyproject.toml`

## What survives

Source:
- `src/sumo_qa/server.py` (slimmed to skill prompts + 11 tools)
- `src/sumo_qa/knowledge_loaders.py`, `skill_prompts.py`, `debug_capture.py`
- `src/sumo_qa/tdm_*.py`, `standards.py`, `rules.py` (slimmed)
- `src/sumo_qa/tools.py` (slimmed to test-data flows)

Knowledge + skills:
- All `knowledge/*.md` (5 catalogues)
- All `skills/*/SKILL.md` (10 skills)

Tests (all green):
- `test_knowledge_loaders.py`, `test_skill_conformance.py`, `test_skill_prompts.py`, `test_phase3_e2e_skill_path.py`, `test_token_weight_regression.py`, `test_tdm.py`, `test_debug_capture.py`, slimmed `test_server.py` / `test_tools.py` / `test_standards.py` / `test_rules.py`

Entry points:
- `sumo-qa-mcp` only

## Test gate

- `uv run pytest`: <N> passed, 0 failed, 1 xfailed (unfiltered standards — Task 12 follow-up still deferred).
- MCP server: 11 tools, 10 prompts. No heavy tools leaked.
- `sumo-qa-mcp --help` works.

## Ready for Phase 5

Phase 5 covers docs rewrite + cross-platform install polish: README points at AGENTS.md, docs/* reflect the new architecture, `docs/QA_WORKFLOW.md` and `docs/WORKFLOW-LOOP.md` get deleted (or merged), `install.py` Win/Mac/Linux smoke-test.
```

- [ ] **Step 10.5: Commit completion doc.**

```bash
git add docs/superpowers/iteration-runs/round-11-phase-4-deletion.md
git commit -m "docs(iteration): Phase 4 heavy-tool deletion complete"
```

---

## Phase 4 done

After Tasks 1-10:
- 6 heavy tools gone.
- 9 legacy prompts gone.
- ~10-12 Python modules deleted.
- ~12 test files deleted, others slimmed.
- pyproject.toml entry points trimmed to `sumo-qa-mcp` only.
- MCP server tested: 11 tools, 10 prompts.
- Full suite green.

The MCP surface is now exactly what the spec described. Phase 5 (docs + install polish) is the last phase.
