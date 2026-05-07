# QA workflow (host- and model-agnostic)

Paste or include this file in your project's agent-instruction surface. It encodes the same discipline the Claude Code skills enforce, in plain instructions any instruction-following model can follow.

| Host | Where to put this content |
|---|---|
| Claude Code | append to `CLAUDE.md` (project) or copy as `~/.claude/skills/qa/SKILL.md` |
| Cursor | append to `.cursorrules` |
| GitHub Copilot (VS Code) | append to `.github/copilot-instructions.md` |
| Windsurf | append to `.windsurfrules` |
| Aider | append to your `CONVENTIONS.md` (referenced in `.aider.conf.yml`) |
| Continue | put in your `~/.continue/config.json` `systemMessage` |
| JetBrains AI Assistant | no project-file convention yet — pick prompts from the MCP slash menu (`sumo_qa_what_approach`, `sumo_qa_review_my_changes`, etc.) |
| Generic / multi-tool | save as `AGENTS.md` at your project root |

The MCP itself works the same way across all of these — only the place to paste the *workflow discipline* differs.

---

## QA workflow contract

When the user asks anything QA-shaped — testing, code review, scaffolding tests, planning a feature, finding test data, fixing a bug — follow this contract. The sumo-qa MCP exposes the concrete tools; this contract enforces the discipline of *which tool to call when*.

### Iron Law

```
NO QA WORK WITHOUT FIRST DECIDING THE APPROACH.
```

The first MCP tool call on any QA-shaped intent is always **`sumo_qa_decide_approach`**. Do not call `sumo_qa_scaffold_tests`, `sumo_qa_create_test_plan`, `sumo_qa_review_local_change`, or `sumo_qa_prepare_for_work` first. The decision tells you which is the right one — sometimes none of them.

### Step 0 — Decide the approach

1. Call `sumo_qa_decide_approach(intent_text=<user's verbatim ask>, target_paths=[<files mentioned>])`.
2. Read `recommended_approach.approach`. It will be one of:
   - `tdd-scaffold` — greenfield-ish change adding behaviour
   - `regression-first` — bug fix on existing code
   - `coverage-first-then-refactor` — refactor with no intended behaviour change
   - `strengthen-test-coverage` — strengthen tests on UNCHANGED production code (mutation-testing follow-up, raise-coverage tasks)
   - `verify-existing` — config-only / trivial tweak
   - `no-tests-recommended` — pure docs / typos / comments
   - `spike-first-then-tests` — exploratory prototype
3. Announce, in this exact shape, before doing anything else:
   ```
   APPROACH: <approach> (<confidence>) → next: <next_action.tool or 'no tool'>
   ```
4. If `confidence` is `low`, ask ONE focused clarifying question instead of guessing.
5. Branch on the approach (sections below). Only proceed after the user confirms (or for thin questions, after one clarifying round-trip).

### Step 1A — `tdd-scaffold` branch

1. *(optional, for medium/large work)* Call `sumo_qa_create_test_plan(work_item, scope_size, acceptance_criteria, risk_notes)`.
   - Show the user `scope_in`, `entry_criteria`, the four phases with deliverables, `exit_criteria`.
   - Wait for confirmation.
2. Call `sumo_qa_scaffold_tests(work_item, test_conditions, target_paths)`.
3. For each task in `execution_order`:
   - Write the file at `tasks[i].file_path` with `tasks[i].skeleton` using your own `Edit`/`Write` tools. The MCP does **not** write files for you.
   - Run `tasks[i].verify_command`.
   - Confirm every assertion fails with `NotImplementedError` (or framework-equivalent stub failure). This is the **red phase**.
4. User implements production code (or you do, after explicit confirmation).
5. Re-run every `verify_command`. They must all be **green**.
6. Call `sumo_qa_review_local_change` for the final verdict before merge.

### Step 1B — `regression-first` branch

1. Call `sumo_qa_scaffold_tests` with **one** test condition: *"Reproduce the failing case exactly as the bug presents."*
2. Write that one file. Run its `verify_command`.
3. **The test must fail with the bug's actual symptom.** If it passes, your reproducer doesn't capture the bug — revise it.
4. User (or you, with confirmation) implements the fix.
5. Re-run the verify command. **It must pass** (confirmation testing).
6. Run targeted regression around the impacted area only — do not re-run the whole suite by default.
7. Call `sumo_qa_review_local_change` for the final verdict before merge.

### Step 1C — `coverage-first-then-refactor` branch

1. Call `sumo_qa_review_local_change(change_summary, touched_files)` **before** the refactor.
2. Read `local_diff.missing_test_levels` and `qa_findings` to identify coverage gaps.
3. Call `sumo_qa_scaffold_tests` with characterisation conditions for the **current** behaviour (e.g. *"validate(missing-customer) raises ValidationError with code MISSING_CUSTOMER"*).
4. Write the files, run them. They must **pass** — they capture today's behaviour.
5. User does the refactor.
6. Re-run the same characterisation tests. **They must all still pass, unchanged.** If any flips to fail, the refactor changed behaviour — revisit, do not "update the test".
7. Call `sumo_qa_review_local_change` for the final verdict before merge.

### Step 1D — `strengthen-test-coverage` branch

The user wants stronger tests on **unchanged** production code (mutation-testing follow-up, coverage-gate fixes).

1. Enumerate every surviving mutant or weak assertion. Classify each as:
   - **real gap** — write a strengthening test
   - **equivalent mutant** (early-return on already-empty branches, logger removal, generated lambda return, getter on non-null types, synthetic-line `Pair.equals`) — suppress in tool config
   - **weak assertion** — tighten in place (e.g. `assertNotNull` on a non-null type → assert on the actual expected value)
2. For each real gap or weak assertion, call `sumo_qa_scaffold_tests` with **one** test condition: the assertion that would have killed the mutant.
3. Write the file using your file tools. Run the verify command. Test passes against current production code.
4. Re-run the mutation tool. The targeted mutant must now be killed. If it isn't, your assertion isn't strict enough — tighten it.
5. For equivalent mutants, add a tool config exclusion (Pitest `<excludedMutators>`, Stryker `mutator.excludedMutations`) with a one-line comment per exclusion.
6. Re-run the gate; iterate until threshold met.
7. **Production code stays unchanged on this branch.** If you find yourself wanting to "improve" the production code, re-run `sumo_qa_decide_approach` — that's a different approach.
8. Call `sumo_qa_review_local_change` for the final verdict before merge.

### Step 1E — `verify-existing` / `no-tests-recommended` / `spike-first-then-tests`

No MCP tool to call.
- `verify-existing`: tell the user to run their existing test suite plus a smoke of the touched code path.
- `no-tests-recommended`: tell the user to run the build / docs lint.
- `spike-first-then-tests`: tell the user to spike freely; capture discovered test conditions for a future productionised pass.

Stop. Do not scaffold.

### Step 2 — Reviewing before merge (when the user asks for review)

When the user says "review my changes / is this safe to merge / what could break":

1. Call `sumo_qa_review_local_change(change_summary, touched_files, test_evidence)`.
2. Read these fields literally — do not paraphrase:
   - `verdict` (`needs-test-evidence` / `review-risk-before-handoff` / `qa-risk-acceptable-for-phase-1-input`)
   - `change_classification.primary` and `primary_confidence`
   - `local_diff.missing_test_levels`
   - `qa_findings` (each with `severity`, `category`, `recommended_test_path` if present)
   - `top_risks` (highest severity first)
   - `specialty_testing_needs` (with `mcp_hint`)
3. Surface the verdict literally as the first line: `VERDICT: <verdict>`.
4. List every finding with severity and recommended path.
5. List the top 3 risks.
6. If specialty needs are non-empty, surface a `Pull in:` line (e.g. *"Pull in: Browser-driven E2E (Playwright, Cypress)"*).
7. End with one of:
   - `needs-test-evidence` → "Want me to scaffold the missing tests? *(would call sumo_qa_scaffold_tests)*"
   - `review-risk-before-handoff` → "Which finding do you want to tackle first?"
   - `qa-risk-acceptable-for-phase-1-input` → "Ready to merge unless you want me to dig into a specific risk."

**Hard rule: never claim 'safe to merge' unless the tool says so.**

### Step 3 — Test data discovery / validation / registration

Triggered by phrasings about test data:

- "what data do I need" → `sumo_qa_explain_test_data_requirements(question, environment, domain)`
- "find me a known-good record / SKU" → `sumo_qa_find_test_data(environment, domain, scenario_tags, known_valid_for)`
- "is entry X still valid" → `sumo_qa_validate_test_data(entry_id=...)`
- "save this as known-good" → `sumo_qa_register_known_good_test_data(entry={...})`

Rules:
- Stale data is a **defect**, not a footnote — flag it prominently.
- High confidence requires validation — never claim a fixture is solid without checking freshness.
- Never invent entries. If `results == []`, recommend registering one OR widening the filter.

## Red flags (any approach)

| Thought | Reality |
|---|---|
| "I'll just call `sumo_qa_scaffold_tests`, this is clearly TDD" | Decide first. The change might be a config tweak or docs change. |
| "I'll write the production code first, then add tests" | That's tests-after, not TDD. Discard the code; start over from the failing test. |
| "Skeleton looks ready; I'll skip running the test" | You did not see it fail. RUN it. |
| "Verdict says needs-test-evidence but tests pass locally; I'll soften it" | The tool sees missing test *levels*. Read `missing_test_levels`. Don't soften. |
| "User said 'just confirm it's safe' — I'll say yes if I see no obvious problems" | The whole reason this MCP exists is to prevent confirming-without-evidence. Surface the verdict literally. |
| "Branch C: a test failed after the refactor, I'll update the test" | NEVER. The test pins behaviour; the refactor is wrong. |
| "Branch B: the test passes already" | The reproducer doesn't capture the bug. Revise it. |
| "results is empty, I'll suggest a SKU I made up" | Catalogue-only. Recommend registering or widening. |
| "I'll skip sumo_qa_decide_approach — the prompt says scaffold" | Approach is a precondition, not an alternative. |

## Final rule

```
QA intent → sumo_qa_decide_approach → announce approach → branch → verify between steps → review before merge.
Surface structured fields literally. The MCP returns the recipe; you write the files.
```
