# Real-world QA scenarios

Ten scenarios sumo-qa is designed to handle. Each one captures: the user's actual prompt, which skill activates, the *shape* of the interaction the user should see, and what would tell you the interaction has gone wrong.

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

## How to validate these scenarios

Two complementary paths:

**1. Static review of the skills (free, ongoing):** for each scenario above, open the matching skill under `skills/<name>/SKILL.md` and check that its checklist, HARD-GATE, examples, and red-flag rows would produce the "Expected interaction shape" and prevent the "Anti-patterns". The skills are written so this static check is meaningful — they enforce structure, not just describe it.

**2. Live agent role-play (one-shot, captured under `worked-examples/`):** an agent reads the relevant skill, role-plays the scenario, and produces the first-turn response. These are captured as worked examples and serve as the visible "what good looks like" reference. They're not re-run on every commit (would cost API credits each time); they're a point-in-time validation that the skill works on a real scenario.

**Not validated by:** pytest assertions against agent output. The static skill review + the worked examples are the validation; pytest is reserved for code-level correctness (the 148 tests in `tests/`).
