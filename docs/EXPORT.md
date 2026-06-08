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
start**) and an optional export-level title, supplied via the **`export_title`**
tool argument (named `export_title`, not `title`, so it stays distinct from each
case's `title` and survives the served-schema title-slimming pass) and rendered
as the top-level `title` in the JSON and in the markdown header. A producer that
forgets to stamp the version, or stamps a version this build doesn't recognise,
is rejected with a clear `schema_version_mismatch` message.

## Formats

`format` is one of three documented, host-neutral shapes:

| Format | Shape | Notes |
|---|---|---|
| `markdown` | A markdown table | **The default.** Human-facing; ordered preconditions/steps render as `1. … ; 2. …` inside their cell. |
| `json` | A versioned, key-sorted document | **Deterministic** (`sort_keys=True`, no float content) so it is byte-for-byte stable and snapshot/diff-friendly. `linked_risk_id` is always present (`null` when absent) so the shape is uniform across cases. |
| `csv` | Flat rows | **Optional, and only for a *flat* outline** — at most one precondition and one step per case. A nested case would force an ordered list into a single CSV cell, which CSV cannot represent without losing structure, so a non-flat CSV request is **refused** with a message naming the offending case ids. Export as `json` or `markdown` to keep the ordered structure. Free-text cells are **hardened against spreadsheet formula injection** (OWASP guidance): a value starting with `=`, `+`, `-`, `@`, a tab or a carriage return is prefixed with a single apostrophe so it is treated as literal text, not evaluated as a live formula. |

There is **no dependency on any single external test-management vendor**, and
**no new mandatory install dependency**: `json` and `csv` are Python standard
library.

## Side-effect free by default

By default the export tool **returns the rendered text and writes nothing**. With
no `output_path` the tool does no file IO, so an export request can never mutate
the working tree — your host can save the returned `content` itself.

## Explicit file write (`output_path`)

Issue #148 authorises one carve-out: *"Keep export commands side-effect free
unless the user explicitly asks to write a file."* When — and only when — the
caller supplies an explicit **`output_path`**, the **same rendered bytes** that
`content` returns are **also** persisted to disk, and the resolved location comes
back in `written_path` (otherwise `written_path` is `None`).

The write is deliberately tight:

- **Confined to the project export root.** Writes land under
  `<cwd>/.sumo-qa/exports` (its own subdir under the user-pack root, parallel to
  `feedback/`, never colliding with the bundled knowledge/standards/rules tiers).
  A relative `output_path` resolves under that root.
- **No escape.** An absolute path outside the root, or a `..` traversal (or a
  symlink under `exports/`) that resolves outside it, is refused — nothing is
  written.
- **No silent overwrite.** If the target already exists the write is refused
  rather than clobbering it; choose another `output_path` or remove the file.
- **Atomic, validate-first.** The write happens only after a clean
  validate+render (a bad export never leaves a partial file). On POSIX the
  write opens the destination's parent directory and uses an `O_NOFOLLOW`
  `openat` + `renameat` chain against that verified directory fd, so a parent
  directory swapped for a symlink after validation (the TOCTOU race) cannot
  redirect the write outside the export root; Windows falls back to a
  `mkstemp` + `os.replace` swap. Either way a pre-existing symlinked target
  name is never followed during the write.

Each refusal surfaces as the same structured error envelope used elsewhere
(`ExportValidationError` for an out-of-root path, `FileExistsError` for an
existing target).

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

Every field is quoted (`QUOTE_ALL`) so an embedded carriage return or newline is
always re-readable across Python versions (a bare CR left unquoted broke
`csv.reader` round-trips on py3.10):

```csv
"id","title","precondition","step","expected_result","linked_risk_id","priority","evidence_status"
"TC1","Refund is idempotent across a retried request.","A charge exists with a known idempotency key.","POST the refund twice with the same idempotency key.","The charge is refunded exactly once; the second call is a no-op.","R1","critical","passing"
"TC2","Webhook retry does not double-fire.","","","Exactly one downstream event is emitted per source event.","","medium","planned"
```
