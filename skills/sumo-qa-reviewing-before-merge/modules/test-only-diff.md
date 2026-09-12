# Reviewing before merge: test-only diff (test_change) probe

Lazy module of `sumo-qa-reviewing-before-merge` (load via `sumo_qa_load_skill_context` with `mode="module"`). **Load when:** the diff touches ONLY test files (no runtime file anywhere, by behaviour not path). **Extends:** checklist step 4 (diff-shape branch), step 9 (test-only-diff probe), and the test_change verdict-format discipline. The root's Iron Law, verdict gate, and output discipline apply unchanged.

## Branch on the diff shape (step 4)

**First, branch on the diff shape.** If the diff is test files ONLY (no `app/`/`src/`/`lib/` runtime file — a `test_change`), the runtime probes in `discovery-probes` mostly do not apply; run the **test-only-diff probe (step 9)** instead — the central risk is whether each new/changed test can actually fail (tautology / non-discriminating assertion / matcher under-coverage / unproven regression), and its findings ARE this turn's named risks. A green suite is NOT a pass for a test_change: a tautological assertion passes against any implementation. Do this BEFORE the verdict; then continue to the `discovery-probes` sweep only for any runtime file present.

## Test-only-diff probe (step 9)

**Test-only-diff probe (pinned).** When the diff is test files ONLY (no `app/`/`src/`/`lib/` runtime file — a `test_change`), the runtime coverage ledger (`coverage-ledger`) has no anchor, so the risk becomes *does each new/changed test discriminate broken from fixed?* Run a test-quality probe before the verdict, reusing — not restating — the tautology / setup-discriminator / expected-value-derivation framing from `sumo-qa-implementing-with-tdd` step 3, applied to the diff. Plus a matcher-coverage check: name each test's oracle/matcher, enumerate the input *shapes* it must catch, confirm each has a discriminating case — a matcher that silently under-matches a shape (the singular-vs-plural false-negative class) is a hole even when every present assertion is sound. These findings ARE the named risks here. A new test whose assertion restates the production code or passes against a broken impl (a tautology — one that re-derives "expected" from the SUT itself, `result = add(2, 3); assert add(2, 3) == result`, so any impl passes; the expected value must be derived INDEPENDENTLY of the SUT), or a regression/contract test with no evidence it fails on the pre-fix/drift state, is a SAFE-blocker → `NEEDS WORK`/`NOT SAFE TO MERGE`, naming the vacuous assertion. A genuine discriminator (an assertion a broken impl fails; for a regression, red-on-pre-fix evidence) passes. The runtime module-match rows in `coverage-ledger` do not apply with no runtime file in the diff.

## Test-only-diff (test_change) verdict discipline

**Test-only-diff (test_change) discipline (pinned):** if the diff touches ONLY test files (no `app`/`src`/`lib` runtime file), the runtime coverage-ledger (item 2) does NOT apply — but it is NOT a trivial change, and a green suite is NOT a pass. Before the verdict you MUST, per new/changed test, emit one probe line in this shape:
`Test probe: <test name> | Discriminates broken→fixed? <YES (the assertion a broken impl fails / for a regression, the cited RED-on-pre-fix evidence) | NO (the vacuous assertion, named verbatim — e.g. self-referential expected, type-only, restates prod code)> | <PASS | SAFE-blocker>`
Any `NO` line is a SAFE-blocker → the verdict is `NEEDS WORK`/`NOT SAFE TO MERGE`, naming the vacuous assertion. Items 1 (named risks = the probe findings), 3, 4, 5, 6 still required; item 2 is replaced by these probe lines.

## Red Flags

| Thought | Reality |
|---|---|
| "Diff is only tests — no runtime anchor, so SAFE once green" | A test_change has its own probe (step 9). Green proves nothing if the assertion is a tautology or the matcher under-matches a shape. A vacuous assertion is NEEDS WORK, not SAFE. |
