# Risk-to-test traceability ledger

sumo-qa's skills already name risks and map tests to them — but until now that
mapping lived only as prose inside a single response. The risk-to-test ledger
(issue #144) is a small **structured appendix** that makes the same mapping
paste-able into an issue or PR and traceable across a review: one row per named
risk, carrying the covering test (or planned check), the current evidence, and
the residual decision.

The ledger is an **appendix, never a replacement**. The markdown-first verdict —
the named risks, the coverage map, the SAFE / NOT SAFE call — is still the
deliverable. The ledger is offered when the user wants the structured artifact;
the prose answer is unchanged either way.

## What identifies the risks

The **host LLM** identifies the risks, from repo context, exactly as it does
today inside the skills. The Python side is pure plumbing: it validates the rows
the host produced and renders them. **No Python code performs LLM-style risk
inference** — `sumo_qa_format_risk_ledger` only validates, counts, and formats.

## Row schema

Each row carries six required fields plus one optional link:

| Field | Meaning |
|---|---|
| `risk_id` | Stable id **within this response or exported artifact** (e.g. `R1`). Not a cross-session id — see *Stability* below. |
| `risk` | The risk statement, plain English. |
| `source_anchor` | Where the risk lives: `file:line`, a domain term, or a contract name. |
| `test` | The covering test id, **or** a planned check phrase (e.g. `planned: boundary-value test on Decimal('10.10') vs float`). |
| `evidence_status` | One of the five distinct states below. |
| `residual` | The residual decision: `open`, `accepted`, `mitigated`, or `blocker`. |
| `repo_map_node_id` *(optional)* | A link to a `.sumo-qa/repo-map.json` node id ([REPO-MAP.md](REPO-MAP.md)). Absent is fine — a missing or stale repo-map is weaker evidence, never a blocker. |

### Evidence-status vocabulary

The five states are deliberately distinct so a ledger can represent every point
in a check's lifecycle:

| `evidence_status` | Represents |
|---|---|
| `planned` | Planned but not executed (the only state a planning-only ledger uses). |
| `passing` | Executed and passing this turn. |
| `failing` | Executed and failing this turn. |
| `stale` | Stale evidence — a prior pass that no longer reflects the current code (e.g. an `xfail` pinning old behaviour). |
| `accepted_residual` | An accepted residual risk — a deliberate decision not to cover, distinct from an un-run check. |

### Uncovered blockers

A row is an **uncovered blocker** when its evidence is not demonstrably
`passing`, it has not been marked `accepted_residual`, and its `residual` is
`blocker`. The review workflow refuses a SAFE-to-merge verdict while any
uncovered blocker remains — the structured mirror of the prose rule that an
uncovered high-risk row blocks merge. The tool surfaces an
`uncovered_blocker_count` so this gate is a single field, not a manual re-read.

## Output shape

`sumo_qa_format_risk_ledger(rows, max_rows=25)` returns:

- `markdown` — the rendered ledger table (the appendix the verdict carries). The
  optional `Repo-map node` column appears only when a row carries a link, and
  the table truncates past `max_rows` with a `… +N more` notice so a large
  ledger stays inside the host token budget (issues #89 / #137).
- `compact_summary` — a one-line roll-up, e.g.
  `Risk ledger: 3 risks — 1 passing, 1 planned, 1 failing; 1 uncovered blocker.`
- `row_count`, `uncovered_blocker_count`, `truncated`.

A ledger payload can also be validated directly through
`sumo_qa.ledger_validation.load_ledger`, which raises `LedgerValidationError`
with a stable `kind` (`schema_version_mismatch`, `missing_field`,
`unknown_field`, `vocab_error`, `value_error`, `type_error`) so callers branch on
the category rather than parsing messages.

## Stability and privacy

- **Stable within one response / artifact, not across sessions.** Row ids are a
  lookup key inside a single ledger; cross-session identity is deliberately out
  of scope until a later persistence feature exists. The schema is versioned
  (`schema_version: "1.0"`) so that future change is a visible version bump.
- **No persistence by default.** The tool stores nothing. Repo paths, issue
  text, and review findings only ever appear in a row the host explicitly built
  and only travel where the host already surfaces its answer.

## Which skills maintain the ledger

The ledger is an **optional** appendix in these workflows — each still leads with
its prose deliverable:

- **`sumo-qa-reviewing-before-merge`** — projects the named risks + coverage map
  below the verdict; `uncovered_blocker_count` must be 0 before SAFE.
- **`sumo-qa-preparing-for-work`** — a planning-only ledger (all rows `planned`),
  no code change and no test run required.
- **`sumo-qa-creating-test-plan`** — the confirmed risk→technique table as a
  traceable appendix to the formal plan.
- **`sumo-qa-finishing-qa-work`** — the run's risk-to-test map rendered as a
  paste-ready ledger for the PR / summary.

## When NOT to use it

- **Trivial-change reviews.** A docs typo or a one-line config tweak does not
  warrant a ledger; manufacturing one adds noise. Prose suffices.
- **When the user only wants the verdict / brief.** The ledger is offered on
  request, not forced into every answer — bloating a normal answer with a table
  regresses the token-budget work.
- **As a source of truth that can contradict the skill response.** The ledger is
  a projection of the same risks the prose names. It must never diverge from the
  verdict; if they disagree, the prose verdict is authoritative and the ledger is
  wrong.
- **For cross-session or cross-PR identity.** Row ids are not stable across
  sessions yet; do not build tooling that assumes `R1` means the same risk
  tomorrow.
