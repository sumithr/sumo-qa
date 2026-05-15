---
id: SCN-10
scenario_type: skill
expected_skill: sumo-qa-deciding-approach
anti_patterns:
  - Adds tests to "be thorough".
  - Forces the change through `sumo-qa-reviewing-before-merge` for a typo fix.
  - Surfaces the internal classification/approach labels verbatim.
  - Walks the user through a 5-section formal review for one character changed.
---

## User prompt

I'm fixing a typo in a comment in `docs/CONFIGURATION.md`. Anything I need to do?

## Expected interaction shape

1. Classifies the change as `docs_change`.
2. Picks approach `no-tests-recommended` — and that IS the senior-QA answer here. Adding tests for a docs typo wastes signal.
3. Translates the taxonomy to natural English: NOT *"Classification: docs_change, Approach: no-tests-recommended"*, but *"this is a docs-only typo — no tests needed. Just check the doc still renders."*
4. Does NOT route to `sumo-qa-preparing-for-work` or `sumo-qa-reviewing-before-merge` — those are wrong shapes for the change.
5. Offers the lightweight follow-up: *"want me to verify it renders correctly with `mkdocs serve` or similar?"*

## Anti-patterns

- Adds tests to "be thorough".
- Forces the change through `sumo-qa-reviewing-before-merge` for a typo fix.
- Surfaces the internal classification/approach labels verbatim.
- Walks the user through a 5-section formal review for one character changed.
