# Real-world QA scenarios

Real-world scenarios sumo-qa is designed to handle. Each one captures: the user's actual prompt, which skill activates, the *shape* of the interaction the user should see, and what would tell you the interaction has gone wrong.

These aren't pytest assertions — they're an interaction-quality reference. The runtime test is in [`tests/test_session_start_hook.py`](../test_session_start_hook.py) (verifies the using-sumo-qa router gets injected on every session). The interaction-quality test is human-in-the-loop: dispatch sumo-qa on these prompts and check the response matches the pattern below.

For each scenario, an agent role-play of the expected interaction is captured under [`worked-examples/`](worked-examples/) — they show what "good" looks like end-to-end, including the one-section-per-turn pacing.

---

## 1. Plan QA for a new story before coding starts

**User prompt:** *"Plan QA for ticket BILL-481 — adding a partial-refund flow to the billing service. Files probably touch `services/billing/refund.py` and `services/billing/invoice.py`. Refund amount can be less than the invoice total; consumers expect 4xx-vs-5xx semantics for partial-vs-full failure."*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-preparing-for-work`.

**Expected interaction shape:**
1. Reads `services/billing/refund.py` and `services/billing/invoice.py` via the host's file tools (NOT asks the user what's in them).
2. Names 3–7 risks, each anchored to a file path or domain term from the prompt (e.g. *"partial-refund amount precision when the invoice has multiple currency line items"*, *"consumer retry logic — does it differentiate the new 4xx from the existing 5xx"*).
3. Picks one technique per risk from the loaded catalogue (boundary value / decision table / property-based / etc.).
4. Proposes a smallest-useful test set (3–7 tests) tied to those risks. NOT "test happy path, test edge cases".
5. Sectioned conversational prose — risks, tests, techniques, open assumptions — NOT a JSON blob.

**Anti-patterns that would fail this scenario:**
- Generic "add unit tests and integration tests".
- 15+ risks (confabulation, not reasoning).
- Asks the user what's in the files instead of reading them.
- Surfaces "Classification: business_logic_change" verbatim in the output.

---

## 2. Review uncommitted changes before merging

**User prompt:** *"Review my changes — is this safe to merge?"*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-reviewing-before-merge`.

**Expected interaction shape:**
1. Runs `git diff` / `git diff --staged` / `git diff <base>...HEAD` via the host's git tools to read the actual diff.
2. Reads each changed file (not just the diff hunks).
3. Calls `sumo_qa_load_classifications()` + `sumo_qa_load_standards(classification=...)` + `sumo_qa_load_rules(...)` to know which team rules apply.
4. Names 3–7 risks anchored to **file + line**, not generic.
5. Presents scope + classification in one paragraph, asks ONE focused question for anything ambiguous.
6. **HARD GATE:** runs the test suite in *this turn*. Shows actual pass/fail counts. "CI was green earlier" is NOT acceptable.
7. Maps each named risk to a covering test (file + test name) or flags it as uncovered.
8. Final verdict: SAFE TO MERGE / NOT SAFE / NEEDS WORK with concrete evidence. SAFE only if (a) suite green now, (b) every risk has a covering test, (c) no loaded rule violated.

**Anti-patterns:**
- Declares "safe to merge" without running tests in this turn.
- Generic risks ("edge cases", "error handling").
- Single-shot dump with all 5 sections at once instead of confirmation gates between.

---

## 3. Fix a production bug regression-first

**User prompt:** *"Fix the VIP-customer double-discount bug regression-first. The discount stacks twice when a VIP gets a promo code applied. Logic is in `pricing/discount_calculator.py`."*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-implementing-with-tdd` (approach: `regression-first`).

**Expected interaction shape:**
1. Walks the repo: reads `pricing/discount_calculator.py`, finds the matching test file, reads sibling test files to detect framework/fixture conventions. Does NOT ask the user "what test framework do you use?"
2. Picks the smallest failing test: names the function under test, the input that triggers the bug, the assertion that distinguishes broken from fixed.
3. Confirms the test idea with the user, asking ONE focused question for the ambiguous part (e.g. *"is the expected total £90.00 — does VIP override promo entirely, or do they stack but cap?"*).
4. After confirmation: writes the failing test.
5. Runs it. **Surfaces the red output verbatim** (`AssertionError: assert 80.0 == 90.0` at `test_discount_calculator.py:47`).
6. Hands off: *"red phase confirmed — implement to make it green; I'll re-run when you're ready."*

**Anti-patterns:**
- Writes the test AND the production fix in the same turn (Iron Law violated).
- Tautology assertion (`assert add(2,3) == 2+3`) that the broken code also passes.
- Skips the red phase, declares green.
- Asks 4+ questions up front before doing any exploration.

---

## 4. Add tests for a new behaviour-driven feature (TDD-scaffold)

**User prompt:** *"I'm adding rate-limiting to the auth service — 100 requests / minute / IP, sliding window. Want to TDD it. Scaffold the failing tests first."*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-implementing-with-tdd` (approach: `tdd-scaffold`).

**Expected interaction shape:**
1. Walks the auth service to find where rate-limiting would attach (middleware, request handler, etc.). Reads sibling tests for framework conventions.
2. Names the *risk surfaces* before tests: (a) boundary at 100th vs 101st request, (b) sliding-window vs fixed-window edges, (c) per-IP isolation, (d) clock-skew under load, (e) reset-after-window.
3. Confirms the test plan in one paragraph; asks the ONE ambiguous question (e.g. *"reset behaviour at the window boundary — drop the oldest request as the window slides, or hard-reset every 60s?"*).
4. Writes the smallest *first* failing test (boundary at 100→101). Runs it. Shows red output. Hands off to user for implementation.
5. Does NOT scaffold all 5 tests up front — TDD is one red→green cycle at a time.

**Anti-patterns:**
- Writes 5 tests up front before any goes red.
- Writes the rate-limiter implementation alongside the test.
- Asserts on internal state (`assert limiter._internal_counter == 100`) instead of observable behaviour (`assert response.status == 429`).

---

## 5. Strengthen tests against mutation-testing survivors

**User prompt:** *"Pitest report shows 6 surviving mutants in `pricing/calculator.py`. Help me strengthen the tests. Production code stays unchanged."*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-strengthening-tests`.

**Expected interaction shape:**
1. Reads the Pitest report to identify the 6 survivors (line + mutation type: e.g. `>` → `>=`, `&&` → `||`, removed-conditional).
2. Walks one survivor at a time. For each: (a) tautology check (is the current test re-asserting the production code?), (b) picks a technique from the catalogue that would kill this specific mutant, (c) names the strengthening test.
3. Confirms the technique choice before writing the test. Asks ONE focused question if the right behaviour is ambiguous.
4. Writes the strengthening test, runs it (now passes against current prod), then asks Pitest to rerun against the mutated prod — verifies the mutant is now killed.
5. Moves to next survivor only after confirmation.

**Anti-patterns:**
- Modifies production code to make tests pass.
- Batches all 6 strengthening tests in one go.
- Writes tests that still pass on the mutated code (didn't actually kill the mutant).

---

## 6. Generic testing question — "how do I test this?"

**User prompt:** *"How should I test a service that re-orders user feeds based on engagement signals?"*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-answering-testing-question`.

**Expected interaction shape:**
1. Reads any code/spec the user supplied (or asks for one specific clarification if none provided).
2. Calls `sumo_qa_load_principles()` + `sumo_qa_load_techniques()` — identifies the QA shape (correctness of ordering rules / regression on existing ordering / performance under load).
3. Cites at least one ISTQB principle by number/name (e.g. *"Principle 4 — defects cluster; feed-ordering is a hotspot"*).
4. Names at least one technique from the catalogue (e.g. *"decision table for the ordering-rule combinations; equivalence partitioning for feed sizes"*).
5. Names the best-fit tool if a specialty surface is implied (e.g. k6 if performance at scale matters, Hypothesis if ordering invariants suggest property-based).
6. 3–7 sentences total. Conversational, NOT a JSON blob.

**Anti-patterns:**
- "Add unit tests and integration tests, consider edge cases" — no cited principle, no named technique.
- 20-sentence essay (senior QA answers concisely).
- Routes to a sub-skill instead of answering inline (the question doesn't need a full plan).

---

## 7. Find a known-good test data record

**User prompt:** *"Find me a refund-eligible invoice for the partial-refund flow test in staging."*

**Skill activated:** `sumo-qa-finding-test-data`.

**Expected interaction shape:**
1. Routes internally to `find` (one of the 4 routes: explain / find / validate / register). Does NOT echo "Route: find" to the user.
2. Calls `sumo_qa_find_test_data(question="...", environment="staging", domain="billing", criteria=...)`.
3. For each match, validates it against the source system *in this turn* (not from cache).
4. Surfaces the result with freshness timestamp + validation evidence — e.g. *"Found `INV-44120` — refund-eligible, validated against staging just now (2026-05-12 09:14)."*
5. If a catalogue entry is stale: surfaces the failure explicitly, does NOT silently substitute another.
6. For register requests: confirms with the user before writing to the catalogue.

**Anti-patterns:**
- Invents an invoice ID ("try INV-12345").
- Returns a stale entry without re-validation.
- Silent substitution when the requested entry is stale.

---

## 8. Audit test coverage + design QA strategy

**User prompt:** *"Audit our test coverage across the customer-platform monorepo and design a QA strategy. We've got 4 services and a shared lib."*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-strategising`.

**Expected interaction shape:**
1. Walks the repo *with the host's file tools first*. Inventory: services, top-level modules, test dirs, CI config, coverage reports. Does NOT ask the user to enumerate the repo.
2. Per-area provisional analysis: classification per area, existing coverage shape (unit-heavy / integration-heavy / e2e-heavy), 2–3 named risks per area citing file paths.
3. **Confirms scope + inventory** in one paragraph, asks ONE focused question (e.g. *"are all 4 services in scope, or just the ones you own?"*).
4. Walks subsequent sections one at a time with confirmation gates: per-area risks → specialty fit + tool setup offer → prioritisation → target pyramid → phased rollout → residual risks.
5. Final deliverable: a coherent strategy document; offers to write it to `docs/qa-strategy.md` only after the user confirms.

**Anti-patterns:**
- Single-shot dump: "Phase 1 unit tests, Phase 2 integration, Phase 3 e2e, aim for 80% coverage."
- Generic recommendation: *"introduce a QA Center of Excellence"*.
- Asks the user what services exist (read the repo).
- No residual risks listed (every strategy has them).

---

## 9. Create a formal test plan with entry/exit criteria

**User prompt:** *"Create a formal test plan for the Q3 search-relevance launch. We need entry/exit criteria the team can sign off on."*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-creating-test-plan`.

**Expected interaction shape:**
1. Walks scope → risks → entry criteria → phases → exit criteria → residual risks **one section at a time** with confirmation gates.
2. **HARD GATE:** explicit entry criteria AND explicit exit criteria — no plan without both. (Iron Law of this skill: "NO PLAN WITHOUT EXPLICIT ENTRY/EXIT CRITERIA.")
3. Entry criteria are *measurable* (e.g. *"baseline NDCG@10 ≥ 0.72 on the golden query set"*, *"all P0 search-index integration tests green"*), not aspirational.
4. Each phase has named gates at its end.
5. Residual risks named honestly, with mitigation or acceptance reasoning.
6. Section-by-section confirmation; not a 5-page dump.

**Anti-patterns:**
- "Test plan: do the tests, sign off." (no actual criteria)
- Single-shot 5-section dump with no confirmation.
- Entry criteria like "team is ready" (not measurable).
- Residual risks: none listed.

---

## 10. Trivial change — no tests needed

**User prompt:** *"I'm fixing a typo in a comment in `docs/CONFIGURATION.md`. Anything I need to do?"*

**Skill activated:** `sumo-qa-deciding-approach` (terminates at the approach decision).

**Expected interaction shape:**
1. Classifies the change as `docs_change`.
2. Picks approach `no-tests-recommended` — and that IS the senior-QA answer here. Adding tests for a docs typo wastes signal.
3. Translates the taxonomy to natural English: NOT *"Classification: docs_change, Approach: no-tests-recommended"*, but *"this is a docs-only typo — no tests needed. Just check the doc still renders."*
4. Does NOT route to `sumo-qa-preparing-for-work` or `sumo-qa-reviewing-before-merge` — those are wrong shapes for the change.
5. Offers the lightweight follow-up: *"want me to verify it renders correctly with `mkdocs serve` or similar?"*

**Anti-patterns:**
- Adds tests to "be thorough".
- Forces the change through `sumo-qa-reviewing-before-merge` for a typo fix.
- Surfaces the internal classification/approach labels verbatim.
- Walks the user through a 5-section formal review for one character changed.

---

## 11. Router invocation — first-turn QA intent

**User prompt:** *"Help me QA this thing — I added a new pricing function `apply_seasonal_discount` in `pricing/seasonal.py`."*

**Skill activated:** `using-sumo-qa` (the router; should immediately route to `sumo-qa-deciding-approach` since the intent is QA-shaped).

**Expected interaction shape:**
1. The host LLM treats `using-sumo-qa` as the entry router for any QA-shaped intent — not as a content-bearing skill.
2. Loads the global discipline (knowledge authority hierarchy, output discipline, internal scaffolding stays internal, specialty-tool-fit discovery).
3. Hands off to `sumo-qa-deciding-approach` — does NOT attempt to plan, review, or scaffold inline.
4. The handoff happens *transparently* — the user sees the deciding-approach output, not a "switching to sumo-qa-deciding-approach" announcement.
5. The classification + approach decision is internal scaffolding; the user-facing first response is shaped by whichever sub-skill the routing lands on (here: `sumo-qa-preparing-for-work` for a new pricing function with no review-shaped or strategy-shaped framing).

**Anti-patterns:**
- Generates a plan, review, or scaffold inline without routing through `sumo-qa-deciding-approach` first.
- Surfaces *"Routing to sumo-qa-deciding-approach"* as if it were a chat message.
- Skips loading the global discipline (then violates output economy or surfaces internal taxonomy labels).
- Treats `using-sumo-qa` as a heavy entry point that demands its own scenario-shaped output — it's a router, not a deliverable.

---

## 12. Bite-sized, dispatchable plan from a chunk of QA work

**User prompt:** *"Take the Phase 1 work from our QA strategy (mutation baselines on `pricing/calculator.py` + `shared/money.py`, property-tests on rounding, Hypothesis fixtures) and turn it into a plan I can dispatch across subagents tomorrow."*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-planning-qa-rollout`.

**Expected interaction shape:**
1. Reads the strategy doc (or the cited Phase 1 scope) and the relevant production paths to anchor each task in evidence.
2. Walks scope → file structure → bite-sized tasks → confirm, **one section per turn** with confirmation gates (per the skill's checklist).
3. **Bite-sized = independently executable in a fresh subagent.** Each task names the prod file, the test file, the test technique, the expected red→green or strengthening pattern, and any test data fixture it owns.
4. Tagging: each task carries an Approach tag (`tdd-scaffold` / `regression-first` / `coverage-first-then-refactor` / `strengthen-test-coverage`) so `sumo-qa-executing-qa-rollout` knows which sub-skill the subagent should invoke.
5. **Iron Law:** NO EXECUTION FROM THE PLANNER. The plan is the deliverable. Production code stays untouched in this skill.
6. Final deliverable: a markdown file at `docs/qa/plans/YYYY-MM-DD-<feature>.md` (or wherever the user's repo configures plan storage), with each task in a structured block ready for subagent dispatch.

**Anti-patterns:**
- Begins implementing tests inline ("Iron Law violated — start the executor instead").
- Tasks shaped at "implement Phase 1" level (too big for a fresh subagent).
- Tasks named without anchoring file path, technique, or risk reference.
- Single-shot dump of all tasks without confirmation gates.
- Approach tag missing (downstream executor doesn't know which sub-skill to fire).

---

## 13. Dispatch a written plan task-by-task

**User prompt:** *"Run the plan at `docs/qa/plans/2026-05-15-phase4.2-mutation-strengthening.md`."*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-executing-qa-rollout`.

**Expected interaction shape:**
1. Reads the plan markdown; extracts each task block.
2. **One fresh subagent per task**, dispatched in parallel where the plan marks tasks as independent (no shared-state edits).
3. Each subagent invokes the sub-skill named by the task's Approach tag.
4. After each subagent returns, runs a **two-stage review**: (a) test-correctness review (does the test actually exercise the named risk?), (b) test-quality review (boundary coverage, exact-equality vs substring, no tautology).
5. **Continuous execution** — no per-task confirmation gates with the user once the plan is signed off (the planning skill already gathered confirmation).
6. Surfaces evidence per task in a single status line (task name → subagent verdict → review-stage verdict). Verbose only on failure.
7. On completion, routes to `sumo-qa-finishing-qa-work` to capture evidence and produce the PR-ready summary.

**Anti-patterns:**
- Pauses after every task to check in (the plan was already signed off; the executor's job is to drive).
- Skips the two-stage review and accepts subagent output verbatim.
- Edits the plan mid-execution ("found a better task structure") — if the plan needs changes, route back to `sumo-qa-planning-qa-rollout`.
- Single-shot review of all tasks at the end (per-task review catches drift early).

---

## 14. Capture evidence + produce a PR-ready summary at the end of a rollout

**User prompt:** *"All Phase 4.2 mutation tasks ran green. Wrap it up — I need something I can paste into the PR."*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-finishing-qa-work`.

**Expected interaction shape:**
1. **Iron Law:** NO FINISH WITHOUT FRESH EVIDENCE + WRITTEN SUMMARY. Runs the suite *in this turn* (does NOT cite "CI was green earlier"); captures pass/fail counts + duration + coverage %.
2. Captures the risk-to-test map: for each named risk in the plan, names the covering test (file + name) or flags it as uncovered.
3. Lists open follow-ups honestly — items deferred to a future PR, equivalent mutants suppressed with rationale, residual risks accepted.
4. Writes the summary to `docs/qa/runs/YYYY-MM-DD-<feature>.md`. Includes: evidence block, risk-to-test map, mutation/coverage figures, files touched, notable findings, known gaps + open follow-ups.
5. Offers to draft the PR description with the same evidence packaged for GitHub.

**Anti-patterns:**
- Declares "wrap-up complete" without running the suite in this turn.
- "All risks covered" without enumerating which test covers which risk.
- "Residual risks: none" (every multi-task rollout leaves residuals — naming none means you didn't think about it).
- Writes the summary to a path the user didn't agree to.
- Skips offering to draft the PR description.

---

## 15. No native sumo-qa fit — discover an external skill

**User prompt:** *"I want to add Playwright E2E tests for our checkout flow. None of your skills look right for that — what do I do?"*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-suggesting-external-skill`.

**Expected interaction shape:**
1. Recognises that Playwright setup is *outside* the native sumo-qa skill set (the catalogue is concept-level discipline; the tool-bring-up is implementation-level work).
2. Calls `sumo_qa_search_external_skills` to find current external skill candidates instead of using a remembered tool list.
3. Offers — with `[y/N]` confirmation — to install the chosen external skill through `sumo_qa_install_external_skill`.
4. **Never auto-installs** anything. The `[y/N]` is real; default is "no".
5. After install, calls `sumo_qa_execute_external_skill` and follows the returned `SKILL.md` body.
6. If Node.js / npx is missing, surfaces the MCP tool's actionable hint and stops — does NOT auto-elevate via sudo.

**Anti-patterns:**
- Hallucinates a specialty tool brand ("just use Playwright Cloud Runner") — the discovery rule from `using-sumo-qa` requires citation.
- Runs `npx skills ...` directly from the host shell instead of the sumo-qa MCP tools.
- Routes to `sumo-qa-implementing-with-tdd` and tries to scaffold Playwright tests inline (wrong shape — the user asked for skill discovery, not in-place TDD).
- Tries `sudo` to install Node.js without consent.

---

## 16. Close a review-named gap, one evidenced loop at a time

**User prompt:** *"Your review flagged three uncovered risks on the refund flow — close them, drive them to regression tests."*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-closing-qa-gaps`.

**Expected interaction shape:**
1. Scopes the loop to EXACTLY ONE of the three named gaps and parks the others by id, out loud (*"R2 and R3 are parked as later loops — I'll start the next one only when you ask."*).
2. Inspects the loop prerequisites with the host's file tools: the production file, the matching test file, and how to run the tests. **HARD GATE:** if any of the three cannot be inspected (no named gap, unreadable files, unknown test command), it refuses to start the loop this turn, names every missing prerequisite, and asks — no invented paths, no fabricated output, no generic plan in place of the pause.
3. Runs the inner cycle under the TDD skill's red-first discipline: focused failing-test idea (file, function, input, assertion, verbatim catalogue technique), red output captured verbatim BEFORE any production change.
4. After the minimum green change: green output + targeted regression counts captured; only then does the gap's recorded status move (a ledger row's `evidence_status` flips `failing`→`passing` quoting both evidence lines, with its `residual` resolved).
5. Closes the loop by offering — not starting — the next parked gap, in conditional form. The second loop begins only on an explicit ask.
6. Never says "safe to merge" — routes any merge question to `sumo-qa-reviewing-before-merge`.

**Anti-patterns:**
- Batches all three gaps in one pass (no per-loop evidence trail).
- Writes the production fix in the same turn as the failing test (no captured red).
- Marks a ledger row covered on wording alone, or flips a row whose evidence didn't change.
- Proceeds on assumed repo context instead of pausing when files can't be inspected.
- Treats "while you're in there, tidy the module" as authorization for a broad rewrite.

---

## 17. Take a mutation survivor through the closed loop

**User prompt:** *"mutmut left a survivor on `pricing/discounts.py:42` (`>` mutated to `>=`) — take it through the loop end to end."*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-closing-qa-gaps` (mutation-survivor entry).

**Expected interaction shape:**
1. Enters under the strengthening skill's Iron Law: **production code stays unchanged** while the test is strengthened to kill the survivor.
2. Anchors the survivor at both ends: its production location and mutation (`pricing/discounts.py:42` — `subtotal > 10000` → `>=`) AND the named strengthening test (file + test name), with the technique cited by its verbatim catalogue heading (boundary value analysis at `subtotal = 10000`, assertion polarity that the original passes and the mutant fails).
3. Only if the strengthened test exposes a genuine production defect does the loop continue into a red→green fix — surfaced as a separate, explicit decision, never silently.
4. Evidence discipline is unchanged from scenario 16: red captured before any change, green + regression before the status moves, one survivor per loop, next survivor only on explicit ask.

**Anti-patterns:**
- Edits production code before the test is strengthened ("easiest way to kill it").
- Tautological assertion that re-states the production expression.
- Walks every survivor in one batch.
- Claims the module is now safe to merge after one survivor is killed.

---

## 18. Triage an unknown-cause failing or flaky test

**User prompt:** *"`test_user_cache_hit` keeps failing in the full run but passes when I run it alone — sort it out."*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-triaging-test-failures` (approach: `triage-test-failure`).

**Expected interaction shape:**
1. Diagnosis is separated from fixing: the first output is a cause classification plus the smallest next isolation step, NOT a patch.
2. Secures the failure signal (the failing test name, the assertion/error, the traceback); if it is absent or too thin to classify, the HARD-GATE fires — names what is still needed and asks, this turn.
3. Classifies the cause against the six categories (product regression, test bug, fixture/data, environment/dependency, timing/order, external-service) with its evidence — here, passing alone but failing in the suite points at order/shared-state, not the product.
4. Names the smallest discriminating experiment matched to the cause (run the tests in randomised/reversed order), stating the hypothesis and what each outcome means. A rerun is allowed only tied to that hypothesis, never "run it until green".
5. Routes to a fixing skill (`regression-first` / `sumo-qa-closing-qa-gaps`) ONLY when the confirmed cause is a concrete product-behaviour gap; test/fixture/environment/order/external causes are resolved in their own layer with production untouched.

**Anti-patterns:**
- Reruns to green with no stated hypothesis, or normalises the flake as residual risk without the user's explicit acceptance.
- Patches production code for a failure whose cause is a test/fixture/environment/order/external issue.
- Classifies from the test name alone, or invents a traceback the context did not supply.
- Proposes a fix before naming the cause and an isolation step.

---

## 19. Focus security-testing evidence

**User prompt:** *"Security-test the new password reset flow."*

**Skill activated:** `sumo-qa-deciding-approach` → routes to `sumo-qa-security-testing` (approach: `security-focused-qa`).

**Expected interaction shape:**
1. Starts from a grounded source anchor: the user-stated flow, named files, config/dependency, or routed security gap. If none exists, asks one scope question instead of inventing vulnerabilities.
2. Uses existing `security_change` rules/standards/techniques; does not introduce a parallel vulnerability taxonomy.
3. Names concrete failure modes, such as token expiry, replay/single-use, tampering, account enumeration, missing ownership guard, permissive config, or dependency movement, limited to the supplied evidence.
4. Chooses the smallest evidence type by fit: native test, review, static check, dynamic check, config check, dependency check, fuzz/property check, or external tool/skill.
5. Recommends external tooling only after native evidence is insufficient and stack/scope are known; dependency installs, scanner setup, external-skill execution, and live/invasive probing require confirmation.
6. Returns the compact security brief: grounded risk, source anchor, evidence choice, first action, and residual risk.

**Anti-patterns:**
- Dumps OWASP categories, a vulnerability checklist, or a scanner roster.
- Recommends ZAP/Burp/Snyk/SAST before stack/scope and native evidence fit are checked.
- Claims security vulnerabilities without an anchor in files, flow, config, dependency, or user scope.
- Treats a scanner clean result as proof that a specific risk is covered.

---

## How to validate these scenarios

Three complementary paths:

**1. Static review of the skills (free, ongoing):** for each scenario above, open the matching skill under `skills/<name>/SKILL.md` and check that its checklist, HARD-GATE, examples, and red-flag rows would produce the "Expected interaction shape" and prevent the "Anti-patterns". The skills are written so this static check is meaningful — they enforce structure, not just describe it.

**2. Live agent role-play (one-shot, captured under `worked-examples/`):** an agent reads the relevant skill, role-plays the scenario, and produces the first-turn response. These are captured as worked examples and serve as the visible "what good looks like" reference. They're not re-run on every commit (would cost API credits each time); they're a point-in-time validation that the skill works on a real scenario.

**3. Deterministic trigger-routing harness (CI gate, every commit):** [`tests/test_skill_triggering.py`](../test_skill_triggering.py) reads [`tests/fixtures/skill_triggers.yaml`](../fixtures/skill_triggers.yaml) — a machine-readable prompt → expected-skill matrix — and asserts every skill tool is (a) registered and (b) triggerable by at least one user-natural phrase pinned in the fixture. No live LLM; runs in the standard pytest suite. Add a row to the fixture, not the test, when adding coverage for a new prompt or skill. Catches the silent-mis-routing failure mode where a description rewording drops the trigger phrase the host LLM was relying on. Complements (does not replace) the LLM-judged routing evals under [`tests/evals/promptfoo/`](../evals/promptfoo/), which remain optional and need `OPENAI_API_KEY`.

**4. Deterministic conformance validator (CI gate, no LLM):** [`CONFORMANCE.md`](CONFORMANCE.md) documents a machine-readable fixture ([`conformance/scenarios.yaml`](conformance/scenarios.yaml)) that encodes the routing + tool-call + output-marker contract for the scenarios above, seeded directly from these headings. The validator ([`../../src/sumo_qa/conformance.py`](../../src/sumo_qa/conformance.py)) scores a captured host/tool-call transcript against a scenario and fails it on a wrong-skill route, a missing required tool call, a forbidden tool call, or a forbidden output claim. It goes beyond trigger-phrase presence (path 3) by checking what the host actually did across the turn, still without a live LLM. Tests: [`../test_conformance_transcript_validator.py`](../test_conformance_transcript_validator.py).

The behavioural-shape and anti-pattern checks above are NOT asserted by the deterministic harness — those are LLM-quality questions and live in static review + role-play + the optional promptfoo evals.
