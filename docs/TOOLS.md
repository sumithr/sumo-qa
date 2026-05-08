# Tools and Prompts

Reference for the 10 MCP tools and 9 prompts the sumo-qa server exposes. The canonical state lives in [`docs/superpowers/iteration-runs/MCP-STATE-AND-CAPABILITIES.md`](superpowers/iteration-runs/MCP-STATE-AND-CAPABILITIES.md).

All tools return JSON by default. Pass `response_format: "markdown"` to get a render-ready string.

Annotation legend: read-only = no side effects. Idempotent = same args → same output. Open-world = reads outside the conversation (e.g. `git diff`).

---

## Tools

Source: [`src/sumo_qa/server.py`](../src/sumo_qa/server.py). Response models: [`src/sumo_qa/models.py`](../src/sumo_qa/models.py) and [`src/sumo_qa/tdm_models.py`](../src/sumo_qa/tdm_models.py).

### `sumo_qa_decide_approach`

Picks the QA approach for a change before any deeper work. Entry point on every QA intent.

- **Required:** `intent_text`
- **Optional:** `target_paths`, `signals` (`is_bug`, `is_refactor`, `is_test_only`, `is_spike`, `is_strategic_planning`, `is_docs_only`, `is_config_only`, `has_acceptance_criteria`), `response_format`
- **Returns:** `approach`, `rationale`, `next_action {tool, skill, deliverable}`, `top_risks`, `suggested_tests`, `named_techniques`, `specialty_needs`, `alternatives`, `assumptions`, `do_not_test`, `principle_cited`, `confidence`. Per-approach extensions: `characterization_tests` (refactor), `pyramid_shape` / `gate_calibration` / `ci_feedback_time` / `rollout_plan` (strategy).
- **Annotations:** read-only, idempotent.

### `sumo_qa_review_local_change`

Reviews uncommitted code, a diff, or a list of touched files for QA risk.

- **Required:** `change_summary`
- **Optional:** `diff`, `touched_files`, `test_evidence`, `explicit_classifications`, `response_format`. When `diff` and `touched_files` are both omitted, the server runs `git diff` in the working directory.
- **Returns:** `verdict` (`needs-test-evidence` / `review-risk-before-handoff` / `qa-risk-acceptable-for-phase-1-input`), `change_classification {primary, primary_confidence, confidence_note}`, `local_diff.missing_test_levels`, `qa_findings[].recommended_test_path`, `top_risks`, `named_techniques`, `smallest_useful_tests`, `principle_cited`, `do_not_test`, `assumptions`, `specialty_needs`, `recommended_approach`.
- **Annotations:** read-only, idempotent, open-world.

### `sumo_qa_prepare_for_work`

Produces a QA plan from a work item / story / ticket. Used for everyday work where a flat risk list is enough.

- **Required:** `work_item`
- **Optional:** `acceptance_criteria`, `risk_notes`, `explicit_classifications`, `target_paths`, `response_format`
- **Returns:** `top_risks`, `smallest_useful_tests`, `named_techniques`, `principle_cited`, `missing_information`, `entry_questions`, `recommended_approach`, `specialty_needs`, `assumptions`, `do_not_test`. Critical-path uplift fires automatically when intent mentions auth / payment / encryption / rate-limit / session / token / etc.
- **Annotations:** read-only, idempotent.

### `sumo_qa_create_test_plan`

Phased ISTQB-style test plan with entry/exit criteria. For substantial work where `prepare_for_work` is not enough.

- **Required:** `work_item`
- **Optional:** `scope_size` (`small` / `medium` / `large`, default `medium`), `acceptance_criteria`, `risk_notes`, `explicit_classifications`, `response_format`
- **Returns:** `test_plan` with scope in/out, test basis, approach, entry criteria, exit criteria, four phases (analysis, design, implementation & execution, completion) each with named deliverables, residual risks, open questions. Plus the standard senior-QA fields (top_risks, named_techniques, specialty_needs, etc.).
- **Annotations:** read-only, idempotent.

### `sumo_qa_scaffold_tests`

Returns structured red-phase scaffold tasks. The MCP itself does NOT write files — the host model writes each task with its own `Edit` / `Write` tool.

- **Required:** `work_item`
- **Optional:** `test_conditions`, `target_paths`, `explicit_classifications`, `response_format`
- **Returns:** `tasks[]` each with `file_path`, `framework` (pytest / Vitest / Jest / Playwright / Cypress / k6 / Schemathesis / Promptfoo / axe-core / Appium / JUnit 5 / XCTest), `language`, `level` (unit / integration / contract / functional / nonfunctional), `techniques`, `assertions`, `skeleton` (assertions raise `NotImplementedError` / TODO so it's TDD red phase), `verify_command`, `specialty + specialty_mcp_hint` when relevant. Plus `boundary_scaffolds` (`B1`, `B2`...), `uncovered_branches` (`U1`, `U2`...), `cross_cutting_assertions`, `top_risks` linked via `scaffold_coverage_task_id`, `principle_citations` per task, `named_techniques` per task, `execution_order`.
- **Annotations:** read-only, idempotent.

### `sumo_qa_answer_testing_question`

Free-form testing question → senior-QA answer.

- **Required:** `question`
- **Optional:** `context`, `explicit_classifications`, `response_format`
- **Returns:** `short_answer`, `smallest_useful_tests` (capped 3-5), `top_risks`, `named_techniques`, `principle_cited`, `recommended_approach` (with strategy-orchestration routing for whole-service asks), `strategy_extension` when applicable, `do_not_test`, `assumptions`, `specialty_needs`.
- **Annotations:** read-only, idempotent.

### `sumo_qa_explain_test_data_requirements`

Explains the test-data shape needed for a scenario, before searching for records.

- **Required:** `question`
- **Optional:** `environment`, `domain`, `response_format`
- **Returns:** required product characteristics, stock conditions, fulfilment conditions, downstream dependencies, edge cases, `what_not_to_use`, freshness, validation source.
- **Annotations:** read-only, idempotent.

### `sumo_qa_find_test_data`

Searches the local known-good catalogue under `knowledge/test_data/`.

- **Required:** none
- **Optional:** `environment`, `domain`, `scenario_tags`, `known_valid_for`, `product_id`, `sku`, `limit` (default 5), `offset` (default 0), `response_format`
- **Returns:** ranked matches with confidence, freshness, suitability reasons. Pagination: `total_count`, `has_more`, `next_offset`.
- **Annotations:** read-only, idempotent.

### `sumo_qa_validate_test_data`

Validates a catalogue entry or supplied entry without provisioning.

- **Required:** one of `entry_id` or `entry`
- **Optional:** `response_format`
- **Returns:** validation result with confidence, freshness, explained reason. Flags future timestamps and high-confidence-but-never-validated entries.
- **Annotations:** read-only, idempotent.

### `sumo_qa_register_known_good_test_data`

Adds or updates a known-good entry in the local YAML catalogue. Detects duplicates by environment + domain + product/SKU + scenario overlap. Writes to `knowledge/test_data/<domain>/known_good.yaml`.

- **Required:** `entry`
- **Optional:** `response_format`
- **Returns:** registration result with the persisted entry id.
- **Annotations:** NOT read-only (writes YAML), idempotent on duplicate detection, not destructive (additive only).

---

## Common error shape

Every tool body wraps exceptions in an MCP `isError` envelope:

```json
{
  "isError": true,
  "error": {
    "type": "ExceptionClass",
    "message": "...",
    "actionable_hint": "Concrete next step the user can take."
  }
}
```

---

## Prompts

The MCP also registers 9 prompts that hosts surface in their slash menu (Claude Code's `/mcp prompts`, IntelliJ AI Assistant, Cursor's prompt menu, etc.). Pick a prompt by hand and edit it before sending; don't slash-invoke a tool name.

| Prompt | Args | What it does |
|---|---|---|
| `sumo_qa_what_approach` | `intent`, `target_path?` | Calls `sumo_qa_decide_approach`, surfaces approach + rationale + next action, branches per approach. The discipline doorway. |
| `sumo_qa_review_my_changes` | `scope?` | Calls `sumo_qa_review_local_change`, surfaces verdict literally as the first line, refuses to claim safe-to-merge unless the tool says so. |
| `sumo_qa_plan_for_work` | `work_item` | Lightweight QA plan via `sumo_qa_prepare_for_work`. |
| `sumo_qa_test_plan_for_work` | `work_item`, `scope_size` | Phased test plan via `sumo_qa_create_test_plan`. |
| `sumo_qa_scaffold_tests_for_work` | `work_item`, `target_path?` | Scaffolds via `sumo_qa_scaffold_tests`; host writes the files. |
| `sumo_qa_how_do_i_test` | `thing` | Free-form via `sumo_qa_answer_testing_question`. |
| `sumo_qa_explain_data_needs` | `scenario` | Test-data shape via `sumo_qa_explain_test_data_requirements`. |
| `sumo_qa_find_data` | `scenario` | Catalogue lookup via `sumo_qa_find_test_data`. |
| `sumo_qa_validate_data` | `entry_id_or_entry` | Validation via `sumo_qa_validate_test_data`. |

The tool names and prompt names are deliberately different — tools are called by the model; prompts are the things you pick by hand.
