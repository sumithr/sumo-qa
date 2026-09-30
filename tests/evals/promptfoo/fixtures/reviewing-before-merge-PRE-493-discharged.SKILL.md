---
name: sumo-qa-reviewing-before-merge
description: Use after sumo-qa-deciding-approach routes here, when the user asks "review my changes" / "is this safe to merge" / "what could break". Refuses to claim safe-to-merge without fresh verification evidence.
---

# Reviewing before merge

Help the user decide whether a change is safe to ship, one Checklist section at a time; ask for the product context the diff cannot reveal, never assume it.

**Announce at start:** *"Reviewing the diff against fresh test evidence."*

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: **output discipline** (no internal taxonomy labels or raw change-rule keys; cite rules in plain English), **output economy** (findings not preamble; one question per turn; no pleasantries), knowledge authority hierarchy, internal scaffolding stays internal, specialty-tool fit.

<HARD-GATE>
Run tests this turn before the verdict; earlier CI is not fresh evidence; the only verdict source is this turn's run on THIS diff, counts surfaced. A required run you cannot do or see is `unverified`, not invented: deliver `NOT SAFE TO MERGE` now, never a held verdict or a question. This outranks steps 5-6: their questions never hold a verdict whose required run is missing.
</HARD-GATE>

## The Iron Law

**NEVER CLAIM SAFE-TO-MERGE WITHOUT FRESH VERIFICATION EVIDENCE.** "All tests pass" is necessary but not sufficient — every named risk must also have a passing test covering it.

## Evidence-backed gate reporting

Every gate claim (suite verdict, risk coverage, safe-to-merge call) carries a status (`passed` / `failed` / `skipped` / `blocked` / `unverified`) and, unless `skipped` or `unverified`, cites the ONE observed evidence item backing it by source (`command`, `tool_call`, `file_read`, `user_fact`, `external_ci`, `manual_observation`). Citing means a labeled line naming the source and quoting the observation: `Evidence (command): $ pytest tests/auth -q → 42 passed, 2 skipped`. Test names or counts alone, with no labeled source behind them, do NOT count as a cite. A `passed` / `failed` / `blocked` claim with no cited source is an overstatement; `unverified` is the honest state when nothing was observed this turn. `SAFE TO MERGE` is a `passed` safe-to-merge gate, unreachable while any gate is `failed` / `blocked` / `unverified`. Keep it compact: a status word + a short source cite per line, never a second dump.

## When to Use

Triggers in the description; `sumo-qa-deciding-approach` routes here for `verify-existing`.

## Checklist

Work through these in order. Steps 1-4 are AI-only homework (no user questions); the user's confirmation gates steps 5 onward. Load a step's modules (routing table below) first.

1. **Read the diff via the host's git tools** — `git diff`, `git diff --staged`, or `git diff <base>...HEAD`. Capture files + line counts. Supplied repo-map / bundle / coverage artifacts go through `context-inputs`; if none, say `no coverage/mutation artifact this turn — not measured`.

2. **Read the actual changed files** — not just the diff hunks. For each, identify the public surface that moved.

3. **Classify and load applicable standards** — call `sumo_qa_load_classifications()`, infer the classification(s), then `sumo_qa_load_standards(...)` and `sumo_qa_load_rules(...)`. Note which loaded rules apply.

4. **Adversarial discovery pass** — `runtime-scope` settles the diff shape (test-only → `test-only-diff`; non-executable → trivial-change exemption). For every runtime file run `discovery-probes`, adding `security-relevance`, `external-contract`, or `contract-and-fence-probes` when the diff shows that shape, and `feedback-memory` when saved feedback is supplied (absent: say `no saved review feedback supplied — advisory-hint check skipped`). Each hit is a named risk anchored to file:line; an uncovered one is a SAFE-blocker labelled per `coverage-ledger`, never a residual note.

5. **Confirm scope, only for the AMBIGUOUS parts** — name the files, line counts, and what the change does in domain terms, then ask ONE focused question for what the diff couldn't reveal. Else skip it.

6. **Present named risks, ask after** — 3-7 risks anchored to file:line, each with its domain meaning; ground a technique-shaped failure mode through `unproven-escalation`'s hints, not per-AI judgment. Ask *"do these match how you'd describe the risks? add / remove / refine?"* and wait.

7. **Run the test suite — show the actual output** — use the host's runner. Surface: total / passed / failed / skipped / duration. Name any failures. Do NOT proceed to verdict on partial output.

8. **Run targeted tests around the changed files** — e.g. `pytest tests/test_<changed_module>.py -v`; confirm closest neighbours stay green; surface the count.

9. **Map risk coverage** — for each named risk, cite the fresh test that demonstrably exercises that exact failure path (file + fully-qualified test + the verbatim assertion/condition), else label it from its row's tests field: tests listed is UNPROVEN, even for missing behaviour; `NONE` is UNCOVERED. Never infer coverage from a shared name or domain.

   Apply `coverage-ledger` to every runtime risk, then the step-9 modules the routing table calls for (`unproven-escalation` for any UNPROVEN row), `discharged-check` last.

10. **Deliver the verdict + residual concerns**, emitting the Verdict-format lines below first, even in a single-pass review, then `SAFE TO MERGE` | `NOT SAFE TO MERGE` | `NEEDS WORK`. SAFE only if (a) suite green now, (b) every named risk COVERED per step 9, (c) no loaded rule violated, (d) every supplied acceptance criterion is MET, (e) every applicable verification-evidence line is discharged. **ANY UNCOVERED or UNPROVEN risk, UNMET or UNVERIFIED criterion, or undischarged verification line means NOT SAFE TO MERGE, no exceptions, even on a green suite.** UNPROVEN clears only when its prescribed discriminating input runs GREEN in a fresh run (a deferral never yields SAFE); blockers clear by supplying evidence, never by weakening a verifier or rubric.

## Module routing table

Conditional rules live in `modules/<id>.md`, each the ONLY copy of what it carries. Fetch one via `sumo_qa_load_skill_context(skill_name="sumo-qa-reviewing-before-merge", mode="module", module="<id>")` or read the file, BEFORE the step that needs it; load only what the diff shape requires, never a rule from memory.

| Module | Load when |
|---|---|
| `runtime-scope` | settling whether a diff is runtime (executable behaviour, not path prefix) or trivial |
| `discovery-probes` | every runtime review (step 4): code-shape probes, discovery-to-verdict; a command/string classifier also takes `runtime-scope`'s probe |
| `security-relevance` | auth, secrets, input sanitisation, rate limiting, audit logging, security config/dependency |
| `external-contract` | any matcher/parser over output the diff may not control (tool/CLI/API text, a fixture) |
| `contract-and-fence-probes` | a docstring/contract invariant (`Never raises`), or a stateful marker/fence parser |
| `feedback-memory` | the host supplies saved review-feedback memory |
| `context-inputs` | a repo-map / diff-impact result, context bundle, or coverage/mutation artifact is supplied |
| `coverage-ledger` | every runtime review (step 9): item-2 rows incl. 2c/2d |
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

Output order: these items, the Verdict close, the verdict line, then only an appendix `ledger-appendix` or `readiness-scorecard` pins below it. For a runtime change (per `runtime-scope`), before the verdict you MUST emit, in order:
1. Each named risk by exact name, one per line (`Risk 1: Auth Session Bypass`).
2. A coverage-ledger line per risk as pinned in `coverage-ledger`, plus the 2a/2b/2c/2d extension rows a present risk class requires.
3. `Touched files:` citing every diff path verbatim (e.g. `app/auth/session.py, tests/billing/test_checkout.py`).
4. `Change shape:` one phrase anchored to the touched files (e.g. `auth predicate + billing checkout ordering, both runtime`).
5. The verification command verbatim as a LABELED evidence line: `Evidence (command): $ <verification command> → <counts>`; no observable run: `Evidence (command): unverified, <the run that clears it>`.
6. The test counts verbatim (`X passed, Y skipped, Z failed`); none without an observable run.
7. **AC lines** when criteria were supplied, one per criterion as pinned in `acceptance-criteria` (MET ones too); else exactly `No acceptance criteria supplied — AC-coverage check skipped; verdict rests on risk coverage.`
8. **Verification-evidence lines** as pinned in `surface-verifier`, `feature-flow`, `eval-validity`: one per skill/eval change, new guard or `.ab.yaml`, and UI/API/CLI/worker/artifact flow served, named as a risk or not; each a SAFE-blocker until discharged. None applies → emit nothing for item 8.

A runtime verdict missing an applicable item is a discipline violation. Trivial and test-only diffs follow their modules; items 1, 3, 4, 5, 6 stay mandatory in every mode, item 8 where it applies.

**Verdict close (every mode).** Just before the verdict line emit `Why:`, 2-4 plain sentences tying the risks, the fresh run and each criterion to the call, then `Residual concerns:`, at least one concrete item outside every named risk's failure path, anchored to file:line or a named input (never `none`). A defect the changed path can hit, even a pre-existing one, is a named risk, never a residual. Counts appear only in items 5 and 6 and a verifier run's cite on its item-8 line. Emit only status or skip lines the root or a loaded module pins; a gate that did not apply makes no claim, so invent no line for it. BAD: `No UI/API/CLI changes: verification-evidence check skipped`. GOOD: `Why: <each risk and criterion tied to its fresh passing test>` then `Residual concerns: <unexercised path> (<file:line>)`.

## Process Flow

The Checklist is the flow.

## Red Flags - STOP and rework

| Thought | Reality |
|---|---|
| "Looks good" / "CI was green an hour ago" / "tests are slow, skip them" | None is fresh evidence; slow tests are still the verdict source. |
| "Trivial change, no need to walk through sections" | The Iron Law has no trivial-change exemption; the review can be short, but every section gets confirmation. |
| "No standards apply to this change" | Re-classify. Every change has at least one applicable classification with loaded rules. |
| "I'll list the risks AND deliver the verdict in one message" | Gate, unless a required run is missing (HARD-GATE). The user's correction on the risks shapes the verdict. |
| "I'll ask which test framework / where tests live" | Read the repo; sibling files answer that. |

## Next skill in the chain

After the verdict → `sumo-qa-finishing-qa-work` to capture the evidence and produce the PR-ready summary.

--- LOADED MODULES (fetched via sumo_qa_load_skill_context mode="module") ---

--- MODULE runtime-scope ---
# Reviewing before merge: runtime scope and the trivial-change exemption

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** deciding whether a diff is a runtime change (executable behaviour, not path prefix) or qualifies for the trivial-change exemption; always load for a diff touching hooks, scripts, CI/workflow steps, automation, or docs/static config. **Extends:** the runtime-change trigger in Verdict-format discipline and checklist step 4. The root's Iron Law, verdict gate, and output discipline apply unchanged.

## What counts as a runtime change (pinned)

**What counts as a runtime change (pinned — behaviour, not path prefix):** any diff touching **executable code with a behavioural surface** — code that *runs* and can branch, parse a command, gate an action, transform input, or persist state, producing a wrong observable result. Keyed on what the file *does*, NOT on `app/`/`src/`/`lib/` location. It includes executable code OUTSIDE those dirs — a hook under `.claude/hooks/`, a `scripts/` script, a `.claude/` automation or generated runner, a CI/release workflow shell step, a Makefile/justfile recipe, a git hook — the moment it carries branching or command logic (broadens the trigger; the source-dir paths stay runtime too). So an executable hook with command-parsing logic gets the full sweep + coverage ledger like any library module; a pure metadata bump (version string, name list) stays the inventory-drift rule's, not promoted to runtime on its own.

## Command/input-classifier probe (pinned)

**Command/input-classifier probe (pinned):** when the change adds or edits a predicate that classifies a command or string (`split()` plus token membership, `in`, `startswith`, a regex), probe it BOTH ways against the function's stated PURPOSE, not its mechanism line. False positive: the token as an argument or inside echoed or quoted text (`echo "run pytest later"`, `grep pytest log`). False negative: an equivalent form the match misses (alternate or legacy entrypoint, path-prefixed or suffixed token such as `/usr/bin/pytest`, the `python -m` form). A docstring or comment restating the naive rule describes the defect; it is not a spec that clears it. Each confirmed mis-classification is a named risk with its own ledger row. A green test feeding only the canonical command is path-matching but not at the failure mode, so that risk is UNPROVEN, never a residual concern. `Named risks: None` on a command-parsing change is the waved-through failure.

## Location claim (pinned)

**Location claim (pinned):** when the requester or PR calls a change trivial, tooling, or non-runtime because of WHERE it lives ("just a hook", "not under src", "only a script"), answer that claim in one line of the review: location does not decide runtime scope, executable behaviour does, then name the behaviour that makes THIS change runtime (e.g. the hook parses every Bash command and gates it). Running the sweep without saying so leaves the requester's rule standing for the next diff; silence is not a rebuttal.

## Trivial-change exemption (pinned)

**Trivial-change exemption (pinned):** for **genuinely non-executable diffs**, NOT "anything outside `app`/`src`/`lib`". A diff qualifies only when it touches solely docs (`docs/`, markdown), static/inert config (YAML/TOML/JSON read as data, not executed — formatter/linter ignore lists, editor config), or other files with **no executable behavioural surface**. Path is irrelevant — an executable hook/script/automation under `.claude/hooks/`, `scripts/`, or `.claude/` is a runtime change despite sitting outside the source dirs, so it does NOT qualify (run the full sweep + ledger). When the diff DOES qualify: SKIP item 2; the verification command (linter/formatter/build) IS the coverage, so mark those anchors `COVERED BY VERIFICATION`. Items 1, 3, 4, 5, 6 still required. `Touched files:` and `Change shape:` are mandatory in both modes; citing the verification command's file argument does not discharge `Touched files:`.

## Red Flags

| Thought | Reality |
|---|---|
| "This hook/script is under `.claude/hooks/` or `scripts/`, not `app/src/lib`, so it's trivial — skip the sweep" | Wrong — the runtime trigger keys on executable behaviour, not path prefix. An executable hook/script with branching or command-parsing logic is runtime wherever it lives; run the full sweep + ledger. The command-parsing defects (echo-token, flag-arity, quote-splitting) hiding in such hooks are exactly the sweep's target class. |
--- END MODULE runtime-scope ---

--- MODULE discovery-probes ---
# Reviewing before merge: adversarial discovery probes

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** the diff touches any runtime (executable) file. **Extends:** checklist step 4 (adversarial discovery pass); the root's rules apply unchanged.

## Code-shape probes (step 4)

Each probe maps a code-shape signal to the defect class to suspect:

- **Reordered statements in a write/persist path** → an intermediate state is now observable or persisted; on partial failure it can leave invalid/partial state (rollback / data-loss).
- **A removed, loosened, or inverted guard/conditional** → the path it blocked is now reachable; name what that exposes.
- **A rollback / cleanup / undo path** → does it RESTORE overwritten or pre-existing state, or does it `unlink`/clobber it? Deleting a destination that pre-existed is data loss, not rollback. Probe the whole path the diff touches, not the delta: an equivalent or tidier rewrite of a path that loses data still ships the loss.
- **A documented count/name/inventory, a version bump, or a generated artifact (manifest, lockfile, sidecar)** → search the supplied repo state repo-wide for stale copies of the old value; for generated files, was the generator re-run and the output committed? (see `inventory-drift`).
- **A file/path enumeration (`git ls-files`, glob, walk)** → does it include entries it must not — tracked-but-deleted, ignored, suffix-variant, hidden?
- **A path check compared against `cwd` or a relative root** → should it anchor to the repo/project root? cwd-relative checks are bypassable from a subdirectory (security boundary).
- **A platform/OS branch (`sys.platform`, symlink-vs-copy, path separators, spaces in paths)** → is every branch's inverse/cleanup symmetric, and is each branch actually exercised?
- **A widened type/schema (bare `dict`/`Any`/`object`, new optional union, relaxed validation)** → does it weaken a previously-constrained contract or a published/derived schema into an unconstrained branch?
- **A retry / async / timeout / teardown / shutdown path** → idempotency across retries, poison-message parking, and teardown-after-assert that can raise and error a logically-passing test (cleanup flakiness).
- **A CI / merge-gate change (required checks, admin-merge, wait conditions)** → does it wait on ALL required checks (the full matrix), or can it proceed before some finish?
- **A weakened test assertion (substring/presence-only replacing exact/structural)** → would it still pass if the contract under test were removed? (tautology — a test-only-change SAFE-blocker).

The security-relevant surface, external-output, declared-invariant, and fence-parser probes are their own modules (`security-relevance`, `external-contract`, `contract-and-fence-probes`), and a command/string classifier predicate takes the command/input-classifier probe in `runtime-scope`; load them when the diff shows that shape.

**Discovery → verdict (pinned).** A defect this sweep surfaces that the fresh tests do not cover is a NAMED RISK, mapped through the coverage ledger (step 9) as UNPROVEN (with its 2b line) when path-matching fresh tests ran, even if the guard or behaviour is missing outright, and UNCOVERED only when none ran, exactly as `coverage-ledger` defines them. It is a SAFE-blocker → NOT SAFE TO MERGE. A defect the old code shared counts too: "pre-existing" or "not worsened by this diff" never demotes it, because SAFE certifies the changed path as it will ship, not the delta. Do NOT demote a discovered latent defect to a "residual concern" under a SAFE verdict, and do NOT call it COVERED because a green test runs nearby: a green run that uses a happy fixture, ingests into an empty target, runs from the repo root, or hits only one platform/matrix leg does NOT cover the overwrite / deleted-entry / subdirectory / other-OS path, yet when path-matching fresh tests ran it stays listed in that risk's row, which makes the row UNPROVEN, never UNCOVERED. This demotion is the exact failure this pass exists to prevent.

The sweep produces 3–7 named risks, each citing a specific file + line + the domain meaning — NOT generic ("edge cases", "untested paths"). **Skip the sweep only for the trivial-change exemption in `runtime-scope`** (genuinely non-executable diffs — docs, and tool-only / static config with no runtime consumer); running it there manufactures phantom runtime risk. The sweep keys on **executable behaviour, not path prefix** (per `runtime-scope`): an executable hook/script/automation under `.claude/hooks/`, `scripts/`, or any non-`src/` location gets the same mandatory sweep as a library module.

## The two-pass split (steps 4 and 9)

**The two-pass split (pinned).** In the `/work-issue` pipeline this review is pass 1; an adversarial codex pass runs after it. The catch this skill must NOT outsource: when it can name a precision/recall risk and the technique has a catalogued failure mode, it prescribes the discriminating input ITSELF (step 9 / 2b) — it does not defer that to codex. That keeps the review whole when codex is unavailable; codex is a second independent check, never the only source of an UNPROVEN risk's discriminating input.

## Red Flags

| Thought | Reality |
|---|---|
| "I spotted a latent issue but tests are green — SAFE, with a residual note" | Sweep hits are NAMED RISKS, never residual notes: UNPROVEN (path-matching tests ran) or UNCOVERED (none ran) per `coverage-ledger`; either is NOT SAFE. |
| "The defect is pre-existing; this diff is equivalent and does not worsen it" | A sweep hit on the changed path is a named risk whether or not the old code had it; SAFE would certify the loss as it ships. |
| "I'll skip the discovery sweep — looks like a clean refactor" | The sweep is mandatory for any runtime diff: cwd bypass, rollback data-loss, schema widening, and partial CI gates hide in clean-looking diffs and pass green suites. |
--- END MODULE discovery-probes ---

--- MODULE coverage-ledger ---
# Reviewing before merge: risk coverage ledger

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** the diff touches any runtime file. **Extends:** checklist step 9 and Verdict-format items 1 and 2; the root's rules apply unchanged.

## Re-anchor, then apply the module-match rule (step 9)

**Re-anchor first.** If risks arrive as bare names (*"Auth Session Bypass, Duplicate Charge on Retry"*), locate each one's anchor file in the diff before mapping (→ `app/auth/session.py:33`). A repo-map (`sumo_qa_query_repo_map`) can locate an anchor or candidate test, which counts only once in THIS turn's fresh run with a verbatim assertion; stale paths never merge (each keeps its own `inventory-drift` 2a row).

**Module-match rule (pinned):** a risk's covering test must live under the test directory mirroring the anchor's module (`tests/<module>/` for `app/<module>/`). **Flat layout:** in a repo with flat tests, `tests/test_<file>.py` path-matches `<pkg>/<file>.py` by file stem; a different stem does not match. A `tests/billing/` test covering an `auth/session.py` risk via *"indirectly validates"* / *"implicitly covers"* is one of the forbidden hallucinated bridges; mark UNCOVERED when paths don't match. If the fresh run loaded no test for a changed file's module, every risk anchored there is UNCOVERED, however green the rest is. **Integration/e2e exception:** a `tests/integration/` or `tests/e2e/` test MAY cover any module risk, but only if the cited assertion verbatim invokes (or asserts a property of) the anchor function; "the integration suite passed" is the same hallucinated bridge. **External-contract exception (pinned):** the module-match path rule does NOT apply to an external-contract risk (step 4's external-output probe). Its evidence is REAL captured output: a real-run-traceable fixture (capture command/provenance cited) is COVERED and DISCHARGED wherever the tests live. Do NOT mark an external-contract risk UNCOVERED because its tests sit at `tests/test_x.py` instead of `tests/<module>/`.

**Worked contrast (same-domain ≠ proof).** Risk *"Duplicate Charge on Retry"*; path-matching `tests/billing/test_checkout.py::test_does_not_mark_failed_charge_paid` passes but never re-invokes `complete_checkout` after a partial failure:
- BAD: *"Covered by that test."* GOOD: `... | Fresh matching tests: <that test> | Coverage: UNPROVEN`, then `UNPROVEN escalation: Duplicate Charge on Retry | Discriminating input: retry after partial failure | Broken impl does: charges twice | Correct impl does: charges once | Required before SAFE: add a test asserting one charge to tests/billing/test_checkout.py`

## Coverage-ledger row shape (Verdict-format item 2)

A coverage-ledger line per risk in this exact shape:

`Risk: <exact name> | Anchor: <diff file:line> | Required test path: <the test dir covering this anchor — tests/<module>/ for app/<module>/, or tests/test_<file>.py in a flat layout; for an anchor outside a source dir, its mirror (tests/hooks/ for .claude/hooks/)> | Fresh matching tests: <by path alone: copy EVERY fresh-run test ID under the required path (risks sharing that path list the same IDs), plus an integration/e2e test the exception admits, even one never reaching the changed line; NONE only if none ran there> | Coverage: <tests listed: COVERED (cited test + verbatim assertion), else UNPROVEN, never UNCOVERED even if none reaches the risk; NONE: UNCOVERED>`
- **Coverage labels (pinned):** defined only here. `COVERED`: a fresh path-matching test quotes a verbatim assertion/condition at the risk's failure mode. `UNPROVEN`: path-matching fresh tests pass but none asserts at the failure mode, including one that never executes the changed branch (a happy fixture, a coverage artifact's missing line); list them, emit the 2b line (`unproven-escalation`). `UNCOVERED`: no path-matching fresh test (`Fresh matching tests: NONE`); never cite non-matching tests. The label describes the tests field, not the code: any test ID there makes the row COVERED or UNPROVEN, even when no listed test touches the risk or the behaviour is missing outright, since the fix is a new assertion beside those tests; only `NONE` is UNCOVERED. BAD: `Fresh matching tests: test_happy_path | Coverage: UNCOVERED (never tested)`. GOOD: `... | Coverage: UNPROVEN`. Name a risk by what breaks, never its test state ("X Not Tested").
- Risks whose name, anchor or failure mode involves **Retry, Duplicate, or Idempotency** require an assertion showing the operation invoked MORE THAN ONCE (two calls, a loop, or a call-count/idempotency-token assertion). **Concurrent, Race, or Lock** require overlapping execution (threads, `asyncio.gather`, or an explicit interleave). A single non-overlapping invocation, even one that raises, proves none of these: UNPROVEN (no listed test: UNCOVERED).
- `COVERED BY VERIFICATION` is for the trivial-change exemption (`runtime-scope`) only, never a runtime anchor.

- **2c. External-contract extension (pinned).** For an external-contract risk, emit this row INSTEAD of the path-keyed row:
  `External-contract anchor: <file:line> | External source: <tool/CLI/API> | Real-output evidence: <captured fixture + provenance/capture command, or NONE> | Coverage: <COVERED (real-run-traceable fixture cited) | UNPROVEN (hand-authored/no real-run traceability)>`
  A hand-authored fixture with no real-run traceability → UNPROVEN, SAFE-blocker.
- **2d. Internal/self-produced declination (pinned).** When the external-output probe resolves INTERNAL (producer test), emit this line so the true-negative is on the record:
  `External-contract axis: NOT FIRED (internal/self-produced) | Value: <verbatim self-produced value, e.g. [sumo-qa:CODE]> | Producer: <fn/module> | Consumer: <fn/module, same change> | No external source: confirmed`

Rows `2a` (`inventory-drift`) and `2b` (`unproven-escalation`) apply per their risk class.
--- END MODULE coverage-ledger ---

--- MODULE inventory-drift ---
# Reviewing before merge: documented-inventory drift

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** the diff changes a documented count, name, inventory, public-surface name, schema field, version, or a generated artifact (manifest, lockfile, sidecar). **Extends:** checklist step 9 (documented-inventory drift rule) and Verdict-format item 2a. The root's Iron Law, verdict gate, and output discipline apply unchanged.

## Documented-inventory drift rule (step 9)

**Documented-inventory drift rule (pinned).** When the diff changes a documented count, inventory, public-surface name, or schema field — the documented-inventory-drift probe — the obvious doc the diff touches is rarely the only stale spot. Before the verdict, search the supplied ground-truth context (any `rg`/grep listing, "Other repo state" section, etc.) for the OLD value; each path it surfaces is a separate UNCOVERED anchor that needs its own ledger row (format in this module's 2a row). Generic guidance, anchoring only on the obvious doc, or naming one stale path is UNCOVERED. If the ground-truth context names zero stale paths, say so explicitly; do NOT silently default to "covered".

## Inventory-drift ledger rows (Verdict-format item 2a)

- **2a. Inventory-drift extension.** For an inventory-drift risk (see step 9), the item-2 risk row (`coverage-ledger`) is not sufficient. Emit ONE additional ledger row per stale path the supplied ground-truth context names — never crammed into one row or shoved into the risk row's `Required update:` field. Each row uses this exact shape (the `<old> → <new>` value pair must appear inline):
  `Inventory drift anchor: <path>:<line> (<old> → <new>) | Required update: this file | Diff updated it: <YES if the diff touches this exact path; NO otherwise> | Coverage: <COVERED if the diff updates this exact file; UNCOVERED if it does not>`
  Each UNCOVERED row is a SAFE-blocker. The verdict line must name every UNCOVERED stale path explicitly — not "documentation needs updating". Zero stale paths supplied → emit `Inventory drift anchor: NONE supplied | Coverage: N/A` rather than silently defaulting to covered.

  **Worked contrast (one row per stale path, value pair inline).** Two stale paths surfaced (`docs/INSTALL.md:17`, `.github/ISSUE_TEMPLATE/qa_output_quality.yml:22`), old `28` → new `29`:
  - BAD (single crammed row, no value pair): `Risk: Documented-inventory drift | Anchor: README.md:42 | Required update: docs/INSTALL.md, .github/ISSUE_TEMPLATE/qa_output_quality.yml | Coverage: UNCOVERED` — collapses both paths into one row, anchors on the obvious doc, omits `(28 → 29)`. SHAPE FAIL.
  - GOOD (one row per stale path, value pair inline):
    `Inventory drift anchor: docs/INSTALL.md:17 (28 → 29) | Required update: this file | Diff updated it: NO | Coverage: UNCOVERED`
    `Inventory drift anchor: .github/ISSUE_TEMPLATE/qa_output_quality.yml:22 (28 → 29) | Required update: this file | Diff updated it: NO | Coverage: UNCOVERED`
--- END MODULE inventory-drift ---

--- MODULE surface-verifier ---
# Reviewing before merge: surface-specific verifier evidence

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** the changed surface has a repo-specific verifier (a promptfoo eval, fixture/parser corpus, smoke probe, contract test, integration check, generated-artifact verification), or sibling PRs co-edit one surface. Always load for a `skills/*/SKILL.md` or `tests/evals/promptfoo/*.yaml` change. **Extends:** checklist step 9 (verification-evidence discipline, check i), Verdict-format item 8, and step 10(e). The root's Iron Law, verdict gate, and output discipline apply unchanged.

## Verification-evidence discipline (step 9)

**Verification-evidence discipline (pinned).** A green suite + green CI + a green per-file/codex review is NOT evidence that the *changed behaviour* was actually exercised. One discipline, four checks — each surfaces *missing relevant verification* as a SAFE-blocker, never demoted to a residual note, and never cleared by weakening the verifier (only by running it correctly and correcting the behaviour it catches):

- **(i) Surface-specific verifier ran (right runtime/env/scope/tree).** When the changed surface has a relevant repo-specific verifier — a promptfoo eval, fixture/parser corpus, smoke probe, contract test, integration check, generated-artifact verification, or similar targeted command — SAFE requires that verifier to have RUN, and run correctly. **Eval-surface skill changes (a `skills/*/SKILL.md` or `tests/evals/promptfoo/*.yaml` edit) KEEP promptfoo as the REQUIRED verifier:** the relevant config must have run through **the Claude eval gate** (promptfoo on the Claude pair via `run-eval.sh`, `npm run eval` or a bare `promptfoo eval -c <config>`, since every config pins the Claude candidate and judge; no API key) before SAFE. On backend, only a run on another backend (`SUMO_EVAL_BACKEND=local`, an overridden provider) is wrong context; a recorded run that does not restate its backend counts as a Claude-gate run, so never block SAFE on it or ask for the backend. **Name that eval VERBATIM** — copy its exact config path from the supplied diff/context character-for-character (e.g. `tests/evals/promptfoo/skill-<area>-<feature>.yaml`), never abbreviating, truncating to a stem, or paraphrasing it; if the context names the eval you MUST reproduce that exact filename in the verdict. For any other surface, name the repo-specific verifier that observes the changed behaviour and judge from the record whether it ran with the right **runtime / env / backend or key / fixture set / generated-artifact state / scope / tree** — wrong runtime, wrong backend, stale fixtures, or wrong scope is the SAME as not-run. Missing or wrong-context verifier evidence → **UNVERIFIED (surface verifier)**, a SAFE-blocker. **A missing run is a verdict, not a question:** if you can run the verifier this turn, run it and judge its output; otherwise judge the record you were given. A run you only plan, announce, or ask the user to perform is not in it, and the HARD-GATE never means holding the verdict for one. So never ask whether the backend, key or env is set up, never ask the user to run it and paste the output, and never wait for a reply: mark it UNVERIFIED (surface verifier), deliver `NOT SAFE TO MERGE` this turn, and name the run that clears it. A reply that ends on a question or request in place of the verdict fails the review. **Sibling/combined-tree rule:** when sibling PRs co-edit ONE behaviour surface (the same SKILL.md, parser, schema), per-branch-green is NOT combined-green — require the verifier to have run on the **COMBINED tree** before the set is SAFE. Graceful fallback: if the diff names no identifiable verifier surface, say so in one line (status **N/A (no identifiable verifier surface)** — non-blocking, NOT a SAFE-blocker) and rest the verdict on risk + feature-flow coverage.

## Surface-verifier line (Verdict-format item 8)

**Verification-evidence lines (step 9's verification-evidence discipline).** Emit the lines that apply to this diff, each a SAFE-blocker when its status is not DISCHARGED:

- Surface verifier (always, on a runtime/skill/eval change): `Surface verifier: <verifier — the eval's FULL config path quoted verbatim from the diff/context, e.g. tests/evals/promptfoo/skill-<area>-<feature>.yaml (never a truncated stem) | NONE identifiable> | Ran: <YES (runtime/env/backend/scope/tree cited; for eval-surface, the Claude eval gate) | NO | WRONG CONTEXT (which)> | Combined-tree (if sibling PRs co-edit): <YES | NO | N/A> | Status: <DISCHARGED | N/A (no identifiable verifier surface — non-blocking) | UNVERIFIED (surface verifier) — SAFE-blocker>`

## Red Flags

| Thought | Reality |
|---|---|
| "Per-file review, codex, and CI are all green — SAFE" | None of those exercise the changed behaviour. If the surface has a relevant verifier (promptfoo eval, fixture/parser corpus, contract test, smoke probe) that did NOT run — or ran with the wrong runtime/env/backend/scope/tree — that is UNVERIFIED (surface verifier), a SAFE-blocker. For an eval-surface skill change, promptfoo must have run through the Claude eval gate (any promptfoo run of the config on the Claude pair). |
| "I can't run the verifier here, so I'll ask the user to run it and paste the output, then decide" | If you can run it this turn, run it and judge its output. A run you cannot do or see is UNVERIFIED (surface verifier): name the run that clears it and deliver NOT SAFE TO MERGE this turn as the verdict line (only a pinned appendix follows), never a held verdict or a question. |
| "Each sibling PR's eval passed in isolation — SAFE to merge the set" | Per-branch-green ≠ combined-green when siblings co-edit one surface (the same SKILL.md/parser/schema). Require the verifier to have run on the COMBINED tree before SAFE — the larger merged surface can over-fire (3/3 per-branch → 1/3 combined). |
--- END MODULE surface-verifier ---

--- MODULE discharged-check ---
# Reviewing before merge: discharged-check discipline (anti-over-fire)

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** any verification-evidence check (`surface-verifier`, `feature-flow`, `eval-validity`) or an external-contract axis is DISCHARGED and the verdict is SAFE-eligible on that check. **Extends:** checklist step 9 (verification-evidence discipline) and step 10. The root's Iron Law, verdict gate, and output discipline apply unchanged.

## Discharged-check discipline (step 9)

**Discharged-check discipline (anti-over-fire, pinned).** Each verification-evidence check (`surface-verifier`, `feature-flow`, `eval-validity`) has a must-flag side (the SAFE-blocker) AND a discharged/true-negative side. When a check is DISCHARGED — the verifier ran correctly, the flow was exercised end-to-end, the guard's both-direction seed passes, or the A/B control is load-bearing — the verdict rests on the diff's ACTUAL named risks + coverage, NOT on a manufactured extra blocker. Do NOT raise the bar above the seed's own scope or invent speculative residual blockers to withhold SAFE on a true-negative; the larger discovery/UNPROVEN surface over-pressuring a genuinely-discharged check is the same combined-SKILL.md over-fire the #263 anti-over-discovery clause in `external-contract` prevents. Speculative variant-hunting on a discharged check is over-trigger; only a risk the diff's own code path can actually hit is fair to name. **Plain (non-A/B) verifier already discharged → never manufacture an A/B/2b blocker:** when the surface's *plain* promptfoo eval has RUN and PASSED on the combined tree (the Claude eval gate) and the supplied context says it covers the risk, that risk is COVERED — do NOT route it through check (iv) (which fires ONLY when the diff ships a new/changed `.ab.yaml` A/B control), do NOT downgrade it to UNPROVEN to demand a 2b discriminating input, and do NOT demand a redundant re-run. **Residuals are LISTED under SAFE, never blocking, on a discharged check (pinned):** when the feature flow is VERIFIED end-to-end this turn AND the risk gate is closed (the context names the only risk(s) and all are covered), a concern the diff's own code path does NOT exercise — speculative Unicode/encoding, atomic/partial-write, parent-dir creation, any "nice to also test" nuance the change doesn't depend on — is a RESIDUAL you LIST in `Residual concerns:` on a `SAFE TO MERGE` review; it MUST NOT flip the verdict. Per the root's Verdict close that list sits just before the verdict line; listing one NEVER demotes SAFE to NOT SAFE. Only an UNCOVERED/UNPROVEN named risk, or a risk anchored to a line the diff actually changed, blocks.
--- END MODULE discharged-check ---
