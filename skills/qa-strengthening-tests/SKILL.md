---
name: qa-strengthening-tests
description: Use after qa-deciding-approach picked strengthen-test-coverage. Strengthens existing tests against UNCHANGED production code — mutation testing follow-up (Pitest, Stryker), coverage-gate fixes, killing weak assertions. Distinct from coverage-first-then-refactor (no refactor) and from tdd-scaffold (no new behaviour).
---

## When to load

Load this AFTER `qa-deciding-approach` returns `strengthen-test-coverage`. Triggers include:
- "increase / improve / raise test coverage"
- "kill surviving mutants" / "mutation testing follow-up" / "Pitest" / "Stryker"
- "test strength below threshold" / "coverage gate failing"
- "strengthen tests" / "tighten assertions" / "weak assertions"
- "no production code changes" / "test-only change"

Do NOT load on `tdd-scaffold` (new behaviour), `coverage-first-then-refactor` (refactor), `regression-first` (real bug), or any other approach.

## The Iron Law

```
NO PRODUCTION CODE CHANGES IN THIS BRANCH. ONE STRENGTHENING TEST PER REAL MUTANT. EQUIVALENT MUTANTS GET SUPPRESSED, NOT CHASED.
```

Three sub-rules:
1. **Production code is off-limits** — if you find yourself wanting to "improve" the production code, you've drifted into `coverage-first-then-refactor` or `tdd-scaffold`. Stop and re-decide.
2. **Each strengthening test targets a specific weakness** — name the mutant or the weak assertion the test kills. "Generic strengthening" produces brittle tests that don't kill anything.
3. **Equivalent mutants are noise, not gaps** — early-return on already-empty branches, logger removal, generated-lambda return value, synthetic-line `Pair.equals`, getter mutations on non-null Kotlin types. Suppress these in tool config (Pitest excludes, Stryker mutators) rather than writing tests that "kill" them — those tests are arbitrary and add no real coverage.

## Workflow

### Step 1 — enumerate the surviving mutants (or weak assertions)

If the user has a mutation-testing report (Pitest / Stryker), list the survivors. For each one, classify:

- **Real gap**: the mutation changes observable behaviour but no test catches it. Targets for a strengthening test.
- **Equivalent mutant**: the mutation is semantically equivalent to the original code (early-return on already-empty branches, getter on non-null types, logger removal, generated lambdas, synthetic-line equals, etc.). Suppress in config.
- **Weak BDD / unit assertion**: the test exists but its assertion is too loose (e.g. `assertNotNull` on a non-null type, `assertTrue(true)`, asserting a property that's always true by construction). Tighten the assertion.

Refuse to scaffold a "strengthening" test for an equivalent mutant. The honest answer is "this mutant is noise; suppress it in <pitest.xml | stryker.conf.js> with <reason>."

### Step 2 — scaffold one strengthening test per real gap

For each real gap or weak assertion:

```
sumo_qa_scaffold_tests(
  work_item="Strengthen test against unchanged BundleVariantValidator: kill <mutant description>",
  test_conditions=[
    "<the assertion that would have caught this mutant — phrased in domain terms>"
  ],
  target_paths=["<the existing test file you're strengthening>"]
)
```

Each call returns ONE task with one assertion. Write it; run the verify_command; confirm the new test passes against the current production code. Then re-run the mutation tool — the targeted mutant should now be killed.

If the test you wrote does NOT kill the targeted mutant, the assertion isn't strict enough. Tighten it. **Don't accept a test that passes against the original code AND survives the mutant** — that's a no-op test.

### Step 3 — suppress equivalent mutants in tool config

For Pitest, add to `pitest.xml` / `pom.xml` plugin config:
```xml
<excludedClasses>...</excludedClasses>
<excludedMethods>...</excludedMethods>
<excludedMutators>
    <mutator>EMPTY_RETURNS</mutator>  <!-- if early-return on empty is a known noise source -->
</excludedMutators>
```

For Stryker:
```js
mutator: { excludedMutations: ['StringLiteral', 'BlockStatement'] }
```

Document the suppression with a one-line comment per exclusion. Future maintainers must be able to read the config and understand WHY each mutator is excluded.

### Step 4 — re-run the coverage / mutation tool

Re-run after each batch of strengthening tests + suppressions:
- Mutation kill ratio should rise.
- Test strength should cross the gate.
- New survivors (if any) get classified again — go back to step 1.

### Step 5 — review before merge

Once the gate passes:
```
sumo_qa_review_local_change(
  change_summary="Strengthened tests against unchanged production code; killed N mutants, suppressed M equivalent mutants",
  touched_files=[<test files>, <pitest config>]
)
```

The verdict should be `qa-risk-acceptable-for-phase-1-input` since no production code changed. If the verdict is anything else, read the findings before merging.

## Checklist (use as a TodoWrite list)

- [ ] List every surviving mutant / weak assertion
- [ ] Classify each: real gap, equivalent mutant, or weak assertion
- [ ] For each REAL gap: call `sumo_qa_scaffold_tests` with one targeted condition
- [ ] Write the file using your own Edit/Write tools — do NOT modify production code
- [ ] Run the verify_command → test passes against current code
- [ ] Re-run the mutation tool → targeted mutant is killed
- [ ] If not killed, tighten the assertion (it's not strict enough)
- [ ] For each EQUIVALENT mutant: add a config exclusion with a one-line comment
- [ ] Re-run the gate; iterate
- [ ] Call `sumo_qa_review_local_change` for the merge verdict

## Red Flags — STOP

| Thought | Reality |
|---|---|
| "I'll modify the production code to make it more testable" | NO. That's a refactor — re-decide via `qa-deciding-approach` (you'll get `coverage-first-then-refactor`). |
| "This equivalent mutant is suspicious; I'll write a test to be safe" | The test will be arbitrary and brittle. Read the code; if the mutation is truly semantically equivalent, suppress and move on. |
| "I'll write one big test that asserts lots of things" | Each strengthening test targets ONE mutant. A blob test doesn't tell future maintainers which mutant each assertion was for. |
| "The coverage tool says line coverage is 100%, so I'm done" | Line coverage ≠ assertion strength. Pitest's test strength is the gate; line coverage being 100% just means every line ran, not that every line is asserted. |
| "I'll soften the gate threshold" | Lower bar = more bugs. Strengthen the tests, don't soften the gate. |
| "I'll write the strengthening test and ALSO improve the prod code while I'm there" | Two changes in one branch obscure which test killed which mutant. Strengthening branch must be production-code-clean. |
| "All 6 mutants look equivalent to me; I'll suppress all of them" | Probably wrong. Read each one carefully. Genuine equivalent mutants are rare in well-written code; if 6/6 are equivalent, the tool config is too aggressive — narrow the mutators, not the survivors. |

## Examples

### Real-world Pitest follow-up

Surviving mutants on `BundleVariantValidator`:
- 5 baseline equivalent mutants: early-return on emptyList branches that already return emptyList, logger removal, generated lambda return, Pair.equals on synthetic line. → Suppress in `pitest.xml` with one-line comments.
- 1 BR4 BDD scenario: assertion is `description != null` on a non-null Kotlin String. → Tighten the assertion: `description == "Bundle BR4: <expected text>"` (or whatever the rule actually requires).

For the BR4 case:
```
sumo_qa_scaffold_tests(
  work_item="Strengthen BR4 BDD assertion: kill EmptyObjectReturnValsMutator on getDescription",
  test_conditions=[
    "When the BR4 scenario runs, the violation description equals the rule-mandated string, not just non-null"
  ],
  target_paths=["src/test/kotlin/.../BundleValidationSteps.kt"]
)
```

→ Write the file. Run the test. It passes. Re-run Pitest. The `EmptyObjectReturnValsMutator` survivor is killed. Test strength crosses 87%.

### Test-coverage gap on a long-untested helper

User: *"raise coverage on src/util/parser.py from 60% to 90%"*

→ `sumo_qa_decide_approach` returns `strengthen-test-coverage`.
→ List the uncovered lines / branches.
→ For each: `sumo_qa_scaffold_tests` with one condition that exercises that branch.
→ Write the test using your file tools.
→ Run coverage; confirm the line is now covered.
→ Iterate until 90%.

## Final rule

```
Strengthen tests; never touch production code on this branch; suppress
equivalent mutants in config; re-run the gate after every batch.
```
