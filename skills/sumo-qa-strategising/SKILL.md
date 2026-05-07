---
name: sumo-qa-strategising
description: Use for broad open-ended senior-QA asks against a whole repo — "analyse and implement a test strategy for delivering high quality in the shortest time with the fewest bugs", "audit our test coverage", "design our QA strategy from scratch", "where should we invest QA effort first". Walks the repo with your own file-read tools, then chains the sumo-qa MCP tools to produce a prioritised, risk-based strategy.
---

## When to load

Load this skill when the user asks an **open-ended, repo-wide** QA question — not a specific change. Triggers:

- "analyse and implement a test strategy for this repo"
- "audit our test coverage"
- "design a QA strategy from scratch"
- "where should we invest QA effort first"
- "what's the minimum viable QA setup for this codebase"
- "we have no tests; help us build a strategy"
- "our QA gates are failing all over; what's the priority order"

If the user is asking about a **specific change** (a story, a diff, a bug), load `qa-deciding-approach` instead. This skill is for *strategy*, not for a single piece of work.

## The Iron Law

```
ANALYSE THE REPO BEFORE PROPOSING A STRATEGY.
PRIORITISE BY RISK x EFFORT, NOT BY ALPHABETICAL ORDER.
NEVER PROPOSE A WALL OF TESTS WITHOUT NAMING THE PRINCIPLE THAT JUSTIFIES EACH ONE.
```

Three sub-rules, all enforced:
1. **Reading the repo before reasoning is mandatory.** Use your own `Glob` / `Read` / `Grep` tools to map the actual codebase. Don't guess from the user's description.
2. **Prioritisation is risk-based, not exhaustive.** Foundation principle 4 (defects cluster) and principle 2 (exhaustive testing is impossible) together imply: pick the few areas where bugs would hurt most + are most likely + are least covered, and start there.
3. **Every recommendation cites a principle or standard.** "Add unit tests for X" is not a recommendation; "X is a payment-critical path with no test evidence — Foundation principle 7 (absence-of-errors fallacy) implies validation here is mandatory before merge" is.

## Workflow

### Phase 1 — repo analysis (use your file-read tools, not the MCP)

The MCP runs in an isolated env and can't read the repo. **You** (the host model) walk it. Use `Glob` / `Read` / `Grep`:

1. **Identify the language(s) and framework(s)**:
   - Python: `pyproject.toml`, `setup.py`, `requirements*.txt`
   - Node: `package.json` — look for test scripts (`jest`, `vitest`, `mocha`, `cypress`, `playwright`, `k6`)
   - Java: `pom.xml`, `build.gradle` — look for test plugins (`pitest`, `surefire`, `failsafe`)
   - Kotlin: same plus `build.gradle.kts`
   - Go: `go.mod`
   - Ruby: `Gemfile`
2. **Map source vs test directories**:
   - `find src -type f -name "*.py"` etc., compared with `find tests -type f`
   - For each top-level domain dir under src, count source files vs test files
   - Flag domains with 0 tests as **untested**; with <30% test/source ratio as **thin**
3. **Identify coverage / mutation gates if any**:
   - `.github/workflows/*.yml` for CI test jobs
   - `pitest.xml`, `stryker.conf.js`, `.coveragerc` for tool config
   - Look for thresholds (`pitest test strength gate`, `coverage minimum`)
4. **Identify domain-critical areas** (highest blast radius if they break):
   - Auth, payment, billing, encryption, security boundaries
   - Persistence / migrations
   - External contract surfaces (API, webhook handlers, queue consumers)
   - Anything in a `/critical/` or `/core/` directory
5. **Identify recent change hotspots**:
   - `git log --pretty=format: --name-only --since="3 months ago" | sort | uniq -c | sort -rn | head -20`
   - Files changed often + thinly tested = highest priority

Take notes in TodoWrite as you go. The list of (domain, source files, test files, gate state, criticality, recent activity) is the data you'll feed to phase 2.

### Phase 2 — strategy synthesis (chain the MCP tools)

Now use the sumo-qa MCP tools, ONE area at a time, in priority order.

For each high-priority area you identified in phase 1:

1. **Decide approach** — call `sumo_qa_decide_approach(intent_text=<your-1-line-description-of-the-area>, target_paths=[<the-files-in-that-area>])`. The AI-reasoned response (or deterministic fallback) tells you which discipline fits.
2. **Plan if substantial** — for medium/large areas, call `sumo_qa_create_test_plan` for a phased plan with entry/exit criteria. For small areas, skip to step 3.
3. **Capture the proposed work** — record the area, recommended approach, top risks, suggested techniques, specialty needs (Cypress, k6, Pact, etc.). DO NOT scaffold yet — this is strategy, not execution.
4. **Repeat** for each high-priority area. Stop when you've covered the top 5–8 areas. More than that is noise.

### Phase 3 — present the strategy

Render the strategy as a single coherent document. Format:

```
# Sumo QA strategy for <repo name>

## What I found

- Languages: <list>
- Test frameworks in use: <list>
- Coverage / mutation gates: <list with current state>
- Untested domains: <count, names>
- Thin-tested domains (<30% ratio): <count, names>
- Critical paths without tests: <count, names>
- Recent hotspots without tests: <count, names>

## Strategy (prioritised)

### Priority 1 — <area name> (<criticality>, <approach>)
- Why first: <cite Foundation principle / risk reasoning>
- Approach: <approach name from sumo_qa_decide_approach>
- Top risks: <bullet list>
- ISTQB techniques: <list>
- Specialty MCPs to pull in: <list, e.g. Cypress, k6, Pact>
- Estimated effort: <rough s/m/l>

### Priority 2 — <next area>
…

## What I recommend NOT doing first

- <area> — <reason: low risk, well-covered, etc.>
- <generic effort> — <reason>

## Open questions before we start

- <thing the user must decide>
- <missing context>
```

### Phase 4 — confirm + execute (only after explicit go-ahead)

After the user reviews the strategy and says "ok, start with priority 1":

1. Load the relevant sub-skill (`qa-implementing-with-tdd`, `qa-strengthening-tests`, etc. — based on what `sumo_qa_decide_approach` returned).
2. Execute its workflow for that priority area.
3. Verify; review; move to priority 2.

**One area at a time.** Strategy without execution is theatre; execution without confirmation is risk.

## Red Flags — STOP

| Thought | Reality |
|---|---|
| "I'll skip the repo walk and propose a generic strategy" | Generic strategy = generic value. Walk the repo first. |
| "I'll list all 50 untested files as priorities" | Foundation principle 2: exhaustive is impossible. Pick the top 5–8. |
| "I'll alphabetise the priorities" | Order by `criticality * recency * absence-of-tests`, not by name. |
| "Test pyramid says 70/20/10, I'll prescribe that" | Test pyramid is a context-dependent heuristic. Some apps are integration-heavy by nature; some are logic-heavy. Reason from the actual code shape. |
| "I'll start scaffolding before the user confirms" | Strategy is a proposal. The user might want to push back on priority order. Confirm first. |
| "I'll skip sumo_qa_decide_approach for each area; my strategy already says what to do" | The decider grounds the per-area approach in QA principles + their loaded standards. Skipping it loses the principled rationale you need for the strategy doc. |
| "There are no tests; I'll just propose 'add tests everywhere'" | Foundation principle 4: defects cluster. Find where the cluster is — domain-critical code, recent hotspots, external contract surfaces — and start there. |
| "User asked about strategy; I'll dump every QA technique I know" | The strategy is what to do for THIS repo. Other techniques live in the catalogue for when they're needed. |

## Example

User: *"using sumo-qa analyse and implement a test strategy that will ensure delivering high quality software, in the shortest possible time with lowest number of bugs"*

**Phase 1 (host file tools):**
- `Read pyproject.toml` → Python project, pytest already configured
- `Glob src/**/*.py` → 47 source files
- `Glob tests/**/*.py` → 8 test files
- `Read .github/workflows/ci.yml` → no coverage gate, lint-only CI
- `Bash git log --pretty=... --since="3 months ago" | head -20` → top hotspots: `src/payments/`, `src/auth/`, `src/orders/`
- Domain map:
  - `src/payments/` — 9 source files, 0 test files, payment-critical
  - `src/auth/` — 5 source files, 1 test file (smoke only), auth-critical
  - `src/orders/` — 12 source files, 4 test files (~30% ratio)
  - `src/util/` — 8 source files, 3 test files
  - `src/admin_dashboard/` — 13 source files, 0 test files (low criticality)

**Phase 2 (chain MCP tools, one area at a time, top 3 only):**

For `src/payments/` (priority 1):
- `sumo_qa_decide_approach(intent_text="add safety net to untested payment domain (charges, refunds, webhooks); 9 files, 0 tests", target_paths=["src/payments/*.py"])`
- → AI returns `tdd-scaffold` (or `coverage-first-then-refactor` if it reasons that production code is mature) with rationale citing Foundation principles 4 + 7 and ISO 25010 functional_correctness + security_integrity
- `sumo_qa_create_test_plan(work_item="Build a safety-net test suite for the payments domain", scope_size="large", acceptance_criteria=[...])`
- Capture: techniques (decision tables, equivalence partitioning), specialty needs (Pact for downstream contracts; security testing for token handling)

For `src/auth/` (priority 2):
- `sumo_qa_decide_approach(...)` → likely `strengthen-test-coverage` (existing smoke test is too thin) or `coverage-first-then-refactor`
- Capture techniques and specialty needs

For `src/orders/` (priority 3):
- `sumo_qa_decide_approach(...)` → likely `coverage-first-then-refactor` for the thin parts; `strengthen-test-coverage` for the missing assertions

**Phase 3:** present the unified strategy doc to the user.

**Phase 4:** wait for "start with priority 1, payments". Then load `qa-implementing-with-tdd` and execute.

## Final rule

```
Walk the repo → reason per area with the MCP → prioritise by risk × effort → propose → confirm → execute one area at a time.
The shortest path to high quality is concentrating QA effort where defects cluster, not spreading thin coverage everywhere.
```
