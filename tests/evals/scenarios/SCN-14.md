---
id: SCN-14
scenario_type: skill
expected_skill: sumo-qa-finishing-qa-work
anti_patterns:
  - Declares "wrap-up complete" without running the suite in this turn.
  - '"All risks covered" without enumerating which test covers which risk.'
  - '"Residual risks: none" (every multi-task rollout leaves residuals — naming none means you didn''t think about it).'
  - Writes the summary to a path the user didn't agree to.
  - Skips offering to draft the PR description.
---

## User prompt

All Phase 4.2 mutation tasks ran green. Wrap it up — I need something I can paste into the PR.

## Expected interaction shape

1. **Iron Law:** NO FINISH WITHOUT FRESH EVIDENCE + WRITTEN SUMMARY. Runs the suite *in this turn* (does NOT cite "CI was green earlier"); captures pass/fail counts + duration + coverage %.
2. Captures the risk-to-test map: for each named risk in the plan, names the covering test (file + name) or flags it as uncovered.
3. Lists open follow-ups honestly — items deferred to a future PR, equivalent mutants suppressed with rationale, residual risks accepted.
4. Writes the summary to `docs/qa/runs/YYYY-MM-DD-<feature>.md`. Includes: evidence block, risk-to-test map, mutation/coverage figures, files touched, notable findings, known gaps + open follow-ups.
5. Offers to draft the PR description with the same evidence packaged for GitHub.

## Anti-patterns

- Declares "wrap-up complete" without running the suite in this turn.
- "All risks covered" without enumerating which test covers which risk.
- "Residual risks: none" (every multi-task rollout leaves residuals — naming none means you didn't think about it).
- Writes the summary to a path the user didn't agree to.
- Skips offering to draft the PR description.
