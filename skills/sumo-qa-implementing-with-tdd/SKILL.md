---
name: sumo-qa-implementing-with-tdd
description: Use after sumo-qa-deciding-approach picks tdd-scaffold, regression-first, or coverage-first-then-refactor. Walks plan → name-the-risk-and-test-idea → confirm → red → hand off → green → review, one section per turn with confirmation gates. Don't write the test until the test idea has been agreed.
---

# Implementing with TDD

Help the user drive a change through TDD discipline by walking the cycle one step at a time, confirming the test idea before writing it, and proving the red phase happened before handing back the green-making step. The user has product context (what "wrong" looks like, what shape the API should take) the AI can't infer from code alone — surface it through questions, don't assume it.

**Announce at start:** *"Walking the red→green cycle."*

## Output discipline (mandatory)

**Never surface internal taxonomy labels in user-facing output.** No "Classification: X", "Approach: Y", "Per the checklist", "Step 3 of 6". The taxonomy is internal scaffolding; translate to natural English when the meaning matters to the user — *"this is a behaviour change in pricing"*, not *"Classification: business_logic_change"*. If you catch yourself typing a label, delete it.

Inherits the global discipline from `using-sumo-qa` (knowledge authority hierarchy, internal scaffolding stays internal, specialty-tool fit).

## Output economy (mandatory)

Spend output tokens on findings, not framing.

- **Don't preamble the work.** Spend user-visible output on findings, evidence, and gates — don't narrate *"I'll first read X, then Y, then deliver Z."*
- **One question per turn.** Don't follow a question with *"shall I proceed or clarify first?"* — the question IS the gate.
- **No self-narration.** *"Let me now..."* / *"I'm going to..."* → just do it.
- **Don't restate the user's input.** They know what they asked.
- **Section headings only when there are genuinely multiple sections.** A 3-line scope check doesn't need a `## Scope` heading.
- **Tables only when comparing >2 things on >2 axes.** Otherwise prose is shorter.
- **No closing pleasantries.** No *"happy to dig deeper"* / *"let me know if you want X"* — the next-skill handoff at the bottom of every skill is where routing lives.

<HARD-GATE>
Do NOT write the failing test in the same turn you propose the test idea. Walk through risk → assertion shape → smallest failing test → confirm → write → run → show red. Tests written before the user agrees on what they're meant to catch are guesses, not red-phase evidence.
</HARD-GATE>

## The Iron Law

**RED PHASE FIRST. NO PRODUCTION CODE BEFORE A FAILING TEST.** A test that has never failed has never tested anything — the red phase is the proof.

**Stub allowance — narrow.** A production-side stub is permitted in the red phase ONLY when the test cannot otherwise be collected or imported (e.g. the function under test does not exist yet, so the test file fails at import). The stub must be the smallest signature-only shape that lets the test reach its assertion: `def apply_discounts(order): raise NotImplementedError` or `def apply_discounts(order): pass` returning a default. **Any behaviour in the stub — a partial implementation, a heuristic return, a branch that happens to satisfy the assertion — is an Iron Law violation,** because the red phase is no longer proving the test catches the bug, it's proving the stub matches the assertion. If you find yourself writing `if`/`else` or computing a value in the stub, stop — that work belongs in the green phase, handed back to the user.

## When to Use

`sumo-qa-deciding-approach` routes here when the approach is one of:

- `tdd-scaffold` (greenfield-ish behaviour being added)
- `regression-first` (bug fix on existing code; reproduce as failing test first)
- `coverage-first-then-refactor` (behaviour-preserving refactor; characterization tests pin behaviour BEFORE the refactor)

For `strengthen-test-coverage` (mutation follow-up), route to `sumo-qa-strengthening-tests` instead — that has different discipline (production code stays locked).

## Checklist

You MUST work through these in order. Steps 1–3 are AI-only homework (no user questions). The user's confirmation gates steps 4 onward.

1. **Re-state the approach and the named risk** *(no user question)* — restate which TDD-shaped approach we're in and the named risk this cycle targets. If no risk was named, route to `sumo-qa-preparing-for-work` first.

2. **Walk the repo for the target** *(no user question)* — use the host's file tools. Find (a) the production file the change touches, (b) the matching test file (or where one belongs), (c) the existing test style (framework, fixtures, assertion library), (d) for regression-first: the failing path that reproduces the bug. Don't ask the user "what test framework?" — read a sibling test file.

3. **Pick the smallest failing test idea** *(no user question)* — name (a) the target test file path, (b) the function under test, (c) the input that triggers the risk, (d) the assertion that distinguishes broken from fixed, and (e) the test-design technique applied from the loaded `sumo_qa_load_techniques()` catalogue, justified by this risk's shape. Technique name MUST be the verbatim catalogue heading (lowercase, with any suffix the catalogue uses — e.g. "decision tables", "state transition testing", "boundary value analysis", "equivalence partitioning", "exploratory testing", "pairwise testing"). Do not paraphrase, title-case, or shorten the catalogue heading. Tautology check (assertion): if the assertion re-states the production code, pick an observable outcome instead. Setup-discriminator check (mocks/fixtures): if the test setup makes the broken and fixed implementations produce the same outcome, redesign the setup so they produce different outcomes — e.g. a mock that rejects on first call but resolves on second when testing rejection-cache invalidation.

   - For `coverage-first-then-refactor` characterization tests, every fixture value (strings, numbers, identifiers) MUST be copied verbatim from the ground-truth context. Do not paraphrase, simplify, or shorten any value. The asserted output must be exactly what the function currently produces: copy/paste, never summarize.
   - For characterization tests, prefer techniques that pin existing behavior: `equivalence partitioning` (pin the branch that fires for each input class) or `exploratory testing` charters (capture observed behavior in time-boxed exploration). Avoid `use case testing` for characterization work; that technique fits new-behavior scaffolding, not pinning existing behavior.

4. **Confirm the test idea, only for the AMBIGUOUS parts** — present a short paragraph naming target, fixture style, and proposed assertion, then ask ONE focused question for what code couldn't answer (e.g. *"is 90.0 the correct expected value, or does VIP stack with promo?"*). If unambiguous, skip the question.

5. **Write the failing test** — use the host's edit tool. Do NOT ask the user to write it. Match the sibling tests' framework and fixture style.

6. **Run the test and SHOW THE RED OUTPUT** — capture the actual assertion failure (expected vs. got, line number). Import/syntax/fixture errors are NOT red — adjust until you see a real assertion failure for the right reason. Surface verbatim.

7. **Hand off to the user** — end with EXACTLY one of two phrasings, no closing pleasantries, no confirmation questions, no "shall I":
   - if you've shown the actual red assertion failure: "red phase confirmed. Implement to make it green; I'll re-run when ready. If you'd like me to write the production code, say so."
   - if no real red output yet: "I'll run this and surface the assertion failure next."
   Wait.

8. **Re-run after green-making change** — confirm it passes for the right reason (not because the assertion was weakened). If it fails, surface the new failure — don't try a second production change without the user.

9. **Run targeted regression** — run the changed file's test module + closest siblings. Surface pass/fail counts. Confirm no green-to-red elsewhere.

10. **Route to review** — offer to hand off to `sumo-qa-reviewing-before-merge`. Don't claim "safe to merge" from this skill.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags — STOP and rework

| Thought | Reality |
|---|---|
| "I'll write the test AND the production code in one turn" | Iron Law violated. Red phase first, separately, with evidence shown. |
| "Test passed on first run — must have already been implemented correctly" | The test is wrong. It's not testing what you think. Tighten the assertion until you can see it fail. |
| "Failed with import error / syntax error / fixture error — that counts as red" | Not red. A red test fails on its assertion, not on a precondition. |
| "I'll ask the user what test framework they use" | Read a sibling test file. The repo answers that. |
| "Regression check is overkill for a small change" | Targeted regression is cheap and catches nasty surprises. Run it. |
| "I'll write the test idea AND write the test in the same message" | Walk through. Test idea → confirm → write → run. The confirmation gate is what catches misaligned assertions. |
| "Assertion: `assert add(2,3) == 2+3`" | Tautology. The broken code passes this too. Pick an outcome the bug changes. |
| "I'll stub the production function with a quick `return total * 0.9` so the test fails meaningfully" | Iron Law violated via the stub. Stubs in red phase are signature-only (`pass` / `raise NotImplementedError`). The 0.9 belongs in the green phase the user writes. |
| "Mutation testing fits here" | Wrong skill. Mutation follow-up is `sumo-qa-strengthening-tests`. |
| "User asked for the test, not prod code — I'll write both anyway" | Confirm. The TDD discipline only works if the user owns the green-making step (or asks explicitly). |

## Examples

### Good (explore first, confirm test idea, then write)

> **User:** *"Fix the VIP-double-discount bug regression-first."*
>
> **AI (homework):** finds `pricing/discount_calculator.py:apply_discounts()` and target test file `pricing/test_discount_calculator.py` (pytest + `Order` fixtures); applies decision tables for the VIP/promo rule combination; proposes calling `apply_discounts(order_with_vip_and_promo)` asserting `order.total == 90.0`.
>
> **AI (confirm):** *"Smallest failing test will assert `order.total == 90.0`. **Is 90.0 right — does VIP stack with promo or override it?**"*
>
> **User:** *"VIP overrides promo entirely."*
>
> **AI:** writes the test, runs it, captures `AssertionError: assert 80.0 == 90.0` at `test_discount_calculator.py:47`, surfaces verbatim, hands off for the green-making change.

### Good (stateful mock for rejection-cache)

> **User:** *"Fix the async memoizer rejection-caching bug regression-first. If the wrapped function rejects, that failure must not poison the cache; a later call for the same key should retry."*
>
> **AI (homework):** finds `src/cache/memoizeAsync.js:memoizeAsync()` and target test file `test/cache/memoizeAsync.test.js` (jest); applies `state transition testing` for the cache-state transitions (no-entry → rejected → retried-then-resolved); recognises that a mock returning the same outcome on every call (always-reject or always-resolve) makes the test indistinguishable between broken and fixed.
>
> **AI (proposed test idea):** *"Target file `test/cache/memoizeAsync.test.js`; function `memoizeAsync`; input is a `jest.fn` that rejects ONCE then resolves on retry; assertion is that `memoized(key)` rejects on first call and resolves to the success value on second call (with `fn` called twice). Technique: state transition testing. Setup-discriminator check: mock must reject-once-then-resolve, NOT always-reject — broken impl caches the rejection (second await rejects); fixed impl retries (second await resolves)."*
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
> Why this passes the discriminator check: a broken `memoizeAsync` caches the rejected promise, so the SECOND `await memoized('a')` would re-reject (test fails). A fixed `memoizeAsync` re-invokes `fn`, gets the resolved value, and the second `await` returns `'value:a'` (test passes after fix, fails before fix). The mock's stateful behaviour (first-call reject, subsequent-call resolve) is what makes broken and fixed produce different outcomes.

### Bad (write test and prod fix together)

> **User:** *"Fix the VIP-double-discount bug regression-first."*
>
> **AI:** edits `apply_discounts()` to short-circuit when `customer_tier=VIP`, adds an assertion, runs the suite, reports green.
>
> Iron Law violated. No red phase, no proof the test catches the bug — the assertion may pass on broken code too.

## Next skill in the chain

When green is confirmed and the targeted regression passes → `sumo-qa-reviewing-before-merge` to deliver the safe-to-merge verdict against fresh evidence.

If this task is part of a multi-task rollout dispatched by `sumo-qa-executing-qa-rollout` → `sumo-qa-finishing-qa-work` instead, to capture the evidence and produce the PR-ready summary.
