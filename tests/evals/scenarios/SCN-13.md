---
id: SCN-13
scenario_type: skill
expected_skill: sumo-qa-executing-qa-rollout
anti_patterns:
  - Pauses after every task to check in (the plan was already signed off; the executor's job is to drive).
  - Skips the two-stage review and accepts subagent output verbatim.
  - Edits the plan mid-execution ("found a better task structure") — if the plan needs changes, route back to `sumo-qa-planning-qa-rollout`.
  - Single-shot review of all tasks at the end (per-task review catches drift early).
---

## User prompt

Run the plan at `docs/qa/plans/2026-05-15-phase4.2-mutation-strengthening.md`.

## Expected interaction shape

1. Reads the plan markdown; extracts each task block.
2. **One fresh subagent per task**, dispatched in parallel where the plan marks tasks as independent (no shared-state edits).
3. Each subagent invokes the sub-skill named by the task's Approach tag.
4. After each subagent returns, runs a **two-stage review**: (a) test-correctness review (does the test actually exercise the named risk?), (b) test-quality review (boundary coverage, exact-equality vs substring, no tautology).
5. **Continuous execution** — no per-task confirmation gates with the user once the plan is signed off (the planning skill already gathered confirmation).
6. Surfaces evidence per task in a single status line (task name → subagent verdict → review-stage verdict). Verbose only on failure.
7. On completion, routes to `sumo-qa-finishing-qa-work` to capture evidence and produce the PR-ready summary.

## Anti-patterns

- Pauses after every task to check in (the plan was already signed off; the executor's job is to drive).
- Skips the two-stage review and accepts subagent output verbatim.
- Edits the plan mid-execution ("found a better task structure") — if the plan needs changes, route back to `sumo-qa-planning-qa-rollout`.
- Single-shot review of all tasks at the end (per-task review catches drift early).
