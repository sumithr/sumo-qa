# Host-neutral issue/PR context bundle

Modern review assistants improve their output by ingesting issue, PR, diff, and
CI context before making findings. sumo-qa's skills already tell the host to
inspect repo context, but the context bundle (issue #149) makes that an explicit,
**host-neutral input contract**: a compact record of the issue summary, PR
summary, changed files, test/CI evidence, and user constraints that review and
planning can read consistently.

The bundle is an **optional accelerator, never a requirement**. When no bundle is
present — or only a partial one is — the consuming skill falls back to direct
repo inspection exactly as before. There is **no mandatory GitHub dependency, no
authenticated network call, and no host-specific connector requirement**: every
field can be filled from manually supplied text, local git state, or an optional
host integration.

## What gathers the facts

The **host** gathers the facts; the Python side is pure plumbing.
`sumo_qa_format_context_bundle` only validates the supplied bundle, renders a
host-neutral markdown brief, and reports its freshness/conflict signals. **No
Python code inspects a repo, runs a command, or makes a network call** — it never
infers a fact, it only formats the ones it is handed.

## Schema

Every field is optional except `schema_version`, so an absent or partial bundle
loads cleanly:

| Field | Meaning |
|---|---|
| `schema_version` | `"1.0"` — required so a versioned artifact can't sneak past validation unstamped. |
| `issue_summary` *(optional)* | Plain-text summary of the issue/ticket. |
| `pr_summary` *(optional)* | Plain-text summary of the PR/change. |
| `head_sha` *(optional)* | The commit the bundle describes; compared against the host's live local head to detect a conflict. |
| `changed_files` *(optional)* | List of `{path, change_kind}` (`change_kind` ∈ added / modified / removed / renamed). |
| `test_evidence` *(optional)* | A go-stale evidence fact (see below). `None` ⇒ no test evidence supplied. |
| `ci_status` *(optional)* | A go-stale evidence fact (see below). `None` ⇒ no CI evidence supplied. |
| `user_constraints` *(optional)* | Constraints the review must honour (e.g. "no schema changes"). |
| `repo_map_ref` / `diff_impact_ref` *(optional)* | Path/hash links to local `.sumo-qa/` artifacts ([REPO-MAP.md](REPO-MAP.md)). Gated on #155/#156; absence is fine. |

### Evidence facts carry source + freshness

CI status and test evidence can go stale, so each carries its own metadata:

| Field | Meaning |
|---|---|
| `result` | `passing`, `failing`, `mixed`, or `not_run`. |
| `freshness` | `fresh`, `stale`, `unknown`, or `absent` (see below). |
| `source` | `manual`, `local_git`, `github`, `ci_provider`, or `other` — host-neutral, not a GitHub-only enum. |
| `captured_at` *(optional)* | When the evidence was captured. Absence never implies fresh — freshness is carried by `freshness`, never inferred from a missing timestamp. |
| `captured_against_sha` *(optional)* | The commit the evidence was captured against. |
| `detail` *(optional)* | Free-text detail (e.g. "3 failed, 211 passed"). |

### Freshness vocabulary

The four freshness states are deliberately distinct:

- `fresh` — captured against the bundle's current commit; trustworthy now.
- `stale` — captured against an older commit (or otherwise known to predate the
  current state). A consumer must treat it as stale and **must not claim safety
  from it**.
- `unknown` — no freshness signal supplied; the consumer cannot assume fresh, so
  it is treated as not-trustworthy-for-a-safety-claim, like `stale`.
- `absent` — the evidence itself was not collected (no run). Distinct from "ran
  but stale".

**Only a fresh `passing` fact is safety-supporting.** Any non-fresh freshness, or
any non-passing result, is rendered with an explicit "do not claim safety from
it" warning. This is the load-bearing guard: a stale pass can never be silently
read as current.

## Conflict with local state

A bundle is point-in-time. When the host can inspect a newer local commit, the
bundle's `head_sha` may differ from the live local head. `local_head_sha`
(supplied by the host) drives a conflict check: when the two differ, the brief
emits an explicit **conflict** block so the skill calls out the divergence and
trusts the live diff it can inspect — it does **not** let the bundle override
newer local state, and it does **not** silently trust the bundle either. When
either sha is absent there is no signal to compare, so no conflict is reported.

## How the skills use it

`sumo-qa-reviewing-before-merge` and `sumo-qa-preparing-for-work` **prefer the
bundle when present** as a head-start for scope, constraints, and what to inspect,
and **fall back to direct repo inspection when absent**. The bundle never
replaces the diff read, and its CI/test facts are an *input*, never the review's
fresh-evidence verdict source — the Iron Law's requirement that only this turn's
fresh run backs a safe-to-merge verdict is unchanged.
