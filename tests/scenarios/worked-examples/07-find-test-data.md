# Scenario 07 — Find a known-good test data record

> **Demo arc:** *"the AI found 2 entries, validated both in real-time, surfaced one as stale (instead of silently dropping it), and asked before writing anything new to the team catalogue."*
>
> Shows: catalogue lookup (no inventing IDs), fresh per-turn validation against staging with timestamp evidence, explicit stale surfacing instead of silent substitution, and a hard confirmation gate before any write to the shared catalogue.

---

## Turn 1 — User

> Find me a refund-eligible invoice for the partial-refund flow test in staging.

---

## Turn 2 — sumo-qa

*(internal: invokes `qa-finding-test-data`. Intent is "find me a record" — routes to the `find` path. Question = "refund-eligible invoice for partial-refund flow"; environment = staging; domain = billing. No clarifying question needed — the user has given enough to dispatch.)*

*(internal: calls `sumo_qa_find_test_data(question="refund-eligible invoice for partial-refund flow", environment="staging", domain="billing", criteria={"scenario_tags": ["invoice_paid", "refund_eligible"]})`. Two catalogue hits. Pipes each into `sumo_qa_validate_test_data` against staging in this turn — not from cache.)*

Checking the billing catalogue for refund-eligible invoices and re-validating each against staging now.

**Catalogue matches (2):**

| ID | Domain | Scenario tags | Owner | Catalogue `last_validated_at` |
|---|---|---|---|---|
| `billing-paid-invoice-001` | billing | `invoice_paid`, `refund_eligible` | billing-platform | 2026-05-05T15:15:00Z |
| `billing-pending-due-boundary-001` | billing | `invoice_pending`, `boundary_due_date` | billing-platform | 2026-04-20T10:00:00Z |

**Fresh validation against staging — just now (2026-05-12 09:14 UTC):**

```
$ sumo_qa_validate_test_data --env staging --id billing-paid-invoice-001
  state:        PAID
  amount:       £420.00
  currency:     GBP
  refunded:     false
  refund_window_expires_at: 2026-06-04T15:15:00Z
  validated_at: 2026-05-12T09:14:07Z
  result:       FRESH — refund-eligible, partial-refund flow supported

$ sumo_qa_validate_test_data --env staging --id billing-pending-due-boundary-001
  state:        PENDING
  amount:       £180.00
  currency:     GBP
  refunded:     n/a (not yet paid)
  validated_at: 2026-05-12T09:14:09Z
  result:       STALE for "refund-eligible" — invoice has not been paid;
                refund flow is not reachable from this state
```

**Result:**

- **`billing-paid-invoice-001` — FRESH.** Re-validated against staging just now (2026-05-12 09:14 UTC). State `PAID`, £420.00, not yet refunded, refund window open until 2026-06-04. Use this one for the partial-refund flow test.
- **`billing-pending-due-boundary-001` — STALE for your scenario.** It's tagged `invoice_pending` / `boundary_due_date` in the catalogue, but the broader "refund-eligible" search picked it up. It's actually *valid* — it's still a clean pending invoice for the due-date boundary test — but it's **not refund-eligible** (you can't refund an unpaid invoice). Flagging it explicitly rather than silently dropping it so you can see what the catalogue claimed vs what staging actually returns. The catalogue's `last_validated_at` is from 22 days ago, which is the other reason I'm surfacing it — it's overdue for a refresh regardless.

Going to use `billing-paid-invoice-001` for the partial-refund test unless you've got a different one in mind. Want me to register a replacement entry tagged specifically for the partial-refund flow while we're here?

---

## Turn 3 — User

> Yes — I've been using `INV-PAID-88204` for the partial-refund test all week, it's a paid invoice with two line items so it actually exercises the partial path. Register that as known-good.

---

## Turn 4 — sumo-qa

*(internal: route shifts to `register`. Per the Iron Law and checklist step 5b — validate first against staging in this turn, then pause for explicit confirmation before writing to `knowledge/test_data/billing/`. Never silent-write.)*

Validating `INV-PAID-88204` against staging before I propose the catalogue entry.

```
$ sumo_qa_validate_test_data --env staging --id INV-PAID-88204
  state:        PAID
  amount:       £640.00
  currency:     GBP
  line_items:   2
    - SKU-A-117   £400.00
    - SKU-B-022   £240.00
  refunded:     false
  refund_window_expires_at: 2026-06-10T11:02:00Z
  validated_at: 2026-05-12T09:15:31Z
  result:       FRESH — paid, multi-line, partial-refund flow supported
```

Validated fresh just now (2026-05-12 09:15 UTC). Two line items confirmed — the partial-refund path is genuinely exercised by this fixture, not just nominally.

Proposed catalogue entry (would be written to `knowledge/test_data/billing/sample_invoices.yaml`):

```yaml
- id: billing-paid-partial-refund-001
  environment: staging
  domain: billing
  scenario_tags:
    - invoice_paid
    - refund_eligible
    - partial_refund
    - multi_line_item
  known_valid_for:
    - partial-refund flow test (multi-line invoice)
  constraints:
    - Reset payment + refund state before re-run.
    - Refund window expires 2026-06-10 — re-validate before that date.
  owner: billing-platform
  last_validated_at: "2026-05-12T09:15:31Z"
  confidence: high
  source: qa-curated
  validation_source: staging-live
  notes: |
    Paid invoice INV-PAID-88204, £640.00, 2 line items
    (SKU-A-117 £400.00 + SKU-B-022 £240.00).
    Exercises the partial-refund flow with real multi-line state.
```

**Register this as known-good?** I'll only write to `knowledge/test_data/billing/sample_invoices.yaml` on your explicit yes — and while I'm there I'll bump `billing-pending-due-boundary-001`'s `last_validated_at` since I re-validated it in this turn too (its core scenario is still good — just not for *this* test).

---

## Turn 5 — User

> Yes — register it. And yes, refresh the boundary one's timestamp while you're there.

---

## Turn 6 — sumo-qa

*(internal: explicit confirmation received for both writes. Now safe to call `sumo_qa_register_known_good_test_data` for the new entry and update the stale timestamp on the existing one.)*

Written.

```
$ sumo_qa_register_known_good_test_data --file knowledge/test_data/billing/sample_invoices.yaml
  appended:  billing-paid-partial-refund-001
  updated:   billing-pending-due-boundary-001 (last_validated_at → 2026-05-12T09:14:09Z)
  result:    OK
```

Summary of what you've got for your test run:

| ID | Use it for | Freshness |
|---|---|---|
| `billing-paid-partial-refund-001` | Partial-refund flow (multi-line, the one you wanted) | FRESH 2026-05-12 09:15 |
| `billing-paid-invoice-001` | Single-line paid-invoice refund flow (fallback) | FRESH 2026-05-12 09:14 |
| `billing-pending-due-boundary-001` | Pending-invoice due-date boundary test (different scenario) | FRESH 2026-05-12 09:14, timestamp refreshed |

For the partial-refund flow test, use `billing-paid-partial-refund-001` (or `INV-PAID-88204` if you're addressing the live record directly). Refund window closes 2026-06-10 — worth a re-validate before then if this test is still in rotation.

---

## Why this is "senior QA" — what to point at in the demo

- **No invented IDs.** The agent never says *"try `INV-12345`, that should work"*. Every record returned is either pulled from the catalogue and re-validated, or it's the user's own ID being validated before it's added.
- **Per-turn validation, not cached freshness.** The catalogue's `last_validated_at` is treated as a hint, not as truth. Both entries are re-hit against staging in this turn, with a timestamp the user can see.
- **Stale entry surfaced, not silently dropped.** `billing-pending-due-boundary-001` came back as not-refund-eligible. A junior AI would quietly drop it; this one explains *what the catalogue claimed*, *what staging actually returned*, and *why it's being set aside* — drift in the shared catalogue stays visible.
- **Internal routing stays internal.** The user never sees "Route: find" or "Route: register" — they see the work (the entries, the validation evidence, the timestamps).
- **Hard confirmation gate before the catalogue write.** The new entry is fully drafted, validated, and shown to the user — but nothing is written until they say yes. The shared catalogue is a team artefact; the agent treats it like one.
- **Bonus housekeeping with consent.** The stale timestamp on the boundary entry gets refreshed in the same write — but only after the user explicitly agrees. No piggy-backed side effects.

This is what *"shift-left QA"* looks like for test data: the team's catalogue stays honest, drift is surfaced not hidden, and nothing gets written without a human signing off.
