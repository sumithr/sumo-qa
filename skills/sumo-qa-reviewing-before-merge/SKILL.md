---
name: sumo-qa-reviewing-before-merge
description: Use when the user asks "review my changes" / "is this safe to merge" / "what could break". Reads the diff and the changed files first, surfaces what was found + named risks, runs tests, then delivers the verdict — section by section with confirmation gates, not as one dump. Refuses to claim safe-to-merge without fresh verification evidence.
---

# Reviewing before merge

Help the user decide whether a change is safe to ship by walking the review one section at a time: explore the diff, surface what was found, name the risks, run the verification, deliver the verdict. The user has product context (was this a deliberate behaviour change? is this consumer used externally?) the AI can't infer from the diff alone — surface it through questions, don't assume it.

**Announce at start:** *"Reviewing the diff against fresh test evidence."*

## Output discipline (mandatory)

**Never surface internal taxonomy labels in user-facing output.** No "Classification: X", "Approach: Y", "Per the checklist", "Step 3 of 6". The taxonomy is internal scaffolding; translate to natural English when the meaning matters to the user — *"this is a behaviour change in pricing"*, not *"Classification: business_logic_change"*. If you catch yourself typing a label, delete it.

Inherits the global discipline from `using-sumo-qa` (knowledge authority hierarchy, internal scaffolding stays internal, specialty-tool fit).

## Output economy (mandatory)

Spend output tokens on findings, not framing.

- **Don't preamble the work.** Spend user-visible output on findings, evidence, and gates — don't narrate *"I'll first read X, then Y, then deliver Z."*
- **One question per turn.** Don't follow a question with *"shall I proceed or clarify first?"* — the question IS the gate.
- **No self-narration.** *"Let me now..."* / *"I'm going to..."* → just do it.
- **Don't restate the user's input.** They know what they asked.
- **Section headings only when there are genuinely multiple sections.** A 3-line scope check doesn't need a `## Scope` heading.
- **Tables only when comparing >2 things on >2 axes.** Otherwise prose is shorter.
- **No closing pleasantries.** No *"happy to dig deeper"* / *"let me know if you want X"* — the next-skill handoff at the bottom of every skill is where routing lives.

<HARD-GATE>
Do NOT deliver a verdict before running tests in this turn. "CI was green earlier" is not fresh evidence. The Iron Law's only verdict source is the suite running RIGHT NOW against THIS diff, with the actual pass/fail counts surfaced.
</HARD-GATE>

## The Iron Law

**NEVER CLAIM SAFE-TO-MERGE WITHOUT FRESH VERIFICATION EVIDENCE.** "All tests pass" is necessary but not sufficient — every named risk must also have a passing test covering it.

## When to Use

User intents that trigger this skill:

- "review my changes"
- "is this safe to merge"
- "what could break with these changes"
- "code review please"
- "anything I missed in this diff"

`sumo-qa-deciding-approach` routes here for `verify-existing` approach (config-only / trivial). For larger reviews, this skill still runs but with broader scope.

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

9. **Map risk coverage** — for each named risk: cite the test that demonstrably exercises that risk (file + test name plus the assertion, condition, or path evidenced by the output) or flag it as uncovered. Do not infer coverage from shared vocabulary or a nearby test name; if the available evidence does not prove the risk path, such as retry behaviour, mark it unproven. A risk with no covering test is a SAFE-blocker.

   **Worked contrast — same-domain test is NOT proof of risk path.** Given risk *"Duplicate Charge on Retry"* and a passing test `tests/billing/test_checkout.py::test_does_not_mark_failed_charge_paid`:
   - BAD mapping: *"Duplicate Charge on Retry — Covered by `test_does_not_mark_failed_charge_paid`."* The test asserts the invoice is not marked paid on a single failed charge; it never re-invokes `complete_checkout` after a partial failure, so it cannot prove idempotency on retry.
   - GOOD mapping: *"Duplicate Charge on Retry — UNCOVERED. No fresh test re-invokes `complete_checkout` after a partial failure or asserts the gateway is charged at most once across retries. Treat as a SAFE-blocker."*

   **Worked contrast — cross-module risk needs a test that touches that module.** Given risk *"Auth Session Bypass"* on `app/auth/session.py` and a fresh run that only loads `tests/billing/test_checkout.py`:
   - BAD mapping: *"Auth Session Bypass — Covered by green billing suite."* Green billing tests never call `can_access_billing`; they prove nothing about the auth path.
   - GOOD mapping: *"Auth Session Bypass — UNCOVERED. The fresh run did not execute any test in `tests/auth/`; the changed predicate in `app/auth/session.py:33` has zero fresh evidence. SAFE-blocker."*

   If the fresh test run does not load tests for a changed file's module, every risk anchored to that file is UNCOVERED — full stop, regardless of how green the rest of the suite is.

   **Re-anchor named risks to the diff first.** When the user hands you a list of risk *names* (e.g. *"Auth Session Bypass, Billing Paid-State Drift, Duplicate Charge on Retry"*) without anchors, locate each risk's anchor file in the diff BEFORE attempting coverage mapping. *Auth Session Bypass* → scan the diff for `auth/*` changes — here `app/auth/session.py:33`. *Billing Paid-State Drift* → `app/billing/checkout.py`. *Duplicate Charge on Retry* → also `app/billing/checkout.py`. Without an anchor, you cannot apply the module-match rule and will hallucinate coverage.

   **Module-match rule (pinned, deterministic):** once each risk has its anchor file, check the filesystem path of any candidate covering test. A risk anchored to a file under `app/auth/` requires a covering test under `tests/auth/`; a risk anchored to `app/billing/` requires a test under `tests/billing/`. Tests in `tests/billing/test_checkout.py` cannot cover an `auth/session.py` risk via *"indirectly validating"*, *"implicitly covers"*, or *"the test session must be valid"* — these are hallucinated bridges and forbidden. Mark the risk UNCOVERED when paths don't match. **Integration/e2e exception:** tests under `tests/integration/`, `tests/e2e/`, or equivalent cross-module test trees MAY cover any module risk, but ONLY if the cited assertion verbatim invokes (or asserts a property of) the risk's anchor function or its public-API entry point. Generic "the integration suite passed" without naming the specific assertion that exercises the risk is the same hallucinated bridge in a different guise.

### Verdict-format discipline

When delivering the verdict, include evidence in this order: quote the verification command verbatim (for example, `Run: pytest tests/auth/permissions_test.py`); cite result counts exactly as `18 passed, 0 skipped, 0 failed`; for each named risk, name the covering test by function name or file path, never generic "tests cover this"; cite exact touched file paths from the diff (for example, `auth/permissions.py`, `docs/README.md`); only then emit `SAFE TO MERGE` or `NOT SAFE TO MERGE` (or existing `NEEDS WORK` when step 10 applies).

**Trivial-change exemption (pinned):** if the diff touches only docs (`docs/`, markdown, README), config (YAML/TOML/JSON outside runtime source), or other non-runtime files — and no `app/` / `src/` / `lib/` / runtime-source file is in the touched list — SKIP the coverage ledger. Emit a streamlined response: name the prior risk(s), quote the verification command + counts, emit `Touched files:` and `Change shape:` lines (calling out *"no runtime behaviour change"*), then the verdict. Applying the full gated review walk to a trivial docs/config-only change is an anti-pattern. The full ledger format below applies ONLY when at least one runtime-source file is in the diff.

The verdict line is the LAST line of the response. For runtime changes, before emitting the verdict, the candidate MUST have already, in this order:
1. Listed each named risk by exact name, one per line (for example, `Risk 1: Auth Session Bypass`).
2. For each risk, emitted a coverage ledger line in this exact shape:
   `Risk: <exact name> | Anchor: <diff file:line> | Required test path: <tests/<module>/ for runtime app/<module>/ anchors> | Fresh matching tests: <only fresh tests whose path starts with the required runtime test path, given as fully-qualified pytest IDs `<file_path>::<test_function_name>` from the fresh test output (NOT just the file path); or NONE> | Coverage: <covered test (fully-qualified pytest ID) + verbatim assertion/condition/path, UNPROVEN, or UNCOVERED>`

   **`COVERED BY VERIFICATION` is reserved for docs/config-only anchors processed under the Trivial-change exemption above — runtime risks anchored to `app/`, `src/`, or `lib/` source files MUST NOT use `COVERED BY VERIFICATION` under any circumstances. Their Coverage column is one of: COVERED (with cited test + assertion), UNPROVEN (path matched but no assertion exercises the risk path), or UNCOVERED (no path match).**
   For runtime anchors, derive "Fresh matching tests" from file paths only; path prefix is necessary but not sufficient. Coverage is COVERED only when a fresh matching test also quotes a verbatim assertion/condition from the supplied test body that directly exercises the risk's failure mode. For risks whose exact name, anchor description, or failure mode contains Retry, Duplicate, or Idempotency, the cited assertion/condition MUST demonstrate the subject operation being invoked MORE THAN ONCE — two calls, a loop, a call-count assertion across attempts, or an idempotency-token assertion across repeated calls. For risks containing Concurrent, Race, or Lock, the cited assertion/condition MUST demonstrate overlapping/interleaved execution — threading primitives (`threading.Thread`, `asyncio.gather`, `concurrent.futures`), an explicit interleave (lock-acquire-during-write), or a property assertion across overlapping calls; sequential repeated invocations alone do NOT prove race safety. A single non-overlapping invocation, even one that raises an exception, exercises none of these risk categories; mark Coverage UNPROVEN when the required evidence shape is absent.

   **Worked example — multi-invocation rule on retry risk.** Given Risk *"Duplicate Charge on Retry"* anchored to `app/billing/checkout.py` and the only fresh matching test body containing `with pytest.raises(GatewayError): complete_checkout(open_invoice(), gateway_failure())`:
   - BAD ledger: `Coverage: COVERED by assertion \`with pytest.raises(GatewayError): complete_checkout(open_invoice(), gateway_failure())\`.` This is a SINGLE invocation — there is one `complete_checkout(...)` call, no second call, no loop, no call-count assertion. The risk contains "Duplicate" AND "Retry" — both are multi-invocation triggers. A single-call assertion CANNOT exercise this risk.
   - GOOD ledger: `Coverage: UNPROVEN. The only matching test invokes complete_checkout once; no fresh test invokes complete_checkout twice or asserts a charge-count across attempts, so retry idempotency is not exercised.`
   The verdict in this scenario MUST be NOT SAFE TO MERGE with a rationale that explicitly names "retry safety unproven" alongside any UNCOVERED runtime risks. If no such assertion/condition exists anywhere in the supplied fresh matching test bodies, Coverage MUST be UNPROVEN and the verdict MUST be NOT SAFE TO MERGE. If "Fresh matching tests" is NONE, Coverage MUST be UNCOVERED, and non-matching tests must not be cited as indirect evidence. For docs/config-only anchors, when the changed anchor is non-runtime (`docs/`, markdown, config files, or YAML outside runtime source) and the verification command includes a linter, formatter, or build step covering that file type, mark Coverage as COVERED BY VERIFICATION, not UNCOVERED.
3. Emitted a `Touched files:` line citing every file path from the diff verbatim (for example, `Touched files: app/auth/session.py, app/billing/checkout.py, tests/billing/test_checkout.py` — or for a docs-only diff, `Touched files: docs/README.md`).
4. Emitted a `Change shape:` line characterising the change in one phrase, anchored to the touched files (for example, `Change shape: docs-only typo fix in docs/README.md, no runtime behaviour change`, or `Change shape: auth predicate + billing checkout ordering, both runtime`).
5. Quoted the verification command verbatim.
6. Cited the test counts verbatim (`X passed, Y skipped, Z failed`).

For runtime changes, any verdict emitted before all six items above are present is a discipline violation. For trivial docs/config-only changes (see the exemption above), only items 1, 3, 4, 5, 6 are required — item 2 (the coverage ledger) is skipped because the verification command IS the coverage. The `Touched files:` and `Change shape:` lines are mandatory in both modes — they are how the verdict cites the diff. Citing the verification command's file argument does NOT discharge the `Touched files:` line; the verification target and the diff target are different evidence channels.
Do NOT emit SAFE TO MERGE before all named risks have been listed and each tied to a covering test (or explicitly marked UNCOVERED).

10. **Deliver the verdict + residual concerns** — SAFE TO MERGE | NOT SAFE TO MERGE | NEEDS WORK with concrete evidence (test counts, risk coverage map, rule citations). SAFE only if: (a) suite green right now, (b) every named risk has ≥1 passing covering test that demonstrably exercises that exact risk path (NOT a tangentially-named test), (c) no loaded rule violated. **If ANY named risk is uncovered or unproven, the verdict MUST be NOT SAFE TO MERGE — no exceptions, even if the suite is fully green.** A test named for module X cannot be cited as coverage for risk Y unless its assertion/condition demonstrably exercises Y's failure mode. Always list residual concerns even on SAFE.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags — STOP and rework

| Thought | Reality |
|---|---|
| "Looks good to me, ship it" | Not evidence. Run the tests. |
| "CI was green an hour ago" | Not fresh. Run them now. |
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
