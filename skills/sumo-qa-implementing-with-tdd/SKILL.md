---
name: sumo-qa-implementing-with-tdd
description: Use after sumo-qa-deciding-approach picks tdd-scaffold, regression-first, or coverage-first-then-refactor — e.g. "write a regression test for this bug" or "scaffold the failing tests first". Walks plan → name-the-risk-and-test-idea → confirm → red → hand off → green → review, one section per turn with confirmation gates. Don't write the test until the test idea has been agreed.
---

# Implementing with TDD

Drive a change through TDD discipline: walk the cycle one step at a time, confirm the test idea before writing it, prove the red phase before handing back the green-making step. The user has product context (what "wrong" looks like, the API shape) the AI can't infer from code — surface it through questions, don't assume.

**Announce at start:** *"Walking the red→green cycle."*

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: **output discipline** (never surface internal taxonomy labels — say *"behaviour change in pricing"*, not *"Classification: business_logic_change"*), **output economy** (spend output on findings not framing; no preamble or self-narration; one question per turn; no closing pleasantries), knowledge authority hierarchy, internal scaffolding stays internal, and specialty-tool fit.

<HARD-GATE>
Do NOT write the failing test in the same turn you propose the test idea. Walk: risk → assertion shape → smallest failing test → confirm → write → run → show red. Tests written before the user agrees what they catch are guesses, not red-phase evidence.
</HARD-GATE>

## The Iron Law

**RED PHASE FIRST. NO PRODUCTION CODE BEFORE A FAILING TEST.** A test that has never failed has never tested anything — the red phase is the proof.

**Stub allowance — narrow.** A production-side stub is permitted in the red phase ONLY when the test can't otherwise be collected (e.g. the function under test doesn't exist yet, so the test file fails at import). It must be signature-only: `def apply_discounts(order): raise NotImplementedError` or `: pass`. **Any behaviour in the stub — a partial implementation, a heuristic return, a branch that happens to satisfy the assertion — is an Iron Law violation:** the red phase would then prove the stub matches the assertion, not that the test catches the bug. Writing `if`/`else` or computing a value in the stub → stop; that's green-phase work for the user.

## When to Use

`sumo-qa-deciding-approach` routes here for: `tdd-scaffold` (greenfield-ish new behaviour), `regression-first` (bug fix — reproduce as a failing test first), or `coverage-first-then-refactor` (behaviour-preserving refactor — characterization tests pin behaviour BEFORE the refactor).

For `strengthen-test-coverage` (mutation follow-up), route to `sumo-qa-strengthening-tests` instead — different discipline (production code stays locked).

## Checklist

You MUST work through these in order. Steps 1–3 are AI-only homework (no user questions). The user's confirmation gates steps 4 onward.

1. **Re-state the approach and the named risk** *(no user question)* — restate the TDD-shaped approach and the named risk this cycle targets. If no risk was named, route to `sumo-qa-preparing-for-work` first.

2. **Walk the repo for the target** *(no user question)* — use the host's file tools. Find (a) the production file touched, (b) the matching test file (or where one belongs), (c) the existing test style (framework, fixtures, assertions), (d) for regression-first: the failing path that reproduces the bug. Don't ask "what test framework?" — read a sibling test file.

3. **Pick the smallest failing test idea** *(no user question)* — first call `sumo_qa_load_techniques()` if not already loaded (this skill owns that load; the router does not pre-load it). Then name (a) the target test file path, (b) the function under test, (c) the input that triggers the risk, (d) the assertion that distinguishes broken from fixed, and (e) the test-design technique from that loaded `sumo_qa_load_techniques()` catalogue, justified by this risk. The technique MUST be the verbatim catalogue heading (lowercase, with the catalogue's suffix — e.g. "decision tables", "state transition testing", "boundary value analysis", "equivalence partitioning", "exploratory testing", "pairwise testing"); don't paraphrase, title-case, or shorten it. **Tautology check:** if the assertion re-states the production code, pick an observable outcome instead. **Setup-discriminator check:** if the test setup makes broken and fixed implementations produce the same outcome, redesign it so they diverge — e.g. a mock that rejects on first call but resolves on second when testing rejection-cache invalidation. **Expected-value derivation check:** derive the expected value from the SPECIFIC input by applying the domain rule, never recall a generic fact. Trace input → rule → expected in one line before pinning (e.g. *"Jan 31, anchor 31 → Feb 2024 has 29 days (leap year) → expected 2024-02-29"*). If the trace doesn't name the input-specific fact (leap-year status for THAT year, length of THAT month, offset of THAT date, locale of THAT string), the expected value is a guess — a broken impl that hardcodes the same generic (Feb=28, all-months=30, UTC=+0) passes the assertion and the test never discriminates.

   - For `coverage-first-then-refactor` characterization tests, every fixture value (strings, numbers, identifiers) MUST be copied verbatim from the ground-truth context — never paraphrase or shorten; the asserted output must be exactly what the function currently produces.
   - For characterization tests, prefer techniques that pin existing behaviour: `equivalence partitioning` or `exploratory testing` charters. Avoid `use case testing` — that fits new-behaviour scaffolding, not pinning existing behaviour.
   - When the function under test parses/matches an external CLI/API's output (greps stdout, regex-matches a response body or log line), the technique is `real-capture fixtures for external-output matchers`: capture the tool's REAL output to the fixture FIRST (run it, redirect to a file), THEN write the matcher. An invented fixture validates against your assumption, not the real contract — green but meaningless (e.g. a hook grepping `mutmut run` for `survived` passes a fabricated fixture yet never fires, because real output is emoji counters like `🙁 4`).

4. **Confirm the test idea, only for the AMBIGUOUS parts** — name target, fixture style, and proposed assertion, then ask ONE focused question for what code couldn't answer (e.g. *"is 90.0 right, or does VIP stack with promo?"*). If unambiguous, skip the question.

5. **Write the failing test** — use the host's edit tool. Do NOT ask the user to write it. Match the sibling tests' framework and fixture style.

6. **Run the test and SHOW THE RED OUTPUT** — capture the actual assertion failure (expected vs. got, line number). Import/syntax/fixture errors are NOT red — adjust until you see a real assertion failure for the right reason. Surface verbatim.

7. **Hand off to the user** — end with EXACTLY one of these two phrasings (no pleasantries, no confirmation question, no "shall I"):
   - if you've shown the actual red assertion failure: "red phase confirmed. Implement to make it green; I'll re-run when ready. If you'd like me to write the production code, say so."
   - if no real red output yet: "I'll run this and surface the assertion failure next."
   Wait.

8. **Re-run after green-making change** — confirm it passes for the right reason (not a weakened assertion). If it fails, surface the new failure — don't try a second production change without the user.

9. **Run targeted regression** — run the changed file's test module + closest siblings. Surface pass/fail counts. Confirm no green-to-red elsewhere.

10. **Route to review** — offer to hand off to `sumo-qa-reviewing-before-merge`. Don't claim "safe to merge" from this skill.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags — STOP and rework

| Thought | Reality |
|---|---|
| "I'll write the test AND the production code in one turn" | Iron Law violated. Red phase first, separately, with evidence shown. |
| "I'll write the test idea AND the test in the same message" | HARD-GATE. Test idea → confirm → write → run; the gate catches misaligned assertions. |
| "Test passed on first run — must already be correct" | The test is wrong; it's not testing what you think. Tighten the assertion until you can see it fail. |
| "Failed with import / syntax / fixture error — that's red" | Not red. A red test fails on its assertion, not on a precondition. |
| "I'll ask the user what test framework they use" | Read a sibling test file. The repo answers that. |
| "Assertion: `assert add(2,3) == 2+3`" | Tautology. The broken code passes this too. Pick an outcome the bug changes. |
| "February has 28 days, so `anchorDay=31` lands on the 28th" | Recall, not derivation. Feb 2024 has 29 days; Feb 2023 has 28. Trace input → rule → expected for THIS input. Same trap: *"UTC offset is +0"*, *"ASCII is 7-bit"* — year/locale/encoding-dependent. A broken impl that hardcodes the same generic passes the assertion. |
| "I'll stub the prod function with `return total * 0.9` so the test fails meaningfully" | Iron Law violated via the stub. Red-phase stubs are signature-only (`pass` / `raise NotImplementedError`); the 0.9 belongs in the user's green phase. |
| "Mutation testing fits here" | Wrong skill. Mutation follow-up is `sumo-qa-strengthening-tests`. |

## Examples

### Good (explore, confirm idea, write)

> **User:** *"Fix the VIP-double-discount bug regression-first."*
>
> **AI (homework):** finds `pricing/discount_calculator.py:apply_discounts()` + test file `pricing/test_discount_calculator.py` (pytest, `Order` fixtures); applies decision tables for the VIP/promo combination; proposes `apply_discounts(order_with_vip_and_promo)` asserting `order.total == 90.0`.
>
> **AI (confirm):** *"Test will assert `order.total == 90.0`. **Is 90.0 right — does VIP stack with promo or override it?**"* → **User:** *"VIP overrides promo."* → **AI:** writes the test, runs it, captures `AssertionError: assert 80.0 == 90.0` at `test_discount_calculator.py:47` verbatim, hands off for the green change.

### Good (stateful mock)

> **User:** *"Fix the async memoizer rejection-caching bug regression-first. If the wrapped function rejects, that failure must not poison the cache; a later call for the same key should retry."*
>
> **AI (proposed test idea):** finds `src/cache/memoizeAsync.js:memoizeAsync()` + test file `test/cache/memoizeAsync.test.js` (jest). *"Function `memoizeAsync`; input is a `jest.fn` that rejects ONCE then resolves on retry; assert `memoized(key)` rejects on the first call and resolves to the success value on the second (with `fn` called twice). Technique: state transition testing (no-entry → rejected → retried-then-resolved). Setup-discriminator: the mock must reject-once-then-resolve, NOT always-reject — broken impl caches the rejection (second await rejects); fixed impl retries (second await resolves)."*
>
> **AI (writes test):**
> ```js
> test('does not cache rejected promises; retries on next call', async () => {
>   const fn = jest.fn()
>     .mockRejectedValueOnce(new Error('Failed'))
>     .mockResolvedValue('value:a');
>   const memoized = memoizeAsync(fn);
>
>   await expect(memoized('a')).rejects.toThrow('Failed');
>   await expect(memoized('a')).resolves.toBe('value:a');
>   expect(fn).toHaveBeenCalledTimes(2);
> });
> ```
>
> Discriminator: broken `memoizeAsync` caches the rejection, so the second `await` re-rejects (red); fixed re-invokes `fn` and resolves to `'value:a'` (green). The reject-once-then-resolve mock is what makes broken and fixed diverge.

### Bad (test + prod fix together)

> **AI** (same VIP bug): edits `apply_discounts()` to short-circuit on `customer_tier=VIP`, adds an assertion, runs the suite, reports green.
>
> Iron Law violated. No red phase, no proof the test catches the bug — the assertion may pass on broken code too.

### Bad (recalled expected value, not derived from the specific input)

> **User:** *"Regression test for `nextChargeDate(date, anchorDay)` — Jan 31 anchored to 31 should land on the last valid day of Feb."*
>
> **AI:** *"Assert `nextChargeDate(LocalDate.of(2024, 1, 31), 31) == LocalDate.of(2024, 2, 28)`. Technique: boundary value analysis."*
>
> Expected-value derivation fails: 2024 is a leap year, so Feb 2024's last day is the 29th. The candidate recalled *"Feb has 28 days"* instead of computing from this input — a broken impl hardcoded to Feb=28 passes the assertion. Fix: trace first (*"Jan 31, anchor 31 → Feb 2024 has 29 days → expected 2024-02-29"*), then pin `LocalDate.of(2024, 2, 29)`. Stronger: parametrise across `2024-01-31 → 2024-02-29` AND `2023-01-31 → 2023-02-28` so leap-year clamping becomes its own discriminator.

## Next skill in the chain

Green confirmed + targeted regression passes → `sumo-qa-reviewing-before-merge` for the safe-to-merge verdict against fresh evidence. If part of a rollout dispatched by `sumo-qa-executing-qa-rollout` → `sumo-qa-finishing-qa-work` instead, to capture evidence and produce the PR-ready summary.
