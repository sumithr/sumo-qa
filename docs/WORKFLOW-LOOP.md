# Workflow Loop

The plan → scaffold → red → implement → green → review flow per approach.

The MCP enforces the discipline (named ISTQB techniques, entry/exit criteria, honest red-phase skeletons, structured task lists with `verify_command` per task). The host's own `Edit` / `Write` tools do the muscle work — the MCP itself never writes files. Specialty MCPs (Cypress, k6, ZAP, Appium, Promptfoo, axe-core, Pact, Schemathesis) can substitute for the relevant tasks if available; each scaffold task is tagged with a `specialty + specialty_mcp_hint` when one fits.

```
0. user        : describes the work / change in any tool call
1. qa MCP      : every response leads with an APPROACH line so the host knows
                 whether to plan, scaffold, write a regression test, refactor
                 with coverage, strengthen tests, just verify, skip tests, or
                 escalate to a repo-wide strategy.
2. host model  : routes to the next tool based on the APPROACH:

   tdd-scaffold:
     a. sumo_qa_create_test_plan -> phased plan with entry/exit criteria
     b. user confirms / edits
     c. sumo_qa_scaffold_tests -> task list (paths, frameworks, assertions, skeletons)
     d. host writes each tasks[i].file_path with its own Edit/Write tools
     e. host runs tasks[i].verify_command -> red
     f. user implements (or asks host to)
     g. host re-runs -> green
     h. sumo_qa_review_local_change -> verdict before merge

   regression-first:
     a. sumo_qa_scaffold_tests with ONE failing reproducer for the bug
     b. host writes the file, runs verify_command -> red
     c. user implements the fix
     d. host re-runs -> green; targeted regression on the impacted area
     e. sumo_qa_review_local_change -> confirm no collateral break

   coverage-first-then-refactor:
     a. sumo_qa_review_local_change on the touched files -> find coverage gaps
     b. sumo_qa_scaffold_tests for the gap-filling characterization tests
     c. host writes them, runs them -> green (proving current behaviour)
     d. user does the refactor
     e. host re-runs same tests -> still green (behaviour preserved)
     f. sumo_qa_review_local_change -> verdict

   strengthen-test-coverage:
     a. sumo_qa_scaffold_tests against existing tests; one targeted test
        per surviving mutant or weak assertion
     b. host writes them, runs the mutation / coverage tool
     c. iterate until threshold met
     d. for equivalent mutants (early-return on already-empty branches,
        generated lambda noise, logger removals): suppress in tool config
        rather than chasing them.

   verify-existing / no-tests-recommended / spike-first-then-tests:
     a. no MCP tool to call; host runs build/lint/existing-suite
     b. for spikes: capture test conditions; revisit when design settles
        (deliverable = "captured_conditions_and_fit_record")

   strategy-orchestration:
     a. STOP - this is not a single change. Load the sumo-qa-strategising
        skill. Walk the repo with host file tools (Glob / Read / Grep /
        git log) FIRST to map languages, frameworks, untested domains,
        gates, hotspots.
     b. THEN chain sumo_qa_decide_approach per priority area.
     c. The response carries pyramid_shape / gate_calibration /
        ci_feedback_time / rollout_plan to anchor the strategy artefact.
```

No slash commands, no tool names typed by the user, no special syntax. The model decides — the MCP just makes sure the decision is senior-QA-shaped.

See [docs/APPROACHES.md](APPROACHES.md) for the canonical list and the signal-driven fallback. See [docs/TOOLS.md](TOOLS.md) for full tool detail.
