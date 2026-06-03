---
name: sumo-qa-reviewing-before-merge
description: Use when the user asks "review my changes" / "is this safe to merge" / "what could break". Reads the diff and the changed files first, surfaces what was found + named risks, runs tests, then delivers the verdict — section by section with confirmation gates, not as one dump. Refuses to claim safe-to-merge without fresh verification evidence.
---

# Reviewing before merge

Help the user decide whether a change is safe to ship by walking the review one section at a time: explore the diff, surface what was found, name the risks, run the verification, deliver the verdict. The user has product context (was this a deliberate behaviour change? is this consumer used externally?) the AI can't infer from the diff alone — surface it through questions, don't assume it.

**Announce at start:** *"Reviewing the diff against fresh test evidence."*

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: **output discipline** (never surface internal taxonomy labels — say *"behaviour change in pricing"*, not *"Classification: business_logic_change"*; this includes the raw keys of any loaded change-rules file — cite the rule in plain English, e.g. *"the documented-inventory rule"*, never by echoing its YAML key), **output economy** (spend output on findings not framing; no preamble or self-narration; one question per turn; no closing pleasantries), knowledge authority hierarchy, internal scaffolding stays internal, and specialty-tool fit.

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

   **Repo-map accelerator (optional).** `sumo_qa_analyze_diff_impact` scans live and persists a repo-map (`persisted_map_path`) when none exists, so a risk surface is never just "no repo-map / not scanned". It returns changed/affected nodes, likely tests, and the risk surface (changed sources with no mapped test); never blocks the review. **It is NOT coverage evidence** — `related_tests` are run-candidates, `risk_surface` candidate UNCOVERED anchors, never proof. If `probable_mapping_gap` is true (tests exist but the map found no links — e.g. CamelCase/Kotlin), the risk surface is a *mapping* gap, not zero coverage — confirm via the test tree. The Iron Law's fresh-run requirement is unchanged.

   **Context bundle (optional input).** If the host hands you a context bundle — a compact, host-neutral record of issue/PR summary, changed files, test/CI evidence (each with a source + freshness marker), and user constraints — PREFER it as a head-start: validate and read it via `sumo_qa_format_context_bundle` (pass the live local head as `local_head_sha` so the tool flags a conflict). No bundle → fall back to direct repo inspection below; the bundle is an accelerator, never a requirement, with no GitHub/network dependency. Three rules: (a) **stale/unknown evidence is not fresh evidence** — the bundle's CI/test facts are input, never the verdict source; any fact in the tool's `untrustworthy_evidence_fields` (freshness `stale`/`unknown`/`absent`) is treated as stale, so re-run the suite this turn and never claim safety from it; (b) **call out conflicts** — when the tool returns a `conflict` (bundle `head_sha` ≠ live local head), say so and trust the live diff you can inspect, overriding neither side silently; (c) **the bundle never replaces the diff read** — still read the actual diff and changed files (steps 1–2).

2. **Read the actual changed files** *(no user question)* — not just the diff hunks. Surrounding code matters for risk analysis. For each changed file: identify the public surface that moved.

3. **Classify and load applicable standards** *(no user question)* — call `sumo_qa_load_classifications()`, infer the classification(s), then `sumo_qa_load_standards(...)` and `sumo_qa_load_rules(...)`. Note which loaded rules apply.

4. **Adversarial discovery pass → named risks anchored to file:line** *(no user question)* — Codex-class defects ship past green suites because nobody swept the diff for them. BEFORE naming risks, run this discovery sweep over the diff; each hit becomes a named risk anchored to file:line. The probes map a code-shape signal to the defect class to suspect:

   - **Reordered statements in a write/persist path** → an intermediate state is now observable or persisted; on partial failure it can leave invalid/partial state (rollback / data-loss).
   - **A removed, loosened, or inverted guard/conditional** → the path it blocked is now reachable; name what that exposes.
   - **A rollback / cleanup / undo path** → does it RESTORE overwritten or pre-existing state, or does it `unlink`/clobber it? Deleting a destination that pre-existed is data loss, not rollback.
   - **A documented count/name/inventory, a version bump, or a generated artifact (manifest, lockfile, sidecar)** → search the supplied repo state repo-wide for stale copies of the old value; for generated files, was the generator re-run and the output committed? (the documented-inventory / generated-artifact drift probe — see step 9).
   - **A file/path enumeration (`git ls-files`, glob, walk)** → does it include entries it must not — tracked-but-deleted, ignored, suffix-variant, hidden?
   - **A path check compared against `cwd` or a relative root** → should it anchor to the repo/project root? cwd-relative checks are bypassable from a subdirectory (security boundary).
   - **A platform/OS branch (`sys.platform`, symlink-vs-copy, path separators, spaces in paths)** → is every branch's inverse/cleanup symmetric, and is each branch actually exercised?
   - **A widened type/schema (bare `dict`/`Any`/`object`, new optional union, relaxed validation)** → does it weaken a previously-constrained contract or a published/derived schema into an unconstrained branch?
   - **A retry / async / timeout / teardown / shutdown path** → idempotency across retries, poison-message parking, and teardown-after-assert that can raise and error a logically-passing test (cleanup flakiness).
   - **A CI / merge-gate change (required checks, admin-merge, wait conditions)** → does it wait on ALL required checks (the full matrix), or can it proceed before some finish?
   - **A weakened test assertion (substring/presence-only replacing exact/structural)** → would it still pass if the contract under test were removed? (tautology — a test-only-change SAFE-blocker).
   - **A matcher/parser over EXTERNAL output (regex/string match on subprocess/CLI text, an API response-shape assumption, another tool's file format, a committed fixture mimicking tool output)** → correctness depends on the REAL output format of a tool/CLI/API the diff doesn't control. Green tests prove matcher LOGIC, not that the marker matches REAL output; a hand-authored fixture can be fiction (the `mutmut run` emoji-vs-`survived` miss). Name the external-contract dependency as a risk (the external-contract probe — step 9). **Producer test (apply first):** the axis fires ONLY when the value is produced by something the diff does NOT control (another tool/CLI/subprocess/API/foreign file). If the SAME change (or the host) is its sole producer — the code serialises its own envelope/marker and parses it back, a round-trip over a self-format — it is INTERNAL: raise no external-contract risk and demand no "real run" capture (ordinary internal risks like round-trip/charset/boundary may still apply, but NOT this axis). When the producer test resolves INTERNAL, you MUST say so explicitly — silent suppression is not enough. State in one line that the matched value is self-produced: quote the concrete value verbatim (e.g. `[sumo-qa:CODE]`), name the sole producer and the same-module consumer, and conclude the external-contract axis does NOT fire (the 2d declination row below carries this on the record).

   **Discovery → verdict (pinned).** A defect this sweep surfaces that the fresh tests do not cover is a NAMED RISK, mapped through the coverage ledger (step 9) as UNCOVERED. It is a SAFE-blocker → NOT SAFE TO MERGE. Do NOT demote a discovered latent defect to a "residual concern" under a SAFE verdict, and do NOT call it covered because a green test runs nearby — a green run that uses a happy fixture, ingests into an empty target, runs from the repo root, or hits only one platform/matrix leg does NOT cover the overwrite / deleted-entry / subdirectory / other-OS path. Treating it as coverage is the bypass that ships these defects; this demotion is the exact failure this pass exists to prevent.

   The sweep produces 3–7 named risks, each citing a specific file + line + the domain meaning — NOT generic ("edge cases", "untested paths"). **Skip the sweep only for the trivial-change exemption below** (docs-only / tool-only config — formatter/linter ignore lists, editor config — with no runtime consumer); running it there manufactures phantom runtime risk, the negative-control failure mode.

5. **Confirm scope, only for the AMBIGUOUS parts** — present a short paragraph naming the files, line counts, and what the change does in domain terms. Then ask ONE focused question for what the diff couldn't reveal (e.g. *"is this consumer external — do we need to coordinate the contract bump?"*). If nothing's ambiguous, skip the question.

6. **Present named risks, ask after** — present the 3–7 risks anchored to file:line:
   *"R1: `api/refund.py:47` — new error path returns 500 instead of 422 for invalid-amount; consumer X depends on 4xx-vs-5xx for retry logic.*
   *R2: `domain/Refund.kt:18` — idempotency key derivation changed; double-refund possible on retry of a partially-completed call. …"*

   **Technique-keyed failure-mode hints (pinned).** When a risk's failure mode maps to a named black-box technique, ground it in that technique's catalogued failure modes (`sumo_qa_load_techniques`) — NOT per-AI judgment — and name the specific one in play. A precision/recall risk on a keyword/substring matcher is *equivalence partitioning* → call out substring/token confusion (a value matches because it CONTAINS the keyword — `unlocked` matches `locked`, `concurrency` matches `currency` — not because it belongs to the class), overlapping classes, and the missing empty-input class. A limit/threshold/off-by-one risk is *boundary value analysis* → call out both-sides + just-inside-vs-just-outside and `<` vs `<=`. A multi-condition business-rule risk is *decision tables* → call out the missing rule row / absent default arm. Surfacing the catalogued failure mode is what turns a vague "precision might be off" into the discriminating input step 9 then demands. If the technique isn't in the loaded catalogue, say so (the knowledge-authority rule) — don't confabulate a failure mode.

   Ask: *"do these match how you'd describe the risks? add / remove / refine?"* Wait for the user.

7. **Run the test suite — show the actual output** — use the host's runner. Surface: total / passed / failed / skipped / duration. If failures: name them. Do NOT proceed to verdict on partial output.

8. **Run targeted tests around the changed files** — e.g. `pytest tests/test_<changed_module>.py -v`. Confirm closest neighbours stay green. Surface the count.

9. **Map risk coverage** — for each named risk, cite the fresh test that demonstrably exercises that exact failure path (file + fully-qualified test + the verbatim assertion/condition), or mark it UNPROVEN / UNCOVERED. Never infer coverage from a shared name or domain. A risk with no covering test is a SAFE-blocker.

   **Re-anchor first.** If risks arrive as bare names (*"Auth Session Bypass, Duplicate Charge on Retry"*), locate each one's anchor file in the diff before mapping — *Auth Session Bypass* → `app/auth/session.py:33`, *Duplicate Charge on Retry* → `app/billing/checkout.py`. Without an anchor you cannot apply the module-match rule and will hallucinate coverage. When a repo-map is loaded, `sumo_qa_query_repo_map` helps locate a RUNTIME risk's anchor file or a candidate test by path/name — but a test counts only once it's in THIS turn's fresh run with a verbatim assertion. It does NOT consolidate inventory drift: each stale path still gets its own 2a row with its own `(<old> → <new>)` pair (below).

   **Module-match rule (pinned):** a risk anchored under `app/auth/` requires a covering test under `tests/auth/`; `app/billing/` requires `tests/billing/`. A `tests/billing/` test cannot cover an `auth/session.py` risk via *"indirectly validates"* / *"implicitly covers"* — forbidden hallucinated bridges; mark UNCOVERED when paths don't match. If the fresh run loaded no test for a changed file's module, every risk anchored there is UNCOVERED, however green the rest is. **Integration/e2e exception:** tests under `tests/integration/` or `tests/e2e/` MAY cover any module risk, but only if the cited assertion verbatim invokes (or asserts a property of) the risk's anchor function; "the integration suite passed" without naming that assertion is the same hallucinated bridge. **External-contract exception (pinned):** the module-match path rule does NOT apply to an external-contract risk (step 4's external-output probe). Its evidence is REAL captured output, never a `tests/<module>/` test. When the fixture is traceable to a real or minimal run (capture command / provenance cited), the axis is COVERED and DISCHARGED — SAFE-eligible — REGARDLESS of where the tests live. Do NOT mark an external-contract risk UNCOVERED because its tests sit at `tests/test_x.py` instead of `tests/<module>/`.

   **Worked contrast (same-domain ≠ proof).** Risk *"Duplicate Charge on Retry"* + passing `tests/billing/test_checkout.py::test_does_not_mark_failed_charge_paid`:
   - BAD: *"Covered by `test_does_not_mark_failed_charge_paid`."* — it asserts one failed charge isn't marked paid; it never re-invokes `complete_checkout` after a partial failure, so it cannot prove retry idempotency.
   - GOOD: *"UNCOVERED. No fresh test re-invokes `complete_checkout` after a partial failure or asserts charge-at-most-once across retries. SAFE-blocker."*

   **External-contract rule (pinned).** For an external-contract risk (step 4's external-output probe), a green matcher proves LOGIC, not that its INPUT matches reality — the captured external output must itself be verified. A hand-authored or guessed fixture with no real-run traceability is UNPROVEN — never SAFE on the green suite alone, however non-vacuous the tests. But when the fixture/sample IS traceable to a REAL or minimal run of the tool (captured output, the capture command/provenance cited), the real output IS the evidence: mark the external-contract risk COVERED and DISCHARGED on that axis — SAFE-eligible — and do not re-block it as uncovered, demand a fresh capture (over-trigger), or invent speculative alternate output formats the diff doesn't depend on. The module-match path rule does not apply to an external-contract risk: its evidence is real captured output, not a `tests/<module>/` test. **Anti-over-discovery (pinned):** once a real-run-traceable fixture DISCHARGES the external-contract axis (COVERED), the external output format is PROVEN for the cases the diff handles. Do NOT then manufacture SPECULATIVE output-format-variant risks — hypothetical locale/encoding/emoji marker variants, or fail-open-on-parse modes — that the diff does not depend on, and do NOT demand fresh captures for them. Inventing speculative variant risks to re-block a COVERED external contract is the SAME over-trigger this guard prevents. A genuine parsing risk that the diff's own code path can actually hit is still fair to name; speculative variant-hunting on an already-discharged real-run contract is not. Regression guard: fires ONLY on genuinely external sources — apply step 4's producer test, never raise it on internal/self-produced values; require EVIDENCE of real-output verification, not a re-run of every external tool.

   **Documented-inventory drift rule (pinned).** When the diff changes a documented count, inventory, public-surface name, or schema field — the documented-inventory-drift probe — the obvious doc the diff touches is rarely the only stale spot. Before the verdict, search the supplied ground-truth context (any `rg`/grep listing, "Other repo state" section, etc.) for the OLD value; each path it surfaces is a separate UNCOVERED anchor that needs its own ledger row (format in Verdict-format discipline item 2a). Generic guidance, anchoring only on the obvious doc, or naming one stale path is UNCOVERED. If the ground-truth context names zero stale paths, say so explicitly; do NOT silently default to "covered".

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

     **Worked contrast (one row per stale path, value pair inline).** Two stale paths surfaced (`docs/INSTALL.md:17`, `.github/ISSUE_TEMPLATE/qa_output_quality.yml:22`), old `28` → new `29`:
     - BAD (single crammed row, no value pair): `Risk: Documented-inventory drift | Anchor: README.md:42 | Required update: docs/INSTALL.md, .github/ISSUE_TEMPLATE/qa_output_quality.yml | Coverage: UNCOVERED` — collapses both paths into one row, anchors on the obvious doc, omits `(28 → 29)`. SHAPE FAIL.
     - GOOD (one row per stale path, value pair inline):
       `Inventory drift anchor: docs/INSTALL.md:17 (28 → 29) | Required update: this file | Diff updated it: NO | Coverage: UNCOVERED`
       `Inventory drift anchor: .github/ISSUE_TEMPLATE/qa_output_quality.yml:22 (28 → 29) | Required update: this file | Diff updated it: NO | Coverage: UNCOVERED`
   - **2b. UNPROVEN-escalation extension (pinned).** A `Coverage: UNPROVEN` row is not dischargeable by simply noting the risk as a "residual concern" — that escape hatch is what let a known precision/recall trade-off ship as SAFE. Every UNPROVEN risk MUST additionally emit ONE of these two lines (in this exact shape) before the verdict, and UNTIL one is present the row is a SAFE-blocker:
     - **Prescribed (preferred):** name a concrete discriminating input — one input the broken and correct implementations handle DIFFERENTLY (the broken impl gives a wrong observable result, a correct impl the right one) — and add a regression test asserting the CORRECT behaviour to the test gate before SAFE. State the behaviour contrast, not test pass/fail: the test you add asserts the right result, so it is RED against the broken impl and GREEN once fixed — never the inverse.
       `UNPROVEN escalation: <risk name> | Discriminating input: <the input> | Broken impl does: <wrong observable result> | Correct impl does: <right result> | Required before SAFE: add a test asserting the correct result to <tests/<module>/...>`
       Anchor the input in the technique's catalogued failure mode where one fits (substring/token confusion → an input that contains the keyword but isn't in the class, e.g. `unlocked` wrongly matched by a `locked` keyword matcher; a boundary → the boundary / just-inside / just-outside value that distinguishes the OBSERVED comparator (e.g. the limit value itself when the bug is `<` vs `<=`, not merely a far-outside value); a decision-table gap → the unenumerated combination). An input both implementations handle the same way is not discriminating — it proves nothing; reject it.
       Because a discriminating input is prescribed, NOT yet run, this row stays a SAFE-blocker until the test is added and green in a fresh run — it RAISES the bar, it does not grant SAFE on its own.
     - **Deferred (only with the failure mode named):** if the user explicitly defers, the deferral must NAME the failure mode being accepted, not wave at "residual precision":
       `UNPROVEN deferral: <risk name> | Accepted failure mode: <the named mode, e.g. substring/token confusion> | Acknowledged by: <user> | SAFE-blocker: YES (always)`
       An acknowledged deferral records the user's accepted risk; it never makes the review verdict SAFE while the risk stays UNPROVEN — the verdict remains NOT SAFE and names the accepted residual. Only a prescribed discriminating input added + green (which makes the risk PROVEN) can clear the UNPROVEN status.
     A bare `Coverage: UNPROVEN` row with neither a 2b prescribed line nor an acknowledged 2b deferral is a discipline violation. This raises the SAFE bar on UNPROVEN risks only — it loosens no other gate.
   - **2c. External-contract extension (pinned).** For an external-contract risk, emit this row INSTEAD of the path-keyed row (`Required test path` does not apply):
     `External-contract anchor: <file:line> | External source: <tool/CLI/API> | Real-output evidence: <captured fixture + provenance/capture command, or NONE> | Coverage: <COVERED (real-run-traceable fixture cited) | UNPROVEN (hand-authored/no real-run traceability)>`
     A documented real-run capture → COVERED, SAFE-eligible. A hand-authored fixture with no real-run traceability → UNPROVEN, SAFE-blocker. Never emit `Required test path: tests/<module>/` for an external-contract risk.
   - **2d. Internal/self-produced declination (pinned).** When the external-output probe resolves INTERNAL (producer test), emit this line so the true-negative is on the record:
     `External-contract axis: NOT FIRED (internal/self-produced) | Value: <verbatim self-produced value, e.g. [sumo-qa:CODE]> | Producer: <fn/module> | Consumer: <fn/module, same change> | No external source: confirmed`
3. `Touched files:` citing every diff path verbatim (e.g. `app/auth/session.py, tests/billing/test_checkout.py`).
4. `Change shape:` one phrase anchored to the touched files (e.g. `auth predicate + billing checkout ordering, both runtime`).
5. The verification command, quoted verbatim.
6. The test counts verbatim (`X passed, Y skipped, Z failed`).

A runtime verdict emitted before all six are present is a discipline violation.

**Trivial-change exemption (pinned):** if the diff touches only docs (`docs/`, markdown), config (YAML/TOML/JSON outside runtime source), or other non-runtime files — no `app/`/`src/`/`lib/` file present — SKIP item 2; the verification command (linter/formatter/build) IS the coverage, so mark those anchors `COVERED BY VERIFICATION`. Items 1, 3, 4, 5, 6 still required. `Touched files:` and `Change shape:` are mandatory in both modes; citing the verification command's file argument does not discharge `Touched files:`.

10. **Deliver the verdict + residual concerns** — `SAFE TO MERGE` | `NOT SAFE TO MERGE` | `NEEDS WORK` with concrete evidence (counts, coverage map, rule citations). SAFE only if (a) suite green now, (b) every named risk has ≥1 fresh test demonstrably exercising that exact path (not a tangentially-named one), (c) no loaded rule violated. **If ANY named risk is UNCOVERED or UNPROVEN, the verdict MUST be NOT SAFE TO MERGE — no exceptions, even on a fully green suite.** The ONLY way an UNPROVEN risk becomes SAFE-eligible is to add its prescribed 2b discriminating input and have it run GREEN in a fresh run — that turns the risk PROVEN/COVERED and clears the UNPROVEN status. A deferral never yields SAFE: an acknowledged failure-mode-named deferral is better-documented but still NOT SAFE (the verdict names the accepted residual), and a bare UNPROVEN row is a discipline violation. Every UNPROVEN row still MUST carry its 2b line (a prescribed discriminating input, or an acknowledged failure-mode-named deferral) — but only the prescribed-input-added-and-green path clears it to SAFE. Always list residual concerns, even on SAFE.

   **The two-pass split (pinned).** In the `/work-issue` pipeline this review is pass 1; an adversarial codex pass runs after it. The catch this skill must NOT outsource: when it can name a precision/recall risk and the technique has a catalogued failure mode, it prescribes the discriminating input ITSELF (step 9 / 2b) — it does not defer that to codex. Pushing the catch into this phase is what makes the review scale when codex isn't available (CI-only runs, limited codex tokens). Codex remains a second independent check, never the only place an UNPROVEN risk gets a discriminating input.

### Risk-to-test ledger appendix (optional, structured)

The prose verdict above is the deliverable; it is never replaced. When the user wants a paste-into-PR artifact (*"give me the ledger"*, *"export the risk map"*), project the SAME named risks + coverage map into the structured ledger via `sumo_qa_format_risk_ledger` and append it BELOW the verdict — never in place of it. The tool is file/format plumbing: YOU identify the risks (steps 4/9), it only validates and renders them. Build one row per named risk with `evidence_status` from this turn's run — `passing` (a fresh path-matching test quotes the assertion), `failing` (a fresh test red against this risk), `planned` (no fresh test yet — i.e. UNCOVERED/UNPROVEN), `stale` (a prior pass that no longer reflects the diff, e.g. an `xfail` pinning old behaviour), or `accepted_residual` (a deliberately accepted non-coverage). Set `residual: blocker` for every UNCOVERED/UNPROVEN high-risk row; the tool's `uncovered_blocker_count` must be 0 before any SAFE verdict, mirroring step 10. Optionally link `repo_map_node_id` when a repo-map is loaded; a missing repo-map is weaker evidence, never a blocker. Skip the appendix entirely for trivial-change reviews — don't manufacture a ledger where prose suffices.

**Render it as the markdown table the tool returns** — a markdown table, never a JSON blob, with exactly these columns: `| Risk | Statement | Source | Test / check | Evidence | Residual |` (one row per named risk; `Evidence` is the `evidence_status` value, `Residual` the residual decision). The `Test / check` cell holds the covering test id or a `planned: …` phrase; `Source` is the file:line anchor. **EVERY cell is filled — `Residual` is never blank**: a covered/passing risk is `accepted` (or `mitigated` if mitigated elsewhere); an uncovered/unproven high-risk row is `blocker`; an unsettled one is `open`. If a host hasn't surfaced the tool, emit this exact table shape by hand. Worked two-row example (one covered, one uncovered):
`| R1 | Invalid-amount now returns 422 not 500 | services/billing/refund.py:47 | tests/billing/test_refund_api.py::test_invalid_amount_returns_422 | passing | accepted |`
`| R2 | Idempotency key derivation moved → double refund on retry | domain/Refund.kt:18 | planned: re-invoke refund after partial failure, assert at-most-once | planned | blocker |`

## Process Flow

See the Checklist above — that's the flow.

## Red Flags — STOP and rework

| Thought | Reality |
|---|---|
| "Looks good to me" / "CI was green an hour ago" | Neither is fresh evidence. Run the suite now. |
| "Trivial change, no need to walk through sections" | The Iron Law doesn't have a trivial-change exemption. Walk through; the review can be short, but every section gets confirmation. |
| "I'll skip running tests — they're slow" | Then you can't claim safe-to-merge. Slow tests are still the verdict source. |
| "All tests pass, so SAFE" | Necessary, not sufficient. Each named risk must also have a covering test. |
| "I spotted a latent issue but tests are green — SAFE, with a residual note" | The discovery sweep's hits are NAMED RISKS, not residual notes. A discovered defect the fresh tests don't exercise is UNCOVERED = NOT SAFE. Demoting it to a residual concern is the gap step 4 closes. |
| "The path is covered but no assertion hits the failure mode — I'll note it UNPROVEN and ship as a known trade-off" | An UNPROVEN risk demoted to a residual trade-off is the exact bypass 2b closes. Prescribe a concrete discriminating input (one the broken impl mishandles and a correct impl handles right — e.g. `unlocked` wrongly matched by a `locked` substring matcher) and require it before SAFE. Only adding that input and running it GREEN clears UNPROVEN to SAFE; a deferral — even a failure-mode-named acknowledged one — stays NOT SAFE (just better-documented). A bare UNPROVEN row never reaches SAFE. |
| "Codex will catch the discriminating input later, I'll just name the risk" | Don't outsource the catch. When you can name the risk and the technique has a catalogued failure mode, YOU prescribe the discriminating input — codex is a second pass, not the only one (it isn't there in CI-only runs). |
| "I'll skip the discovery sweep — looks like a clean refactor" | The sweep is mandatory for any runtime diff. Codex-class defects (cwd bypass, rollback data-loss, schema widening, partial CI gate) hide in clean-looking diffs and pass green suites. Only docs-only / tool-only config is exempt. |
| "The matcher is green, so parsing the tool's output is covered" | Green proves matcher LOGIC, not that the marker matches REAL output. A hand-authored fixture with no real-run traceability is UNPROVEN — NOT SAFE; covered only when it traces to a real/minimal run. Don't over-trigger on internal values or re-demand a capture the context already supplies. |
| "External-contract tests live at `tests/test_x.py` not `tests/<module>/`, so UNCOVERED" | The path rule does NOT apply to external-contract risks — their evidence is real captured output. A real-run-traceable fixture is COVERED wherever its tests sit. |
| "The real-run fixture covers the contract, but what about emoji/locale/other output variants?" | Speculative output-variant hunting on an already-discharged (COVERED) external contract is over-trigger. The real-run fixture proves the format for the cases the diff handles; do not manufacture variant risks the diff doesn't depend on to re-block SAFE. |
| "It's self-produced, so I'll just not raise the external-contract risk" | Declining silently fails grounding. State it: quote the self-produced value, name producer and same-module consumer, conclude no external contract. |
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
