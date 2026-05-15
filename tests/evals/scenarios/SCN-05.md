---
id: SCN-05
scenario_type: skill
expected_skill: sumo-qa-strengthening-tests
anti_patterns:
  - Modifies production code to make tests pass.
  - Batches all 6 strengthening tests in one go.
  - Writes tests that still pass on the mutated code (didn't actually kill the mutant).
---

## User prompt

Pitest report shows 6 surviving mutants in `pricing/calculator.py`. Help me strengthen the tests. Production code stays unchanged.

## Expected interaction shape

1. Reads the Pitest report to identify the 6 survivors (line + mutation type: e.g. `>` → `>=`, `&&` → `||`, removed-conditional).
2. Walks one survivor at a time. For each: (a) tautology check (is the current test re-asserting the production code?), (b) picks a technique from the catalogue that would kill this specific mutant, (c) names the strengthening test.
3. Confirms the technique choice before writing the test. Asks ONE focused question if the right behaviour is ambiguous.
4. Writes the strengthening test, runs it (now passes against current prod), then asks Pitest to rerun against the mutated prod — verifies the mutant is now killed.
5. Moves to next survivor only after confirmation.

## Anti-patterns

- Modifies production code to make tests pass.
- Batches all 6 strengthening tests in one go.
- Writes tests that still pass on the mutated code (didn't actually kill the mutant).
