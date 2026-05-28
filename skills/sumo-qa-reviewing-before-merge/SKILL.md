---
name: sumo-qa-reviewing-before-merge
description: Use when the user asks "review my changes" / "is this safe to merge" / "what could break". Reads the diff and the changed files first, surfaces what was found + named risks, runs tests, then delivers the verdict — section by section with confirmation gates, not as one dump. Refuses to claim safe-to-merge without fresh verification evidence.
---

# Reviewing before merge

Help the user decide whether a change is safe to ship by walking the review one section at a time: explore the diff, surface what was found, name the risks, run the verification, deliver the verdict. The user has product context (was this a deliberate behaviour change? is this consumer used externally?) the AI can't infer from the diff alone — surface it through questions, don't assume it.

**Announce at start:** *"Reviewing the diff against fresh test evidence."*

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: **output discipline** (never surface internal taxonomy labels — say *"behaviour change in pricing"*, not *"Classification: business_logic_change"*), **output economy** (spend output on findings not framing; no preamble or self-narration; one question per turn; no closing pleasantries), knowledge authority hierarchy, internal scaffolding stays internal, and specialty-tool fit.

<HARD-GATE>
Do NOT deliver a verdict before running tests in this turn. "CI was green earlier" is not fresh evidence. The Iron Law's only verdict source is the suite running RIGHT NOW against THIS diff, with the actual pass/fail counts surfaced.
</HARD-GATE>

## The Iron Law

**NEVER CLAIM SAFE-TO-MERGE WITHOUT FRESH VERIFICATION EVIDENCE.** "All tests pass" is necessary but not sufficient — every named risk must also have a passing test covering it.

## When to Use

Triggers: *"review my changes"*, *"is this safe to merge"*, *"what could break"*, *"code review please"*, *"anything I missed in this diff"*, and similar.

`sumo-qa-deciding-approach` routes here for `verify-existing` (config-only / trivial); larger reviews run here too with broader scope.

## Checklist

You MUST work through these in order. Steps 1–4 are AI-only homework (no user questions). The user's confirmation gates steps 5 onward.

1. **Read the diff via the host's git tools** *(no user question)* — `git diff`, `git diff --staged`, or `git diff <base>...HEAD` depending on intent. Capture file list + line counts.

2. **Read the actual changed files** *(no user question)* — not just the diff hunks. Surrounding code matters for risk analysis. For each changed file: identify the public surface that moved.

3. **Classify and load applicable standards** *(no user question)* — call `sumo_qa_load_classifications()`, infer the classification(s), then `sumo_qa_load_standards(...)` and `sumo_qa_load_rules(...)`. Note which loaded rules apply.

4. **Identify named risks anchored to file:line** *(no user question)* — 3–7 risks, each citing a specific file + line + the domain meaning. NOT generic ("edge cases", "untested paths"). Use the words from the user's intent + the actual code.

5. **Confirm scope, only for the AMBIGUOUS parts** — present a short paragraph naming the files, line counts, and what the change does in domain terms. Then ask ONE focused question for what the diff couldn't reveal (e.g. *"is this consumer external — do we need to coordinate the contract bump?"*). If nothing's ambiguous, skip the question.

6. **Present named risks, ask after** — present the 3–7 risks anchored to file:line:
   *"R1: `api/refund.py:47` — new error path returns 500 instead of 422 for invalid-amount; consumer X depends on 4xx-vs-5xx for retry logic.*
   *R2: `domain/Refund.kt:18` — idempotency key derivation changed; double-refund possible on retry of a partially-completed call. …"*
   Ask: *"do these match how you'd describe the risks? add / remove / refine?"* Wait for the user.

7. **Run the test suite — show the actual output** — use the host's runner. Surface: total / passed / failed / skipped / duration. If failures: name them. Do NOT proceed to verdict on partial output.

8. **Run targeted tests around the changed files** — e.g. `pytest tests/test_<changed_module>.py -v`. Confirm closest neighbours stay green. Surface the count.

9. **Map risk coverage** — for each named risk, cite the fresh test that demonstrably exercises that exact failure path (file + fully-qualified test + the verbatim assertion/condition), or mark it UNPROVEN / UNCOVERED. Never infer coverage from a shared name or domain. A risk with no covering test is a SAFE-blocker.

   **Re-anchor first.** If risks arrive as bare names (*"Auth Session Bypass, Duplicate Charge on Retry"*), locate each one's anchor file in the diff before mapping — *Auth Session Bypass* → `app/auth/session.py:33`, *Duplicate Charge on Retry* → `app/billing/checkout.py`. Without an anchor you cannot apply the module-match rule and will hallucinate coverage.

   **Module-match rule (pinned):** a risk anchored under `app/auth/` requires a covering test under `tests/auth/`; `app/billing/` requires `tests/billing/`. A `tests/billing/` test cannot cover an `auth/session.py` risk via *"indirectly validates"* / *"implicitly covers"* — forbidden hallucinated bridges; mark UNCOVERED when paths don't match. If the fresh run loaded no test for a changed file's module, every risk anchored there is UNCOVERED, however green the rest is. **Integration/e2e exception:** tests under `tests/integration/` or `tests/e2e/` MAY cover any module risk, but only if the cited assertion verbatim invokes (or asserts a property of) the risk's anchor function; "the integration suite passed" without naming that assertion is the same hallucinated bridge.

   **Worked contrast (same-domain ≠ proof).** Risk *"Duplicate Charge on Retry"* + passing `tests/billing/test_checkout.py::test_does_not_mark_failed_charge_paid`:
   - BAD: *"Covered by `test_does_not_mark_failed_charge_paid`."* — it asserts one failed charge isn't marked paid; it never re-invokes `complete_checkout` after a partial failure, so it cannot prove retry idempotency.
   - GOOD: *"UNCOVERED. No fresh test re-invokes `complete_checkout` after a partial failure or asserts charge-at-most-once across retries. SAFE-blocker."*

   **Documented-inventory drift rule (pinned).** When the diff changes a documented count, inventory, public-surface name, or schema field — the `docs_change` rule's inventory-drift probe — the obvious doc the diff touches is rarely the only stale spot. Before the verdict, search the supplied ground-truth context (any `rg`/grep listing, "Other repo state" section, etc.) for the OLD value; each path it surfaces is a separate UNCOVERED anchor that needs its own ledger row (format in Verdict-format discipline item 2a). Generic guidance, anchoring only on the obvious doc, or naming one stale path is UNCOVERED. If the ground-truth context names zero stale paths, say so explicitly; do NOT silently default to "covered".

### Verdict-format discipline

The verdict line is the LAST line. For a **runtime change** (any `app/`/`src/`/`lib/` file in the diff), before the verdict you MUST emit, in order:
1. Each named risk by exact name, one per line (`Risk 1: Auth Session Bypass`).
2. A coverage-ledger line per risk in this exact shape:
   `Risk: <exact name> | Anchor: <diff file:line> | Required test path: <tests/<module>/ for app/<module>/ anchors> | Fresh matching tests: <fresh tests whose path starts with the required path, as fully-qualified `<file>::<test>` IDs, or NONE> | Coverage: <COVERED (cited test + verbatim assertion) | UNPROVEN | UNCOVERED>`
   - `COVERED` only when a fresh path-matching test quotes a verbatim assertion/condition that exercises the risk's failure mode — path prefix is necessary, not sufficient.
   - Risks whose name/anchor/failure-mode contains **Retry, Duplicate, or Idempotency** require an assertion showing the operation invoked MORE THAN ONCE (two calls, a loop, a call-count or idempotency-token assertion across attempts). **Concurrent, Race, or Lock** require overlapping execution (threading / `asyncio.gather` / `concurrent.futures`, or an explicit interleave). A single non-overlapping invocation — even one that raises — proves none of these; mark UNPROVEN.
   - `Fresh matching tests: NONE` → Coverage UNCOVERED; never cite non-matching tests as indirect evidence.
   - `COVERED BY VERIFICATION` is reserved for docs/config-only anchors (below); runtime anchors MUST NOT use it.
   - **2a. Inventory-drift extension.** For an inventory-drift risk (see step 9), the risk row above is not sufficient. Emit ONE additional ledger row per stale path the supplied ground-truth context names — never crammed into one row or shoved into the risk row's `Required update:` field. Each row uses this exact shape (the `<old> → <new>` value pair must appear inline):
     `Inventory drift anchor: <path>:<line> (<old> → <new>) | Required update: this file | Diff updated it: <YES if the diff touches this exact path; NO otherwise> | Coverage: <COVERED if the diff updates this exact file; UNCOVERED if it does not>`
     Each UNCOVERED row is a SAFE-blocker. The verdict line must name every UNCOVERED stale path explicitly — not "documentation needs updating". Zero stale paths supplied → emit `Inventory drift anchor: NONE supplied | Coverage: N/A` rather than silently defaulting to covered.
3. `Touched files:` citing every diff path verbatim (e.g. `app/auth/session.py, tests/billing/test_checkout.py`).
4. `Change shape:` one phrase anchored to the touched files (e.g. `auth predicate + billing checkout ordering, both runtime`).
5. The verification command, quoted verbatim.
6. The test counts verbatim (`X passed, Y skipped, Z failed`).

A runtime verdict emitted before all six are present is a discipline violation.

**Trivial-change exemption (pinned):** if the diff touches only docs (`docs/`, markdown), config (YAML/TOML/JSON outside runtime source), or other non-runtime files — no `app/`/`src/`/`lib/` file present — SKIP item 2; the verification command (linter/formatter/build) IS the coverage, so mark those anchors `COVERED BY VERIFICATION`. Items 1, 3, 4, 5, 6 still required. `Touched files:` and `Change shape:` are mandatory in both modes; citing the verification command's file argument does not discharge `Touched files:`.

10. **Deliver the verdict + residual concerns** — `SAFE TO MERGE` | `NOT SAFE TO MERGE` | `NEEDS WORK` with concrete evidence (counts, coverage map, rule citations). SAFE only if (a) suite green now, (b) every named risk has ≥1 fresh test demonstrably exercising that exact path (not a tangentially-named one), (c) no loaded rule violated. **If ANY named risk is UNCOVERED or UNPROVEN, the verdict MUST be NOT SAFE TO MERGE — no exceptions, even on a fully green suite.** Always list residual concerns, even on SAFE.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags — STOP and rework

| Thought | Reality |
|---|---|
| "Looks good to me" / "CI was green an hour ago" | Neither is fresh evidence. Run the suite now. |
| "Trivial change, no need to walk through sections" | The Iron Law doesn't have a trivial-change exemption. Walk through; the review can be short, but every section gets confirmation. |
| "I'll skip running tests — they're slow" | Then you can't claim safe-to-merge. Slow tests are still the verdict source. |
| "All tests pass, so SAFE" | Necessary, not sufficient. Each named risk must also have a covering test. |
| "No standards apply to this change" | Re-classify. Every change has at least one applicable classification with loaded rules. |
| "I'll list the risks AND deliver the verdict in one message" | Gate. The user's correction on the risks is what shapes the verdict. |
| "I'll ask the user which test framework / where tests live" | Read the repo. The framework and test layout are answered by sibling files. |
| "Residual concerns: none" | Every change has them. None = you didn't think about what could still go wrong. |

## Examples

### Good (explore first, confirm scope, then risks, then verdict)

> **User:** "review my changes, is this safe to merge?"
>
> **AI (scope):** *"3 files: `api/refund.py` (+38/-4), `domain/Refund.kt` (+12/-2), `tests/test_refund_api.py` (+25/-0). Response shape + amount calc moved; `tests/contracts/refund_v1.json` untouched. Consumer external or internal-only?"*
>
> *(risks → tests → coverage map → verdict, one section per turn)*

### Bad (single-shot verdict)

> **User:** "review my changes, is this safe to merge?"
>
> **AI:** *"Looks straightforward — 3 files, mostly internal refactor. Should be fine to merge. Maybe run CI."*
>
> No fresh test evidence. No risk anchoring. No standards check. Iron Law violated.

## Next skill in the chain

When the verdict is delivered (SAFE / NOT SAFE / NEEDS WORK) with fresh evidence + risk-coverage map → `sumo-qa-finishing-qa-work` to capture the evidence and produce the PR-ready summary the user can paste into a description or release note.
