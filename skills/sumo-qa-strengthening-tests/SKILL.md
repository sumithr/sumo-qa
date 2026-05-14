---
name: sumo-qa-strengthening-tests
description: Use after sumo-qa-deciding-approach picks strengthen-test-coverage. Mutation-testing follow-up, raise-coverage tasks, killing weak assertions. Walks survivor → tautology check → technique → strengthening test, one mutant at a time with confirmation gates. Production code STAYS UNCHANGED.
---

# Strengthening tests

Help the user kill weak assertions and surviving mutants by walking each survivor one at a time: triage tautology vs real, pick a technique, draft the strengthening test, confirm. The user has judgement context (is this mutant "real" given how the code is consumed in practice?) the AI can't infer from the report alone — surface it through questions, don't assume it.

**Announce at start:** *"Killing the mutation survivors, one at a time."*

## Output discipline (mandatory)

**Never surface internal taxonomy labels in user-facing output.** No "Classification: X", "Approach: Y", "Per the checklist", "Step 3 of 6". The taxonomy is internal scaffolding; translate to natural English when the meaning matters to the user — *"this is a behaviour change in pricing"*, not *"Classification: business_logic_change"*. If you catch yourself typing a label, delete it.

Inherits the global discipline from `using-sumo-qa` (knowledge authority hierarchy, internal scaffolding stays internal, specialty-tool fit).

## Output economy (mandatory)

Spend output tokens on findings, not framing.

- **Don't preamble the work.** The host already shows tool calls — present findings, don't narrate *"I'll first read X, then Y, then deliver Z."*
- **One question per turn.** Don't follow a question with *"shall I proceed or clarify first?"* — the question IS the gate.
- **No self-narration.** *"Let me now..."* / *"I'm going to..."* → just do it.
- **Don't restate the user's input.** They know what they asked.
- **Section headings only when there are genuinely multiple sections.** A 3-line scope check doesn't need a `## Scope` heading.
- **Tables only when comparing >2 things on >2 axes.** Otherwise prose is shorter.
- **No closing pleasantries.** No *"happy to dig deeper"* / *"let me know if you want X"* — the next-skill handoff at the bottom of every skill is where routing lives.

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

1. **Identify the target and the report** *(no user question)* — re-read the user's intent. Identify the target module/file. If the user supplied a mutation-testing report path or pasted output, parse it; otherwise note the report is missing.

2. **Read prod + test files** *(no user question, READ-ONLY on prod)* — read the production file (do NOT edit it) and the matching test file. Note the existing test style (framework, fixtures, parameterise vs separate tests).

3. **Triage the survivor list** *(no user question)* — for each surviving mutant, classify provisionally: (a) likely **tautological / equivalent** (e.g. `i++` → `i--` where only the final value is observable and already asserted); (b) likely **real** (assertion gap is meaningful — e.g. boundary mutated from `>` to `>=` and no test exercises the boundary). User gates the call in step 5.

4. **Confirm target + report scope, only for the AMBIGUOUS parts** — present what you found (target file, test file, survivor count, provisional split). Then ONE focused question for what wasn't clear. If unambiguous, move to step 5.

5. **Walk one mutant at a time — confirm tautology vs real** — for each survivor, present line + mutation + your call + rationale, then ask: *"Agree, or is this equivalent given how it's constructed upstream?"* Wait for confirmation. Equivalent → step 6; real → step 7.

6. **Suppress equivalent mutants in tool config** — show the exact config edit (e.g. `pitest.xml` exclusion or `# pragma: no mutate`). Cite the mutant ID and a one-line rationale. Move on.

7. **Pick a technique + draft the strengthening test, confirm before writing** — call `sumo_qa_load_techniques()` if not loaded. Pick ONE from the catalogue per real mutant (boundary-value for `>` / `>=`; decision-table for branch-condition; property-based for invariants). Present the test name + the assertion idea, wait for confirmation, then write. Match the existing test style.

8. **After all survivors are processed, run the existing suite** — confirm it's still green. Your changes are additive; a pre-existing red means you touched a shared fixture. Surface the count.

9. **Re-run the mutation tool (if user can)** — confirm the survivor count dropped by the number of real mutants addressed. Surface the new count + which survivors remain.

10. **Final report** — list: strengthening tests added (file + name + technique), equivalent mutants suppressed (config + ID + rationale), new survivor count, residual concerns.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags — STOP and rework

| Thought | Reality |
|---|---|
| "I'll tweak the prod code to make the mutant easier to kill" | Iron Law violated. Production code stays still. Route to `sumo-qa-implementing-with-tdd` if behaviour needs to change. |
| "Write a test that asserts the exact code: `assert x == y + 1 if condition else y`" | Tautology. Re-stating the production logic. Suppress the mutant in tool config instead. |
| "All surviving mutants need a test" | No. Equivalent mutants are noise; suppressing them is correct. Only real mutants get tests. |
| "Coverage went from 85% to 92% — done" | Line coverage isn't assertion strength. The right measure is "did the mutation survivor count drop?" |
| "I'll add property-based testing for everything" | Pick from the catalogue based on the actual mutant. Property-based fits invariants, not all mutants. |
| "I'll process all 8 survivors in one message to save turns" | Single-shot dump. Walk one mutant at a time — the user's correction on M3 may change how you classify M4. |
| "I'll ask the user which test framework / fixture style" | Read the test file. The repo answers that. |
| "Equivalent mutants: suppress all of them silently" | Each suppression needs a one-line rationale in the config. Otherwise the next reviewer can't tell whether you suppressed a real one. |

## Examples

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
