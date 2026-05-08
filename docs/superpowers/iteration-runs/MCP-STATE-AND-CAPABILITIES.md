# sumo-qa MCP — Final State and Capabilities

Date: 2026-05-08
Branch: `feat/ai-driven-iteration-loop` (22 commits, not pushed)

This document is the canonical answer to "what does the sumo-qa MCP do
right now, after seven rounds of iteration plus two MCP-builder cleanup
passes". Read it once and you have the whole picture.

---

## What sumo-qa is

A Model Context Protocol (MCP) server that turns the host LLM into a
**senior ISTQB-certified QA engineer**. The host model ships its own
intelligence; sumo-qa supplies the standing context and structured
schemas that force senior-QA discipline on every QA decision.

The fundamental design:

1. **The AI is the brain.** Every QA decision (approach selection, risk
   identification, test recommendation, specialty routing, classification)
   happens in the host LLM via MCP sampling.
2. **The harness is grounded plumbing.** It carries (a) the senior-QA
   persona system prompt, (b) per-tool grounding prompts with strict
   JSON schemas, (c) the team's loaded YAML standards/rules, (d) a
   structural fallback for when AI sampling isn't available.
3. **No keyword tables.** Earlier iterations stripped every phrase
   table. Pattern matching can't keep up with how language varies; the
   AI reasons from principles instead.

---

## Verified output quality

Eleven scripted scenarios spanning the full specificity spectrum
(very-specific 6-line diff → very-generic whole-service strategy ask)
all score **`senior-istqb-grade`** — every dimension of a 10-point
ISTQB rubric met:

- principle citation by Foundation number
- smallest useful test set tied to specific risks
- named ISTQB techniques (BVA, decision tables, state transition,
  MC-DC, mutation, exploratory charters, etc.)
- risk-based focus on THIS change
- explicit facts vs assumptions split
- no waived evidence
- decisive routing (right approach for the change shape)
- specialty + tool pairing that fits the actual risk
- domain-specific naming (no "the system", "the service")
- no generic advice / boilerplate

This held stable across:
- 5 prompt-iteration rounds (Round 1: 0/11 → Round 5: 11/11)
- 2 MCP-builder cleanup passes (rename, outputSchema, etc.) — 11/11 preserved
- Round 6 schema strictness pass — 11/11 preserved
- Round 7 backlog fixes — 11/11 preserved

3 consecutive rounds at steady state with no new scenarios required.

---

## Architecture (logical layers)

```
┌─────────────────────────────────────────────────────────────────┐
│ Host LLM (Claude Code, etc.)                                    │
│                                                                 │
│   - Calls MCP tools via JSON-RPC                                │
│   - Receives sampling requests, reasons, returns JSON           │
│   - Renders structured output                                   │
└───────────────┬─────────────────────────────────────────────────┘
                │  MCP protocol (stdio)
┌───────────────▼─────────────────────────────────────────────────┐
│ sumo-qa-mcp (FastMCP server, Python)                            │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │ 10 MCP tools — sumo_qa_* prefix, isError envelope,      │  │
│   │ outputSchema, response_format=json|markdown, pagination,│  │
│   │ readOnlyHint/destructiveHint/idempotentHint/openWorldHint│  │
│   │ annotations.                                            │  │
│   └─────────────────────────────────────────────────────────┘  │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │ 9 MCP prompts (sumo_qa_*) — natural-language entry       │  │
│   │ points exposed to hosts that surface prompts in UI.     │  │
│   └─────────────────────────────────────────────────────────┘  │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │ QAShiftLeftService — sync + async (aqa_*) methods       │  │
│   │ Per-tool prompt builders (_build_*_sampling_prompt)     │  │
│   │ Standards engine + rules engine + classification        │  │
│   │ Specialty routing (registry-only, no pattern detection) │  │
│   │ Approach decision (signal-driven fallback only)         │  │
│   │ TDM (test-data management) sub-service                  │  │
│   │ Debug capture (SUMO_QA_DEBUG_DIR env var)               │  │
│   └─────────────────────────────────────────────────────────┘  │
└───────────────┬─────────────────────────────────────────────────┘
                │  Sampling (ctx.session.create_message)
┌───────────────▼─────────────────────────────────────────────────┐
│ Standing context the host LLM gets on every sampling call:      │
│                                                                 │
│   - SENIOR_QA_SYSTEM_PROMPT                                     │
│     · ISTQB Foundation 7 principles                             │
│     · ISO/IEC 25010 quality characteristics                     │
│     · Test design techniques (black-box / white-box / experience)│
│     · Static testing & test pyramid & risk-based testing        │
│     · Senior-QA disciplines (decide-shape-first, smallest set,  │
│       critical-path tightening, honest TDD red phase, etc.)     │
│     · HARD REQUIREMENT: facts-vs-assumptions field              │
│     · HARD REQUIREMENT: domain anchoring                        │
│     · HARD REQUIREMENT: specialty+tool pairing (conditional)    │
│     · Tool selection guide (per-risk-shape canonical fits)      │
│                                                                 │
│   - Per-tool prompt with structured JSON output schema          │
│   - Loaded team standards (YAML packs)                          │
│   - Loaded team rules (change_rules.yaml — 10 classifications)  │
│   - Critical-path uplift block when intent matches auth/payment │
└─────────────────────────────────────────────────────────────────┘
```

---

## The 10 MCP tools

| Tool | Annotations | What it returns |
|---|---|---|
| `sumo_qa_decide_approach` | read-only, idempotent | Picks an approach (tdd-scaffold / regression-first / coverage-first-then-refactor / strengthen-test-coverage / verify-existing / no-tests-recommended / spike-first-then-tests / strategy-orchestration). Returns rationale, top_risks, suggested_tests, named_techniques, specialty_needs, alternatives, assumptions, do_not_test, next_action {tool, skill, deliverable}, principle_cited, confidence. When approach is `coverage-first-then-refactor`: also `characterization_tests`. When `strategy-orchestration`: also `pyramid_shape`, `gate_calibration`, `ci_feedback_time`, `rollout_plan`. |
| `sumo_qa_review_local_change` | read-only, idempotent, openWorld (reads `git diff`) | Reviews uncommitted code / a diff / touched files for QA risk. Verdict (`needs-test-evidence` / `review-risk-before-handoff` / `qa-risk-acceptable-for-phase-1-input`), classification, missing test levels, recommended test paths, qa_findings keyed to actual files, top_risks, named_techniques, smallest_useful_tests, principle_cited, do_not_test, assumptions, specialty_needs, recommended_approach. |
| `sumo_qa_prepare_for_work` | read-only, idempotent | QA plan from a work item / story / ticket. Top risks, smallest_useful_tests, named_techniques, principle_cited, missing_information, entry_questions, recommended_approach, specialty_needs, assumptions, do_not_test. Auto-applies critical-path uplift when intent mentions auth/payment/encryption/rate-limit/session/token/etc. |
| `sumo_qa_create_test_plan` | read-only, idempotent | Phased ISTQB-style test plan with entry/exit criteria, scope in/out, deliverables per phase, residual risks, open questions. Plus the standard top_risks / techniques / specialty / etc. |
| `sumo_qa_scaffold_tests` | read-only, idempotent | Structured red-phase scaffold tasks. Each task has file_path, framework, language, level, techniques, assertions, skeleton (honest stubs that fail), verify_command, specialty + specialty_mcp_hint when relevant. Plus boundary_scaffolds (`B1`, `B2`...), uncovered_branches (`U1`, `U2`...), cross_cutting_assertions, top_risks linked via scaffold_coverage_task_id (T*/U*/B*/NONE), principle_citations per task, named_techniques per task, execution_order. The MCP itself never writes files. |
| `sumo_qa_answer_testing_question` | read-only, idempotent | Free-form testing question → short_answer, smallest_useful_tests (capped 3-5), top_risks, named_techniques, principle_cited, recommended_approach (with strategy-orchestration routing for whole-service asks), strategy_extension when applicable, do_not_test, assumptions, specialty_needs. |
| `sumo_qa_explain_test_data_requirements` | read-only, idempotent | Required test data shape: product characteristics, stock conditions, fulfilment conditions, downstream dependencies, edge cases, what_not_to_use, freshness, validation source. |
| `sumo_qa_find_test_data` | read-only, idempotent | Search the local catalogue. Now returns `total_count`, `has_more`, `next_offset` for paging. |
| `sumo_qa_validate_test_data` | read-only, idempotent | Validate a test data entry without provisioning. Returns confidence + freshness + reason. |
| `sumo_qa_register_known_good_test_data` | NOT read-only (writes YAML). Idempotent on duplicate detection. | Add or update a known-good entry in the local catalogue. Detects duplicates by environment + domain + product/SKU + scenario overlap. |

Every tool body is wrapped in an `isError` envelope — exceptions never
propagate as protocol errors; they come back as
`{"isError": true, "error": {"type", "message", "actionable_hint"}}`.

---

## The 8 canonical approaches

(The AI may invent a new one if none fits.)

| Approach | When | next_action |
|---|---|---|
| `tdd-scaffold` | Greenfield-ish change adding behaviour | `tool: sumo_qa_scaffold_tests` |
| `regression-first` | Bug fix on existing code | `tool: sumo_qa_scaffold_tests` (reproducer-as-failing-test) |
| `coverage-first-then-refactor` | Behaviour-preserving refactor | `tool: sumo_qa_review_local_change`; output requires `characterization_tests` |
| `strengthen-test-coverage` | Mutation-testing follow-up; production code unchanged | `tool: sumo_qa_scaffold_tests` (against existing tests) |
| `verify-existing` | Trivial / config / version-bump tweak | `tool: null` (run existing suite + smoke) |
| `no-tests-recommended` | Pure docs / typos / comments | `tool: null, skill: null, deliverable: "static_review_completed"` |
| `spike-first-then-tests` | Exploratory throwaway prototype | `tool: null, skill: null, deliverable: "captured_conditions_and_fit_record"` |
| `strategy-orchestration` | Repo-wide / policy / pyramid / rollout | `skill: "sumo-qa-strategising"`; output requires `pyramid_shape` / `gate_calibration` / `ci_feedback_time` / `rollout_plan` |

---

## The 10 canonical change classifications

`api_contract_change`, `business_logic_change`, `state_transition_change`,
`ui_only_change`, `configuration_change`, `data_mapping_change`,
`error_handling_change`, `async_flow_change`, `caching_change`,
`security_change`. Each carries `must_consider`, `suggested_test_types`,
`test_design_techniques`, `quality_characteristics`, `risk_templates` in
`standards/rules/change_rules.yaml`.

The host can pass `explicit_classifications` to any tool. When omitted,
the AI classifies during sampling.

---

## The senior-QA system prompt

`SENIOR_QA_SYSTEM_PROMPT` (in `src/sumo_qa/prompts.py`) is sent on every
sampling call. It establishes:

- **Persona:** senior QA engineer with ISTQB Foundation, Advanced (Test
  Manager / Test Analyst / Technical Test Analyst), and specialty
  (Mobile / Performance / Security / AI Testing) certifications.
- **ISTQB Foundation 7 principles** by number with one-line each.
- **ISO/IEC 25010** quality characteristics.
- **Test design techniques** — black-box, white-box, experience-based.
- **Static testing**, test levels and pyramid, test types.
- **Risk-based testing** (Advanced TM).
- **Senior-QA disciplines** — decide shape first, smallest useful set,
  strategy vs single change, mutation-testing follow-up discipline,
  critical-path tightening, honest TDD red phase, static testing counts.
- **Output discipline** — JSON when asked, narrative shape, principle
  citation, never paraphrase guardrails.
- **HARD REQUIREMENT — facts vs assumptions**: every structured output
  carries an `assumptions` field.
- **Domain anchoring**: forbids generic phrases like "the service" /
  "the system" when target paths or classifications are supplied.
- **HARD REQUIREMENT — specialty + tool pairing** with a tool-selection
  guide (positive examples per risk shape: JJWT for token TTL, Pact for
  REST contract, k6 for performance, Pitest for mutation, Cypress for
  frontend, etc.). Conditional — `[]` is fine for in-process work.

---

## What the host actually gets back

A senior-QA-shaped JSON output for any QA intent. Concrete example for
`sumo_qa_decide_approach` on a config-only TTL bump:

```json
{
  "approach": "verify-existing",
  "rationale": "ISTQB Foundation Principles 2 (exhaustive testing impossible) and 5 (pesticide paradox) apply...",
  "next_action": {"tool": "sumo_qa_review_local_change", "skill": null, "deliverable": null},
  "techniques": ["boundary value analysis (TTL boundary at 14d-1s/14d/14d+1s)", ...],
  "specialty_needs": [{"specialty": "security", "tool": "JJWT integration test fixtures"}],
  "alternatives": [...],
  "top_risks": [
    {"risk": "Existing fixtures hard-code 7d and silently pass after the bump",
     "why_specific_to_this_change": "...", "evidence_path": "src/main/resources/application.yml"},
    ...
  ],
  "suggested_tests": [
    {"name": "Run existing auth integration suite unchanged", "technique": "regression",
     "covers_risk": "Existing fixtures hard-code 7d..."},
    ...
  ],
  "do_not_test": [
    {"area": "DAST scans against the refresh endpoint", "why_not": "TTL bump does not change HTTP surface"},
    ...
  ],
  "assumptions": [
    "An existing auth integration suite covers issue/refresh/rotate paths",
    ...
  ],
  "principle_cited": "ISTQB Foundation Principle 2 — Exhaustive testing is impossible",
  "named_techniques": [{"technique": "boundary value analysis", "covers_risk": "..."}],
  "confidence": "high",
  "reasoned_by": "ai"
}
```

---

## What sumo-qa is NOT

- **Not a black box.** Every output has an audit trail (cited principles,
  evidence paths, labelled assumptions, traceable scaffold IDs).
- **Not opinionated about a host.** Works with any MCP-capable host —
  Claude Code, IntelliJ AI Assistant, Cursor, etc. The host model
  supplies the intelligence; sumo-qa supplies the discipline.
- **Not a test runner.** It produces structured QA artefacts (plans,
  scaffolds, risks, recommendations). The host model writes files,
  runs commands, and verifies.
- **Not domain-specific.** It ships generic ISTQB grounding plus a
  small Kotlin/JVM-leaning standards pack as default. Teams load their
  own YAML standards via `QA_STANDARDS_PATH` env var.

---

## Engineering quality

- **257 tests** pass, including 11+ tests per round pinning the new
  prompt contracts (e.g. `test_scaffold_prompt_has_top_risks_slot`,
  `test_question_prompt_has_strategy_extension_when_strategy_orchestration`,
  `test_decide_review_prepare_question_test_plan_have_do_not_test_field`).
- **Eval suite** 28/28 across 4 fixture YAMLs (fulfilment + stock).
- **MCP best practices** applied: `sumo_qa_*` prefix, annotations,
  outputSchema declared via Pydantic, response_format=json|markdown,
  pagination metadata on list tools, isError envelope, Field examples,
  consistent server name.
- **No phrase-table decision making** anywhere — the deterministic
  fallback is structural-signal-only (file extensions, caller-supplied
  signals like `is_bug`, `is_strategic_planning`).
- **Standards loaded from YAML packs** so teams customise without
  editing source.
- **Debug-mode capture** via `SUMO_QA_DEBUG_DIR` env var dumps every
  tool exchange to disk for offline review.

---

## How a host uses sumo-qa (typical flow)

```
User: "review my changes / is this safe to merge"
  →  Host AI invokes `sumo_qa_review_local_change`
     → sumo-qa samples the host AI with senior-QA system prompt + per-tool grounding
     → host AI reasons → returns structured JSON
     → sumo-qa renders + returns to user
  →  User sees: VERDICT, top risks with evidence_path, named techniques,
     smallest useful tests, what NOT to test, what was assumed, what
     specialty tools to pull in, recommended next action.

User: "design a test strategy for this whole service"
  →  Host AI invokes `sumo_qa_decide_approach` with is_strategic_planning=True
     → sumo-qa returns approach=strategy-orchestration with structured
       pyramid_shape / gate_calibration / ci_feedback_time / rollout_plan
       and next_action.skill="sumo-qa-strategising".
  →  Host loads the sumo-qa-strategising skill and walks the repo.

User: "spike: prototype X with no production wiring"
  →  Host AI invokes `sumo_qa_decide_approach` with is_spike=True
     → sumo-qa returns approach=spike-first-then-tests with
       next_action.deliverable="captured_conditions_and_fit_record".
  →  User spikes freely; the deliverable signals what to capture for
     the productionised pass.
```

---

## The 21-commit branch chain

```
77e3016 docs(iteration): round 7 verified
946e8b6 feat(prompts): round 7 — harmonise prepare schema, question strategy_extension, stable scaffold IDs, do_not_test field, spike deliverable route, characterization_tests for refactor
d54f60b docs(iteration): round 6 verified
c625738 feat(prompts): round 6 — harmonise review, structured strategy fields, next_action.tool|skill, specialty tool fit examples
5ed407d docs(iteration): post-cleanup verification
7c87506 refactor(server): MCP best practices part 2 — outputSchema, tool prefix rename, response_format
62a6a01 refactor(server): MCP best practices — annotations, pagination, isError, Field examples, server name fix
997c80f docs(iteration): steady state — 11/11 across 5 rounds
6bb9ef6 round 5 — scaffold schema overhaul
6a98756 round 4 — softened specialty rule, boundary_scaffolds, security target_paths
40dc7b5 round 3 — scaffold/question HARD REQUIREMENTs, specialty+tool pairing, security_change classification, target_paths on prepare
9b92ea2 round 2 — assumptions, top_risks, suggested_tests, domain anchoring, drop generic-risk hardcoding
69186ca feat(server): SUMO_QA_DEBUG_DIR capture
37fc520 feat(docs): iteration-runs directory + per-round template
7ebcbb6 refactor(eval): hoist target repo path to env-configurable constant
6627ab9 feat(eval): subagent-brief builder
7e0a9a4 fix(rubric): add missing no_generic_advice dimension
389cfca feat(rubric): ISTQB grading rubric
582b5e2 refactor(eval): polish scenarios
fc02932 fix(eval): add real verify-existing scenario
abb3771 feat(eval): seed initial 10 scenarios
c303a84 feat(eval): RepoScenario dataclass
```

---

## What's left

1. **Live MCP wire-protocol verification** (optional). Restart sumo-qa
   from Claude Code's MCP panel, set `SUMO_QA_DEBUG_DIR=/tmp/...`, run
   3-5 scenarios via the live MCP and read the captured `trace.md`
   files. Catches anything the in-process subagents wouldn't see.

2. **User read-through.** The whole point of all 7 rounds is to get the
   MCP to a place where you (human reviewer) read the structured QA
   output and recognise a senior-QA-grade artefact. Pick any scenario
   from `evaluation/repo_scenarios.py` and trace it through the live
   MCP or via the iteration-runs documents.

3. **Optional Round 8 polish (non-blocking):**
   - Surface `strategy_extension` blocks in the rendered markdown for
     `qa_answer_testing_question` so they're visible without raw JSON.
   - Add backend / event-driven anti-pattern defaults for `do_not_test`
     in the system prompt.

The MCP is converged. Done is when you say it is.
