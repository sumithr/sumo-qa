# Reviewing before merge: risk coverage ledger

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** the diff touches any runtime file (every runtime review maps each named risk to fresh test evidence here). **Extends:** checklist step 9 (map risk coverage) and Verdict-format items 1 and 2. The root's Iron Law, verdict gate, and output discipline apply unchanged.

## Re-anchor, then apply the module-match rule (step 9)

**Re-anchor first.** If risks arrive as bare names (*"Auth Session Bypass, Duplicate Charge on Retry"*), locate each one's anchor file in the diff before mapping — *Auth Session Bypass* → `app/auth/session.py:33`, *Duplicate Charge on Retry* → `app/billing/checkout.py`. Without an anchor you cannot apply the module-match rule and will hallucinate coverage. When a repo-map is loaded, `sumo_qa_query_repo_map` helps locate a RUNTIME risk's anchor file or a candidate test by path/name — but a test counts only once it's in THIS turn's fresh run with a verbatim assertion. It does NOT consolidate inventory drift: each stale path still gets its own 2a row with its own `(<old> → <new>)` pair (below).

**Module-match rule (pinned):** a risk anchored under `app/auth/` requires a covering test under `tests/auth/`; `app/billing/` requires `tests/billing/`. A `tests/billing/` test cannot cover an `auth/session.py` risk via *"indirectly validates"* / *"implicitly covers"* — forbidden hallucinated bridges; mark UNCOVERED when paths don't match. If the fresh run loaded no test for a changed file's module, every risk anchored there is UNCOVERED, however green the rest is. **Integration/e2e exception:** tests under `tests/integration/` or `tests/e2e/` MAY cover any module risk, but only if the cited assertion verbatim invokes (or asserts a property of) the risk's anchor function; "the integration suite passed" without naming that assertion is the same hallucinated bridge. **External-contract exception (pinned):** the module-match path rule does NOT apply to an external-contract risk (step 4's external-output probe). Its evidence is REAL captured output, never a `tests/<module>/` test. When the fixture is traceable to a real or minimal run (capture command / provenance cited), the axis is COVERED and DISCHARGED — SAFE-eligible — REGARDLESS of where the tests live. Do NOT mark an external-contract risk UNCOVERED because its tests sit at `tests/test_x.py` instead of `tests/<module>/`.

**Worked contrast (same-domain ≠ proof).** Risk *"Duplicate Charge on Retry"* + passing `tests/billing/test_checkout.py::test_does_not_mark_failed_charge_paid`:
- BAD: *"Covered by `test_does_not_mark_failed_charge_paid`."* — it asserts one failed charge isn't marked paid; it never re-invokes `complete_checkout` after a partial failure, so it cannot prove retry idempotency.
- GOOD: *"UNCOVERED. No fresh test re-invokes `complete_checkout` after a partial failure or asserts charge-at-most-once across retries. SAFE-blocker."*

## Coverage-ledger row shape (Verdict-format item 2)

A coverage-ledger line per risk in this exact shape:

`Risk: <exact name> | Anchor: <diff file:line> | Required test path: <the test dir covering this anchor — tests/<module>/ for app/<module>/; for an executable anchor outside a source dir, the sibling test dir mirroring it, e.g. tests/hooks/ for .claude/hooks/, tests/scripts/ for scripts/> | Fresh matching tests: <fresh tests whose path starts with the required path, as fully-qualified `<file>::<test>` IDs, or NONE> | Coverage: <COVERED (cited test + verbatim assertion) | UNPROVEN | UNCOVERED>`
- `COVERED` only when a fresh path-matching test quotes a verbatim assertion/condition that exercises the risk's failure mode — path prefix is necessary, not sufficient.
- Risks whose name/anchor/failure-mode contains **Retry, Duplicate, or Idempotency** require an assertion showing the operation invoked MORE THAN ONCE (two calls, a loop, a call-count or idempotency-token assertion across attempts). **Concurrent, Race, or Lock** require overlapping execution (threading / `asyncio.gather` / `concurrent.futures`, or an explicit interleave). A single non-overlapping invocation — even one that raises — proves none of these; mark UNPROVEN.
- `Fresh matching tests: NONE` → Coverage UNCOVERED; never cite non-matching tests as indirect evidence.
- `COVERED BY VERIFICATION` is reserved for docs/config-only anchors (the trivial-change exemption in `runtime-scope`); runtime anchors MUST NOT use it.

- **2c. External-contract extension (pinned).** For an external-contract risk, emit this row INSTEAD of the path-keyed row (`Required test path` does not apply):
  `External-contract anchor: <file:line> | External source: <tool/CLI/API> | Real-output evidence: <captured fixture + provenance/capture command, or NONE> | Coverage: <COVERED (real-run-traceable fixture cited) | UNPROVEN (hand-authored/no real-run traceability)>`
  A documented real-run capture → COVERED, SAFE-eligible. A hand-authored fixture with no real-run traceability → UNPROVEN, SAFE-blocker. Never emit `Required test path: tests/<module>/` for an external-contract risk.
- **2d. Internal/self-produced declination (pinned).** When the external-output probe resolves INTERNAL (producer test), emit this line so the true-negative is on the record:
  `External-contract axis: NOT FIRED (internal/self-produced) | Value: <verbatim self-produced value, e.g. [sumo-qa:CODE]> | Producer: <fn/module> | Consumer: <fn/module, same change> | No external source: confirmed`

Extension rows: `2a` inventory drift lives in `inventory-drift`; `2b` UNPROVEN escalation lives in `unproven-escalation`. Emit them whenever their risk class is present.
