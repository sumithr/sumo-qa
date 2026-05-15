---
id: SCN-06
scenario_type: skill
expected_skill: sumo-qa-answering-testing-question
anti_patterns:
  - '"Add unit tests and integration tests, consider edge cases" — no cited principle, no named technique.'
  - 20-sentence essay (senior QA answers concisely).
  - Routes to a sub-skill instead of answering inline (the question doesn't need a full plan).
---

## User prompt

How should I test a service that re-orders user feeds based on engagement signals?

## Expected interaction shape

1. Reads any code/spec the user supplied (or asks for one specific clarification if none provided).
2. Calls `sumo_qa_load_principles()` + `sumo_qa_load_techniques()` — identifies the QA shape (correctness of ordering rules / regression on existing ordering / performance under load).
3. Cites at least one ISTQB principle by number/name (e.g. *"Principle 4 — defects cluster; feed-ordering is a hotspot"*).
4. Names at least one technique from the catalogue (e.g. *"decision table for the ordering-rule combinations; equivalence partitioning for feed sizes"*).
5. Names the best-fit tool if a specialty surface is implied (e.g. k6 if performance at scale matters, Hypothesis if ordering invariants suggest property-based).
6. 3–7 sentences total. Conversational, NOT a JSON blob.

## Anti-patterns

- "Add unit tests and integration tests, consider edge cases" — no cited principle, no named technique.
- 20-sentence essay (senior QA answers concisely).
- Routes to a sub-skill instead of answering inline (the question doesn't need a full plan).
