---
name: sumo-qa-planning-qa-rollout
description: Use when you have a chunk of QA work (a story, a PR, a strategy phase) that needs to be turned into a written plan of bite-sized, independently-executable tasks before any test code is written. Walks scope → file structure → bite-sized tasks → confirm, one section per turn. Produces docs/qa/plans/YYYY-MM-DD-<feature>.md ready for subagent dispatch via sumo-qa-executing-qa-rollout.
---

# Planning a QA rollout

Help the user turn an amorphous QA ask ("we need test coverage for the new refund flow", "Phase 1 of the strategy") into a written plan a fresh agent or teammate could pick up and execute task-by-task — without you in the room.

**Announce at start:** *"Turning this into a dispatchable plan."*

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
Do NOT start scaffolding tests or dispatching subagents from this skill. This skill's only output is the written plan document. Execution happens in `sumo-qa-executing-qa-rollout` after the plan is signed off.
</HARD-GATE>

## The Iron Law

**NO EXECUTION FROM THE PLANNER. THE PLAN IS THE DELIVERABLE.** The plan must stand alone — readable by someone who wasn't in the conversation, specific enough that a fresh subagent given just one task could execute it without coming back for clarification.

## When to Use

`sumo-qa-deciding-approach` routes here when:

- the work spans **3+ tasks** that can be done independently (otherwise: skip planning, route straight to `sumo-qa-implementing-with-tdd` or similar)
- the user said *"plan QA for this story"* / *"plan the test rollout"* / *"break this into tasks"* / *"prep this for subagent execution"*
- `sumo-qa-strategising` has produced a strategy and the user wants to act on Phase 1
- the work is going to be picked up by someone other than the planner (handoff)

For a single 30-minute QA task, planning is overhead — go straight to the matching skill.

## Checklist

**Note on confirmation rhythm:** the per-step gates are upper bounds, not
mandatory turn-counts. Per the Confirmation discipline (see `using-sumo-qa`),
collapse adjacent obvious sections into a single update when the user has
clearly endorsed the trajectory; reserve a structured question for steps
where the choice meaningfully changes the rest of the plan. In particular,
step 6 ("Walk the plan section-by-section, confirm") should be read as: batch
adjacent task groups when the user has already validated the approach — the
goal is to catch mis-shaped tasks early, not to ask permission for each one.

You MUST work through these in order. Steps 1–3 are AI-only homework. Steps 4 onward are gated by user confirmation.

1. **Walk the repo for context** *(no user question)* — use the host's file tools. Find: the actual files the work touches, the test framework + fixture conventions, CI config, any sibling tests demonstrating local patterns. Don't ask the user what's in the repo.

2. **Identify the scope chunks** *(no user question)* — break the QA work into 3–10 chunks. Each chunk must be: (a) independent enough to hand to a fresh subagent, (b) sized for 10–30 minutes of work, (c) anchored to specific files or risks. NOT *"add unit tests"*. YES *"write a property-based test for `pricing/calculator.py:apply_discounts` covering the VIP-discount stacking invariant"*.

3. **Sketch the file structure** *(no user question)* — for each chunk, name the file(s) it creates or modifies. New test files go where existing sibling tests live (read the convention, don't invent one).

4. **Confirm scope + structure** — present the chunks + file structure in one paragraph; ask the ONE focused question that exploration couldn't answer. If exploration left nothing ambiguous, skip the question.

5. **Draft the plan document** — write it to `docs/qa/plans/YYYY-MM-DD-<feature-slug>.md` using the template below. Tasks must be:
   - **Bite-sized:** 5–15 minutes each. Bigger means decompose. Smaller means combine.
   - **Independent:** task N must not depend on task N+1's output. If they're coupled, name the coupling explicitly.
   - **Specified:** file paths, function names, expected assertion shapes, the named risk being covered.
   - **Discipline-labelled:** each task carries the approach tag from `sumo-qa-deciding-approach` so the executor knows which workflow to follow.

6. **Walk the plan section-by-section, confirm** — present file-structure → first 3 tasks → next 3 → residual. Each section gets a confirmation gate. Ask: *"do these tasks match how you'd shape them?"* Don't dump the whole plan at once.

7. **Hand off** — when the plan is signed off, say: *"plan is at `docs/qa/plans/YYYY-MM-DD-<feature>.md`. Ready to dispatch subagents? `sumo-qa-executing-qa-rollout` reads this plan and runs each task in a fresh subagent with two-stage review."* Do NOT start executing.

## Plan Document Template

Every plan ships with this header:

```markdown
# [Feature] QA Plan

> **For agentic execution:** Use `sumo-qa-executing-qa-rollout` to dispatch this plan task-by-task with two-stage review. Tasks use checkbox (`- [ ]`) syntax for tracking. Independent tasks (marked `[parallel]`) can be dispatched concurrently.

**Goal:** [One sentence — what the QA work delivers]

**Approach mix:** [tdd-scaffold / regression-first / strengthen-test-coverage / verify-existing — each task may use a different one]

**Files touched:**
- `path/to/production_file.py` — [why; no edits if the approach is strengthen-test-coverage or verify-existing]
- `tests/path/to/test_file.py` — [new tests added here]
- `tests/path/to/new_test_file.py` — [new file]

**Risks covered (anchored):**
- R1 — `production_file.py:47` — [specific risk in one sentence]
- R2 — `production_file.py:82` — [specific risk]
- ...

---

### Task 1: [Name] [parallel|sequential]

**Approach:** [regression-first / tdd-scaffold / strengthen-test-coverage / etc.]
**Risk covered:** R[n]
**Files:**
- Create: `tests/pricing/test_discount_stacking.py`
- Touch: none (production stays unchanged for strengthen / regression-first)

- [ ] Step 1: Read `pricing/discount_calculator.py:apply_discounts` and the closest sibling test for fixture conventions.
- [ ] Step 2: Write the failing test `test_apply_discounts_vip_does_not_stack_with_promo`. Assert `Order(tier=VIP, promo=BLACKFRIDAY10).apply_discounts().total == 90.00`.
- [ ] Step 3: Run pytest; confirm the test fails for the right reason (assertion, not import / fixture error).
- [ ] Step 4: Surface red output verbatim.

**Done when:** the test exists, runs, and fails with `AssertionError: assert 80.0 == 90.00`. (Or, if approach is strengthen-test-coverage, the test passes and kills the named mutant.)

---

### Task 2: ...
```

## Process Flow

See the Checklist above — that's the flow.

## Red Flags — STOP and rework

| Thought | Reality |
|---|---|
| "The plan is short — I'll just go ahead and start the first task" | Iron Law violated. Plan is the deliverable; execution is the next skill. |
| "Task: 'add tests for the refund flow'" | Generic. Decompose to file + function + expected assertion + risk covered. |
| "I'll list 12 tasks for thoroughness" | Probably 6 with overlap. Combine until each task is genuinely distinct. |
| "I'll mark everything as sequential to be safe" | Default to parallel. Each task should be independent enough to hand to a fresh subagent. Sequential is the exception with a stated reason. |
| "Parallel file-ownership overlap" | Parallel file-ownership overlap — two [parallel] tasks that both modify the same file; resolve by marking one [sequential after Task N] or merging the tasks. |
| "Each task is 'about an hour'" | Decompose. 5–15 minutes each. An hour = 4–8 tasks. |
| "I'll dump the whole plan in one message and ask 'looks good?'" | Single-shot. Walk section-by-section so the user catches mis-shaped tasks early. |
| "The plan doesn't need approach tags — the executor will figure out the right workflow per task" | The executor is a fresh subagent. It has no context. Tag every task. |

## Examples

### Good (walk → decompose → confirm → write)

> **User:** *"Plan Phase 1 of the strategy: cover the billing service's refund flow."*
>
> **AI (internal homework):** walks `services/billing/`, finds 3 entrypoints, existing `tests/billing/` uses pytest + Decimal fixtures. Identifies 5 risk-anchored chunks + 1 fixture-module chunk; 0 production edits.
>
> **AI (step 4):** *"Walked `services/billing/`. Refund flow has 3 entrypoints in `refund.py` + `invoice.py`. Provisional plan: 6 tasks, all in `tests/billing/`. **One thing to pin: the new partial-refund path returns 422 where the old fall-through returned 500 — contract-test with the portal team in scope, or separate?**"*
>
> **User:** *"Out of scope; portal team has their own ticket."*
>
> **AI (step 5):** writes `docs/qa/plans/2026-05-12-billing-refund-coverage.md`. Marks tasks 1–5 `[parallel]`, task 6 `[sequential]` (depends on task 1's fixture).
>
> **AI (step 6):** walks file-structure → first 3 tasks → next 3, confirming each section.
>
> **AI (step 7, after sign-off):** *"Plan is at `docs/qa/plans/2026-05-12-billing-refund-coverage.md`. Want me to dispatch via `sumo-qa-executing-qa-rollout`?"*

### Bad (plan and execute in one go)

> **User:** *"Plan Phase 1 of the strategy."*
>
> **AI:** *"Sure! Phase 1 covers refund flow. Let me start writing the tests…"* edits `tests/billing/test_refund.py`.
>
> Iron Law violated. No plan written; no teammate could pick this up tomorrow.

## Next skill in the chain

When the plan is signed off → `sumo-qa-executing-qa-rollout` to dispatch subagents per task with two-stage review. If the user wants to execute manually, point them at the plan file and stop.
