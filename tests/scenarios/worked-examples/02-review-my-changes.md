# Scenario 02 — Review my changes

> **Demo arc:** *"my AI told me my code was safe to merge. sumo-qa says: not quite — and here's the named risk that has no covering test."*
>
> Shows: diff-reading without asking, named risks anchored to file:line, fresh test-run evidence, risk-to-test coverage map, refusal to declare safe-to-merge until the gap is closed.

---

## Turn 1 — User

> Review my changes — is this safe to merge?

---

## Turn 2 — sumo-qa

*(internal: invokes `qa-deciding-approach`. Reads recent intent + scope. Classification: `api_contract_change` + `business_logic_change`. Approach: `verify-existing`. Routes to `qa-reviewing-before-merge`.)*

*(internal: walks the diff and changed files using the host's git + file tools — does NOT ask the user "what files did you change?".)*

I've walked the diff and the changed files. Here's the scope; one thing I need to clarify before I run the suite and call the verdict.

**Diff scope (3 files, +44/-6):**

| File | Change |
|---|---|
| `services/billing/refund.py` | +38/-4 — new partial-refund path; new validation; new error class `RefundAmountInvalid` |
| `domain/Refund.kt` | +12/-2 — `idempotencyKey` derivation moved from caller into the domain object |
| `tests/test_refund_api.py` | +25/-0 — 2 new tests on the happy path + invalid-amount rejection |

**Classification:** behaviour change in the refund pipeline + new error shape on the API contract. The team's loaded API-change rule (`change_rules.yaml#api-contract-change`) requires a consumer-side contract test bump when an error shape changes.

**One thing to confirm before I call this:** the new `RefundAmountInvalid` returns `422` where the old fall-through returned `500`. **Is the upstream consumer (the customer-portal frontend, I think — let me know if there's another) using 4xx-vs-5xx to decide whether to retry? If it is, this change shifts what they treat as transient vs permanent.**

---

## Turn 3 — User

> Yes — the portal retries on 5xx, surfaces a hard error on 4xx. They'd want the 422 too. There's also a billing-events consumer that listens for `RefundFailed` events; that path didn't move.

---

## Turn 4 — sumo-qa

Good — that's the risk I needed pinned. Here are the named risks I've drawn from the diff, anchored to file + line. Tell me if any of these are wrong-shaped or if I've missed one before I run the verification:

> **R1 — `services/billing/refund.py:47`** — invalid-amount path now returns `422`; previously fell through to `500`. **Consumer impact:** portal retry logic switches behaviour from "transient — retry" to "permanent — surface to user". You confirmed portal wants the 422, so the risk now is: **does any other consumer assume 5xx == retry?** The `RefundFailed` event consumer is on a different code path, so it's clean.
>
> **R2 — `domain/Refund.kt:18`** — `idempotencyKey` derivation moved from caller into the domain object. **Risk:** on retry of a partially-completed refund, the key is now derived from the domain state at call time, not from the request. If the domain state changed between the original call and the retry (e.g. the invoice's `lastModifiedAt` advanced), the key differs → **double refund possible**.
>
> **R3 — `services/billing/refund.py:62`** — new `validate_partial_amount()` rejects amounts that don't round-trip through the currency's minor-unit conversion (e.g. £10.005 → 1000.5 minor units → invalid). **Risk:** consumers passing JSON-deserialised floats may hit this on amounts that look fine to a human (£10.10 becomes 1010.00000001 minor in float math).
>
> **R4 — `tests/test_refund_api.py`** — covers R1 (the new 422 path) and the simple happy path, but **does NOT cover R2 (idempotency-on-retry) or R3 (float-rounding edge)**. That's where the gap is.

Match how you'd describe it? Anything to add or re-anchor before I run the suite?

---

## Turn 5 — User

> Spot on. Run the suite.

---

## Turn 6 — sumo-qa

*(internal: HARD GATE — runs the test suite in *this turn*. "CI was green earlier" is not acceptable evidence.)*

Running the suite now.

```
$ uv run pytest -q
............................... [ 76%]
.........                       [100%]
40 passed in 2.34s
```

Targeted re-run around the changed files:

```
$ uv run pytest tests/test_refund_api.py tests/test_idempotency.py -v
tests/test_refund_api.py::test_partial_refund_happy_path PASSED
tests/test_refund_api.py::test_partial_refund_invalid_amount_returns_422 PASSED
tests/test_idempotency.py::test_idempotency_key_stable_across_retries PASSED
tests/test_idempotency.py::test_idempotency_key_changes_when_invoice_modified xfail
4 passed, 1 xfailed in 0.31s
```

Suite is green right now. Note the `xfail` on `test_idempotency_key_changes_when_invoice_modified` — that pinned the OLD behaviour. With your change moving the key derivation into the domain, this test now actually describes the NEW risk (R2). It's xfailed, not passing, so the new failure mode isn't guarded against.

**Risk → covering test map:**

| Risk | Covering test | Status |
|---|---|---|
| R1 — new 422 path, consumer retry impact | `test_partial_refund_invalid_amount_returns_422` | ✅ green |
| R2 — idempotency on partially-completed retry | `test_idempotency_key_changes_when_invoice_modified` | ❌ **xfail** (the test exists but pins the old behaviour; no test guards the new failure mode) |
| R3 — float-rounding edge on minor-unit conversion | *(none)* | ❌ **uncovered** |
| Generic happy path | `test_partial_refund_happy_path` | ✅ green |

---

## Turn 7 — sumo-qa (verdict)

### **NOT SAFE TO MERGE.**

Two reasons, both concrete:

1. **R2 (idempotency double-refund on retry) has no covering test.** The existing test is xfailed and describes the old behaviour. **Suggested fix:** add a regression test — call `process_refund()` twice with the same request, with an `invoice.lastModifiedAt` change between calls; assert the second call returns the cached result of the first, not a fresh refund. I can scaffold this red-first if you want.
2. **R3 (float-rounding rejection) is uncovered.** A JSON-deserialised `£10.10` round-trips through float and fails the new `validate_partial_amount` check. **Suggested fix:** boundary-value test using `Decimal('10.10')` AND `10.10` (float). If both should be accepted, the validator needs to normalise; if only `Decimal` is the supported input, the API should reject early with a clearer error than the current `422`.

**Plus a soft note (not a SAFE blocker):** the team's `change_rules.yaml#api-contract-change` rule says new error shapes require a consumer-side contract test bump. The portal team has a Pact contract in their repo; you'll need a coordinated PR there before this lands behind their version pin.

Want me to scaffold the regression test for R2 first (red-phase, you make it green)?

---

## Why this is "senior QA" — what to point at in the demo

- **Read the diff before asking.** Most AI assistants would say *"what files did you change?"* — this one walks the diff via git itself.
- **Risks anchored to file:line.** Not *"check for edge cases"* — `domain/Refund.kt:18 — idempotency key derivation moved`.
- **Confirmation gate before the verdict.** One focused question (*"does the portal retry on 5xx?"*) — not a 4-question interrogation.
- **HARD GATE on test evidence.** Refuses to call safe-to-merge from "CI was green earlier." Runs the suite now, shows the output.
- **Risk-to-test coverage map.** Every risk is matched to a passing test or flagged as uncovered. Two risks were uncovered — that's the verdict.
- **Verdict refuses to soften the call.** The portal team's contract bump is real but separate; the suite-uncovered risks are the SAFE blockers.

This is what *"senior QA"* looks like in practice: the bug doesn't ship; the AI doesn't pretend.
