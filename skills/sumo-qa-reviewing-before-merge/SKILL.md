---
name: sumo-qa-reviewing-before-merge
description: Use when the user asks "review my changes" / "is this safe to merge" / "what could break". Reads the diff and the changed files first, surfaces what was found + named risks, runs tests, then delivers the verdict — section by section with confirmation gates, not as one dump. Refuses to claim safe-to-merge without fresh verification evidence.
---

# Reviewing before merge

Help the user decide whether a change is safe to ship by walking the review one section at a time: explore the diff, surface what was found, name the risks, run the verification, deliver the verdict. The user holds product context the diff cannot reveal; surface it through questions, never assume it.

**Announce at start:** *"Reviewing the diff against fresh test evidence."*

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: **output discipline** (no internal taxonomy labels or raw change-rule keys; cite rules in plain English), **output economy** (findings not framing; one question per turn; no pleasantries), knowledge authority hierarchy, internal scaffolding stays internal, specialty-tool fit.

<HARD-GATE>
Do NOT deliver a verdict before running tests in this turn. "CI was green earlier" is not fresh evidence. The Iron Law's only verdict source is the suite running RIGHT NOW against THIS diff, with the actual pass/fail counts surfaced.
</HARD-GATE>

## The Iron Law

**NEVER CLAIM SAFE-TO-MERGE WITHOUT FRESH VERIFICATION EVIDENCE.** "All tests pass" is necessary but not sufficient — every named risk must also have a passing test covering it.

## Evidence-backed gate reporting

Every gate claim (suite verdict, risk coverage, safe-to-merge call) carries a status (`passed` / `failed` / `skipped` / `blocked` / `unverified`) and, unless `skipped` or `unverified`, cites the ONE observed evidence item backing it by source (`command`, `tool_call`, `file_read`, `user_fact`, `external_ci`, `manual_observation`). Citing means NAMING the source and quoting the observation, as a labeled line: `Evidence (command): $ pytest tests/auth -q → 42 passed, 2 skipped`. Test names or counts alone, with no labeled source behind them, do NOT count as a cite. A `passed` / `failed` / `blocked` claim with no cited source is an overstatement; `unverified` is the honest state when nothing was observed this turn. `SAFE TO MERGE` is a `passed` safe-to-merge gate, unreachable while any gate is `failed` / `blocked` / `unverified`. Keep it compact: a status word + a short source cite per line, never a second dump.

## When to Use

Triggers: *"review my changes"*, *"is this safe to merge"*, *"what could break"*, *"code review please"*. `sumo-qa-deciding-approach` routes here for `verify-existing`.

## Checklist

You MUST work through these in order. Steps 1-4 are AI-only homework (no user questions); the user's confirmation gates steps 5 onward. Load a step's modules (routing table below) first.

1. **Read the diff via the host's git tools** *(no user question)* — `git diff`, `git diff --staged`, or `git diff <base>...HEAD` depending on intent. Capture file list + line counts. Supplied repo-map / bundle / coverage artifacts go through `context-inputs`; if none, say `no coverage/mutation artifact this turn — not measured`.

2. **Read the actual changed files** *(no user question)* — not just the diff hunks. Surrounding code matters for risk analysis. For each changed file: identify the public surface that moved.

3. **Classify and load applicable standards** *(no user question)* — call `sumo_qa_load_classifications()`, infer the classification(s), then `sumo_qa_load_standards(...)` and `sumo_qa_load_rules(...)`. Note which loaded rules apply.

4. **Adversarial discovery pass** *(no user question)* — Settle the diff shape with `runtime-scope`: a test-files-only diff runs `test-only-diff` instead; a genuinely non-executable diff takes the trivial-change exemption. For every runtime file run `discovery-probes`, adding `security-relevance`, `external-contract`, or `contract-and-fence-probes` when the diff shows that shape, and `feedback-memory` when saved feedback is supplied (absent: say `no saved review feedback supplied — advisory-hint check skipped`). Each hit is a named risk anchored to file:line; one the fresh tests do not cover is UNCOVERED, a SAFE-blocker, never a residual note.

5. **Confirm scope, only for the AMBIGUOUS parts** — name the files, line counts, and what the change does in domain terms, then ask ONE focused question for what the diff couldn't reveal. If nothing's ambiguous, skip the question.

6. **Present named risks, ask after** — 3-7 risks anchored to file:line, each with its domain meaning; ground a technique-shaped failure mode through `unproven-escalation`'s hints, not per-AI judgment. Ask *"do these match how you'd describe the risks? add / remove / refine?"* and wait.

7. **Run the test suite — show the actual output** — use the host's runner. Surface: total / passed / failed / skipped / duration. If failures: name them. Do NOT proceed to verdict on partial output.

8. **Run targeted tests around the changed files** — e.g. `pytest tests/test_<changed_module>.py -v`; confirm closest neighbours stay green and surface the count.

9. **Map risk coverage** — for each named risk, cite the fresh test that demonstrably exercises that exact failure path (file + fully-qualified test + the verbatim assertion/condition), or mark it UNPROVEN / UNCOVERED. Never infer coverage from a shared name or domain. A risk with no covering test is a SAFE-blocker.

   Apply `coverage-ledger` to every runtime risk, then the conditional modules the diff calls for: `inventory-drift`; `unproven-escalation` for any UNPROVEN row; `acceptance-criteria` (and `ac-evidence-views` on a close call) when criteria are supplied; `surface-verifier`, `feature-flow`, `eval-validity`, then `discharged-check`.

10. **Deliver the verdict + residual concerns** — `SAFE TO MERGE` | `NOT SAFE TO MERGE` | `NEEDS WORK`. SAFE only if (a) suite green now, (b) every named risk has a fresh test demonstrably exercising that exact path, (c) no loaded rule violated, (d) every supplied acceptance criterion is MET, (e) every applicable verification-evidence line is discharged. **ANY UNCOVERED or UNPROVEN risk, UNMET or UNVERIFIED criterion, or undischarged verification line means NOT SAFE TO MERGE, no exceptions, even on a green suite.** UNPROVEN clears only when its prescribed discriminating input runs GREEN in a fresh run (a deferral never yields SAFE); blockers clear by supplying evidence, never by weakening a verifier or rubric. Always list residual concerns, even on SAFE. A ledger (`ledger-appendix`) or scorecard (`readiness-scorecard`) goes BELOW the prose verdict.

## Module routing table

Conditional rules live in `modules/<id>.md`, each the ONLY copy of what it carries. Fetch one via `sumo_qa_load_skill_context(skill_name="sumo-qa-reviewing-before-merge", mode="module", module="<id>")` or read the file, BEFORE the step that needs it; load only what the diff shape requires, never a rule from memory.

| Module | Load when |
|---|---|
| `runtime-scope` | settling whether a diff is runtime (executable behaviour, not path prefix) or trivial |
| `discovery-probes` | every runtime review (step 4): code-shape probes, discovery-to-verdict, two-pass split |
| `security-relevance` | auth, secrets, input sanitisation, rate limiting, audit logging, security config/dependency |
| `external-contract` | any matcher/parser over output the diff may not control (tool/CLI/API text, a fixture): its producer test decides INTERNAL (declare it) vs external |
| `contract-and-fence-probes` | a docstring/contract invariant (`Never raises`), or a stateful marker/fence parser |
| `feedback-memory` | the host supplies saved review-feedback memory |
| `context-inputs` | a repo-map / diff-impact result, context bundle, or coverage/mutation artifact is supplied |
| `coverage-ledger` | every runtime review (step 9): re-anchoring, module-match rule, item-2 rows incl. 2c/2d |
| `inventory-drift` | a documented count, name, inventory, version, schema field, or generated artifact changed (2a) |
| `unproven-escalation` | any risk is UNPROVEN, or maps to a catalogued technique's failure mode (2b, hints) |
| `test-only-diff` | the diff touches only test files |
| `acceptance-criteria` | the host supplies acceptance criteria |
| `ac-evidence-views` | with `acceptance-criteria`: a close MET/UNVERIFIED call, or the AC map as a table |
| `surface-verifier` | a repo-specific verifier exists; ALWAYS for a skill or eval change; sibling PRs co-edit |
| `feature-flow` | a runtime change serves a UI/API/CLI/worker/artifact flow |
| `eval-validity` | a new regression guard / "do X but NOT Y" rule, or a new/changed `.ab.yaml` control |
| `discharged-check` | a verification-evidence check or external-contract axis is discharged |
| `ledger-appendix` | the user wants a paste-into-PR risk ledger |
| `readiness-scorecard` | the user asks for a readiness summary |

### Verdict-format discipline

The verdict line is the LAST line. For a runtime change (per `runtime-scope`), before the verdict you MUST emit, in order:
1. Each named risk by exact name, one per line (`Risk 1: Auth Session Bypass`).
2. A coverage-ledger line per risk as pinned in `coverage-ledger`, plus the 2a/2b/2c/2d extension rows a present risk class requires.
3. `Touched files:` citing every diff path verbatim (e.g. `app/auth/session.py, tests/billing/test_checkout.py`).
4. `Change shape:` one phrase anchored to the touched files (e.g. `auth predicate + billing checkout ordering, both runtime`).
5. The verification command, quoted verbatim as a LABELED evidence-source line (the gate-evidence source cite): `Evidence (command): $ <verification command> → <counts>`.
6. The test counts verbatim (`X passed, Y skipped, Z failed`).
7. **AC lines** when criteria were supplied, one per criterion as pinned in `acceptance-criteria` (MET ones too); else exactly `No acceptance criteria supplied — AC-coverage check skipped; verdict rests on risk coverage.`
8. **Verification-evidence lines** that apply, as pinned in `surface-verifier`, `feature-flow`, `eval-validity`; each a SAFE-blocker until discharged.

A runtime verdict emitted before all six (plus item 7 when ACs are present, item 8 when the change touches a verifiable surface / feature flow / guard / eval-driven skill) is a discipline violation. A trivial diff follows `runtime-scope`'s exemption and a test-only diff the `Test probe:` discipline in `test-only-diff`; items 1, 3, 4, 5, 6 stay mandatory in every mode.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags - STOP and rework

| Thought | Reality |
|---|---|
| "Looks good to me" / "CI was green an hour ago" | Neither is fresh evidence. Run the suite now. |
| "Trivial change, no need to walk through sections" | The Iron Law has no trivial-change exemption; the review can be short, but every section gets confirmation. |
| "I'll skip running tests — they're slow" | Then you can't claim safe-to-merge. Slow tests are still the verdict source. |
| "All tests pass, so SAFE" | Necessary, not sufficient. Each named risk must also have a covering test. |
| "No standards apply to this change" | Re-classify. Every change has at least one applicable classification with loaded rules. |
| "I'll list the risks AND deliver the verdict in one message" | Gate. The user's correction on the risks is what shapes the verdict. |
| "Residual concerns: none" | Every change has them. None = you didn't think about what could still go wrong. |
| "I'll ask which test framework / where tests live" | Read the repo; sibling files answer that. |

## Next skill in the chain

When the verdict is delivered (SAFE / NOT SAFE / NEEDS WORK) with fresh evidence + risk-coverage map → `sumo-qa-finishing-qa-work` to capture the evidence and produce the PR-ready summary.
