---
name: sumo-qa-executing-qa-rollout
description: Use after sumo-qa-planning-qa-rollout to dispatch a written QA plan task-by-task. Each task runs in a fresh subagent (parallel where independent); each subagent's output goes through a two-stage review (test-correctness → test-quality) before the task is marked done. Continuous execution — no per-task check-ins. Finishes by routing to sumo-qa-finishing-qa-work.
---

# Executing a QA rollout with subagents

Take a written plan from `sumo-qa-planning-qa-rollout` (or a hand-written equivalent at `docs/qa/plans/...`) and execute it by dispatching one fresh subagent per task, then walking each subagent's output through a two-stage review.

**Announce at start:** *"Dispatching the plan with subagents."*

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: **output discipline** (never surface internal taxonomy labels — say *"behaviour change in pricing"*, not *"Classification: business_logic_change"*), **output economy** (spend output on findings not framing; no preamble or self-narration; one question per turn; no closing pleasantries), knowledge authority hierarchy, internal scaffolding stays internal, and specialty-tool fit.

<HARD-GATE>
Do NOT execute tasks inline. Every task goes to a fresh subagent — a fresh delegated worker with no inherited task context (see `using-sumo-qa` → Shared vocabulary). The orchestrator (you) does dispatch + review + coordination only — it never edits test files directly. If the current host has no worker-delegation primitive at all, STOP and report the capability gap to the user; do NOT silently execute the plan inline. If a subagent fails three times, escalate to the user.
</HARD-GATE>

## The Iron Law

**ONE FRESH SUBAGENT PER TASK. TWO-STAGE REVIEW. CONTINUOUS EXECUTION.**

Fresh subagent prevents context pollution; two-stage review separates "catches the right risk" from "well-shaped test"; continuous because mid-plan check-ins waste the user's attention.

## When to Use

Routes here from:
- `sumo-qa-planning-qa-rollout` when a plan is signed off
- Direct user invocation: *"execute the QA plan at `docs/qa/plans/...`"*, *"run through the test rollout"*, *"dispatch the QA work"*

For a single-task piece of work, skip this skill — go straight to `sumo-qa-implementing-with-tdd` or the matching individual skill.

## Checklist

You MUST work through these in order. Steps 1–2 are AI-only homework. The dispatch loop in step 3 is **continuous**: do NOT pause for user check-ins between tasks. Step 4 only fires when all tasks are done or one is genuinely blocked.

1. **Read the plan** *(no user question)* — load `docs/qa/plans/<plan>.md`. Extract every task verbatim, its approach tag, files, `[parallel]`/`[sequential]` marker, and "done when" criteria. Add an entry to the ordered work tracker per task.

2. **Group by parallelism** *(no user question)* — bucket tasks into parallel waves. All `[parallel]` tasks with no upstream dependency form wave 1. Sequential or dependency-blocked tasks form wave 2, 3, etc. Most QA plans collapse to 1–2 waves.

3. **Dispatch loop (per wave, continuous):**
   - **3a. Dispatch implementer subagents** — for each task in the wave, dispatch a fresh subagent using `prompts/implementer-prompt.md`, filling in the task spec. Wave dispatches go in parallel (one delegation call per worker, all issued together so the host can run them concurrently).
   - **3b. Spec-correctness review** — after each subagent returns, dispatch a spec-reviewer subagent using `prompts/spec-reviewer-prompt.md`. Checks: does the test cover the named risk? Does it run? Did the red phase happen (if TDD)? Did production code stay unchanged (if strengthen / verify-existing)?
   - **3c. If spec review fails:** re-dispatch the implementer with findings. Loop until pass or 3 rounds elapsed (then escalate).
   - **3d. Test-quality review** — once spec review passes, dispatch a quality-reviewer subagent using `prompts/quality-reviewer-prompt.md`. Checks: observable assertion (not implementation-coupled)? Deterministic? Tautology check?
   - **3e. If quality review fails:** re-dispatch the implementer with quality findings. Loop until pass or 3 rounds (escalate).
   - **3f. Mark the task complete in the ordered work tracker.** Move to next task / wave. **Do NOT ask the user "continue?".**

4. **Final cross-task review** — when all tasks are done, dispatch a final reviewer with the entire plan + all task outputs. Do the tests collectively cover all named risks? Are there seams between tasks neither covers? Run the full suite; surface counts.

5. **Hand off to `sumo-qa-finishing-qa-work`** — pass the plan, the task outputs, and the cross-task review. That skill captures evidence, produces the PR-ready summary, and closes the loop.

## Process Flow

See the Checklist above — that's the flow.

## Model Selection

Match the subagent model to the task shape via the host's worker-delegation primitive (where it exposes a model override):

- **Test-writing subagents** (clear spec, 1–2 files): fast/cheap (haiku).
- **Spec-correctness reviewer**: standard (sonnet). Reads code + assesses risk coverage.
- **Quality reviewer**: capable (sonnet/opus). Tautology + observability judgments.
- **Final cross-task reviewer**: capable (opus). Guards whole-plan integrity.

## Red Flags — STOP and rework

| Thought | Reality |
|---|---|
| "I'll just do task 1 inline — subagents are overkill for 3 tasks" | Iron Law violated. Even small plans get fresh subagents per task. |
| "I'll combine spec + quality into one review subagent to save time" | Two reviews because they ask different questions. One agent doing both skimps on one. |
| "Task 3 mentioned task 2's fixture; I'll inherit context to skip re-explanation" | No. Fresh subagent. Re-explain via the prompt template. |
| "Let me pause after task 2 and ask the user if the direction's right" | Continuous execution. The user signed off the plan; mid-plan check-ins waste attention. |
| "Spec review came back with 2 issues; I'll fix one, push the other to task 5" | Fix both before moving on. |
| "Production code changed in a strengthen-test-coverage task — it was a tiny refactor" | Reject the output. Production stays clean. |
| "All tasks done; I'll just summarise and finish" | Cross-task review first, then route to `sumo-qa-finishing-qa-work`. |

## Examples

### Good (parallel wave 1, then sequential wave 2)

> **User:** *"Execute the plan."*
> **AI (announce):** *"Dispatching the plan with subagents."*
> **AI:** 6 tasks; 1–5 parallel, 6 sequential on task 1's fixture.
> **Wave 1:** 5 implementers dispatched in one message → spec → quality → done. Task 4 spec-review fails round 1; passes round 2.
> **Wave 2:** task 6 dispatches after task 1 commits; two-stage review as before.
> **Final:** cross-task reviewer confirms 5 risks covered, suite green. Routes to `sumo-qa-finishing-qa-work`.

### Bad (inline execution + skipped reviews)

> **User:** *"Execute the plan."*
> **AI:** edits `tests/billing/test_refund.py` directly with 3 tasks' tests; runs pytest; reports green.
> Iron Law violated: no fresh subagents, no spec/quality reviews, no audit trail that tests catch the named risks.

## Next skill in the chain

After cross-task review passes → `sumo-qa-finishing-qa-work` to capture evidence, write the PR-ready summary, and close the loop.
