# Phase 4 — Heavy-Tool Deletion

Branch: `feat/superpowers-restructure`. State at completion: **140 passed / 0 failed / 1 xfailed**.

The pre-Phase-4 baseline (round-10) was 312 passed / 0 failed / 2 xfailed. The drop to 140 is the intended consequence of deleting the entire heavy single-shot test surface: 12 heavy-path source modules and their 12+ dedicated test files were removed. The remaining 140 tests cover the slimmed public surface — skill prompts, knowledge loaders, test-data tools, and the conformance smoke. One xfail remains and is acknowledged in the test itself (`test_unfiltered_standards_and_rules_are_acknowledged_heavy` — calling `sumo_qa_load_standards()` / `sumo_qa_load_rules()` without a classification filter still exceeds per-call budget; flows must pass a filter).

## Public surface after Phase 4

MCP tools registered: **11**

- 4 test-data flows backed by the local YAML catalogue
  - `sumo_qa_explain_test_data_requirements`
  - `sumo_qa_find_test_data`
  - `sumo_qa_validate_test_data`
  - `sumo_qa_register_known_good_test_data`
- 7 knowledge-loader tools (plain-text returners; host LLM picks)
  - `sumo_qa_load_approaches`
  - `sumo_qa_load_classifications`
  - `sumo_qa_load_principles`
  - `sumo_qa_load_rules`
  - `sumo_qa_load_specialty_tools`
  - `sumo_qa_load_standards`
  - `sumo_qa_load_techniques`

MCP prompts registered: **10** (all skill-derived, body = SKILL.md content read fresh)

- `using_sumo_qa`
- `qa_deciding_approach`
- `qa_preparing_for_work`
- `qa_creating_test_plan`
- `qa_implementing_with_tdd`
- `qa_reviewing_before_merge`
- `qa_strengthening_tests`
- `qa_finding_test_data`
- `qa_answering_testing_question`
- `sumo_qa_strategising`

Script entry points: **1** — `sumo-qa-mcp` only. The legacy `sumo-qa-eval` and `sumo-qa-render` CLIs were removed because the heavy evaluation harness and render-preview pipeline they fronted no longer exist.

## What got deleted

Source modules removed from `src/sumo_qa/` (10 + 2 = 12 modules):

- `prompts.py`
- `approach_decision.py`
- `scaffolder.py`
- `render_preview.py`
- `render_cli.py`
- `rubric.py`
- `specialty_routing.py`
- `classification.py`
- `local_diff.py`
- `evaluation.py`
- `models.py` (heavy response models — test-data models still live in `tdm_models.py`)
- `llm.py` (sampling client; only the heavy single-shot path used it)
- `knowledge.py` (heavy KnowledgeProvider; the knowledge_loaders read files directly)

Test files removed (13):

- `tests/test_approach_decision.py`
- `tests/test_classification.py`
- `tests/test_evaluation.py`
- `tests/test_iteration_brief.py`
- `tests/test_knowledge.py`
- `tests/test_llm.py`
- `tests/test_local_diff.py`
- `tests/test_prompts.py`
- `tests/test_render_preview.py`
- `tests/test_repo_scenarios.py`
- `tests/test_rubric.py`
- `tests/test_scaffolder.py`
- `tests/test_specialty_routing.py`

The `evaluation/` directory of scenario YAML and the Python harness module that read it were both deleted.

## Token-budget result

`tests/test_token_weight_regression.py::test_create_test_plan_flow_stays_under_token_budget` was xfailed throughout Phases 1–3 because the heavy single-shot tools dominated the per-flow byte total. After Phase 4 the entire create-test-plan flow now totals **~2432 tokens** across 6 knowledge_loader calls (classifications, approaches, techniques, specialty_tools, standards filtered, rules filtered). Budget set at 2600 to give a small regression cushion. For comparison the old heavy single-shot path emitted >10k tokens for a single tool call — which is what broke IntelliJ AI Assistant's SSE in the first place and triggered this whole restructure.

## Commit chain

Oldest to newest, on `feat/superpowers-restructure`:

1. `957e657` — feat(server): remove 6 heavy tool registrations and 9 legacy MCP prompts
2. `f669dfb` — feat: delete 10 heavy-path source files and the evaluation/ harness
3. `3b762e2` — feat(tools): slim to test-data flows only
4. `45c6c3a` — feat(models): delete obsolete heavy response models (test-data models live in tdm_models.py)
5. `3508682` — feat(llm): delete obsolete sampling client (heavy-path only)
6. `06985dd` — feat(knowledge): delete obsolete domain knowledge module
7. `2ede2d3` — test: delete tests for 12 heavy-path source modules
8. `f9fe40c` — test: slim heavy-tool tests; un-xfail create-test-plan flow budget
9. `4cf897f` — build: drop obsolete sumo-qa-eval and sumo-qa-render entry points
10. _(this doc)_ — docs(iteration): Phase 4 heavy-tool deletion complete

## Self-review checklist

- [x] 11 MCP tools registered (4 test-data + 7 loaders)
- [x] 10 MCP prompts registered (skill-derived)
- [x] No heavy tool leaks (verified via `test_no_heavy_tools_leak_after_phase_4_deletion` and `test_heavy_tools_are_deleted_and_skill_path_is_canonical`)
- [x] `sumo-qa-mcp` script installs cleanly as the only entry point
- [x] Full suite green: 140 passed / 0 failed / 1 xfailed
- [x] One commit per task, 9 functional + 1 docs commit
