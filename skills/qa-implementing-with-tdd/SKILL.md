---
name: qa-implementing-with-tdd
description: Use after qa-deciding-approach picked tdd-scaffold, regression-first, or coverage-first-then-refactor. Walks through plan → scaffold → write red tests → user implements → green → review, with verification between every step.
---

## When to load

Load this AFTER `qa-deciding-approach` returns one of:
- `tdd-scaffold` — full TDD on a greenfield-ish change
- `regression-first` — TDD applied to a bug fix (reproduce → fix → confirm)
- `coverage-first-then-refactor` — TDD applied to a refactor (cover → refactor → still green)

Do NOT load on `verify-existing`, `no-tests-recommended`, or `spike-first-then-tests`.

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST. NO CLAIM OF DONE WITHOUT VERIFY EVIDENCE.
```

Three sub-rules, all enforced:
1. **Red phase is mandatory** — every test must be seen failing before any production code is written.
2. **Verify after each step** — run the test command after writing the test (must fail), after writing production code (must pass), before claiming done.
3. **The MCP itself does not write files** — it returns a structured task list; YOU (the host) write the files using your own Edit/Write tools.

## Branches

The flow has three branches; the approach decided in the previous skill picks one.

### Branch A — `tdd-scaffold` (greenfield-ish)

```
1. (optional) sumo_qa_create_test_plan if scope is medium/large
   → user reviews scope, entry/exit criteria, phases
2. sumo_qa_scaffold_tests with the test conditions
   → returns task list with file paths, frameworks, assertions, skeletons
3. For each task in execution_order:
   a. host writes tasks[i].file_path with tasks[i].skeleton (Edit/Write)
   b. host runs tasks[i].verify_command
   c. CONFIRM red — every assertion fails with NotImplementedError or equivalent
4. User implements production code (or asks the host to)
5. Host re-runs each verify_command → must all be green
6. sumo_qa_review_local_change → final verdict before merge
```

### Branch B — `regression-first` (bug fix)

```
1. sumo_qa_scaffold_tests with ONE test condition: "Reproduce the failing case exactly as the bug presents"
   → returns ONE task (single reproducer)
2. host writes that one file
3. host runs the verify_command → must FAIL with the bug's symptom
   - if it does NOT fail, the reproducer doesn't actually capture the bug; revise
4. User (or host) implements the fix
5. Host re-runs verify_command → must PASS (confirmation testing)
6. Host runs targeted regression around the impacted area, NOT the whole suite
7. sumo_qa_review_local_change → final verdict before merge
```

### Branch C — `coverage-first-then-refactor`

```
1. sumo_qa_review_local_change on the touched files BEFORE the refactor
   → returns missing_test_levels and qa_findings showing coverage gaps
2. sumo_qa_scaffold_tests with characterization conditions for the CURRENT behaviour
   → e.g. "Function accepts X and returns Y today; this must remain after refactor"
3. host writes the files
4. host runs verify_command → must PASS (current behaviour is captured)
5. User (or host) does the refactor
6. Host re-runs the SAME verify commands → must all still PASS unchanged
   - if any flips to FAIL, the refactor changed behaviour; revisit
7. sumo_qa_review_local_change → final verdict before merge
```

## Checklist (use as a TodoWrite list)

- [ ] (Branch A only) Optional: call `sumo_qa_create_test_plan` for medium/large work
- [ ] Call `sumo_qa_scaffold_tests` with the right conditions
- [ ] Read `execution_order` and `tasks[]`
- [ ] **For each task in order:**
  - [ ] Write the file at `tasks[i].file_path` using your own file tool — do NOT skip
  - [ ] Run `tasks[i].verify_command` and read the output
  - [ ] Branch A: confirm test fails with NotImplementedError (red)
  - [ ] Branch B: confirm test fails with the bug's actual symptom (real reproducer)
  - [ ] Branch C: confirm test PASSES (current behaviour captured)
- [ ] (Branches A and B) User implements production code
- [ ] (Branch C) User does the refactor
- [ ] Re-run all verify commands
  - [ ] Branches A and B: all green
  - [ ] Branch C: same green/fail set as before the refactor
- [ ] Call `sumo_qa_review_local_change` for the final verdict
- [ ] Verify the verdict, the missing_test_levels, and the recommended_test_path before claiming done

## Red Flags — STOP

| Thought | Reality |
|---------|---------|
| "I'll write the production code first, then add tests" | That's tests-after, not TDD. Discard the production code; start over from the failing test. |
| "The skeleton looks ready; I'll skip running the test" | You did not see it fail. You don't know if the assertion is wrong, the import is wrong, or the test runner is wrong. RUN it. |
| "I wrote one task, I'll write the rest before running anything" | Verify after each task. A broken setup hides until you run; finding it after 5 files is 5x the work. |
| "Branch B: the test passes already, that proves the bug is fixed" | If the test passes BEFORE your fix, the test does not capture the bug. Your reproducer is wrong. Revise it. |
| "Branch C: a test failed after the refactor, I'll update the test" | NEVER. The whole point of branch C is that the test pins behaviour. If it fails, the REFACTOR is wrong, not the test. |
| "sumo_qa_review_local_change said needs-test-evidence but tests pass locally" | Read `recommended_test_path` and `missing_test_levels`. The tool sees gaps your local pass doesn't. |
| "I'm tired, I'll skip the final review" | Skipping review is exactly when missed-test-level bugs ship. Don't. |

## Examples

### Branch A example

User: *"Add a payment retry handler with idempotency keys"* (after `qa-deciding-approach` returned `tdd-scaffold`).

Step 1: Optional plan.
```
sumo_qa_create_test_plan(
  work_item="Add a payment retry handler with idempotency keys",
  scope_size="medium",
  acceptance_criteria=[
    "Failed charges retry with exponential backoff",
    "Idempotency keys prevent double-charges",
  ]
)
```

Step 2: Scaffold.
```
sumo_qa_scaffold_tests(
  work_item="Add a payment retry handler with idempotency keys",
  test_conditions=[
    "Failed charge retries with exponential backoff",
    "Same idempotency key never double-charges",
    "Boundary: idempotency key TTL just-fresh and just-expired",
  ],
  target_paths=["src/payments/retry.py"]
)
```

Step 3: For each task, write file → run verify → confirm red. Skeleton has `raise NotImplementedError(...)` per assertion.

Step 4–7: Implement → green → review.

### Branch B example

User: *"fix the broken oauth refresh in production"* (after `qa-deciding-approach` returned `regression-first`).

```
sumo_qa_scaffold_tests(
  work_item="Reproduce: oauth refresh fails for sessions older than 10 minutes",
  test_conditions=[
    "An oauth session token older than 10 minutes is correctly refreshed and the user remains authenticated",
  ],
  target_paths=["src/auth/refresh.py"]
)
```

→ ONE task. Write it. Run it. Test fails (real bug reproduced). Fix code. Run it. Test passes. Targeted regression on the auth module. Review.

### Branch C example

User: *"refactor the order pipeline to extract validation into its own module"* (after `qa-deciding-approach` returned `coverage-first-then-refactor`).

```
sumo_qa_review_local_change(change_summary="...", touched_files=["src/orders/pipeline.py"])
→ missing_test_levels: ["unit", "integration"]; qa_findings: gap on validation branch

sumo_qa_scaffold_tests(
  work_item="Characterize current order pipeline validation behaviour before refactor",
  test_conditions=[
    "validate(valid_order) returns the order unchanged",
    "validate(missing-customer) raises ValidationError with code MISSING_CUSTOMER",
    "validate(zero-quantity) raises ValidationError with code ZERO_QTY",
  ],
  target_paths=["src/orders/pipeline.py"]
)
```

→ Tasks. Write them. Run them. They PASS (capturing current behaviour). User refactors. Re-run. Still pass. Review.

## Final rule

```
Red → green → review. Verify between every step. The MCP returns the recipe; YOU write the files.
```
