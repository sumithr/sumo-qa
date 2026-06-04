# Exporting structured QA test cases

sumo-qa produces strong QA plans and review prose, but teams that work in
test-management tooling sometimes need the same artifacts in a machine-readable
shape they can import or script against. The QA-artifact export (issue #148) does
exactly that — and nothing more: it deterministically projects test cases the
host has **already structured** into a small set of documented formats.

Markdown prose stays the **default human-facing output**. Export is opt-in: it
happens only when the user explicitly asks for it, and a normal review or
planning turn is unchanged. Export never becomes the default response shape.

## What identifies the cases

The **host LLM** identifies the test cases, from the QA work it has already done
(a plan, a risk-to-test map, a review). The Python side is pure plumbing: it
validates the cases the host produced and renders them. **No Python code performs
LLM-style inference** — `sumo_qa_export_test_cases` only validates, counts, and
formats. It reuses existing structured state (the risk-ledger
[`EvidenceStatus`](RISK-LEDGER.md) vocabulary) rather than reparsing prose.

## Test-case schema

Each case carries these fields:

| Field | Meaning |
|---|---|
| `id` | Stable id **within this export** (e.g. `TC1`) — the key a downstream import/script anchors on. Not a cross-session id; cross-session identity is out of scope until a persistence feature exists. |
| `title` | One-line human title for the case. |
| `preconditions` *(optional)* | Ordered setup steps that must hold before the checks run. May be empty. |
| `steps` *(optional)* | Ordered actions/checks the case performs. May be empty for a pure-assertion case. |
| `expected_result` | The observable outcome that distinguishes pass from fail. |
| `linked_risk_id` *(optional)* | Link to a risk id in a companion [risk ledger](RISK-LEDGER.md). Absence is fine — not every case traces to a single recorded risk. |
| `priority` | One of `critical`, `high`, `medium`, `low`. |
| `evidence_status` | One of `planned`, `passing`, `failing`, `stale`, `accepted_residual` — the **same vocabulary as the risk ledger**, so a case and a ledger row mean the same thing by the same word. |

The whole export carries a `schema_version` (`"1.0"` — **versioned from the
start**) and an optional `title` for the export as a whole. A producer that
forgets to stamp the version, or stamps a version this build doesn't recognise,
is rejected with a clear `schema_version_mismatch` message.

## Formats

`format` is one of three documented, host-neutral shapes:

| Format | Shape | Notes |
|---|---|---|
| `markdown` | A markdown table | **The default.** Human-facing; ordered preconditions/steps render as `1. … ; 2. …` inside their cell. |
| `json` | A versioned, key-sorted document | **Deterministic** (`sort_keys=True`, no float content) so it is byte-for-byte stable and snapshot/diff-friendly. `linked_risk_id` is always present (`null` when absent) so the shape is uniform across cases. |
| `csv` | Flat rows | **Optional, and only for a *flat* outline** — at most one precondition and one step per case. A nested case would force an ordered list into a single CSV cell, which CSV cannot represent without losing structure, so a non-flat CSV request is **refused** with a message naming the offending case ids. Export as `json` or `markdown` to keep the ordered structure. |

There is **no dependency on any single external test-management vendor**, and
**no new mandatory install dependency**: `json` and `csv` are Python standard
library.

## Side-effect free

The export tool **returns the rendered text; it never writes a file**. If you
want the export on disk, your host saves the returned `content` — the tool itself
does no file IO, so an export request can never mutate the working tree.

## Invalid requests

An unsupported `format` (anything outside `json` / `markdown` / `csv`) fails with
a clear message listing exactly the supported formats. A CSV request for a
non-flat export fails with a message naming the cases that aren't flat. Both
surface as a structured error envelope, so the host can act on the category
rather than parse free text.

## Import-mapping caveat

The exported formats are **generic, not tool-specific**. Every test-management
system (Testmo, Testsigma, TestMap.ai, Jira, Xray, and others) has its own field
names, required columns, and id conventions. **Tool-specific import mappings may
need local adjustment** — for example mapping `priority`/`evidence_status` onto a
target tool's own enums, or renaming `id` to the importer's expected key. Treat
the export as a faithful, stable source the team adapts to its importer, not a
turnkey upload for any one vendor.

## Worked sample

A two-case export rendered as the default markdown table:

```text
**QA test cases — Billing refund + webhook**

| ID | Title | Preconditions | Steps / checks | Expected result | Risk | Priority | Evidence |
|---|---|---|---|---|---|---|---|
| TC1 | Refund is idempotent across a retried request. | 1. A charge exists with a known idempotency key. | 1. POST the refund twice with the same idempotency key. | The charge is refunded exactly once; the second call is a no-op. | R1 | critical | passing |
| TC2 | Webhook retry does not double-fire. | — | — | Exactly one downstream event is emitted per source event. | — | medium | planned |
```

The same export as `csv` (flat — one precondition and one step per case):

```csv
id,title,precondition,step,expected_result,linked_risk_id,priority,evidence_status
TC1,Refund is idempotent across a retried request.,A charge exists with a known idempotency key.,POST the refund twice with the same idempotency key.,The charge is refunded exactly once; the second call is a no-op.,R1,critical,passing
TC2,Webhook retry does not double-fire.,,,Exactly one downstream event is emitted per source event.,,medium,planned
```
