---
name: sumo-qa-closing-qa-gaps
description: Use when a review, mutation run, or graded scenario has already named a concrete uncovered behavior gap and the user wants it closed with evidence — e.g. 'close this gap', 'drive this uncovered risk to a regression test', 'fix this surviving mutant end to end'. Drives ONE closed loop per gap — failing test → red evidence → minimal fix → green evidence → risk/ledger update. Pauses when repo context or evidence is insufficient.
---

# Closing QA gaps

QA evidence — a review's uncovered risk, an unmet acceptance criterion, a mutation survivor, a graded-scenario failure — has named a concrete behaviour with no covering test. This skill drives it to closure one loop at a time (failing test → red evidence → minimum change → green evidence → status update), orchestrating the existing disciplines — never replacing them, never an autonomous fixer.

**Announce at the start of EVERY turn while this skill is active** — entry, red, green, status-update, refusal, and decline turns all open with: *"Closing one QA gap at a time."* A turn that skips the announce has left the loop discipline.

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: output discipline (no internal taxonomy labels), output economy (findings not framing; one question per turn; no closing pleasantries), knowledge authority hierarchy, internal scaffolding stays internal, specialty-tool fit.

<HARD-GATE>
Do NOT start a loop you cannot evidence. Three inspectable prerequisites: (a) ONE concretely named behaviour gap from real QA evidence (review verdict, mutation report, graded-scenario failure, or a defect the user described) — a service or module name is not a gap; the gap is a specific behaviour with no covering test; (b) readable production AND test files; (c) a known way to run the relevant tests — locally, or, when no local run is possible, the user's explicit go-ahead on the step-4 no-local-run fallback. If ANY is missing, STOP: check (a)–(c) one by one, name EVERY absent prerequisite, ask for them, and do nothing else. Never substitute assumption for inspection — no invented paths or contents, no fabricated test output, no generic test plan in place of the pause.
</HARD-GATE>

## The Iron Law

**ONE GAP PER LOOP, EVIDENCE AT BOTH ENDS.** The red (failing) output is captured before any production change; the green output plus targeted regression is captured before the gap's status moves. A second gap starts only when the user explicitly asks. And this skill NEVER declares a change safe to merge — that verdict belongs to `sumo-qa-reviewing-before-merge`, against fresh evidence, after the loop closes.

## When to Use

`sumo-qa-deciding-approach` routes here for `closed-loop-gap-fix`: *"close this gap"*, *"drive this uncovered risk to a regression test"*, *"take this survivor through the loop"*.

NOT for: feature work with no named gap (`tdd-scaffold` / `regression-first` directly); a batch or module-wide rewrite (no single named gap); the merge verdict itself (`sumo-qa-reviewing-before-merge`).

## Checklist

You MUST work through these in order, tracked as an ordered work list. Steps 4–7 are one loop; the loop body repeats only via step 8's explicit-ask gate.

1. **Name the ONE gap and its source** — restate the gap as a single concrete behaviour (file/function + the uncovered behaviour) and where it came from (review risk or AC row, mutation survivor, graded-scenario failure, user-described defect). If the evidence names several gaps, pick exactly one — the user's stated priority, else the first — and park the rest BY ID, out loud, in a sentence of this shape: *"R2 and R3 are parked as later loops — I'll start the next one only when you ask."* Choosing one gap without naming the parked ones is batching ambiguity. Never batch.

2. **Inspect the loop's prerequisites** — open the production file and the matching test file with the host's file tools; confirm the command that runs the relevant tests. Any prerequisite not inspectable → the HARD-GATE fires: stop and ask, this turn.

3. **Route the entry by its kind** —
   - **Mutation survivor** → `sumo-qa-strengthening-tests` discipline FIRST: production code stays UNCHANGED while the test is strengthened to kill the survivor (that skill's Iron Law binds here, unweakened). The strengthening proposal carries the SAME obligations as step 4, anchored at both ends: name the survivor by its production location and mutation (e.g. `pricing/discounts.py:42` — `subtotal > 10000` mutated to `>=`), cite the technique by its verbatim loaded-catalogue heading (e.g. "boundary value analysis"), AND name the target test file and test (e.g. `tests/pricing/test_discounts.py::test_no_discount_at_exact_threshold`). Only if the strengthened test then exposes a genuine production defect does this loop continue into a fix — surfaced as a separate, explicit decision, never silently.
   - **Review risk / AC row / graded-scenario failure / described defect** → `sumo-qa-implementing-with-tdd` discipline (`regression-first`): its red-first Iron Law, stub allowance, and confirmation gates apply unchanged.

4. **Red — capture the failing evidence before anything changes** — write (or request) the focused failing test for THIS gap only, citing the test-design technique by its verbatim loaded-catalogue heading (load the techniques catalogue first if it isn't already loaded). Never name a test file or function the supplied context has not shown — a test path the context can't ground is fabrication; ask for the files instead. Run it; capture the real assertion failure verbatim. Import/syntax/fixture errors are not red. When the test cannot be run locally (missing runtime, remote-only suite), say so explicitly, record what evidence IS available, and get the user's go-ahead before any change — never claim a red you didn't see.

5. **Green — minimum change, re-run, capture** — the smallest production change that closes THIS gap (or the user makes it, per the TDD skill's handoff). Re-run the test; capture the green output verbatim. A pass for the wrong reason (weakened assertion) is not green.

6. **Targeted regression** — run the changed module's tests plus closest siblings; capture pass/fail counts. Any green-to-red elsewhere reopens the loop: surface it and do NOT move the gap's status.

7. **Update the gap's status — only now, only on evidence** — the gap's recorded status moves because evidence changed (red→green captured this loop), never because prose changed. If a risk-to-test ledger is in play, update that row in the SAME ledger format — `evidence_status` from `failing`/`planned` to `passing` — and QUOTE both evidence lines verbatim from the run output the turn supplied, immediately before or after the ledger: (1) the gap's own green line (e.g. `tests/billing/test_refund.py::test_refund_over_balance_rejected PASSED`) and (2) the targeted-regression count (e.g. `41 passed`). A ledger row flipped to `passing` without BOTH quoted lines is wording-only progress, not coverage. When the row flips to `passing`, also resolve its `residual` — a closed blocker becomes `mitigated`, never left as `blocker` on a passing row. Touch only the row whose evidence changed. Do not invent a competing status format. If the same turn carries a merge question, step 8's pinned merge-decline applies IN THIS TURN — answer it here, don't defer it.

8. **Close the loop, offer — don't start — the next** — report the evidence pair (red, green) plus regression counts, name the remaining parked gaps, and offer the next one in CONDITIONAL form only: *"R2 is next if you want it — say the word and I'll start that loop."* Never "for the next loop, R2…" or any phrasing that reads as the loop already opening. Continue only when the user explicitly asks. If the user asks whether it's safe to merge, answer EXPLICITLY with this pinned line — *"I can't call this safe to merge — that verdict belongs to `sumo-qa-reviewing-before-merge`, against fresh evidence; route there next."* — omitting the merge question is not declining it. If the user asks for a module-wide tidy/rewrite instead of a named gap, decline it OUT LOUD in this exact shape (substituting the recorded gap ids, risks, and planned tests): *"The loop that just closed covered R1 only. Declining the module-wide change — no single named gap, no red evidence to anchor it. Parked: R2 — multi-currency rounding unpinned (planned: rounding boundary test); R3 — close with pending refund (planned: pending-refund guard test). Pick one and I'll run it as its own loop."* Then STOP — a broad ask is not an explicit ask for the next gap, so do not open any loop on that turn.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags — STOP and rework

| Thought | Reality |
|---|---|
| "I'll close all three gaps in one pass — it's faster" | One gap per loop — the user's correction on loop 1 changes loop 2. Park the rest, visibly. |
| "The fix is obvious — skip straight to it" | A test that has never failed has never tested anything. Red first, captured verbatim. |
| "This survivor is easiest to kill by tweaking the production code" | Production stays locked until the test is strengthened; a defect found after that is a NEW, surfaced decision. |
| "Green — so it's safe to merge" | Never from this skill. The merge verdict belongs to `sumo-qa-reviewing-before-merge` against fresh evidence. |
| "The strengthening test is written — mark the ledger row covered" | Written is not run. `evidence_status` moves on captured output only — quote the green line AND the regression count. |
| "I can't read the repo, but payment services all look alike" | HARD-GATE: pause and ask. Invented paths close loops on fiction. |
| "While I'm in here, I'll tidy the whole module" | Scope is the named gap. A broader rewrite needs an explicit, separate ask after this loop is green. |
| "User said 'keep going', so I'll fix R2 and R3 together" | Explicit ask buys the NEXT loop, not a batch. |

## Examples

### Good (review gap, one loop, red first)

> Review names three uncovered risks; user: *"close them."*
>
> **AI:** *"Closing one QA gap at a time. Starting with R1 — `apply_refund` accepts an over-balance amount (R2, R3 parked as later loops). Test idea: `tests/billing/test_refund.py::test_refund_over_balance_rejected`, refund of 150.00 against a 100.00 remaining balance, expecting `RefundError` — boundary value analysis on the remaining-balance edge. **Is `RefundError` the agreed contract for over-balance, or should it clamp to the remaining balance?**"*
>
> On confirm (per the TDD discipline's idea→confirm→write gate): writes the test, runs it, surfaces the `FAILED … RefundError not raised` output BEFORE any production change, hands off for the green change.

### Good (mutation survivor, production locked)

> mutmut survivor: `subtotal > 10000` → `subtotal >= 10000`, no test fails. User: *"take it through the loop."*
>
> **AI:** *"Closing one QA gap at a time. Production stays unchanged — strengthening the test first. The survivor lives at `pricing/discounts.py:42` (`subtotal > 10000` mutated to `>=`). Boundary value analysis at `subtotal = 10000`: the original must NOT qualify (`>` is strict), so the strengthening test `tests/pricing/test_discounts.py::test_no_discount_at_exact_threshold` asserts `qualifies(10000) is False` — the mutant (`>=`) fails it, the original passes. If the strengthened test instead exposes a real defect in `qualifies`, I'll surface that as a separate fix decision."*

### Bad (batch + premature claim)

> **AI:** *"I've added tests for all three risks, patched `refund.py` and `invoice.py`, everything's green — safe to merge."*
>
> Three violations: batched gaps, production changed before any captured red, and a merge verdict this skill must never issue.

## Next skill in the chain

Loop closed → offer the next parked gap, or route to `sumo-qa-reviewing-before-merge` for the safe-to-merge verdict against fresh evidence. Inside a rollout dispatched by `sumo-qa-executing-qa-rollout` → `sumo-qa-finishing-qa-work` for evidence capture + the PR-ready summary.
