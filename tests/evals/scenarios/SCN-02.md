---
id: SCN-02
scenario_type: skill
expected_skill: sumo-qa-reviewing-before-merge
anti_patterns:
  - Declares "safe to merge" without running tests in this turn.
  - Generic risks ("edge cases", "error handling").
  - Single-shot dump with all 5 sections at once instead of confirmation gates between.
---

## User prompt

Review my changes — is this safe to merge?

## Expected interaction shape

1. Runs `git diff` / `git diff --staged` / `git diff <base>...HEAD` via the host's git tools to read the actual diff.
2. Reads each changed file (not just the diff hunks).
3. Calls `sumo_qa_load_classifications()` + `sumo_qa_load_standards(classification=...)` + `sumo_qa_load_rules(...)` to know which team rules apply.
4. Names 3–7 risks anchored to **file + line**, not generic.
5. Presents scope + classification in one paragraph, asks ONE focused question for anything ambiguous.
6. **HARD GATE:** runs the test suite in *this turn*. Shows actual pass/fail counts. "CI was green earlier" is NOT acceptable.
7. Maps each named risk to a covering test (file + test name) or flags it as uncovered.
8. Final verdict: SAFE TO MERGE / NOT SAFE / NEEDS WORK with concrete evidence. SAFE only if (a) suite green now, (b) every risk has a covering test, (c) no loaded rule violated.

## Anti-patterns

- Declares "safe to merge" without running tests in this turn.
- Generic risks ("edge cases", "error handling").
- Single-shot dump with all 5 sections at once instead of confirmation gates between.
