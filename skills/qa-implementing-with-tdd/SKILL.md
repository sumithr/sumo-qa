---
name: qa-implementing-with-tdd
description: Use after qa-deciding-approach picks tdd-scaffold, regression-first, or coverage-first-then-refactor. Walks plan → name-the-risk-and-test-idea → confirm → red → hand off → green → review, one section per turn with confirmation gates. Don't write the test until the test idea has been agreed.
---

# Implementing with TDD

Help the user drive a change through TDD discipline by walking the cycle one step at a time, confirming the test idea before writing it, and proving the red phase happened before handing back the green-making step. The user has product context (what "wrong" looks like, what shape the API should take) the AI can't infer from code alone — surface it through questions, don't assume it.

**Announce at start:** *"I'm using qa-implementing-with-tdd to walk the red→green cycle with confirmation between phases."*

## Output discipline (mandatory)

**Never surface internal taxonomy labels in user-facing output.** No "Classification: X", "Approach: Y", "Per the checklist", "Step 3 of 6". The taxonomy is internal scaffolding; translate to natural English when the meaning matters to the user — *"this is a behaviour change in pricing"*, not *"Classification: business_logic_change"*. If you catch yourself typing a label, delete it.

Inherits the global discipline from `using-sumo-qa` (knowledge authority hierarchy, internal scaffolding stays internal, specialty-tool fit).

<HARD-GATE>
Do NOT write the failing test in the same turn you propose the test idea. Walk through risk → assertion shape → smallest failing test → confirm → write → run → show red. Tests written before the user agrees on what they're meant to catch are guesses, not red-phase evidence.
</HARD-GATE>

## The Iron Law

**RED PHASE FIRST. NO PRODUCTION CODE BEFORE A FAILING TEST.** A test that has never failed has never tested anything — the red phase is the proof.

## When to Use

`qa-deciding-approach` routes here when the approach is one of:

- `tdd-scaffold` (greenfield-ish behaviour being added)
- `regression-first` (bug fix on existing code; reproduce as failing test first)
- `coverage-first-then-refactor` (behaviour-preserving refactor; characterization tests pin behaviour BEFORE the refactor)

For `strengthen-test-coverage` (mutation follow-up), route to `qa-strengthening-tests` instead — that has different discipline (production code stays locked).

## Checklist

You MUST work through these in order. Steps 1–3 are AI-only homework (no user questions). The user's confirmation gates steps 4 onward.

1. **Re-state the approach and the named risk** *(no user question)* — restate which TDD-shaped approach we're in and the named risk this cycle targets. If no risk was named, route to `qa-preparing-for-work` first.

2. **Walk the repo for the target** *(no user question)* — use the host's file tools. Find (a) the production file the change touches, (b) the matching test file (or where one belongs), (c) the existing test style (framework, fixtures, assertion library), (d) for regression-first: the failing path that reproduces the bug. Don't ask the user "what test framework?" — read a sibling test file.

3. **Pick the smallest failing test idea** *(no user question)* — name the function under test, the input that triggers the risk, and the assertion that distinguishes broken from fixed. Tautology check: if the assertion re-states the production code, pick an observable outcome instead.

4. **Confirm the test idea, only for the AMBIGUOUS parts** — present a short paragraph naming target, fixture style, and proposed assertion, then ask ONE focused question for what code couldn't answer (e.g. *"is 90.0 the correct expected value, or does VIP stack with promo?"*). If unambiguous, skip the question.

5. **Write the failing test** — use the host's edit tool. Do NOT ask the user to write it. Match the sibling tests' framework and fixture style.

6. **Run the test and SHOW THE RED OUTPUT** — capture the actual assertion failure (expected vs. got, line number). Import/syntax/fixture errors are NOT red — adjust until you see a real assertion failure for the right reason. Surface verbatim.

7. **Hand off to the user** — *"red phase confirmed. Implement to make it green; I'll re-run when you're ready. If you'd like me to also write the production code, say so."* Wait.

8. **Re-run after green-making change** — confirm it passes for the right reason (not because the assertion was weakened). If it fails, surface the new failure — don't try a second production change without the user.

9. **Run targeted regression** — run the changed file's test module + closest siblings. Surface pass/fail counts. Confirm no green-to-red elsewhere.

10. **Route to review** — offer to hand off to `qa-reviewing-before-merge`. Don't claim "safe to merge" from this skill.

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
| "Mutation testing fits here" | Wrong skill. Mutation follow-up is `qa-strengthening-tests`. |
| "User asked for the test, not prod code — I'll write both anyway" | Confirm. The TDD discipline only works if the user owns the green-making step (or asks explicitly). |

## Examples

### Good (explore first, confirm test idea, then write)

> **User:** *"Fix the VIP-double-discount bug regression-first."*
>
> **AI (homework):** finds `pricing/discount_calculator.py:apply_discounts()` and `pricing/test_discount_calculator.py` (pytest + `Order` fixtures); proposes calling `apply_discounts(order_with_vip_and_promo)` asserting `order.total == 90.0`.
>
> **AI (confirm):** *"Smallest failing test will assert `order.total == 90.0`. **Is 90.0 right — does VIP stack with promo or override it?**"*
>
> **User:** *"VIP overrides promo entirely."*
>
> **AI:** writes the test, runs it, captures `AssertionError: assert 80.0 == 90.0` at `test_discount_calculator.py:47`, surfaces verbatim, hands off for the green-making change.

### Bad (write test and prod fix together)

> **User:** *"Fix the VIP-double-discount bug regression-first."*
>
> **AI:** edits `apply_discounts()` to short-circuit when `customer_tier=VIP`, adds an assertion, runs the suite, reports green.
>
> Iron Law violated. No red phase, no proof the test catches the bug — the assertion may pass on broken code too.

## Next skill in the chain

When green is confirmed and the targeted regression passes → `qa-reviewing-before-merge` to deliver the safe-to-merge verdict against fresh evidence.

If this task is part of a multi-task rollout dispatched by `qa-executing-qa-rollout` → `qa-finishing-qa-work` instead, to capture the evidence and produce the PR-ready summary.
