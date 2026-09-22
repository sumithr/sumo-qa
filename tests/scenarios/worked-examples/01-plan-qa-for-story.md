# Scenario 01 — Plan QA for a new story

> **Summary:** *"the AI prepped a real QA plan with named risks for a story — anchored to actual file paths, not generic edge-case-shaped advice."*
>
> Shows: explore-before-asking discipline, a small set of risks anchored to file:line (5 here: a multi-file change where each risk is a distinct failure the other four miss), one technique per risk from the loaded catalogue, smallest-useful test set tied to those risks, sectioned conversational pacing with a single confirmation gate.

---

## Turn 1 — User

> Plan QA for ticket BILL-481 — adding a partial-refund flow to the billing service. Files probably touch `services/billing/refund.py` and `services/billing/invoice.py`. Refund amount can be less than the invoice total; consumers expect 4xx-vs-5xx semantics for partial-vs-full failure.

---

## Turn 2 — sumo-qa

*(internal: invokes `sumo-qa-deciding-approach`. Reads the intent — pre-coding QA prep for a new flow that touches the API contract and the refund business logic. Classification: `api_contract_change` + `business_logic_change`. Approach: `risk-first-prep`. Routes to `sumo-qa-preparing-for-work`.)*

*(internal: loads `sumo_qa_load_standards(classification="api_contract_change,business_logic_change")` + `sumo_qa_load_rules(...)` — the billing team's `change_rules.yaml#refund-flow` rule requires idempotency guarantees on any money-moving endpoint, and the API-contract rule pins new error shapes to a consumer-side contract test.)*

*(internal: walks `services/billing/refund.py` and `services/billing/invoice.py` with the host's file tools — does NOT ask the user "what's in these files?".)*

I've read both files. Quick scope summary, then I'll lay out the named risks and the test set in the next turn — flag if any of the scope is off before I do.

**What's actually in scope (from reading the files):**

| File | Current shape | Where partial-refund attaches |
|---|---|---|
| `services/billing/refund.py` | One existing `process_refund()` at line 34 — full-refund only. Validates `charge_id`, calls the payment processor, writes a `RefundIssued` event. Raises `RefundFailed` on any processor error → caller maps to 500. | New code path needs to branch on `amount < invoice.total` and call a different processor method (`processor.refund_partial(charge_id, minor_units, idempotency_key)`) which has different failure semantics. |
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
> **Technique:** *state transition testing*: the `(submitted, processor_accepted_ledger_failed, retried)` triple, with `total` changed and the clock moved across a year and ISO-week boundary before the retry, asserting every processor call passes the same `idempotency_key` value, one processor refund and exactly one `RefundIssued` event across the retry.
>
> **R3 — `services/billing/refund.py` new branch (`amount < invoice.total`) — 4xx-vs-5xx misclassification.** You confirmed the split: bad-request → 4xx, accepted-but-broken-downstream → 5xx. The risk is the new code path catching `RefundFailed` from `processor.refund_partial(...)` and mapping it the same way as the old full-refund path — collapsing both back into a generic 500 and losing the partial-failure signal that consumers need to decide retry vs surface-to-user.
> **Technique:** *decision table* — `(processor_outcome, ledger_outcome) → HTTP status`. Forces the four cells (both ok / processor ok + ledger fail / processor fail / both fail) to be named explicitly.
>
> **R4 — `services/billing/invoice.py:12` — `Decimal` vs `float` at the JSON boundary.** `Invoice.total` and `line_item.amount` are `Decimal`, but inbound refund requests are JSON-deserialised. Depending on the deserialiser, `19.99` becomes a float, and a naive minor-unit conversion (`int(19.99 * 100)`, where `19.99 * 100` is `1998.9999999999998`) yields `1998`, a penny short. The validation will either accept it (and lose precision later) or reject a value that looks fine to the caller.
> **Technique:** *boundary value analysis* on the currency precision boundary — values with trailing decimals that are exact in `Decimal` but inexact in `float`.
>
> **R5 — Multi-currency invoices (`services/billing/invoice.py:12`, `line_items[i].currency`).** Nothing in the current code enforces single-currency invoices. If `line_items` contains mixed currencies, *what does a partial refund of "£15.00" against an invoice with both GBP and EUR lines even mean?* This is a domain-model risk, not a code risk — the right answer might be "reject mixed-currency partials at the validator", but it has to be a *deliberate* answer.
> **Technique:** *equivalence partitioning* — single-currency invoice vs mixed-currency invoice are different equivalence classes; partial-refund behaviour needs to be specified for both before code lands.

5 risks, one per substantive failure mode across the two files. I deliberately didn't pad further: the remaining surfaces (auth, rate limiting, observability) are already covered elsewhere in the service and aren't moved by this change.

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
| T1 | `test_partial_refund_never_exceeds_live_sum_when_cached_total_drifts` | R1 (`total` drift) | decision table | Invoice issued at `total` 100.00, then a 20.00 line voided (live sum 80.00); request a partial refund of 90.00. Both reconciliation rules reject it (live sum wins: rejected as drifted; refresh `total` and revalidate: `total` becomes 80.00 and 90.00 exceeds it), so assert only what holds under both: no `processor.refund_partial` call, no `RefundIssued` event, and a 4xx. The cached `total` staying authoritative is not a candidate rule: turn 5 confirmed R1, a refund above the live sum, as the failure. No reason code is asserted (assumption 1). Fixture mutates `line_items` after invoice issue. |
| T2 | `test_partial_refund_idempotent_when_mutable_state_changes_before_retry` | R2 (idempotency) | state transition | Invoice `total` 100.00; `process_refund(charge_id, amount=15.00)`: the processor accepts, its ledger write fails. Before the retry, change the mutable inputs R2 names: void a 10.00 line and update the cached `total` to 90.00 (15.00 stays valid under every reconciliation rule), and advance the UTC test clock 2 ms across a year and ISO-week boundary (Sunday 2028-12-31 23:59:59.999Z, ISO week 2028-W52, to Monday 2029-01-01 00:00:00.001Z, ISO week 2029-W01), with the service truncating timestamps in UTC, so the raw timestamp and its second, minute, hour, day, ISO-week, month and year truncations all change, while 2 ms is well inside any realistic idempotency TTL (assumption 2). Retry the same request; its ledger write succeeds. Assert: the processor refunds once and exactly one `RefundIssued` event is written across both calls. That pair is what discriminates under BOTH assumption-3 orderings — if the processor key, or the stored-result lookup the short-circuit ordering depends on, derives from `total` or from a truncated timestamp, the mutated inputs yield a second refund either way. Additionally, where the retry does re-send to the processor (assumption 3's second ordering, observable as two `processor.refund_partial` calls), assert the two calls carry the same `idempotency_key` as each other. Do NOT assert the key's expected VALUE: the story constrains what the key may depend on, not how it is derived, so an absolute value would be an oracle this story cannot supply, and a value lifted from the implementation would establish nothing; the processor refunds once; exactly one `RefundIssued` event is written across both calls. What the retry returns is not asserted (assumption 3). |
| T3 | `test_partial_refund_status_code_decision_table` | R3 (4xx-vs-5xx) | decision table | Parameterised over `(processor_outcome, ledger_outcome)`: asserts `(ok, ok) → 2xx`, `(ok, fail) → 5xx`, `(fail_bad_request, fail) → 4xx`, `(fail_transient, fail) → 5xx`. In both processor-failure rows the ledger stub is set to fail and the test asserts no `RefundIssued` write is attempted, so the ledger outcome cannot reach the status and those rows cover the processor-fail and both-fail cells. One test, four rows. The exact success code is not asserted (assumption 4). |
| T4 | `test_partial_refund_amount_precision_at_decimal_float_boundary` | R4 (Decimal/float) | boundary value | Parameterised over both sides of the float-exactness boundary, posted as JSON floats: `{"amount": 10.25}` (exact in binary float) and `{"amount": 19.99}` (inexact: `19.99 * 100` is `1998.9999999999998`). Whether the API accepts a JSON-float amount is not yet agreed (assumption 5), so the expected outcome is stated per option. Accept and normalise: the amounts are recorded as `Decimal('10.25')` and `Decimal('19.99')`, and `processor.refund_partial` receives exactly `1025` and `1999` minor units. Reject: a 4xx and no `processor.refund_partial` call for either. Under either option the processor never receives `1998` or a non-integer amount. Once the option is confirmed, T4 keeps only that branch, so a regression to the other one fails. |
| T5 | `test_partial_refund_rejects_mixed_currency_invoice` | R5 (multi-currency) | equivalence partitioning | Given an invoice with `line_items` in both GBP and EUR, partial refund of "£15.00" is rejected at the validator: a 4xx, no `processor.refund_partial` call, no `RefundIssued` event. That is the *deliberate* answer you confirmed in turn 5; its reason code was not agreed, so none is asserted. |

**Specialty tool fits (offer, not impose):**
- **Pact (or schemathesis if your consumers are internal-only)** — for R3. New error shapes on the partial-refund response are exactly what consumer-driven contract tests exist for; the team's `change_rules.yaml#api-contract-change` rule already requires a consumer-side bump, so a Pact test gives you the artefact that satisfies the rule. **Want me to scaffold the contract under `tests/contracts/`?** I can wire the first interaction against the new 4xx shape.
- **Hypothesis** — for R2. Idempotency is a property (running `process_refund(req)` twice has the same side effects as running it once, regardless of intervening transient failures), and property-based generation is the cheapest way to find the retry-ordering case you didn't think of. Worth one property test alongside T2.
- **Not k6, not Playwright** — performance and end-to-end aren't moved by this change; the risk surfaces are domain-model and contract-shaped, not latency-shaped.

**Open assumptions to validate before coding:**
1. *Reconciliation source-of-truth.* When `cached_total` drifts from `sum(line_items)`, either the live sum wins and the refund is rejected as drifted, or `total` is refreshed lazily and the request is revalidated against it. (Turn 2's other option, reconciling against the cached `total` as authoritative, is ruled out: you confirmed R1, a refund above the live sum, as a real failure. The lazy-refresh rule is a second way to use the fresh sum, raised here rather than in turn 2.) T1 asserts only what holds under both (no processor call, no `RefundIssued` event, a 4xx) and no reason code, because neither rule nor the confirmed 4xx/5xx split fixes one. Confirm the product call and the rejection reason code (a drift-specific code, or the ordinary amount-exceeds-total one); then T1 can assert that code, and a refund at or below the live sum can get its own expected outcome.
2. *Retry window for idempotency.* Whether idempotency on `(charge_id, amount)` holds indefinitely or expires after a TTL (e.g. 24h) is unstated. T2 retries 2 ms later, which is well inside any realistic TTL, across a boundary that changes the UTC second, minute, hour, day, ISO week, month and year. That holds only if the service truncates timestamps in UTC; if it uses a local timezone, move the boundary to that zone's year end. A retry after the window needs the confirmed TTL before it can be written.
3. *Retry ordering after a ledger failure.* When the processor accepts but the ledger write fails, it is unstated whether the result is stored before the ledger write, or the retry re-sends the same `idempotency_key` to `processor.refund_partial` and completes the ledger. Either way, the 5xx meaning you confirmed ("you can retry") means the retry must finish the refund, so T2 asserts one processor refund and exactly one `RefundIssued` event; once the ordering is confirmed, T2 can also assert what the retry returns.
4. *Success status code.* You confirmed the 4xx/5xx split, not which 2xx a successful partial refund returns (200, 201 or 202). T3 asserts any 2xx; pin the exact code in the contract test once it is agreed.
5. *JSON-float amounts.* Whether a request with `{"amount": 19.99}` as a JSON float is accepted and normalised, or rejected in favour of a string or minor-unit amount, is unstated. T4 gives the expected outcome under each option; confirm the contract so T4 keeps one.
6. *Mixed-currency policy locked in writing.* T5 codifies the answer from turn 5 but asserts no reason code, since none was agreed. Worth a one-liner in the ticket description (the policy and its reason code) so the test isn't the only place the policy lives.

That's the prep brief — 5 risks, 5 tests, 2 specialty fits offered, 6 assumptions to nail down before the first commit. Want me to scaffold T1 red-first as the entry point, or pick a different test to start from?

---

## Why this is senior QA

- **Read the files before asking.** Two reads (`refund.py`, `invoice.py`) before a single risk was named. The `total`-vs-`sum(line_items)` drift only surfaces because the file was actually read — no amount of reasoning from the prompt alone would have caught it.
- **Risks anchored to file:line, not vibes.** *"`services/billing/invoice.py:12` — `Decimal` vs `float` at the JSON boundary"* — not *"check for input validation"*. Every risk names the failure mode and the specific line where it lives.
- **One confirmation gate, not an interrogation.** A single focused question in turn 2 (*"is partial-failure 5xx or 4xx?"*) before committing to risks. Not a four-question dump.
- **Catalogue techniques, not folk wisdom.** Each risk gets a named technique — decision table, state transition, boundary value, equivalence partitioning — taken from the loaded techniques catalogue, not invented on the spot.
- **5 risks, not 15.** The Iron Law is *no test idea without a named risk*; the discipline is the inverse: *no risk without a real failure mode*. Padding to "look thorough" is confabulation. 5 was the right count for this multi-file change; without a grounded security risk, a single-component change stops at 3-4.
- **Specialty tools offered by fit, not by brand.** Pact for the contract risk, Hypothesis for the property risk, *explicitly not* k6 or Playwright because those surfaces aren't moved. Empty list would have been fine; reaching for k6 to look complete would not have been.
- **Internal labels translated to English.** No *"Classification: business_logic_change, Approach: risk-first-prep"* in the user-facing output. The taxonomy stays behind the curtain; the user gets named risks.
- **Open assumptions are explicit.** Six assumptions named at the bottom: the product and contract calls not yet confirmed. Where a test's expected outcome hinges on one (T1 to T5), it asserts what holds under every candidate rule, or the outcome under each, instead of silently picking one. Senior QA surfaces these *before* code is written, not after a bug ships.

This is what *"senior QA"* looks like before the first line of production code: the risks are on the wall, the tests have addresses, and the assumptions are visible.
