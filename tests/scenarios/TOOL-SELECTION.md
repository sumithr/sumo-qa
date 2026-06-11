# Tool-selection scenarios

For each MCP tool below, an eval prompt + the tool the host LLM should pick + the anti-pick (the tool a less-disciplined LLM might wrongly fire).

These complement [`SCENARIOS.md`](SCENARIOS.md) (which evaluates *skill* behaviour) by evaluating *tool selection* — does the host LLM choose the right tool name when the user's intent surfaces? Tool descriptions in `src/sumo_qa/server.py` are the only signal the host has, so these scenarios stress-test those descriptions.

| Layer | Tools | Atomicity |
|---|---|---|
| Skill tools | 15 (one per `skills/<name>/SKILL.md`) | Returns the SKILL.md body |
| Knowledge loaders | 6 (`sumo_qa_load_*`) | Returns a markdown catalogue verbatim |
| Test-data tools | 4 (`sumo_qa_*_test_data*`) | Reads / writes the local known-good catalogue |
| External-skill lifecycle | 4 (`sumo_qa_*_external_skill*`) | Searches, installs, locates, and loads external skills |

The 15 skill tools are tested transitively by the scenarios in `SCENARIOS.md` — when the user's intent matches a skill, the host LLM should invoke that skill's tool. They are not duplicated here.

Fifteen of the sixteen atomic non-skill tools each get a dedicated scenario below. `sumo_qa_ingest_knowledge_pack` is a knowledge-management action covered by its own contract tests, not a tool-selection scenario.

---

## Knowledge loaders (6)

### TS-1. Load classifications

**User prompt:** *"What canonical change classifications does sumo-qa recognise?"*

**Expected tool:** `sumo_qa_load_classifications` (no args).

**Expected use of result:** the LLM names the 10 classifications from the returned catalogue (api_contract_change, business_logic_change, security_change, performance_change, frontend_change, infrastructure_change, test_change, docs_change, config_change, data_migration). Doesn't paraphrase from training data.

**Anti-pick:** invents classifications from training data; calls `sumo_qa_deciding_approach` (the skill) instead of the loader; calls `sumo_qa_load_principles` (wrong catalogue).

---

### TS-2. Load approaches

**User prompt:** *"List the QA approaches sumo-qa supports — I want to see what `coverage-first-then-refactor` actually means."*

**Expected tool:** `sumo_qa_load_approaches` (no args).

**Expected use of result:** the LLM cites the approach by its catalogue entry, including when-to-use guidance. Names the 8 approaches (strategy-orchestration, tdd-scaffold, regression-first, coverage-first-then-refactor, strengthen-test-coverage, verify-existing, no-tests-recommended, spike-first-then-tests).

**Anti-pick:** training-data recall ("coverage-first means add tests then refactor — common practice"); calls `sumo_qa_load_principles` instead.

---

### TS-3. Load principles (ISTQB / ISO)

**User prompt:** *"Cite an ISTQB Foundation principle for why exhaustive testing is a fool's errand."*

**Expected tool:** `sumo_qa_load_principles` (no args).

**Expected use of result:** the LLM cites Principle 2 ("Exhaustive testing is impossible") with the exact wording from the loaded catalogue, not a paraphrase.

**Anti-pick:** paraphrasing from training data; calling `sumo_qa_load_techniques` (wrong catalogue — techniques is HOW to test, principles is WHY).

---

### TS-4. Load techniques

**User prompt:** *"Which test-design techniques apply to a date-range filter with edge cases at month boundaries?"*

**Expected tool:** `sumo_qa_load_techniques` (no args).

**Expected use of result:** the LLM picks one or two techniques from the catalogue (boundary value analysis + equivalence partitioning) and ties each to a specific risk on the date-range filter. Cites by catalogue wording.

**Anti-pick:** training-data recall ("just use BVA"); generic answer ("test edge cases" — no named technique); calls `sumo_qa_load_principles` instead.

---

### TS-5. Load standards (filtered by classification)

**User prompt:** *"What team-loaded standards apply to a security-classified change in this repo?"*

**Expected tool:** `sumo_qa_load_standards(classification="security_change")`.

**Expected use of result:** the LLM enumerates the standards packs whose frontmatter declares `security_change` (no keyword inference — pure metadata filter). Surfaces an empty result honestly if no pack declares the classification, rather than fabricating one.

**Anti-pick:** unfiltered call (returns all packs — over-broad); calls `sumo_qa_load_rules` (different catalogue: standards = team policies, rules = per-classification dos/don'ts).

---

### TS-6. Load rules (filtered by classification)

**User prompt:** *"What's our team rule for what testing must accompany an api_contract_change?"*

**Expected tool:** `sumo_qa_load_rules(classification="api_contract_change")`.

**Expected use of result:** the LLM cites the must / should / must-not entries for `api_contract_change` from the returned YAML, in plain English.

**Anti-pick:** unfiltered call; calls `sumo_qa_load_standards` (wrong catalogue); inventing a rule from training data ("you must add a contract test" without citing whether the team's loaded rule actually says that).

---

## Test-data tools (4)

### TS-7. Explain test-data requirements

**User prompt:** *"What kind of test data would I need to test partial refunds in staging?"*

**Expected tool:** `sumo_qa_explain_test_data_requirements(question="...", environment="staging", domain="billing")`.

**Expected use of result:** the LLM returns the structured requirements text the tool produced (data shape, source of truth, required fields, freshness expectations) — does NOT invent a fake invoice ID inline.

**Anti-pick:** invents an invoice ID from training data ("INV-12345 should work"); calls `sumo_qa_find_test_data` (wrong route — find is for *retrieving* an existing entry, explain is for *describing what's needed* before any retrieval).

---

### TS-8. Find test data

**User prompt:** *"Find me a refund-eligible invoice in staging for the partial-refund flow."*

**Expected tool:** `sumo_qa_find_test_data(question="refund-eligible invoice for partial-refund flow", environment="staging", domain="billing")`.

**Expected use of result:** the LLM surfaces the matching catalogue entry (ID, last_validated_at, scenario_tags); revalidates against the source system in this turn (per the `sumo-qa-finding-test-data` skill's discipline). If catalogue is stale, says so explicitly — does NOT silently substitute another entry.

**Anti-pick:** invents an ID; calls `sumo_qa_validate_test_data` first without finding (validate needs an ID — wrong order).

---

### TS-9. Validate a specific test-data entry

**User prompt:** *"Is `auth-locked-account-001` still a valid known-good entry?"*

**Expected tool:** `sumo_qa_validate_test_data(entry_id="auth-locked-account-001")`.

**Expected use of result:** the LLM surfaces the validation result + freshness assessment (fresh / aging / stale / unknown / not_applicable) + any plausibility issues. Does NOT cache stale validations.

**Anti-pick:** calls `sumo_qa_find_test_data` (wrong shape — find is for matching an intent, validate is for checking a known ID); says "yes it's valid" from training-data recall.

---

### TS-10. Register a known-good test-data entry

**User prompt:** *"I just confirmed `INV-44120` works for the partial-refund flow in staging — register it as known-good."*

**Expected tool:** `sumo_qa_register_known_good_test_data(entry={...})`.

**Expected use of result:** the LLM constructs the full `entry` dict with required fields (id, environment, domain, scenario_tags, known_valid_for, owner, confidence, source) before calling. Confirms with the user before writing to the catalogue (per the skill's discipline). Surfaces the resulting `isError` envelope with `actionable_hint` if the entry shape is invalid.

**Anti-pick:** calls without confirmation; partial entry that fails pydantic validation; tries to update the catalogue file directly via Bash instead of the tool.

---

## External-skill lifecycle (4)

### TS-11. Search external skills

**User prompt:** *"No native skill fits this. Find an external skill for Python type checking."*

**Expected tool:** `sumo_qa_search_external_skills(query="python type checking mypy")`.

**Expected use of result:** the LLM inspects `matches` and `raw_output`, names only candidates returned by the tool, and asks before installing anything.

**Anti-pick:** runs `npx skills find` directly; invents a skill name from memory; installs before presenting the `[y/N]` gate.

---

### TS-12. Check installed external skill

**User prompt:** *"Before installing, check whether the mypy type-checking skill is already installed."*

**Expected tool:** `sumo_qa_check_external_skill_installed(skill="mypy-type-checking", scope="auto")`.

**Expected use of result:** if a path is returned, the LLM executes that installed skill; if null, it searches or asks before installing.

**Anti-pick:** reads `~/.codex/skills` directly; assumes absence without checking project and global locations.

---

### TS-13. Install external skill

**User prompt:** *"Yes, install `mypy-type-checking` from `vercel-labs/skills` for Codex in project scope."*

**Expected tool:** `sumo_qa_install_external_skill(skill="mypy-type-checking", source="vercel-labs/skills", scope="project", agent="codex", confirmed=true)`.

**Expected use of result:** the LLM passes `confirmed=true` only after explicit user approval, then surfaces success or the `isError` actionable hint.

**Anti-pick:** omits `confirmed=true`; shells out directly; silently switches to global scope.

---

### TS-14. Execute external skill

**User prompt:** *"The type-checking skill is installed. Execute it for this repo and create the first automated checks."*

**Expected tool:** `sumo_qa_execute_external_skill(skill="mypy-type-checking", intent="create automated type-checking checks for this repo", scope="auto")`.

**Expected use of result:** the LLM follows the returned `skill_body` and keeps sumo-qa confirmation gates for dependency installs and file writes.

**Anti-pick:** treats execution as a shell command; ignores the returned `SKILL.md`; bypasses sumo-qa evidence requirements.

---

## Capabilities discovery (1)

### TS-15. Discover what sumo-qa can do

**User prompt:** *"What can sumo-qa do? Show me the main QA workflows available."*

**Expected tool:** `sumo_qa_capabilities()` (no args).

**Expected use of result:** the LLM lists the core workflows from the returned map (review changes, regression-first fix, QA prep, formal test plan, mutation strengthening, test-data discovery, repo strategy, external-skill discovery) with their sample prompts and target skills — drawn from the tool output, not training-data recall.

**Anti-pick:** recites a tool list from training data; calls `using_sumo_qa` or `sumo_qa_deciding_approach` (those route a concrete QA intent — capabilities is pure discovery, no intent to route); dumps full skill bodies.

---

## Skill tools (15) — covered transitively

The 15 skill tools are evaluated by the scenarios in [`SCENARIOS.md`](SCENARIOS.md) — when the user's intent matches a skill, the host LLM should invoke that skill's tool *and* follow its checklist. The selection-side check is implicit in the scenario's "Skill activated" line; the behaviour-side check is the rest of the scenario.

| Skill tool | Selection scenario in SCENARIOS.md |
|---|---|
| `using_sumo_qa` | #11 (router invocation on first-turn QA intent) |
| `sumo_qa_deciding_approach` | #10 (terminates here for trivial change) |
| `sumo_qa_preparing_for_work` | #1 |
| `sumo_qa_creating_test_plan` | #9 |
| `sumo_qa_implementing_with_tdd` | #3 (regression-first), #4 (tdd-scaffold) |
| `sumo_qa_reviewing_before_merge` | #2 |
| `sumo_qa_strengthening_tests` | #5 |
| `sumo_qa_finding_test_data` | #7 |
| `sumo_qa_answering_testing_question` | #6 |
| `sumo_qa_strategising` | #8 |
| `sumo_qa_planning_qa_rollout` | #12 |
| `sumo_qa_executing_qa_rollout` | #13 |
| `sumo_qa_finishing_qa_work` | #14 |
| `sumo_qa_suggesting_external_skill` | #15 |
| `sumo_qa_closing_qa_gaps` | #16 (review-gap loop), #17 (mutation-survivor loop) |

A scenario passes the *selection* check if the host LLM invokes the named skill tool (or its slash-command equivalent) on the first turn after the user's intent.

---

## How to validate these scenarios

Two complementary paths:

1. **Deterministic trigger-routing harness (CI gate):** [`tests/test_skill_triggering.py`](../test_skill_triggering.py) reads [`tests/fixtures/skill_triggers.yaml`](../fixtures/skill_triggers.yaml) and asserts every skill tool is registered and that its description contains at least one of the natural-language phrases pinned for the prompts that should route to it. No live LLM. This is a **necessary, not sufficient** check for the 15 skill tools: phrase presence in the description is required for the host LLM to even consider this tool, but the LLM's actual selection is judged by the optional evals in path 2. The 16 atomic non-skill tools above are scenario-led rather than fixture-pinned — their description contracts are tested by the existing `tests/test_server.py` suite.
2. **LLM-as-judge evals (optional):** see [`LLM-EVALS.md`](LLM-EVALS.md) for the rubric design and [`tests/evals/promptfoo/`](../evals/promptfoo/) for the runnable implementation. These judge *behaviour* on top of selection; they need `OPENAI_API_KEY` and are not part of required CI.
