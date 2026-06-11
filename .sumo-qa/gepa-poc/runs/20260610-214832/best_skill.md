---
name: sumo-qa-reviewing-before-merge
description: Use when the user asks "review my changes" / "is this safe to merge" / "what could break" / "code review please" / "anything I missed in this diff". Reads the diff and the changed files first, runs an adversarial discovery sweep that names each defect to a specific file:line, runs tests, then delivers the verdict section by section with confirmation gates. Refuses to claim safe-to-merge without fresh verification evidence.
---

# Reviewing before merge

Decide whether a change is safe to ship by walking the review one section at a time: explore the diff, surface what was found, name the risks **to exact file:line**, run the verification, deliver the verdict. The user holds product context the diff can't reveal (deliberate behaviour change? consumer external?) — surface it with questions, don't assume it.

**Announce at start:** *"Reviewing the diff against fresh test evidence."*

## Output discipline (mandatory)

Inherits `using-sumo-qa`: **output discipline** (never surface internal taxonomy labels or raw change-rule YAML keys — say *"behaviour change in pricing"* / *"the documented-inventory rule"*, never the key), **output economy** (findings not framing; no preamble; one question per turn; no closing pleasantries), knowledge-authority hierarchy, internal scaffolding stays internal, specialty-tool fit.

<HARD-GATE>
Do NOT deliver a verdict before running tests THIS turn. "CI was green earlier" is not fresh evidence. The verdict's only source is the suite running RIGHT NOW against THIS diff, with actual pass/fail counts surfaced.
</HARD-GATE>

## The Iron Law

**NEVER CLAIM SAFE-TO-MERGE WITHOUT FRESH VERIFICATION EVIDENCE.** "All tests pass" is necessary but not sufficient — every named risk must also have a fresh test exercising its exact failure path.

## THE SHAPE BAR — how to name a discovery-sweep hit (read first, this is the #1 failure)

The most common review failure is naming a **generic** risk instead of the **specific seeded defect**. A risk that says "possible edge cases in path enumeration", "untested paths", or "unwanted items might be included" is an automatic SHAPE FAIL even when the probe category is right. Every named risk MUST carry all three of:

1. **The named defect class** — the catalogued class in play (e.g. *rollback data-loss*, *cleanup-time flakiness*, *platform-branch asymmetry*, *tautological assertion*, *stale-entry-from-deleted-path*, *contract-vs-signature contradiction*), not a vague category.
2. **The exact anchor** — the precise `file:line` of the defective construct in THIS diff (the `unlink` line, the `proc.wait(timeout=5)` teardown, the changed `assert`, the docstring line). Not the file in general — the line.
3. **The concrete consequence** — what observably breaks, in domain terms ("deletes pre-existing user content → data loss", "teardown raises on timeout → errors a logically-passing test").

Template: **`<named defect class> at <file:line> — <concrete observable failure>`.** Missing any of the three = SHAPE FAIL.

### Seeded-defect catalogue (map the code-shape signal → named class → what to say)

When the diff matches a row, that row's named class + consequence is the risk you must produce, anchored to the line.

| Code-shape signal in the diff | Named defect class | What to state (anchored to the line) |
|---|---|---|
| `git ls-files` / glob / `os.walk` / dir-enumeration feeding a map/index | **stale-entry-from-deleted-path** | the enumeration includes entries it must not — a **tracked-but-deleted** path (also ignored / suffix-variant / hidden) → a **stale repo-map node / phantom index entry** that points at a file no longer present |
| rollback / cleanup / undo / except-branch that `unlink`s / `rmtree`s / overwrites a destination | **rollback data-loss** | the path **deletes or clobbers a destination that pre-existed** instead of restoring it → **user/pre-existing content is lost**. Rollback must RESTORE prior state, not remove it |
| teardown / `finally` / fixture-cleanup after the asserts that calls `proc.wait(timeout=…)`, `.close()`, `.kill()`, join | **cleanup-time flakiness** | the **unguarded teardown can raise** (timeout / already-closed) AFTER assertions passed → **errors a logically-passing test**. Anchor the exact unguarded call (e.g. `proc.wait(timeout=5)`) |
| platform/OS branch (`sys.platform`, symlink-vs-copytree, sep, spaces) where install and uninstall differ | **platform-branch asymmetry** | install **copytree-copies on Windows** but uninstall **removes only the symlink** → **copied dirs are orphaned**; the branch's inverse is not symmetric (and a branch may never be exercised) |
| test assertion weakened to substring / presence-only, replacing exact/structural | **tautological (non-discriminating) assertion** | the assertion **still passes if the contract under test is removed** → it no longer proves conformance. SAFE-blocker on a test_change |
| docstring/contract invariant (`Never raises`, "always returns an error envelope", total-function) vs the actual signature | **contract-vs-signature contradiction** | the "never raises / always-envelope" promise is **violated by a REQUIRED arg with no default** (for an MCP-registered fn the schema layer rejects an omitted required arg as a **raise BEFORE** the body's envelope branches run), a bare `raise`, or an un-envelope'd error path — for the very "invalid input" the contract promises to absorb. Anchor the docstring line vs the signature/raise line |
| matcher/parser over EXTERNAL output (regex/string on subprocess/CLI/API/foreign-file) | **external-contract dependency** (apply the producer test, step 4) | correctness depends on the REAL output format of a tool the diff doesn't control; a green matcher proves LOGIC, not that the marker matches reality |

This table is the load-bearing knowledge of this skill — apply it BEFORE writing any risk, and name the row's class verbatim.

## When to Use

Triggers: *"review my changes"*, *"is this safe to merge"*, *"what could break"*, *"code review please"*, *"anything I missed in this diff"*. `sumo-qa-deciding-approach` routes here for `verify-existing` (config-only/trivial); larger reviews run here with broader scope.

## Checklist (work in order; steps 1–4 are AI-only homework, the user's confirmation gates step 5 onward)

1. **Read the diff via the host's git tools** *(no question)* — `git diff` / `--staged` / `<base>...HEAD` per intent. Capture file list + line counts.

   **Repo-map accelerator (optional).** `sumo_qa_analyze_diff_impact` scans live and persists a repo-map when none exists; returns changed/affected nodes, likely tests, and the risk surface (changed sources with no mapped test). It is **NOT coverage evidence** — `related_tests` are run-candidates, `risk_surface` candidate UNCOVERED anchors. If `probable_mapping_gap` is true (tests exist but the map found no links — CamelCase/Kotlin), the risk surface is a *mapping* gap, confirm via the test tree. Never blocks; never replaces the fresh run.

   **Context bundle (optional input).** If the host hands a context bundle (issue/PR summary, changed files, test/CI evidence with source+freshness, user constraints), PREFER it as a head-start: read it via `sumo_qa_format_context_bundle`, passing the live local head as `local_head_sha`. Three rules: (a) **stale/unknown evidence is not fresh evidence** — any field in `untrustworthy_evidence_fields` (freshness `stale`/`unknown`/`absent`) is input only; re-run the suite this turn. (b) **Call out conflicts** — on a `conflict` (bundle `head_sha` ≠ live head), say so and trust the live diff. (c) **The bundle never replaces the diff read** (steps 1–2). No bundle → inspect the repo directly.

2. **Read the actual changed files** *(no question)* — not just hunks; surrounding code matters. For each changed file, identify the public surface that moved.

3. **Classify and load standards** *(no question)* — `sumo_qa_load_classifications()`, infer classification(s), then `sumo_qa_load_standards(...)` and `sumo_qa_load_rules(...)`. Note which loaded rules apply. ("No standards apply" is wrong — re-classify; every change has ≥1.)

4. **Adversarial discovery pass → 3–7 named risks anchored to file:line** *(no question)* — Codex-class defects ship past green suites because nobody swept the diff. Sweep the diff against the catalogue above; every hit becomes a named risk meeting **THE SHAPE BAR**.

   **First, branch on the diff shape:**
   - **Test files ONLY** (no `app/`/`src/`/`lib/` runtime file — a `test_change`): the runtime probes mostly don't apply; run the **test-only-diff probe (step 9)** — the central risk is whether each new/changed test can actually fail (tautology / non-discriminating assertion / matcher under-coverage / unproven regression). A green suite is NOT a pass — a tautological assertion passes against any impl. Those findings ARE this turn's named risks.
   - **Genuinely non-executable** (docs / markdown / inert static config read as data — formatter ignore-lists, editor config, YAML/TOML/JSON not executed): the **trivial-change exemption** applies. Do NOT run the runtime sweep; running it manufactures phantom runtime risk — the **negative-control failure mode** these reviews must avoid. Stay lightweight (see Verdict-format exemption). Path is irrelevant to this — an executable hook/script/automation under `.claude/hooks/`, `scripts/`, `.claude/` does NOT qualify; it gets the full sweep.
   - Otherwise: run the full runtime sweep.

   The sweep keys on **executable behaviour, not path prefix**: an executable hook/script under `.claude/hooks/`, `scripts/`, or any non-`src/` location gets the same mandatory sweep as a library module (its command-parsing defects — echo-token, flag-arity, quote-splitting — are exactly the target class).

   Probes beyond the catalogue rows (same SHAPE bar — name + anchor + consequence):
   - **Reordered statements in a write/persist path** → an intermediate state is now observable/persisted; partial failure leaves invalid/partial state (rollback / data-loss).
   - **Removed/loosened/inverted guard or conditional** → the blocked path is now reachable; name what it exposes.
   - **Documented count/name/inventory, version bump, or generated artifact** → search the supplied repo state repo-wide for stale copies of the old value; for generated files, was the generator re-run and committed? (documented-inventory / generated-artifact drift — step 9).
   - **Path check against `cwd` or a relative root** → should it anchor to repo/project root? cwd-relative checks are bypassable from a subdirectory (security boundary).
   - **Widened type/schema** (bare `dict`/`Any`/`object`, new optional union, relaxed validation) → does it weaken a constrained contract or a published/derived schema?
   - **Retry / async / timeout / teardown / shutdown** → idempotency across retries, poison-message parking, teardown-after-assert that can raise (cleanup flakiness).
   - **CI / merge-gate change** → does it wait on ALL required checks (the full matrix) or proceed before some finish?
   - **Stateful character-scanning parser tracking an open/close marker** (fenced-code-block / heading indexer, bracket/quote matcher, tokenizer) → does its close-test match the FULL opening marker or only the marker CHARACTER? Char-only fence tracking is the tell that **length is not tracked** — a `` ``` `` close wrongly closes a `` ```` `` (4-tick) outer fence, so `## heading`-looking lines inside the block get indexed (or real headings after it get skipped). "Verified correct" requires constructing the **discriminating input**: a **variable-length nested fence — a 4-tick fence wrapping a 3-tick block** (length-aware keeps the outer open across the inner `` ``` ``; char-only closes early). Until that input is built and exercised the parser is UNPROVEN — never COVERED from reading that the code "compares the fence char". (CommonMark edge cases that do NOT discriminate the char-stored bug, so don't cite them as the discriminator: `~~~`-vs-backtick, unclosed-at-EOF. Cases that DO test the indexer: a ≥4-space-indented close-looking line stays as block CONTENT per §4.5 ex.137 — the indexer must still skip it; trailing non-space content on a close line is not a valid close.)

   **Discovery → verdict (pinned).** A defect this sweep surfaces that the fresh tests don't cover is a NAMED RISK, mapped UNCOVERED through the ledger (step 9) → **NOT SAFE TO MERGE**. Do NOT demote a discovered latent defect to a "residual concern" under SAFE, and do NOT call it covered because a green test runs nearby — a green run on a happy fixture / empty target / repo root / single matrix leg does NOT cover the overwrite / deleted-entry / subdirectory / other-OS path. This demotion is the exact failure this pass exists to prevent.

5. **Confirm scope, only for AMBIGUOUS parts** — short paragraph naming files, line counts, what the change does in domain terms. Then ONE focused question for what the diff couldn't reveal (e.g. *"is this consumer external — do we coordinate the contract bump?"*). Nothing ambiguous → skip the question. Don't ask which framework / where tests live — read the repo.

6. **Present named risks, ask after** — present the 3–7 risks meeting THE SHAPE BAR:
   *"R1: `api/refund.py:47` — new error path returns 500 not 422 for invalid-amount; consumer X depends on 4xx-vs-5xx for retry.*
   *R2: `domain/Refund.kt:18` — idempotency-key derivation changed; double-refund possible on retry of a partially-completed call."*

   **Technique-keyed failure-mode hints (pinned).** When a risk's failure mode maps to a named black-box technique, ground it in that technique's catalogued failure modes (`sumo_qa_load_techniques`) and name the specific one. Precision/recall on a keyword/substring matcher → *equivalence partitioning* (substring/token confusion: `unlocked` matches `locked`, `concurrency` matches `currency`; overlapping classes; missing empty-input class). Limit/threshold/off-by-one → *boundary value analysis* (both sides, just-inside-vs-just-outside, `<` vs `<=`). Multi-condition business rule → *decision tables* (missing rule row / absent default arm). If the technique isn't in the loaded catalogue, say so — don't confabulate.

   Ask: *"do these match how you'd describe the risks? add / remove / refine?"* Wait.

7. **Run the test suite — show actual output** — host's runner. Surface total/passed/failed/skipped/duration; name failures. Do NOT proceed to verdict on partial output.

8. **Run targeted tests around changed files** — e.g. `pytest tests/test_<changed_module>.py -v`. Confirm closest neighbours stay green; surface the count.

9. **Map risk coverage** — for each named risk, cite the fresh test that demonstrably exercises that exact failure path (file + fully-qualified test + the verbatim assertion/condition), or mark UNPROVEN / UNCOVERED. Never infer coverage from a shared name or domain. A risk with no covering test is a SAFE-blocker.

   **Re-anchor first.** Bare-name risks (*"Auth Session Bypass"*) → locate each anchor file in the diff before mapping (*Auth Session Bypass* → `app/auth/session.py:33`). Without an anchor you'll hallucinate coverage. `sumo_qa_query_repo_map` helps locate a runtime anchor/candidate test, but a test counts only once in THIS turn's fresh run with a verbatim assertion.

   **Module-match rule (pinned):** a risk under `app/auth/` requires a covering test under `tests/auth/`; `app/billing/` requires `tests/billing/`. A `tests/billing/` test cannot cover an `auth/session.py` risk via *"indirectly/implicitly covers"* — forbidden hallucinated bridges; mark UNCOVERED when paths don't match. **Integration/e2e exception:** `tests/integration/` or `tests/e2e/` MAY cover any module risk, but only if the cited assertion verbatim invokes (or asserts a property of) the anchor function. **External-contract exception:** the path rule does NOT apply to an external-contract risk — its evidence is REAL captured output, not a `tests/<module>/` test; a real-run-traceable fixture is COVERED wherever the tests sit.

   **Worked contrast (same-domain ≠ proof).** Risk *"Duplicate Charge on Retry"* + passing `tests/billing/test_checkout.py::test_does_not_mark_failed_charge_paid`:
   - BAD: *"Covered."* — it asserts one failed charge isn't marked paid; never re-invokes `complete_checkout` after a partial failure, so it cannot prove retry idempotency.
   - GOOD: *"UNCOVERED. No fresh test re-invokes `complete_checkout` after partial failure or asserts charge-at-most-once across retries. SAFE-blocker."*

   **Producer test (apply before raising any external-contract risk).** The external-contract axis fires ONLY when the value is produced by something the diff does NOT control (another tool/CLI/subprocess/API/foreign file). If the SAME change (or host) is its sole producer — the code serialises its own envelope/marker and parses it back, a round-trip over a self-format — it is INTERNAL: raise no external-contract risk and demand no real-run capture. When the producer test resolves INTERNAL you MUST say so explicitly (2d row): quote the self-produced value verbatim (e.g. `[sumo-qa:CODE]`), name the sole producer + same-module consumer, conclude the axis does NOT fire.

   **External-contract rule (pinned).** A green matcher proves LOGIC, not that its INPUT matches reality. A hand-authored/guessed fixture with no real-run traceability is UNPROVEN — never SAFE on the green suite alone. But when the fixture IS traceable to a REAL or minimal run (captured output + capture command/provenance cited), the real output IS the evidence: mark COVERED and DISCHARGED, SAFE-eligible. **Anti-over-discovery:** once discharged, do NOT manufacture speculative output-format-variant risks (locale/encoding/emoji marker variants, fail-open-on-parse) the diff doesn't depend on, and do NOT demand fresh captures for them. A genuine parsing risk the diff's own code path can hit is still fair to name.

   **Test-only-diff probe (pinned).** When the diff is test files ONLY, the runtime ledger has no anchor; the risk becomes *does each new/changed test discriminate broken from fixed?* Reuse (don't restate) the tautology / setup-discriminator / expected-value-derivation framing from `sumo-qa-implementing-with-tdd` step 3. Plus a **matcher-coverage check**: name each test's oracle/matcher, enumerate the input *shapes* it must catch, confirm each has a discriminating case — a matcher that silently under-matches a shape (singular-vs-plural false-negative class) is a hole even when present assertions are sound. A new test whose assertion restates the production code or passes against a broken impl (a tautology re-deriving "expected" from the SUT — `result = add(2,3); assert add(2,3) == result`; the expected value must be derived INDEPENDENTLY of the SUT), or a regression/contract test with no evidence it fails on the pre-fix/drift state, is a SAFE-blocker → `NEEDS WORK`/`NOT SAFE TO MERGE`, naming the vacuous assertion.

   **Documented-inventory drift rule (pinned).** When the diff changes a documented count, inventory, public-surface name, or schema field, the obvious doc it touches is rarely the only stale spot. Before the verdict, search the supplied ground-truth context (any `rg`/grep listing, "Other repo state" section) for the OLD value; each path is a separate UNCOVERED anchor with its own ledger row (2a). Generic guidance, or naming one stale path, is UNCOVERED. Zero stale paths surfaced → say so explicitly; do NOT default to "covered". (`sumo_qa_query_repo_map` does NOT consolidate drift — each stale path gets its own 2a row.)

   **Acceptance-criteria coverage (pinned).** "Correct code" and "the *right* code" are distinct — a green, fully risk-covered diff can still fail to deliver what the ticket asked. When the host supplies acceptance criteria (user pastes them, or a context bundle carries them), check EACH against the diff + this turn's fresh evidence. **Surfacing every supplied criterion is MANDATORY, not verdict-conditional** — emit one AC line per criterion with its classification AND cited anchor, including MET ones on an all-MET SAFE path. Classify:
   - **MET** — a diff change AND a fresh path-matching test assert the criterion's *stated* behaviour; cite file + fully-qualified test + verbatim assertion. Prove what the criterion *says*, not every downstream nuance — if it says "returns remaining quota" and a fresh test asserts the endpoint returns `remaining`, that is MET; a separately-unproven nuance (per-token discrimination) is a named *risk*, NOT an AC downgrade. Don't raise the bar above the criterion's wording.
   - **UNMET** — nothing satisfies it, or it's contradicted; a SAFE-blocker.
   - **UNVERIFIED** — the implementing change exists but NO fresh test exercises the criterion's own behaviour this turn (only an adjacent/lower-level unit ran). For "the behaviour was never driven", NOT for "asserted but one nuance unproven". SAFE-blocker until proven.

   Host-neutral and host-supplied: NEVER fetch an issue, call `gh`, or hit a tracker — the host identifies criteria, you check/cite them. **Graceful fallback:** no criteria supplied → *"No acceptance criteria supplied — AC-coverage check skipped; verdict rests on risk coverage."* Never fabricate, never silently drop.

   **Verification-evidence discipline (pinned).** A green suite + green CI + green per-file/codex review is NOT evidence the *changed behaviour* ran. One discipline, four checks; each surfaces missing verification as a SAFE-blocker, never demoted, never cleared by weakening the verifier:
   - **(i) Surface-specific verifier ran (right runtime/env/scope/tree).** When the surface has a relevant repo-specific verifier (promptfoo eval, fixture/parser corpus, smoke probe, contract test, integration check, generated-artifact verification), SAFE requires it to have RUN correctly. **Eval-surface skill changes (`skills/*/SKILL.md` or `tests/evals/promptfoo/*.yaml`) keep promptfoo REQUIRED** — run with **Node 24 + the configured OpenAI key** before SAFE, and **name the eval VERBATIM** (copy its exact config path character-for-character, never a truncated stem). Other surface → ASK which verifier observes the behaviour and whether it ran with the right runtime/env/key/fixtures/scope/tree (wrong context = not-run). Missing/wrong-context → **UNVERIFIED (surface verifier)**, SAFE-blocker. **Sibling/combined-tree:** when sibling PRs co-edit ONE surface, per-branch-green ≠ combined-green — require the verifier on the COMBINED tree first. No identifiable verifier surface → say so (**N/A**, non-blocking).
   - **(ii) Primary feature flow exercised end-to-end.** Even with NO AC, a change whose primary FEATURE FLOW (closest realistic UI/API/CLI/worker/artifact path) was never driven this turn — only a lower-level unit ran — is **UNVERIFIED (feature flow)**, SAFE-blocker. Don't over-fire when a fresh path-matching test genuinely drives it (then VERIFIED). **Defers to the AC rule:** if every supplied AC is MET by a fresh path-matching test, the flow is VERIFIED through those AC tests — don't re-demand a higher-level test than the criterion's wording.
   - **(iii) A newly-added regression guard's eval exercises BOTH directions.** When the change ADDS a guard / "do X but NOT Y" rule, its eval must carry a discriminating **true-negative / over-trigger** seed a guard-violating reviewer would FAIL — not only the positive direction. One-sided → **UNCOVERED**, SAFE-blocker. Once the discriminating seed IS present → **COVERED**, not a blocker; don't demand more directions.
   - **(iv) An eval-driven skill change's A/B control is structurally load-bearing.** When a SKILL.md edit ships a new/changed promptfoo A/B "load-bearing" eval, the pre-edit (A0) leg must be structurally INCAPABLE of passing via pre-existing rules: the rubric PASS must require something ONLY the new text produces. A single A0-FAIL is **variance, not isolation**. The required isolation move is to **NAME the specific pre-existing rule** the A0 body already carries that could reach PASS without the new text; lead with that named rule, not a flakiness note. **Apply 2b to the RUBRIC:** any input the rubric credits as "discriminating" must actually discriminate the seed's defect — crediting a non-discriminating input is a SAFE-blocker. Genuinely incapable A0 + only-discriminating rubric → **LOAD-BEARING**, SAFE-eligible.

   **Discharged-check discipline (anti-over-fire, pinned).** Each check has a must-flag side AND a discharged/true-negative side. When a check is DISCHARGED (verifier ran correctly / flow exercised end-to-end / both-direction guard seed passes / A/B load-bearing), the verdict rests on the diff's ACTUAL named risks + coverage — NOT a manufactured extra blocker. Don't raise the bar above the seed's scope or invent speculative residual blockers on a true-negative. **Plain (non-A/B) verifier discharged → never manufacture an A/B/2b blocker:** when the surface's plain promptfoo eval RAN and PASSED on the combined tree (Node 24 + key) and the context says it covers the risk, that risk is COVERED — don't route it through check (iv), don't downgrade to UNPROVEN to demand a 2b input, don't demand a redundant re-run. **Residuals are LISTED under SAFE, never blocking, on a discharged check:** when the feature flow is VERIFIED end-to-end AND the risk gate is closed, a concern the diff's own code path does NOT exercise (speculative Unicode/encoding, atomic/partial-write, parent-dir creation, any "nice to also test" nuance) is a RESIDUAL listed under `SAFE TO MERGE`; it MUST NOT flip the verdict. Only an UNCOVERED/UNPROVEN named risk, or a risk anchored to a line the diff actually changed, blocks.

### Review-feedback memory (advisory hints only)

A team can promote a recurring lesson into an explicit, user-confirmed local memory (`sumo_qa_capture_review_feedback`, #92 user-pack `feedback/`). Consult it as a HINT that sharpens the discovery sweep — never a blocker or authority. Apply a stored lesson only when its `trigger_signal` matches THIS diff's change shape; surface it as its own labelled line QUOTING `trigger_signal` and `recommended_probe` VERBATIM: *"advisory hint from saved review feedback (trigger: <trigger_signal>): <recommended_probe>"*. A matched hint becomes an ordinary named risk through the ledger; it never overrides a canonical classification or change-rule. Absent/empty memory → *"no saved review feedback supplied — advisory-hint check skipped"* and run the normal sweep; never invent or recall a hint. Do NOT auto-capture from this review.

### Verdict-format discipline

The verdict line is the LAST line.

**What counts as a runtime change (behaviour, not path prefix):** any diff touching **executable code with a behavioural surface** — code that runs and can branch, parse a command, gate an action, transform input, or persist state. Keyed on what the file *does*, not on `app/`/`src/`/`lib/` location: a hook under `.claude/hooks/`, a `scripts/` script, a `.claude/` automation/runner, a CI/release workflow shell step, a Makefile/justfile recipe, a git hook — runtime the moment it carries branching or command logic. A pure metadata bump (version string, name list) stays the inventory-drift rule's, not runtime.

For a runtime change, before the verdict you MUST emit, in order:
1. Each named risk by exact name, one per line (`Risk 1: Auth Session Bypass`).
2. A coverage-ledger line per risk:
   `Risk: <exact name> | Anchor: <diff file:line> | Required test path: <tests/<module>/ for app/<module>/; for an executable anchor outside a source dir, the sibling test dir — tests/hooks/ for .claude/hooks/, tests/scripts/ for scripts/> | Fresh matching tests: <fresh `<file>::<test>` IDs whose path starts with the required path, or NONE> | Coverage: <COVERED (cited test + verbatim assertion) | UNPROVEN | UNCOVERED>`
   - `COVERED` only when a fresh path-matching test quotes a verbatim assertion exercising the failure mode — path prefix is necessary, not sufficient.
   - Names/anchors/failure-modes containing **Retry, Duplicate, or Idempotency** require an assertion showing the operation invoked MORE THAN ONCE (two calls / loop / call-count or idempotency-token assertion across attempts). **Concurrent, Race, or Lock** require overlapping execution (threading / `asyncio.gather` / `concurrent.futures` / explicit interleave). A single non-overlapping invocation — even one that raises — proves none of these; mark UNPROVEN.
   - `Fresh matching tests: NONE` → UNCOVERED; never cite non-matching tests as indirect evidence.
   - `COVERED BY VERIFICATION` is reserved for docs/config-only anchors; runtime anchors MUST NOT use it.
   - **2a. Inventory-drift extension.** Emit ONE additional row per stale path the ground-truth context names (never crammed into one row):
     `Inventory drift anchor: <path>:<line> (<old> → <new>) | Required update: this file | Diff updated it: <YES if the diff touches this exact path; NO> | Coverage: <COVERED if the diff updates this exact file; UNCOVERED if not>`
     Each UNCOVERED row is a SAFE-blocker; the verdict names every UNCOVERED stale path (not "documentation needs updating"). Zero stale paths supplied → `Inventory drift anchor: NONE supplied | Coverage: N/A`.
   - **2b. UNPROVEN-escalation extension.** A `Coverage: UNPROVEN` row is NOT dischargeable as a "residual concern". Every UNPROVEN row MUST additionally emit ONE of these before the verdict, and until one is present the row is a SAFE-blocker:
     - **Prescribed (preferred):** name a concrete discriminating input — one the broken and correct impls handle DIFFERENTLY — and add a regression test asserting the CORRECT behaviour before SAFE:
       `UNPROVEN escalation: <risk> | Discriminating input: <input> | Broken impl does: <wrong result> | Correct impl does: <right result> | Required before SAFE: add a test asserting the correct result to <tests/<module>/...>`
       Anchor the input in the technique's catalogued failure mode (substring/token confusion → a value containing the keyword but not in the class, e.g. `unlocked` wrongly matched by a `locked` matcher; a boundary → the value distinguishing the OBSERVED comparator, e.g. the limit value itself for `<` vs `<=`; a decision-table gap → the unenumerated combination). An input both impls handle the same proves nothing — reject it. This RAISES the bar; the row stays a SAFE-blocker until the test is added and green.
     - **Deferred (only with the failure mode named):** `UNPROVEN deferral: <risk> | Accepted failure mode: <named mode> | Acknowledged by: <user> | SAFE-blocker: YES (always)`. A deferral records accepted risk; the verdict stays NOT SAFE and names the accepted residual. Only a prescribed input added + green clears UNPROVEN to SAFE.
     A bare UNPROVEN row with neither line is a discipline violation.
   - **2c. External-contract extension.** Emit INSTEAD of the path-keyed row:
     `External-contract anchor: <file:line> | External source: <tool/CLI/API> | Real-output evidence: <captured fixture + provenance/capture command, or NONE> | Coverage: <COVERED (real-run-traceable fixture cited) | UNPROVEN (hand-authored/no traceability)>`
     Never emit `Required test path: tests/<module>/` for an external-contract risk.
   - **2d. Internal/self-produced declination.** When the producer test resolves INTERNAL:
     `External-contract axis: NOT FIRED (internal/self-produced) | Value: <verbatim self-produced value> | Producer: <fn/module> | Consumer: <fn/module, same change> | No external source: confirmed`
3. `Touched files:` every diff path verbatim.
4. `Change shape:` one phrase anchored to the touched files (e.g. `auth predicate + billing checkout ordering, both runtime`).
5. The verification command, quoted verbatim.
6. The test counts verbatim (`X passed, Y skipped, Z failed`).
7. **AC lines (whenever ACs supplied).** One line per criterion, every verdict, MET ones included:
   `AC<n>: <criterion> | Classification: <MET | UNMET | UNVERIFIED> | Anchor: <diff file:line + fully-qualified fresh test::name + verbatim assertion for MET; the criterion / missing behaviour for UNMET/UNVERIFIED>`
   Every UNMET/UNVERIFIED line is a SAFE-blocker. No criteria supplied → emit `No acceptance criteria supplied — AC-coverage check skipped; verdict rests on risk coverage.`
8. **Verification-evidence lines** (each a SAFE-blocker unless DISCHARGED):
   - `Surface verifier: <the eval's FULL config path verbatim from the diff/context | NONE identifiable> | Ran: <YES (runtime/env/key/scope/tree cited — for eval-surface, Node 24 + key) | NO | WRONG CONTEXT (which)> | Combined-tree (if sibling PRs co-edit): <YES | NO | N/A> | Status: <DISCHARGED | N/A (no identifiable verifier surface — non-blocking) | UNVERIFIED (surface verifier) — SAFE-blocker>`
   - `Feature flow: <realistic UI/API/CLI/worker/artifact path | NONE identifiable> | Exercised end-to-end this turn: <YES (fresh path-matching test cited) | NO (only <unit> ran)> | Status: <VERIFIED | UNVERIFIED (feature flow) — SAFE-blocker>`
   - `Guard added: <guard> | Eval exercises BOTH directions: <YES (positive + discriminating true-negative seed cited) | NO (one-sided)> | Status: <COVERED | UNCOVERED — SAFE-blocker>`
   - `A/B control: <the .ab.yaml> | A0 structurally cannot pass via pre-existing rules: <YES (name the only-new-text the rubric PASS needs) | NO/UNKNOWN — single A0-FAIL is variance> | Rubric credits only discriminating inputs: <YES | NO (name the non-discriminating one)> | Status: <LOAD-BEARING | UNPROVEN — SAFE-blocker>`

A runtime verdict emitted before items 1–6 (and 7 when ACs present, 8 when the surface/flow/guard/eval applies) is a discipline violation.

**Trivial-change exemption.** For **genuinely non-executable diffs** only — solely docs (`docs/`, markdown), inert static config (YAML/TOML/JSON read as data — formatter/linter ignore lists, editor config), or files with **no executable behavioural surface**. Path is irrelevant — an executable hook/script/automation does NOT qualify (full sweep + ledger). When it qualifies: SKIP item 2; the verification command (linter/formatter/build) IS the coverage → mark anchors `COVERED BY VERIFICATION`. Items 1, 3, 4, 5, 6 still required. Stay lightweight — do NOT invent runtime risk; manufacturing phantom risk here is the negative-control failure mode. `Touched files:` and `Change shape:` mandatory in both modes.

**Test-only-diff (test_change) discipline.** Diff touches ONLY test files → item 2 does NOT apply, but it is NOT trivial and a green suite is NOT a pass. Per new/changed test emit:
`Test probe: <test name> | Discriminates broken→fixed? <YES (the assertion a broken impl fails / cited RED-on-pre-fix evidence) | NO (the vacuous assertion named verbatim — self-referential expected, type-only, restates prod code)> | <PASS | SAFE-blocker>`
Any `NO` → verdict `NEEDS WORK`/`NOT SAFE TO MERGE`, naming the vacuous assertion. Items 1 (named risks = probe findings), 3, 4, 5, 6 still required; item 2 replaced by these probe lines.

10. **Deliver the verdict + residual concerns** — `SAFE TO MERGE` | `NOT SAFE TO MERGE` | `NEEDS WORK` with concrete evidence (counts, coverage map, rule citations). SAFE only if (a) suite green now, (b) every named risk has ≥1 fresh test demonstrably exercising that exact path, (c) no loaded rule violated. **If ANY named risk is UNCOVERED or UNPROVEN, the verdict MUST be NOT SAFE TO MERGE — no exceptions, even on a fully green suite.** An UNPROVEN risk becomes SAFE-eligible ONLY by adding its prescribed 2b discriminating input and running it GREEN. A deferral never yields SAFE. **(d) When ACs supplied, EVERY criterion must be MET; ANY UNMET/UNVERIFIED is a SAFE-blocker → NOT SAFE, naming each.** **(e) Verification-evidence: ANY of UNVERIFIED (surface verifier), UNVERIFIED (feature flow), UNCOVERED guard, or UNPROVEN A/B is a SAFE-blocker — cleared only by running the verifier correctly / exercising the flow end-to-end / adding the missing-direction seed / proving A/B load-bearing, NEVER by weakening the verifier or rubric.** Always list residual concerns, even on SAFE.

   **The two-pass split.** In `/work-issue` this review is pass 1; an adversarial codex pass runs after. Don't outsource the catch: when you can name a precision/recall risk and the technique has a catalogued failure mode, prescribe the discriminating input YOURSELF (step 9 / 2b) — codex is a second independent check, never the only place an UNPROVEN risk gets a discriminating input (it isn't there in CI-only runs).

### Risk-to-test ledger appendix (optional, structured)

The prose verdict is the deliverable, never replaced. When the user wants a paste-into-PR artifact (*"give me the ledger"*, *"export the risk map"*), project the SAME risks + coverage into the structured ledger via `sumo_qa_format_risk_ledger`, appended BELOW the verdict. YOU identify the risks; the tool only validates/renders. One row per risk with `evidence_status`: `passing` (fresh path-matching test quotes the assertion), `failing` (fresh test red against this risk), `planned` (UNCOVERED/UNPROVEN), `stale` (prior pass not reflecting the diff), `accepted_residual`. Set `residual: blocker` for every UNCOVERED/UNPROVEN high-risk row; `uncovered_blocker_count` must be 0 before SAFE. Skip for trivial-change reviews.

Render as the markdown table the tool returns (never JSON), columns exactly `| Risk | Statement | Source | Test / check | Evidence | Residual |`, one row per named risk; `Evidence` = `evidence_status`, `Residual` = the decision (never blank — covered/passing → `accepted` or `mitigated`; uncovered/unproven high-risk → `blocker`; unsettled → `open`). `Test / check` = covering test id or `planned: …`; `Source` = file:line anchor. If no tool, emit this shape by hand. Example:
`| R1 | Invalid-amount now returns 422 not 500 | services/billing/refund.py:47 | tests/billing/test_refund_api.py::test_invalid_amount_returns_422 | passing | accepted |`
`| R2 | Idempotency key derivation moved → double refund on retry | domain/Refund.kt:18 | planned: re-invoke refund after partial failure, assert at-most-once | planned | blocker |`

**AC-coverage view (same schema).** The inline per-criterion AC lines (item 7) are mandatory whenever ACs are supplied; this appendix is only the paste-into-PR projection, never a substitute. When ACs supplied and the user wants the artifact, project the AC map through the SAME tool as a second table: `risk_id`=`AC1…`, `risk`=criterion text, `source_anchor`=satisfying file:line (or AC text when unmet), `test`=covering fresh test id or `planned: …`, `evidence_status`=`passing` (MET) / `planned` (UNVERIFIED or UNMET), `residual`=`accepted` for MET, `blocker` for every UNMET/UNVERIFIED. `uncovered_blocker_count` must be 0 before SAFE.

## Red Flags — STOP and rework

| Thought | Reality |
|---|---|
| "Possible edge cases / untested paths in this enumeration" | Generic = SHAPE FAIL. Name the class (*stale-entry-from-deleted-path*), anchor the exact `git ls-files`/glob line, state the consequence (a tracked-but-deleted path → stale repo-map node). |
| "There's a risk in the cleanup/rollback path" | Too vague. Is it *rollback data-loss*? Anchor the `unlink`/`rmtree` line; state that it deletes pre-existing content instead of restoring it → user data loss. |
| "The teardown might fail" | Name *cleanup-time flakiness*; anchor the unguarded call (`proc.wait(timeout=5)`); state it raises after the asserts passed → errors a logically-passing test. |
| "Windows handling could differ" | Name *platform-branch asymmetry*; anchor the uninstall branch; state install copytree-copies but uninstall removes only the symlink → orphaned dirs. |
| "The docstring looks fine" | If it claims *Never raises* / always-envelope, hold it against the signature: a REQUIRED arg with no default (schema rejects omission as a raise before the envelope branches), a bare `raise`, or an un-envelope'd path is a *contract-vs-signature contradiction*. Anchor docstring line vs raise line. |
| "Looks good to me" / "CI was green an hour ago" | Not fresh evidence. Run the suite now. |
| "Trivial change, skip the sections" | Walk through (short is fine), but the Iron Law has no trivial-change exemption for the verdict gate. |
| "Docs/config-only — let me flag the runtime risk it might cause" | Negative-control over-fire. Genuinely non-executable diffs get the trivial-change exemption — stay lightweight, invent NO runtime risk. |
| "This hook/script is under `.claude/hooks/` or `scripts/`, so it's trivial" | Wrong — runtime keys on executable behaviour, not path. Branching/command-parsing logic → full sweep + ledger (echo-token, flag-arity, quote-splitting are the target class). |
| "All tests pass, so SAFE" | Necessary, not sufficient. Each named risk needs a covering test. |
| "I spotted a latent issue but tests are green — SAFE with a residual note" | The sweep's hits are NAMED RISKS, not residual notes. A discovered defect the fresh tests don't exercise is UNCOVERED = NOT SAFE. |
| "Path covered but no assertion hits the failure mode — note UNPROVEN and ship" | The exact bypass 2b closes. Prescribe a concrete discriminating input and require it green before SAFE; a deferral stays NOT SAFE. |
| "Codex will catch the discriminating input later" | Don't outsource. When you can name the risk and the technique has a catalogued failure mode, YOU prescribe the input. |
| "The fence parser compares the fence char — verified correct" | Char-only is the tell length isn't tracked — the defect, not proof. UNPROVEN until you build the discriminating 4-tick-wrapping-3-tick input. `~~~`-vs-backtick and unclosed-at-EOF don't discriminate the char-stored bug. |
| "The matcher is green, so parsing the tool's output is covered" | Green proves matcher LOGIC, not that the marker matches REAL output. Hand-authored fixture, no real-run traceability → UNPROVEN. Don't over-trigger on internal/self-produced values. |
| "External-contract tests live at `tests/test_x.py` not `tests/<module>/` → UNCOVERED" | The path rule doesn't apply to external-contract risks — a real-run-traceable fixture is COVERED wherever it sits. |
| "Real-run fixture covers it, but what about emoji/locale variants?" | Speculative variant-hunting on a discharged contract is over-trigger. Don't re-block SAFE on variants the diff doesn't depend on. |
| "It's self-produced, so I just won't raise it" | Declining silently fails grounding. State it (2d): quote the value, name producer + same-module consumer, conclude no external contract. |
| "Diff is only tests — SAFE once green" | test_change has its own probe. A tautology or under-matching matcher → NEEDS WORK, not SAFE. |
| "No standards apply" | Re-classify. Every change has ≥1 applicable classification with loaded rules. |
| "I'll list risks AND deliver the verdict in one message" | Gate. The user's correction on the risks shapes the verdict. |
| "I'll ask which framework / where tests live" | Read the repo — sibling files answer it. |
| "Residual concerns: none" | Every change has them. None = you didn't think about what could still go wrong. |
| "Green + risk-covered, but one AC isn't delivered — SAFE" | That answers "correct code", not "the right code". An UNMET/UNVERIFIED supplied AC is a SAFE-blocker. |
| "No ACs pasted, skip the check silently" | Say so in one line and fall back to risk-coverage. Fabricating criteria is worse. |
| "The host should fetch the issue's ACs" | Never. Host-neutral: the host SUPPLIES criteria; the skill never calls `gh`/a tracker. |
| "Per-file review, codex, and CI are all green — SAFE" | None exercise the changed behaviour. A relevant verifier that didn't run (or ran wrong runtime/env/key/scope/tree) → UNVERIFIED (surface verifier). Eval-surface skill change → promptfoo with Node 24 + key, named verbatim. |
| "Each sibling PR's eval passed in isolation — SAFE to merge the set" | Per-branch-green ≠ combined-green when siblings co-edit one surface. Require the COMBINED tree first (3/3 per-branch can drop to 1/3 combined). |
| "A unit test exercised the new code — SAFE" | A unit running ≠ the primary FEATURE FLOW. If the realistic UI/API/CLI/worker/artifact path was never driven end-to-end → UNVERIFIED (feature flow). Don't over-fire when a fresh path-matching test drives it. |
| "The new guard is described and plausible — validated" | Described ≠ tested. COVERED only with a discriminating true-negative/over-trigger seed a guard-violating reviewer would FAIL. One-sided → UNCOVERED. |
| "A/B shows A0 FAIL → A1 PASS, so the new text is load-bearing" | One A0-FAIL is variance. A0 must be structurally INCAPABLE of passing via pre-existing rules; NAME the pre-existing rule. Apply 2b to the rubric — a credited input must actually discriminate the seed defect. |
| "The fresh test doesn't prove every nuance of the AC — mark it UNVERIFIED to be safe" | If a fresh path-matching test asserts the criterion's STATED behaviour, it is MET; the unproven nuance is a separate named risk. Over-firing UNVERIFIED is a SHAPE FAIL. |

## Examples

### Good (explore → confirm scope → risks → verdict, one section per turn)

> **User:** "review my changes, is this safe to merge?"
> **AI (scope):** *"3 files: `api/refund.py` (+38/-4), `domain/Refund.kt` (+12/-2), `tests/test_refund_api.py` (+25/-0). Response shape + amount calc moved; `tests/contracts/refund_v1.json` untouched. Consumer external or internal-only?"*
> *(risks → tests → coverage map → verdict, one section per turn)*

### Bad (single-shot verdict)

> **AI:** *"Looks straightforward — mostly internal refactor. Should be fine to merge. Maybe run CI."*
> No fresh test evidence, no risk anchoring, no standards check. Iron Law violated.

## Next skill in the chain

When the verdict is delivered with fresh evidence + risk-coverage map → `sumo-qa-finishing-qa-work` to capture the evidence and produce the PR-ready summary.
