---
id: SCN-12
scenario_type: skill
expected_skill: sumo-qa-planning-qa-rollout
anti_patterns:
  - Begins implementing tests inline ("Iron Law violated — start the executor instead").
  - Tasks shaped at "implement Phase 1" level (too big for a fresh subagent).
  - Tasks named without anchoring file path, technique, or risk reference.
  - Single-shot dump of all tasks without confirmation gates.
  - Approach tag missing (downstream executor doesn't know which sub-skill to fire).
---

## User prompt

Take the Phase 1 work from our QA strategy (mutation baselines on `pricing/calculator.py` + `shared/money.py`, property-tests on rounding, Hypothesis fixtures) and turn it into a plan I can dispatch across subagents tomorrow.

## Expected interaction shape

1. Reads the strategy doc (or the cited Phase 1 scope) and the relevant production paths to anchor each task in evidence.
2. Walks scope → file structure → bite-sized tasks → confirm, **one section per turn** with confirmation gates (per the skill's checklist).
3. **Bite-sized = independently executable in a fresh subagent.** Each task names the prod file, the test file, the test technique, the expected red→green or strengthening pattern, and any test data fixture it owns.
4. Tagging: each task carries an Approach tag (`tdd-scaffold` / `regression-first` / `coverage-first-then-refactor` / `strengthen-test-coverage`) so `sumo-qa-executing-qa-rollout` knows which sub-skill the subagent should invoke.
5. **Iron Law:** NO EXECUTION FROM THE PLANNER. The plan is the deliverable. Production code stays untouched in this skill.
6. Final deliverable: a markdown file at `docs/qa/plans/YYYY-MM-DD-<feature>.md` (or wherever the user's repo configures plan storage), with each task in a structured block ready for subagent dispatch.

## Anti-patterns

- Begins implementing tests inline ("Iron Law violated — start the executor instead").
- Tasks shaped at "implement Phase 1" level (too big for a fresh subagent).
- Tasks named without anchoring file path, technique, or risk reference.
- Single-shot dump of all tasks without confirmation gates.
- Approach tag missing (downstream executor doesn't know which sub-skill to fire).
