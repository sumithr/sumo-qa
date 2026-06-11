---
name: sumo-qa-strengthening-tests
description: Use after sumo-qa-deciding-approach picks strengthen-test-coverage. Mutation-testing follow-up, raise-coverage tasks, killing weak assertions. Walks survivor → tautology check → technique → strengthening test, one mutant at a time with confirmation gates. Production code STAYS UNCHANGED.
---

# Strengthening tests

Help the user kill weak assertions and surviving mutants by walking each survivor one at a time: triage tautology vs real, pick a technique, draft the strengthening test, confirm. The user has judgement context (is this mutant "real" given how the code is consumed in practice?) the AI can't infer from the report alone — surface it through questions, don't assume it.

**Announce at start:** *"Killing the mutation survivors, one at a time."*

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: **output discipline** (never surface internal taxonomy labels — say *"behaviour change in pricing"*, not *"Classification: business_logic_change"*), **output economy** (spend output on findings not framing; no preamble or self-narration; one question per turn; no closing pleasantries), knowledge authority hierarchy, internal scaffolding stays internal, and specialty-tool fit.

<HARD-GATE>
Do NOT touch production code in this skill. Ever. If a mutant survives because the production code is wrong, that is a separate `regression-first` task — STOP this flow and route to `sumo-qa-implementing-with-tdd`. The Iron Law has no exceptions for "while I'm in here".
</HARD-GATE>

## The Iron Law

**PRODUCTION CODE STAYS UNCHANGED.** Only test code moves; equivalent mutants get suppressed in tool config, not "killed" by tautological tests that re-state the production code.

## When to Use

`sumo-qa-deciding-approach` routes here for `strengthen-test-coverage`. User intents:

- "raise coverage on module X"
- "Pitest shows N surviving mutants — kill them"
- "Stryker / mutmut surfaced weak assertions"
- "strengthen the tests on the order calculator"

Production code is locked. The job is to make the EXISTING tests stronger.

## Checklist

You MUST work through these in order. Steps 1–3 are AI-only homework (no user questions). The user's confirmation gates steps 4 onward, and steps 5–7 repeat per surviving mutant.

1. **Identify the target and the report** *(no user question)* — re-read the user's intent. Identify the target module/file. Use the report the user supplied (a path or pasted output); if none was pasted, DISCOVER the repo's own mutation report with the host's file tools and read it — any tool's format (a Stryker `mutation.json`, a PIT `mutations.xml`, mutmut output) — scoped to the target (the changed code when a diff is in play). Reading a SAVED report is on-demand evidence, NOT a competing run-time hook: the repo's live-run hook/router that fires on a `mutmut run` command keeps that job, so don't re-run the tool just to GENERATE the report here (step 9's post-change re-run to confirm the survivor count dropped is a separate, later step). If no mutation report exists — a coverage report alone does NOT enumerate survivors, so it can't substitute — note that there are no enumerated survivors to walk, and STOP at step 4's gate to ask the user to run mutation testing or name the specific weak assertions to target; never proceed into the per-survivor walk (steps 5+) with no survivors, and never INVENT survivors no report named.

2. **Read prod + test files** *(no user question, READ-ONLY on prod)* — read the production file (do NOT edit it) and the matching test file. Note the existing test style (framework, fixtures, parameterise vs separate tests).

3. **Triage the survivor list** *(no user question)* — for each surviving mutant, classify provisionally: (a) likely **tautological / equivalent** (e.g. `i++` → `i--` where only the final value is observable and already asserted); (b) likely **real** (assertion gap is meaningful — e.g. boundary mutated from `>` to `>=` and no test exercises the boundary). User gates the call in step 5.

4. **Confirm target + report scope, only for the AMBIGUOUS parts** — present what you found (target file, test file, survivor count, provisional split). Then ONE focused question for what wasn't clear. If unambiguous, move to step 5.

5. **Walk one mutant at a time — confirm tautology vs real** — for each survivor, present line + mutation + your call + rationale, then ask: *"Agree, or is this equivalent given how it's constructed upstream?"* Wait for confirmation. Equivalent → step 6; real → step 7.

6. **Suppress equivalent mutants — config-side if the tool supports it, otherwise source annotation** — preferred: a tool config exclusion (e.g. `pitest.xml` `<excludedMutations>`, Stryker `mutate` exclusions). When the tool has no per-mutant config mechanism (mutmut 3.x, for example — only line-level `# pragma: no mutate` is supported), an inline source annotation is acceptable: it's tooling metadata, not a behaviour change, and the Iron Law's intent (don't reshape production behaviour to make testing easier) is preserved. Each annotation MUST be paired with a one-line rationale comment naming the mutant ID and why the mutation is observably equivalent. Anything else fails review.
  - M21  # x * 1 == x for all numeric inputs

7. **Pick a technique + draft the strengthening test, confirm before writing** — call `sumo_qa_load_techniques()` if not loaded. Pick ONE from the catalogue per real mutant, naming the technique using the VERBATIM catalogue heading (e.g. `boundary value analysis`, NOT `boundary` / `boundary mutant`) (boundary-value for `>` / `>=`; decision-table for branch-condition; property-based for invariants). Present the test name + the assertion idea, wait for confirmation, then write. Match the existing test style.

8. **After all survivors are processed, run the existing suite** — confirm it's still green. Your changes are additive; a pre-existing red means you touched a shared fixture. Surface the count.

9. **Re-run the mutation tool (if user can)** — confirm the survivor count dropped by the number of real mutants addressed. Surface the new count + which survivors remain.

10. **Final report** — list: strengthening tests added (file + name + technique), equivalent mutants suppressed (config + ID + rationale), new survivor count, residual concerns.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags — STOP and rework

Production code stays unchanged throughout this skill, and the final report must close as the record with no closing confirmation question.

| Thought | Reality |
|---|---|
| "I'll tweak the prod code to make the mutant easier to kill" | Iron Law violated. Production code stays still. Route to `sumo-qa-implementing-with-tdd` if behaviour needs to change. |
| "Write a test that asserts the exact code: `assert x == y + 1 if condition else y`" | Tautology. Re-stating the production logic. Suppress the mutant in tool config (or with a `# pragma: no mutate` source annotation when the tool has no config-side mechanism) instead. |
| "All surviving mutants need a test" | No. Equivalent mutants are noise; suppressing them is correct. Only real mutants get tests. |
| "Coverage went from 85% to 92% — done" | Line coverage isn't assertion strength. The right measure is "did the mutation survivor count drop?" |
| "I'll add property-based testing for everything" | Pick from the catalogue based on the actual mutant. Property-based fits invariants, not all mutants. |
| "I'll process all 8 survivors in one message to save turns" | Blind single-shot dump. Per-CLASS batching is acceptable when mutants share the same mechanism (e.g. 4 boundary-shift mutants on the same function → one decision, one test class); walk class-by-class, not mutant-by-mutant in that case. But one message with ALL survivors of different mechanisms = Iron Law violated — the user's correction on M3 may change how you classify M4. |
| "I'll ask the user which test framework / fixture style" | Read the test file. The repo answers that. |
| "Equivalent mutants: suppress all of them silently" | Each suppression needs a one-line rationale in the config (or as a comment next to the source annotation). Otherwise the next reviewer can't tell whether you suppressed a real one. |
| "I'll add `# pragma: no mutate` because writing tests is harder" | Wrong direction. Source annotations are for genuinely equivalent mutants only — those where no observable behaviour distinguishes mutant from original. If you can articulate a test that would kill it, it's not equivalent. |
| "No report was pasted, so there's nothing to work from" | Look for the repo's own mutation report (any tool's format) and read it; only when none exists do you say "not available" and ask for a report or the specific weak assertions to target — never INVENT survivors (a coverage report alone has no survivors). Reading a SAVED report is not the live-run hook/router's job — don't duplicate it or re-run the tool to generate the report (step 9's verification re-run is separate). |

## Examples

### Good (boundary mutant killed by assertion polarity)

Survivor: `subtotal > 10000` mutated to `subtotal >= 10000`. Applying **boundary value analysis**: pick input that exposes the boundary — `subtotal = 10000`. Original evaluates `10000 > 10000` → FALSE. Mutant evaluates `10000 >= 10000` → TRUE. Strengthening test must assert FALSE at this input (`expect(qualifies(...)).toBe(false)`), because then the original passes and the mutant fails. Asserting TRUE would have the inverse effect — pass on mutant, fail on original — meaning the mutant survives.

### Good (explore first, walk one mutant at a time)

> **User:** *"Pitest report shows 8 surviving mutants on `discount_calculator.py`."*
>
> **AI (steps 1–3, internal):** reads prod + test files; triages 3 likely equivalent, 5 likely real.
>
> **AI (step 4):** *"Target is `discount_calculator.py` (24 LOC). Tests use pytest + parametrise. 8 survivors; provisionally 3 equivalent, 5 real. Walk through one at a time, or have you pre-classified any?"*
>
> **AI (step 5, M4):** *"M4 line 47: `threshold > 100` → `threshold >= 100`. No existing test hits exactly 100. Calling real — strengthen with a boundary-value test. Agree?"*
>
> *(on confirm → step 7 presents test name + assertion, waits, writes; continues one mutant at a time)*

### Bad (touch production code)

> **User:** *"Pitest report shows 8 surviving mutants."*
>
> **AI:** *"I'll refactor `apply_discounts` to extract the threshold check so the test can target it directly."*
>
> Iron Law violated. Production code moved. STOP and route to `sumo-qa-implementing-with-tdd` for `regression-first`.

## Next skill in the chain

When all survivors are processed (killed or suppressed with rationale) and the existing suite is still green → `sumo-qa-reviewing-before-merge` to deliver the verdict against fresh evidence, if this is a standalone task.

If this task is part of a multi-task rollout dispatched by `sumo-qa-executing-qa-rollout` → `sumo-qa-finishing-qa-work` instead, to capture the strengthening evidence and produce the PR-ready summary.
