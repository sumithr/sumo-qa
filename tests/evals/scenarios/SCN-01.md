---
id: SCN-01
scenario_type: skill
expected_skill: sumo-qa-preparing-for-work
anti_patterns:
  - Generic "add unit tests and integration tests".
  - 15+ risks (confabulation, not reasoning).
  - Asks the user what's in the files instead of reading them.
  - Surfaces "Classification: business_logic_change" verbatim in the output.
---

## User prompt

Plan QA for ticket BILL-481 — adding a partial-refund flow to the billing service. Files probably touch `services/billing/refund.py` and `services/billing/invoice.py`. Refund amount can be less than the invoice total; consumers expect 4xx-vs-5xx semantics for partial-vs-full failure.

## Expected interaction shape

1. Reads `services/billing/refund.py` and `services/billing/invoice.py` via the host's file tools (NOT asks the user what's in them).
2. Names 3–7 risks, each anchored to a file path or domain term from the prompt (e.g. *"partial-refund amount precision when the invoice has multiple currency line items"*, *"consumer retry logic — does it differentiate the new 4xx from the existing 5xx"*).
3. Picks one technique per risk from the loaded catalogue (boundary value / decision table / property-based / etc.).
4. Proposes a smallest-useful test set (3–7 tests) tied to those risks. NOT "test happy path, test edge cases".
5. Sectioned conversational prose — risks, tests, techniques, open assumptions — NOT a JSON blob.

## Anti-patterns

- Generic "add unit tests and integration tests".
- 15+ risks (confabulation, not reasoning).
- Asks the user what's in the files instead of reading them.
- Surfaces "Classification: business_logic_change" verbatim in the output.
