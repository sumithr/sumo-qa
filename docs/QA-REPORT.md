# Local QA report

The local QA report (issue #157) composes the persisted `.sumo-qa` artifacts
into one polished, self-contained static HTML page —
`.sumo-qa/qa-report.html` — that summarises repo health, change impact,
risk-to-test coverage, and evidence freshness at a glance. It is generated
**locally, with no network access and no hosted service**: the page renders
fully from disk via `file://`, with inline CSS only — no scripts, images,
external fonts, or stylesheets.

The report is a **projection, never a verdict**. No inference lives in it:
the artifacts (or the host LLM that built them) supplied every fact, and the
Python side only validates, composes, derives the readiness roll-up, and
renders. The markdown-first review verdict from the skills is unchanged — the
report is the durable, shareable snapshot of the same state.

## What it composes

| Source | Artifact | Produced by |
|---|---|---|
| Repo map | `.sumo-qa/repo-map.json` | `sumo-qa analyze` / `sumo_qa_scan_repo` (#155) |
| Diff impact | `.sumo-qa/diff-impact.json` | `sumo_qa_analyze_diff_impact` with `write_overlay=True` (#156) |
| Risk ledger | `.sumo-qa/risk-ledger.json` | opt-in conventional path (#144 is a chat formatter; persist the same rows there, or pass them inline to the MCP tool) |
| Context bundle | `.sumo-qa/context-bundle.json` | opt-in conventional path (#149 is a chat formatter; persist the same bundle there, or pass it inline) |
| Readiness scorecard | `.sumo-qa/readiness-scorecard.json` | pending — lands with #151; a present file renders `invalid` (no reader exists yet) |
| Coverage / mutation | — | pending — lands with #147; always an explicit not-available state |

**Every source is optional.** The report works with any subset of artifacts —
an empty repo still produces a valid page. That is the load-bearing honesty
contract: **missing data is never reported as passing evidence**. Each source
appears in the artifact inventory with one of four distinct states:

- `available` — present, validated, current
- `missing` — no producer ran; renders "not available"
- `invalid` — a file exists but cannot be used (malformed JSON, schema
  drift, bad vocabulary, or a repo-map describing a different repository);
  the row carries the loader's `[kind]`-prefixed detail
- `stale` — present but no longer reflecting the current state (repo-map
  recorded commit differs from `HEAD`; diff-impact persisted a stale warning
  or was derived from a now-stale repo-map; context bundle describes a
  different commit than the local head)

## Readiness roll-up

The one piece of deterministic logic the report owns. An ordered decision
table — **most severe state wins**:

| State | When |
|---|---|
| `blocked` | an uncovered blocker risk row, a failing risk row, or failing/mixed test/CI evidence |
| `stale_evidence` | a stale artifact, a stale risk row, stale evidence, or a passing result that is not trustworthy (unknown/absent freshness — only a fresh pass backs safety) — re-verify before trusting anything |
| `incomplete` | a core artifact (repo-map, risk ledger, context bundle) missing/invalid, a planned-but-not-executed risk row, an available ledger with zero rows, or test/CI evidence that never ran |
| `ready_with_residuals` | green, but accepted residuals or not-yet-mitigated residual decisions are on record |
| `ready` | everything green |

The ordering is load-bearing: a blocker plus stale evidence reads `blocked`,
and stale-but-present data reads `stale_evidence` rather than `incomplete`
(the re-verify signal outranks gather-more-data). Diff-impact absence never
forces `incomplete` (a clean tree has no diff), and the not-yet-buildable
scorecard / coverage sources (#151 / #147) never drag an otherwise-green repo
down. Every non-`ready` state carries explicit reasons on the page and in the
tool/CLI output.

## Generate it

From the terminal (issue #160 CLI):

```bash
sumo-qa report [path]          # writes .sumo-qa/qa-report.html under the repo
sumo-qa report [path] --json   # stable JSON summary for automation
```

`report` always succeeds on an existing directory (exit 0 means "report
written", never "everything is green") and overwrites the previous page — it
is a regenerated artifact, like the repo-map. The output names the readiness
state, per-artifact statuses, and the next command (`sumo-qa analyze` when
the repo-map is missing or stale, `sumo-qa status` otherwise).

From a host, via MCP:

```text
sumo_qa_generate_qa_report(root, write_to=None, risk_ledger_rows=None, context_bundle=None)
```

The response is a compact readiness summary (`GenerateQAReportOutput`) — the
HTML body never rides back to the host. Pass
`write_to=".sumo-qa/qa-report.html"` to persist the page; a relative path
resolves against the **target root**, not the MCP server's cwd, and is
confined to it — `..` traversal that escapes the root is refused. An absolute
path is caller-explicit and taken as-is. Without `write_to` the tool is
side-effect free.

`risk_ledger_rows` / `context_bundle` are **inline overrides** for the chat
flow: when the ledger or bundle was built in-conversation (via
`sumo_qa_format_risk_ledger` / `sumo_qa_format_context_bundle`) and never
persisted, pass the same shapes directly. They take precedence over any
on-disk file and are validated before anything is written.

## Determinism and snapshots

The builder is split into a pure core and an IO shell:
`load_report_inputs(root)` does all disk reads; `build_report(inputs, now,
generator_version)` is a pure projection. Fixed inputs + fixed clock + fixed
version produce a byte-identical page, which is what lets the renderer be
pinned by golden snapshots (`tests/fixtures/report/*.html` — the five
issue-mandated states: full-data ready, ready-with-residuals, stale-evidence,
blocked, partial-data). On a deliberate renderer change, regenerate via
`uv run python scripts/regen_report_snapshots.py` and inspect the diff in the
same PR — the snapshot exists to make drift visible.

## Bounded, escaped output

Artifact content is host-LLM- and repo-supplied text — attacker-ish input to
the page — so **every dynamic string is HTML-escaped**. Tables and lists
truncate past a hard cap with an explicit "+ N more not shown" notice, so a
giant diff cannot produce an unbounded page. The report schema itself is
versioned (`schema_version: "1.0"`, required-not-defaulted, the
ledger/repo-map pattern).
