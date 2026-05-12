# Scenario 01 — Plan QA for a new story

> **Demo arc:** *"the AI prepped a real QA plan with named risks for a story — anchored to actual file paths, not generic edge-case-shaped advice."*
>
> Shows: explore-before-asking discipline, 3–7 risks anchored to file:line, one technique per risk from the loaded catalogue, smallest-useful test set tied to those risks, sectioned conversational pacing with a single confirmation gate.

---

## Turn 1 — User

> Plan QA for ticket BILL-481 — adding a partial-refund flow to the billing service. Files probably touch `services/billing/refund.py` and `services/billing/invoice.py`. Refund amount can be less than the invoice total; consumers expect 4xx-vs-5xx semantics for partial-vs-full failure.

---

## Turn 2 — sumo-qa

*(internal: invokes `qa-deciding-approach`. Reads the intent — pre-coding QA prep for a new flow that touches the API contract and the refund business logic. Classification: `api_contract_change` + `business_logic_change`. Approach: `risk-first-prep`. Routes to `qa-preparing-for-work`.)*

*(internal: loads `sumo_qa_load_standards(classification="api_contract_change,business_logic_change")` + `sumo_qa_load_rules(...)` — the billing team's `change_rules.yaml#refund-flow` rule requires idempotency guarantees on any money-moving endpoint, and the API-contract rule pins new error shapes to a consumer-side contract test.)*

*(internal: walks `services/billing/refund.py` and `services/billing/invoice.py` with the host's file tools — does NOT ask the user "what's in these files?".)*

I've read both files. Quick scope summary, then I'll lay out the named risks and the test set in the next turn — flag if any of the scope is off before I do.

**What's actually in scope (from reading the files):**

| File | Current shape | Where partial-refund attaches |
|---|---|---|
| `services/billing/refund.py` | One existing `process_refund()` at line 34 — full-refund only. Validates `charge_id`, calls the payment processor, writes a `RefundIssued` event. Raises `RefundFailed` on any processor error → caller maps to 500. | New code path needs to branch on `amount < invoice.total` and call a different processor method (`processor.refund_partial(charge_id, minor_units)`) which has different failure semantics. |
| `services/billing/invoice.py` | `Invoice` dataclass at line 12; `total` is a `Decimal` in major units; `line_items` is a list with per-item `amount` (Decimal) and `currency` (ISO 4217). **No method currently sums line items at refund time — `total` is trusted as cached.** | Partial refund needs to reconcile the requested amount against either the cached `total` or a fresh sum of `line_items`. The two can drift if a line item was voided post-invoice-issue. |

**Loaded team rules that apply:**
- `change_rules.yaml#refund-flow` — money-moving endpoints must be idempotent on `(charge_id, amount)` and the idempotency key must be derivable from the request, not from mutable state.
- `change_rules.yaml#api-contract-change` — new error shapes (the 4xx-vs-5xx split you mentioned) need a consumer-side contract test bump before the change lands.

**One thing I want to pin down before I name the risks:** you said *"4xx-vs-5xx semantics for partial-vs-full failure"* — I want to confirm I've got the mapping right. My read of your wording: **partial failure** (some refund went through, some didn't, e.g. processor accepted but ledger write failed) should be a **5xx** (transient, retry-safe), and **full failure on a bad request** (e.g. amount > invoice.total, or amount is negative) should be a **4xx** (permanent, do not retry). Is that the split, or have I inverted it?

---

## Turn 3 — User

> Yes that's the split. 4xx for "your request was wrong", 5xx for "we accepted it but something downstream broke and you can retry". And `total` can drift from `sum(line_items)` — we had an incident on that two quarters back. Good catch.

---

## Turn 4 — sumo-qa

Good — the drift history is exactly the kind of thing that elevates that risk. Here are the named risks, each anchored to a file:line and a technique from the catalogue. Tell me if any are wrong-shaped or if I've missed one before I propose the test set.

> **R1 — `services/billing/invoice.py:12` — `total` vs `sum(line_items)` drift.** A partial refund authorised against the cached `total` can exceed the *actual* current sum of line items (if a line was voided after the invoice was issued). The refund "succeeds" against `total`, but the customer is refunded for money they were never billed for after the void. Anchored to your two-quarters-ago incident.
> **Technique:** *decision table* — combinations of `(line_voided_after_issue?, refund_amount_vs_cached_total, refund_amount_vs_live_sum)`. The table makes the drift cell visible; it's not a boundary, it's a state mismatch.
>
> **R2 — `services/billing/refund.py:34` (current `process_refund`) — idempotency key derivation on the new partial path.** The team's refund-flow rule requires the idempotency key to be derivable from the request `(charge_id, amount)`, not from mutable state. If the new partial path derives from `invoice.total` (mutable, can drift per R1) or from a server-side timestamp, a retry after a transient failure produces a *different* key → **double refund**.
> **Technique:** *state transition testing* — `(submitted, processor_accepted_ledger_failed, retried)` triple, asserting the second call returns the cached result of the first.
>
> **R3 — `services/billing/refund.py` new branch (`amount < invoice.total`) — 4xx-vs-5xx misclassification.** You confirmed the split: bad-request → 4xx, accepted-but-broken-downstream → 5xx. The risk is the new code path catching `RefundFailed` from `processor.refund_partial(...)` and mapping it the same way as the old full-refund path — collapsing both back into a generic 500 and losing the partial-failure signal that consumers need to decide retry vs surface-to-user.
> **Technique:** *decision table* — `(processor_outcome, ledger_outcome) → HTTP status`. Forces the four cells (both ok / processor ok + ledger fail / processor fail / both fail) to be named explicitly.
>
> **R4 — `services/billing/invoice.py:12` — `Decimal` vs `float` at the JSON boundary.** `Invoice.total` and `line_item.amount` are `Decimal`, but inbound refund requests are JSON-deserialised — depending on the deserialiser, `10.10` becomes a float and round-trips through minor-unit conversion as `1010.0000000001`. The validation will either accept it (and lose precision later) or reject a value that looks fine to the caller.
> **Technique:** *boundary value analysis* on the currency precision boundary — values with trailing decimals that are exact in `Decimal` but inexact in `float`.
>
> **R5 — Multi-currency invoices (`services/billing/invoice.py:12`, `line_items[i].currency`).** Nothing in the current code enforces single-currency invoices. If `line_items` contains mixed currencies, *what does a partial refund of "£15.00" against an invoice with both GBP and EUR lines even mean?* This is a domain-model risk, not a code risk — the right answer might be "reject mixed-currency partials at the validator", but it has to be a *deliberate* answer.
> **Technique:** *equivalence partitioning* — single-currency invoice vs mixed-currency invoice are different equivalence classes; partial-refund behaviour needs to be specified for both before code lands.

5 risks, one per substantive failure mode. I deliberately didn't pad to 7 — the remaining surfaces (auth, rate limiting, observability) are already covered elsewhere in the service and aren't moved by this change.

Match how you'd describe it, or is there a risk to add / re-anchor before I propose the test set?

---

## Turn 5 — User

> R5 is one I hadn't thought about — yes, we should reject mixed-currency at the validator, but you're right it has to be deliberate. Otherwise the list matches. Go.

---

## Turn 6 — sumo-qa

Here's the smallest-useful test set — 5 tests, one per named risk. Each ties to its risk explicitly so you can drop any test if its risk is later judged out of scope.

**Test set:**

| # | Test name | Targets risk | Technique | Smallest assertion |
|---|---|---|---|---|
| T1 | `test_partial_refund_rejects_when_cached_total_drifts_from_live_sum` | R1 (`total` drift) | decision table | Given an invoice with a voided line item, a partial refund authorised against `cached_total` is rejected with 4xx + reason `INVOICE_TOTAL_DRIFTED`; suite uses a fixture that mutates `line_items` after invoice issue. |
| T2 | `test_partial_refund_idempotent_under_retry_after_transient_failure` | R2 (idempotency) | state transition | Two `process_refund(charge_id, amount=15.00)` calls with the processor failing the first ledger write and succeeding the second; assert exactly one `RefundIssued` event written, second call returns the cached result. |
| T3 | `test_partial_refund_status_code_decision_table` | R3 (4xx-vs-5xx) | decision table | Parameterised over `(processor_outcome, ledger_outcome)` — asserts `(ok, ok) → 200`, `(ok, fail) → 5xx`, `(fail_bad_request, _) → 4xx`, `(fail_transient, _) → 5xx`. One test, four cells. |
| T4 | `test_partial_refund_amount_precision_at_decimal_float_boundary` | R4 (Decimal/float) | boundary value | Posts `{"amount": 10.10}` (JSON float) and asserts the validator either normalises to `Decimal('10.10')` exactly or rejects with a clear precision error — *not* a silent `1010.0000000001` minor-unit conversion. |
| T5 | `test_partial_refund_rejects_mixed_currency_invoice` | R5 (multi-currency) | equivalence partitioning | Given an invoice with `line_items` in both GBP and EUR, partial refund of "£15.00" is rejected at the validator with `UNSUPPORTED_MIXED_CURRENCY_REFUND` — the *deliberate* answer you confirmed in turn 5. |

**Specialty tool fits (offer, not impose):**
- **Pact (or schemathesis if your consumers are internal-only)** — for R3. New error shapes on the partial-refund response are exactly what consumer-driven contract tests exist for; the team's `change_rules.yaml#api-contract-change` rule already requires a consumer-side bump, so a Pact test gives you the artefact that satisfies the rule. **Want me to scaffold the contract under `tests/contracts/`?** I can wire the first interaction against the new 422 shape.
- **Hypothesis** — for R2. Idempotency is a property (`process_refund(req)` then `process_refund(req)` ≡ `process_refund(req)` regardless of intervening transient failures), and property-based generation is the cheapest way to find the retry-ordering case you didn't think of. Worth one property test alongside T2.
- **Not k6, not Playwright** — performance and end-to-end aren't moved by this change; the risk surfaces are domain-model and contract-shaped, not latency-shaped.

**Open assumptions to validate before coding:**
1. *Reconciliation source-of-truth.* When `cached_total` drifts from `sum(line_items)`, T1 assumes the live sum wins and the refund is rejected. Confirm that's the product call — the alternative ("refresh `total` lazily and proceed") changes T1 to a happy-path test.
2. *Retry window for idempotency.* T2 assumes idempotency holds *indefinitely* on `(charge_id, amount)`. If there's a TTL (e.g. 24h), the test needs a clock fixture and the rule on the wall.
3. *Mixed-currency policy locked in writing.* T5 codifies the answer from turn 5. Worth a one-liner in the ticket description so the test isn't the only place the policy lives.

That's the prep brief — 5 risks, 5 tests, 2 specialty fits offered, 3 assumptions to nail down before the first commit. Want me to scaffold T1 red-first as the entry point, or pick a different test to start from?

---

## Why this is "senior QA" — what to point at in the demo

- **Read the files before asking.** Two reads (`refund.py`, `invoice.py`) before a single risk was named. The `total`-vs-`sum(line_items)` drift only surfaces because the file was actually read — no amount of reasoning from the prompt alone would have caught it.
- **Risks anchored to file:line, not vibes.** *"`services/billing/invoice.py:12` — `Decimal` vs `float` at the JSON boundary"* — not *"check for input validation"*. Every risk names the failure mode and the specific line where it lives.
- **One confirmation gate, not an interrogation.** A single focused question in turn 2 (*"is partial-failure 5xx or 4xx?"*) before committing to risks. Not a four-question dump.
- **Catalogue techniques, not folk wisdom.** Each risk gets a named technique — decision table, state transition, boundary value, equivalence partitioning — taken from the loaded techniques catalogue, not invented on the spot.
- **5 risks, not 15.** The Iron Law is *no test idea without a named risk*; the discipline is the inverse — *no risk without a real failure mode*. Padding to 7 to "look thorough" is confabulation. 5 was the right count for this change.
- **Specialty tools offered by fit, not by brand.** Pact for the contract risk, Hypothesis for the property risk, *explicitly not* k6 or Playwright because those surfaces aren't moved. Empty list would have been fine; reaching for k6 to look complete would not have been.
- **Internal labels translated to English.** No *"Classification: business_logic_change, Approach: risk-first-prep"* in the user-facing output. The taxonomy stays behind the curtain; the user gets named risks.
- **Open assumptions are explicit.** Three assumptions named at the bottom — what the test set *currently* encodes that hasn't been confirmed by the product call. Senior QA surfaces these *before* code is written, not after a bug ships.

This is what *"shift-left QA"* looks like before the first line of production code: the risks are on the wall, the tests have addresses, and the assumptions are visible.
