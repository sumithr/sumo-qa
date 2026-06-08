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
  below the verdict; `uncovered_blocker_count` must be 0 before SAFE. It ALSO
  reuses the same schema for an **acceptance-criteria coverage view** (issue
  #264) when the host supplies acceptance criteria — see *Acceptance-criteria
  coverage* below.
- **`sumo-qa-preparing-for-work`** — a planning-only ledger (all rows `planned`),
  no code change and no test run required.
- **`sumo-qa-creating-test-plan`** — the confirmed risk→technique table as a
  traceable appendix to the formal plan.
- **`sumo-qa-finishing-qa-work`** — the run's risk-to-test map rendered as a
  paste-ready ledger for the PR / summary.

## Acceptance-criteria coverage (issue #264)

`sumo-qa-reviewing-before-merge` answers two distinct questions: is the change
*correct* (risk→test coverage) and is it the *right* change — does it deliver
what the ticket asked for? The second is **acceptance/requirements
traceability**, the sibling of the risk→test traceability above: AC→evidence
rather than risk→test.

It deliberately **reuses the same `sumo_qa_format_risk_ledger` schema** — there
is no parallel structure and no new tool. One row per host-supplied acceptance
criterion:

| Ledger field | AC-coverage meaning |
|---|---|
| `risk_id` | `AC1`, `AC2`, … |
| `risk` | The criterion text, plain English. |
| `source_anchor` | The diff `file:line` / behaviour that satisfies it (or the criterion text when unmet). |
| `test` | The covering fresh test id, or a `planned: …` phrase. |
| `evidence_status` | `passing` = MET (cited fresh test); `planned` = UNMET (no implementing change) or UNVERIFIED (plausibly addressed but unproven this turn). |
| `residual` | `accepted` for a MET criterion; `blocker` for every UNMET / UNVERIFIED one. |

Because the schema is shared, the SAFE gate is too: `uncovered_blocker_count`
must be 0 before a SAFE verdict, so **any UNMET or UNVERIFIED acceptance
criterion blocks safe-to-merge** exactly as an uncovered high-risk row does.

Two hard rules carry over from the risk ledger:

- **Host-neutral, host-supplied.** The host supplies the criteria (the user
  pastes them, or they arrive in a context bundle). The skill NEVER fetches an
  issue, calls `gh`, or hits any tracker/API — the host identifies; the skill
  checks, cites, and renders. Same data-ownership split as every ledger row.
- **Graceful explicit fallback.** Most ad-hoc *"review my diff"* reviews carry no
  criteria. When none are supplied the skill says so in one line and falls back
  to the risk-coverage verdict — it never fabricates criteria and never silently
  skips the check.

The AC-coverage table is an **optional appendix**, appended below the risk
ledger when the user wants the structured artifact; the markdown-first prose
verdict (now naming any unmet/unverified criterion) is always the deliverable.

## Verification-evidence discipline (issue #332, consolidating #316/#321/#331)

The AC-coverage question above asks whether the change is the *right* change. A
third question is whether the change was actually *verified*: a green per-file /
codex review and green CI do NOT prove the changed behaviour was exercised.
`sumo-qa-reviewing-before-merge` carries one consolidated **verification-evidence
discipline** with four checks, each surfacing *missing relevant verification* as
a SAFE-blocker exactly like an uncovered risk — never demoted to a residual note,
and never cleared by weakening the verifier (only by running it correctly):

| Check | Missing-evidence verdict |
|---|---|
| **Surface-specific verifier ran** (#332) — the changed surface's relevant verifier (promptfoo eval, fixture/parser corpus, contract test, smoke probe, generated-artifact verification) ran with the right runtime/env/key/scope/tree. Eval-surface skill changes KEEP promptfoo as the REQUIRED verifier (Node 24 + the configured key). Sibling PRs co-editing one surface require COMBINED-TREE verification — per-branch-green is not combined-green. | UNVERIFIED (surface verifier) |
| **Primary feature flow exercised end-to-end** (#331) — the closest realistic UI/API/CLI/worker/artifact path was driven this turn, not merely a lower-level unit. Distinct from an UNMET AC; reuses the MET/UNVERIFIED boundary so a fresh path-matching test does not over-fire. | UNVERIFIED (feature flow) |
| **A newly-added regression guard's eval exercises BOTH directions** (#316) — a "do X but NOT Y" guard is only COVERED when its eval carries a discriminating true-negative / over-trigger seed a guard-violating reviewer would FAIL. | UNCOVERED guard |
| **An eval-driven skill change's A/B control is load-bearing** (#321) — A0 structurally cannot pass via pre-existing rules (a single A0-FAIL is variance, not isolation), and any input the rubric credits as "discriminating" must actually discriminate the seed defect. | UNPROVEN A/B control |

Any of these is a SAFE-blocker → NOT SAFE TO MERGE, mirroring the uncovered-risk
rule. All four are host-neutral. Checks (i) surface verifier and (ii) feature
flow carry a graceful one-line fallback for when the relevant verifier surface /
realistic path cannot be identified from the diff; checks (iii) guard coverage
and (iv) A/B control fire only conditionally — (iii) only when the change ADDS a
regression guard, (iv) only when an eval-driven skill change ships an A/B control
— so they simply do not apply (no fallback line needed) when those conditions are
absent.

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
