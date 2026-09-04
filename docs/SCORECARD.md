# QA readiness scorecard

sumo-qa's review and planning workflows already produce a verdict, a risk-to-test
[ledger](RISK-LEDGER.md), and a [context bundle](CONTEXT-BUNDLE.md). The QA
readiness scorecard (issue #151) composes those artifacts into one compact,
release-or-PR-readiness summary: what is covered, what is stale, what remains
risky, and a single derived recommendation.

It is an **evidence summary, not a predictive quality score**. A composite
"quality 0-100" number blends incommensurable signals behind false precision; the
scorecard refuses to invent one. It emits only *counts of real evidence* (N risks,
M passing, K uncovered blockers) and *categorical states*, every one traceable to
a supplied ledger row or context fact. The recommendation is **derived from the
evidence, never asserted by the caller**, there is no "ready" input field, which
is what makes "refuse ready when risks are uncovered or evidence is stale" a
structural guarantee rather than advice.

## What the host supplies

The **host LLM** supplies the already-produced artifacts; the Python side is pure
plumbing that validates them, derives the states, and renders the output. **No
Python code performs risk inference**, `sumo_qa_format_qa_scorecard` composes and
formats only. It deliberately **reuses the ledger and context-bundle schemas**
([RISK-LEDGER.md](RISK-LEDGER.md), [CONTEXT-BUNDLE.md](CONTEXT-BUNDLE.md)) rather
than redefining them.

| Input | Source | Meaning |
|---|---|---|
| `ledger_rows` *(optional)* | #144 risk ledger | The named risks + their evidence. Supplies risk coverage and uncovered blockers. |
| `context_bundle` *(optional)* | #149 context bundle | Issue/PR/diff facts + test/CI evidence with freshness. Supplies evidence-freshness. |
| `coverage` *(optional)* | a coverage run | `{line_percent, freshness, detail}`. Reported, never gated on a threshold. |
| `mutation` *(optional)* | a mutation run | `{survivors, killed, freshness, detail}`. Reported, never gated. |
| `scope` *(optional)* | the host | A short label (a PR title, a release name). |
| `local_head_sha` *(optional)* | the host | The live local head. Flags a stale bundle when it differs from the bundle's `head_sha`. When the bundle names a `head_sha` and this is omitted, the bundle's fresh-passing facts are **unverifiable** and cannot support a ready verdict (see below). A bundle with no `head_sha` has nothing to verify and keeps the partial-bundle contract. |

Every input is optional, an empty payload derives `insufficient_evidence`. An
**absent** coverage/mutation signal is reported as `not measured`, **never assumed
passing**, so it can never outweigh an uncovered high-impact risk. A coverage/mutation
payload supplied with no actual measurement (an empty `{}`, or `freshness`/`detail`
metadata but no `line_percent` / `survivors` / `killed`) is treated as absent, it
too is reported as `not measured`, never as a measured dimension.

## The four recommendation states

Derived first-match-wins from the supplied evidence:

| Recommendation | Derived when |
|---|---|
| `blocked` | A hard stop exists: an uncovered high-impact risk (a ledger `is_uncovered_blocker` row), a failing covering test, or a present failing/mixed test or CI result. |
| `insufficient_evidence` | No blocker, but readiness cannot be *asserted*: required test evidence is absent / stale / unknown-freshness, a ledger risk is only `planned` (not run) or `stale`, the bundle is stale relative to the local tree, the bundle's fresh-passing test/CI facts could not be verified because the bundle names a `head_sha` and no local head was available (unverifiable is reported as its own reason, never as "stale"), or nothing was supplied at all. **"Tests are stale" lands here, never in a ready state.** |
| `ready_with_accepted_residuals` | Evidence is sufficient and nothing blocks, but at least one risk is a consciously accepted residual (an explicit accept decision, not a passing test). |
| `ready` | Evidence is fresh, passing, and complete; no blockers and no accepted residuals. |

`is_ready` is true only for the two ready states.

## Per-dimension status

Each dimension (risk coverage, test evidence, CI status, coverage, mutation,
residual risks) carries its own status so the table and the serialized snapshot
show *where* the evidence is thin:

| Status | Meaning |
|---|---|
| `ok` | Satisfied by fresh, passing evidence. |
| `gap` | A non-blocking shortfall (e.g. a planned-not-run risk). |
| `blocker` | A shortfall that blocks readiness (uncovered blocker, failing result). |
| `stale` | Evidence exists but is not trustworthy now (stale / unknown freshness). |
| `unverified` | A fresh-passing bundle fact whose bundle names a `head_sha` that could not be checked because the local head is unknown. Not known-stale, but never `ok`; the verdict is `insufficient_evidence`. |
| `not_measured` | The optional signal was not supplied, distinct from *passing*, and never assumed green. |

## Output shape

`sumo_qa_format_qa_scorecard(ledger_rows=None, context_bundle=None, coverage=None,
mutation=None, scope=None, local_head_sha=None, max_reasons=25)` returns
(`FormatQaScorecardOutput`):

- `recommendation`: the derived four-state verdict.
- `is_ready`: true only for `ready` / `ready_with_accepted_residuals`.
- `uncovered_blocker_count`, `open_residual_count`, `accepted_residual_count`.
- `stale_evidence`: dimensions present but not fresh-passing. An `unverified`
  dimension is not listed here (it is not known-stale); it is explained in
  `insufficiency_reasons` and shown in the dimension table.
- `not_measured`: dimensions whose optional signal was absent.
- `markdown`: the rendered scorecard (headline + dimension table + reason lists),
  bounded by `max_reasons` with a `… +N more` notice so a large scorecard stays
  inside the host token budget.
- `compact_summary`: a one-line roll-up to drop inline in short answers.
- `serialized`: a JSON-able snapshot of every fact above, for any downstream
  consumer that wants the rendered scorecard's facts. It is stamped
  `schema_version: "1.1"`: 1.1 added the `unverified` dimension status to the
  1.0 enum (`ok`, `gap`, `blocker`, `stale`, `not_measured`); the snapshot's
  keys are unchanged, so a consumer that validates the status enum reads the
  version to know which enum applies. (The #157 local QA report
  does not read this snapshot, it composes its own `QaScorecard` from the same
  ledger + bundle, making this module the single source of truth for the
  readiness verdict.)

A payload can also be validated directly through
`sumo_qa.scorecard_validation.load_scorecard`, which reuses the ledger and
context-bundle loaders verbatim (their errors propagate unchanged) and raises
`ScorecardValidationError` with a stable `kind` (`unknown_field`, `vocab_error`,
`value_error`, `type_error`) for the coverage/mutation signals.

## Good and bad scorecard states

**Blocked**, an uncovered high-impact risk; the scorecard refuses ready:

```
**QA readiness scorecard — PR 42: refund idempotency**

Recommendation: **BLOCKED** — 1 hard stop(s) must be resolved before this is ready.

| Dimension | Status | Evidence |
|---|---|---|
| Risk coverage | blocker | 2 risk(s) — 1 passing, 1 failing; 1 uncovered blocker(s) |
| Test evidence | ok | passing/fresh (local_git) |
| CI status | not measured | not supplied |
| Coverage | not measured | not measured |
| Mutation | not measured | not measured |
| Residual risks | ok | 0 accepted, 1 open |

Blockers (resolve before ready):
- R2: idempotency key derivation moved → double refund on retry — uncovered high-impact risk

This scorecard summarises the evidence supplied; it is not a predictive quality score. Absent coverage/mutation signals are reported as "not measured", never assumed passing.
```

**Insufficient evidence**, fresh unit suite green, but the only end-to-end
evidence is stale; readiness cannot be asserted:

```
Recommendation: **INSUFFICIENT EVIDENCE** — 1 evidence gap(s); readiness cannot be asserted yet.
…
| CI status | stale | passing/stale (ci_provider) |
```

**Ready**, every risk covered by fresh passing tests, no open blockers:

```
Recommendation: **READY** — evidence is fresh, passing, and complete; no uncovered blockers.
```

A scorecard that reads `ready` while the review verdict is `NOT SAFE TO MERGE`
means the ledger rows are mis-coded, fix the rows, never the scorecard.

## Which skills use the scorecard

The scorecard is an **optional** appendix in these workflows, each still leads
with its prose deliverable, and omits the scorecard from short/simple answers:

- **`sumo-qa-reviewing-before-merge`**: on a readiness request, projects the same
  named risks + context bundle below the verdict; the derived recommendation
  agrees with the SAFE gate by construction (a `NOT SAFE TO MERGE` verdict can
  only yield `blocked` or `insufficient_evidence`).
- **`sumo-qa-finishing-qa-work`**: a release/readiness verdict over the run's
  risk-to-test map; refuses ready while a `KNOWN GAP` or stale evidence remains.
- **`sumo-qa-creating-test-plan`**: at plan time every risk is `planned`, so the
  scorecard derives `insufficient_evidence`, an honest "not ready until the exit
  criteria are met" baseline, re-run with real evidence at ship time.

## When NOT to use it

- **Short / simple reviews.** The scorecard is offered on a readiness request, not
  forced into every answer, bloating a normal verdict with a table regresses the
  token-budget work.
- **As a quality score.** It summarises evidence; it never produces a predictive
  number. Do not read a `ready` state as "high quality", only as "the supplied
  evidence shows no uncovered blocker and nothing stale".
- **As a source of truth that can contradict the verdict.** The scorecard is a
  projection of the same risks + evidence. If it disagrees with the prose verdict,
  the prose verdict is authoritative and the scorecard inputs are wrong.
- **To let optional signals outweigh a risk.** High coverage or zero mutation
  survivors never upgrade a `blocked` recommendation, an uncovered high-impact
  risk blocks regardless.
