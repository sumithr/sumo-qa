---
id: SCN-04
scenario_type: skill
expected_skill: sumo-qa-implementing-with-tdd
anti_patterns:
  - Writes 5 tests up front before any goes red.
  - Writes the rate-limiter implementation alongside the test.
  - Asserts on internal state (`assert limiter._internal_counter == 100`) instead of observable behaviour (`assert response.status == 429`).
---

## User prompt

I'm adding rate-limiting to the auth service — 100 requests / minute / IP, sliding window. Want to TDD it. Scaffold the failing tests first.

## Expected interaction shape

1. Walks the auth service to find where rate-limiting would attach (middleware, request handler, etc.). Reads sibling tests for framework conventions.
2. Names the *risk surfaces* before tests: (a) boundary at 100th vs 101st request, (b) sliding-window vs fixed-window edges, (c) per-IP isolation, (d) clock-skew under load, (e) reset-after-window.
3. Confirms the test plan in one paragraph; asks the ONE ambiguous question (e.g. *"reset behaviour at the window boundary — drop the oldest request as the window slides, or hard-reset every 60s?"*).
4. Writes the smallest *first* failing test (boundary at 100→101). Runs it. Shows red output. Hands off to user for implementation.
5. Does NOT scaffold all 5 tests up front — TDD is one red→green cycle at a time.

## Anti-patterns

- Writes 5 tests up front before any goes red.
- Writes the rate-limiter implementation alongside the test.
- Asserts on internal state (`assert limiter._internal_counter == 100`) instead of observable behaviour (`assert response.status == 429`).
