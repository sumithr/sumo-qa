---
id: SCN-03
scenario_type: skill
expected_skill: sumo-qa-implementing-with-tdd
anti_patterns:
  - Writes the test AND the production fix in the same turn (Iron Law violated).
  - Tautology assertion (`assert add(2,3) == 2+3`) that the broken code also passes.
  - Skips the red phase, declares green.
  - Asks 4+ questions up front before doing any exploration.
---

## User prompt

Fix the VIP-customer double-discount bug regression-first. The discount stacks twice when a VIP gets a promo code applied. Logic is in `pricing/discount_calculator.py`.

## Expected interaction shape

1. Walks the repo: reads `pricing/discount_calculator.py`, finds the matching test file, reads sibling test files to detect framework/fixture conventions. Does NOT ask the user "what test framework do you use?"
2. Picks the smallest failing test: names the function under test, the input that triggers the bug, the assertion that distinguishes broken from fixed.
3. Confirms the test idea with the user, asking ONE focused question for the ambiguous part (e.g. *"is the expected total £90.00 — does VIP override promo entirely, or do they stack but cap?"*).
4. After confirmation: writes the failing test.
5. Runs it. **Surfaces the red output verbatim** (`AssertionError: assert 80.0 == 90.0` at `test_discount_calculator.py:47`).
6. Hands off: *"red phase confirmed — implement to make it green; I'll re-run when you're ready."*

## Anti-patterns

- Writes the test AND the production fix in the same turn (Iron Law violated).
- Tautology assertion (`assert add(2,3) == 2+3`) that the broken code also passes.
- Skips the red phase, declares green.
- Asks 4+ questions up front before doing any exploration.
