---
name: qa-reviewing-before-merge
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

- **Don't preamble the work.** The host already shows tool calls — present findings, don't narrate *"I'll first read X, then Y, then deliver Z."*
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

`qa-deciding-approach` routes here for `verify-existing` approach (config-only / trivial). For larger reviews, this skill still runs but with broader scope.

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

9. **Map risk coverage** — for each named risk: cite the test that covers it (file + test name) or flag it as uncovered. A risk with no covering test is a SAFE-blocker.

10. **Deliver the verdict + residual concerns** — SAFE TO MERGE | NOT SAFE | NEEDS WORK with concrete evidence (test counts, risk coverage map, rule citations). SAFE only if: (a) suite green right now, (b) every named risk has ≥1 passing covering test, (c) no loaded rule violated. Always list residual concerns even on SAFE.

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
> **AI (scope):** *"3 files changed: `api/refund.py` (+38/-4), `domain/Refund.kt` (+12/-2), `tests/test_refund_api.py` (+25/-0). API response shape moved and refund-amount calculation changed; `tests/contracts/refund_v1.json` was NOT modified. Is this consumer external (need coordination) or internal-only?"*
>
> *(continues to risks, tests run, risk-coverage map, verdict — one section per turn)*

### Bad (single-shot verdict)

> **User:** "review my changes, is this safe to merge?"
>
> **AI:** *"Looks straightforward — 3 files, mostly internal refactor. Should be fine to merge. Maybe run CI."*
>
> No fresh test evidence. No risk anchoring. No standards check. Iron Law violated.

## Next skill in the chain

When the verdict is delivered (SAFE / NOT SAFE / NEEDS WORK) with fresh evidence + risk-coverage map → `qa-finishing-qa-work` to capture the evidence and produce the PR-ready summary the user can paste into a description or release note.
