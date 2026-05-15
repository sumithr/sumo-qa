---
id: SCN-07
scenario_type: skill
expected_skill: sumo-qa-finding-test-data
anti_patterns:
  - Invents an invoice ID ("try INV-12345").
  - Returns a stale entry without re-validation.
  - Silent substitution when the requested entry is stale.
---

## User prompt

Find me a refund-eligible invoice for the partial-refund flow test in staging.

## Expected interaction shape

1. Routes internally to `find` (one of the 4 routes: explain / find / validate / register). Does NOT echo "Route: find" to the user.
2. Calls `sumo_qa_find_test_data(question="...", environment="staging", domain="billing", criteria=...)`.
3. For each match, validates it against the source system *in this turn* (not from cache).
4. Surfaces the result with freshness timestamp + validation evidence — e.g. *"Found `INV-44120` — refund-eligible, validated against staging just now (2026-05-12 09:14)."*
5. If a catalogue entry is stale: surfaces the failure explicitly, does NOT silently substitute another.
6. For register requests: confirms with the user before writing to the catalogue.

## Anti-patterns

- Invents an invoice ID ("try INV-12345").
- Returns a stale entry without re-validation.
- Silent substitution when the requested entry is stale.
