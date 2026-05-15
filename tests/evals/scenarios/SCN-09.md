---
id: SCN-09
scenario_type: skill
expected_skill: sumo-qa-creating-test-plan
anti_patterns:
  - '"Test plan: do the tests, sign off." (no actual criteria)'
  - Single-shot 5-section dump with no confirmation.
  - Entry criteria like "team is ready" (not measurable).
  - 'Residual risks: none listed.'
---

## User prompt

Create a formal test plan for the Q3 search-relevance launch. We need entry/exit criteria the team can sign off on.

## Expected interaction shape

1. Walks scope → risks → entry criteria → phases → exit criteria → residual risks **one section at a time** with confirmation gates.
2. **HARD GATE:** explicit entry criteria AND explicit exit criteria — no plan without both. (Iron Law of this skill: "NO PLAN WITHOUT EXPLICIT ENTRY/EXIT CRITERIA.")
3. Entry criteria are *measurable* (e.g. *"baseline NDCG@10 ≥ 0.72 on the golden query set"*, *"all P0 search-index integration tests green"*), not aspirational.
4. Each phase has named gates at its end.
5. Residual risks named honestly, with mitigation or acceptance reasoning.
6. Section-by-section confirmation; not a 5-page dump.

## Anti-patterns

- "Test plan: do the tests, sign off." (no actual criteria)
- Single-shot 5-section dump with no confirmation.
- Entry criteria like "team is ready" (not measurable).
- Residual risks: none listed.
