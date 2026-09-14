---
name: sumo-qa-triaging-test-failures
description: Use when a test is failing or flaky and the cause is not yet known — e.g. 'this test keeps failing', 'red in CI but passes locally', 'this test is flaky', 'a test failed, what now?'. Reads the failure output, classifies the likely cause (product regression, test bug, fixture/data, environment/dependency, timing/order, external service), and names the smallest next isolation step BEFORE any fix. Diagnosis only — it does not patch; it routes to a fixing skill only once a concrete product-behaviour gap is confirmed.
---

# Triaging test failures

Separate *why it failed* from *how to fix it*: the same red bar can mean a product regression, a wrong test, stale fixture data, a broken environment, an order/timing race, or a flaky external service, each needing a different response. Patch before naming the cause and a test bug gets "fixed" in the product, or a real regression is buried under a rerun. The output is a **cause classification plus the smallest next verification step**, never a fix first.

**Announce at the start of EVERY turn while this skill is active** — triage, isolation-step, rerun-with-hypothesis, hand-off, and refusal turns all open with: *"Triaging this failure before any fix."* A turn that skips the announce has left the triage discipline.

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: output discipline (no internal taxonomy labels — say *"the test's own expectation is stale"*, not *"Cause: test_bug"*), output economy (findings not framing; one question per turn), knowledge authority hierarchy, specialty-tool fit.

<HARD-GATE>
Do NOT classify a failure you have not seen. Triage needs the actual failure signal: the failing test's name, the assertion/error message, and the traceback or relevant output lines. A test name alone, or "it's flaky", is not enough. If the output is absent or too thin to ground a cause, STOP: say what you have, name exactly what you still need (the failing assertion text and the traceback OR the relevant output lines), ask for it, and do nothing else. Never invent a traceback, line number, or error message; never classify from the test's title alone.
</HARD-GATE>

## The Iron Law

**CLASSIFY, THEN ISOLATE — NEVER FIX FIRST.** The first output for any failure is a named cause plus the single smallest next reproduction/isolation step, NOT a patch. Production code is touched ONLY after triage identifies a concrete product-behaviour gap — a specific behaviour the product gets wrong, evidenced by the failure. A test bug, fixture/data, environment/dependency, timing/order, or external-service flake is NOT a product gap and never licenses a production edit. A rerun is allowed only as a stated experiment testing one hypothesis — never "run it again and hope".

## When to Use

`sumo-qa-deciding-approach` routes here on `triage-test-failure`: *"this test keeps failing"*, *"red in CI, green locally"*, *"this test is flaky"*, *"why does the suite break only sometimes"*.

NOT for: a defect already pinned to a known product behaviour (`regression-first` via `sumo-qa-implementing-with-tdd`); a named uncovered gap ready to close (`closed-loop-gap-fix` via `sumo-qa-closing-qa-gaps`); strengthening weak-but-passing tests / killing mutation survivors (`sumo-qa-strengthening-tests`). Triage comes first and decides whether any apply.

## Checklist

Work through these in order. Steps 3 to 5 repeat per distinct failure; reruns happen only via step 4's hypothesis gate.

1. **Secure the failure signal**: get the actual evidence (the failing test's full name, the assertion/error message, the traceback or relevant output lines, and (when it matters) whether it fails every run or only sometimes). Take it from the user's paste, a saved log, or the host's command-running capability; if missing or too thin to classify, the HARD-GATE fires. Keep the load-bearing lines (failing assertion, exception type and message, key traceback frames); summarise the rest, never dump the whole log.

2. **Gather the cheap surrounding context, no fix yet**: read the failing test and the code it exercises; check what changed recently around the failure (the diff / recent commits on those paths) and whether the symptom is deterministic or intermittent. Read-only.

3. **Classify the likely cause against the six categories** — name the single most likely cause from the signal and context, with its tell. The first two reproduce every run; the last four often present as intermittent:
   - **Product regression** — the product's behaviour changed for the worse, the test correctly catches it. Tell: a recent product-code change on the exercised path; an assertion still encoding a correct expectation; deterministic.
   - **Test bug** — the test is wrong (stale expected value, bad assertion, over-specified mock, wrong setup); the product is right, the test lies. Tell: the asserted expectation no longer matches intended behaviour or contradicts the spec.
   - **Fixture / data issue** — the test depends on fixture/seed data that is stale, missing, or mutated by another test. Tell: `KeyError`/not-found/empty against assumed-present data; passes alone, fails in a state-sharing suite.
   - **Environment / dependency issue** — a runtime, library version, locale, clock, filesystem, or config difference between where it passes and fails. Tell: `ImportError`/version mismatch/path-not-found; "passes locally, fails in CI" with no product change.
   - **Timing / order dependence** — depends on execution order or a race/sleep/async boundary. Tell: passes alone, fails after another test or only under parallelism / on a slow machine; reordering or a seed change flips it.
   - **External-service dependence** — the test reaches a real network/third-party service whose availability varies. Tell: timeouts, rate-limit/5xx, failure tracking the service's health not the code.
   If two causes are genuinely plausible, name the likelier and the single observation that discriminates them — that becomes step 4's isolation step.

4. **Name the smallest next isolation / reproduction step, as a stated experiment**: ONE check with two discriminating outcomes, naming the failing test, written as `Experiment:` / `If <result> ⇒ <cause>` / `If <other result> ⇒ <other cause or re-open>`. The check is a run, or a comparison of the product's OUTPUT against the current spec. Reading the test, fixture, diff, or seed SOURCE is supporting context, never the step; so is the step-5 fix. Only an observed outcome of running this same experiment counts as already recorded (e.g. "3/3 reruns identical" for a rerun, "passes alone" for isolation): state the experiment, cite that outcome, go to step 5. A version, diff, rename, config value, or other context fact is cited as EVIDENCE for the hypothesis, never as a recorded result; the step still names the experiment. Per cause: order/timing → run the tests in randomised / reversed order (fails only after another test ⇒ order/state leak; still fails alone ⇒ re-open); fixture/data → run this one test in isolation against a freshly built fixture (still fails ⇒ the fixture itself is stale; passes ⇒ another test mutates the shared state); environment/dependency → reproduce the failing run's runtime/library version where the test passes, e.g. install it locally and re-run (reproduces ⇒ that version; still passes ⇒ re-open; pinning back is the fix); external-service → run with the boundary stubbed (passes ⇒ service dependence; still fails ⇒ re-open); test bug → compare the product output against the current spec / intended behaviour (output matches the spec while the test asserts the OLD value ⇒ stale TEST, not a product regression; output contradicts the spec ⇒ product regression); product regression → re-run the one test to reproduce the deterministic failure, optionally bisect to the implicated commit (fails every run ⇒ confirmed; passes ⇒ re-open). Stay host-neutral: describe the capability; prefer the narrowest scope that discriminates. A rerun is legitimate ONLY here and ONLY tied to a named hypothesis; a bare "run it again" is forbidden. Capture the real outcome before concluding.

5. **Decide the response from the confirmed cause — fix only a product gap** — once the isolation step confirms (or revises) the cause, state the next move WITHOUT editing production code here. Only a **product regression** is a product-behaviour gap: hand the specific wrong behaviour to `sumo-qa-implementing-with-tdd` (`regression-first`), or `sumo-qa-closing-qa-gaps` for an uncovered-gap loop. Every other cause is resolved in its own layer, production untouched: **test bug** → fix the test's assertion/expectation (strengthening → `sumo-qa-strengthening-tests`); **fixture/data** → repair or isolate the fixture/seed data, remove the cross-test leak; **environment/dependency** → align the environment (pin the version, fix the config/locale/clock), don't patch product code around it; **timing/order** → remove the order coupling or race with real synchronisation/isolation, not a sleep-and-pray or "quarantine and forget"; **external-service** → stub or contract-test the boundary. Do NOT normalise a flake as acceptable residual risk on your own authority — accepting it is the user's explicit, recorded decision.

## Process Flow

The Checklist above is the flow.

## Red Flags — STOP and rework

| Thought | Reality |
|---|---|
| "It's flaky — just rerun it until it's green" | A rerun is an experiment, not a fix — allowed only tied to a named hypothesis (order? timing? service?). "Run again and hope" hides the cause. |
| "The test is red, so the code is broken — patch it" | Maybe the TEST is wrong. Classify first: a test bug, stale fixture, or environment gap never licenses a production edit. |
| "I'll classify from the test name — obviously the cache test" | HARD-GATE: classify from the actual assertion and traceback or output lines, never the title. |
| "Passes locally, fails in CI — pin CI back and re-run" | Environment/dependency or order/timing, not the product. Reproduce CI's version locally first; pinning CI back is the fix, not the experiment. |
| "Two causes fit — I'll fix both to be safe" | Name the likelier and the one observation that discriminates them; that's your isolation step. |
| "Just one flaky test — mark it acceptable residual risk and move on" | Accepting a flake is the user's explicit, recorded call — not a default you make for them. |
| "Triage confirmed a regression — I'll fix it right here" | Triage hands off, it does not patch. Route the named product gap to `regression-first` / the gap-closing loop. |
| "The traceback already shows it's the fixture — next step is to read the SEED/fixture source" | Reading source is supporting context, not the smallest step. The step is the EXPERIMENT: run the test in isolation against a freshly built fixture — it discriminates "fixture wrong on its own" from "another test mutated shared state". |

## Examples

### Good (order dependence, isolation before any fix)

> User: *"`test_user_cache_hit` keeps failing in the full run but passes when I run it alone."*
>
> **AI:** *"Triaging this failure before any fix. Passing alone but failing in the full suite points away from the product, toward shared state or order: likely another test leaves the cache populated. Experiment: run the cache tests in randomised / reversed order. If it fails only after `test_user_cache_populate` ⇒ an order/state leak, not a cache bug. If it still fails alone after reordering ⇒ re-open toward a product cause. Can you run that and paste the result?"*

### Good (fixture/data failure, fix stays out of production)

> User pastes: `KeyError: 'GBP'` in `test_convert_to_gbp`, traceback ending in the test's `rates = load_rates()`.
>
> **AI:** *"Triaging this failure before any fix. The `KeyError: 'GBP'` is raised inside the test's fixture load (`load_rates()`), not the conversion code — so `convert()` never ran. That's a fixture/data problem, not a product regression. Experiment: run `test_convert_to_gbp` alone against a freshly built rates fixture. If it still fails ⇒ the fixture itself is stale. If it passes ⇒ another test is mutating the shared table. Either way the fix lives in the fixture setup; `convert()` stays untouched."*

### Bad (rerun-to-green + wrong-layer fix)

> **AI:** *"That test is flaky — I reran it three times and it went green, and added a `try/except` around the conversion in `convert.py` so it won't blow up again. All good."*
>
> Three violations: a rerun with no hypothesis treated as a fix, a flake silently normalised, and a fixture/data failure "fixed" by swallowing the error in PRODUCTION code.

## Next skill in the chain

Product regression confirmed → `sumo-qa-implementing-with-tdd` (`regression-first`), or `sumo-qa-closing-qa-gaps` for an evidenced uncovered-gap loop, handing over the specific wrong behaviour. Test/fixture-strengthening shape → `sumo-qa-strengthening-tests`. Other causes are fixed in their own layer (step 5); no fixing-skill handoff is owed.
