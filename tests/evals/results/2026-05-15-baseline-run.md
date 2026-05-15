# 25-scenario baseline run — 2026-05-15

First end-to-end run of the eval harness landed in PR #36, against `main` at commit `13edaf0…`.

## Headline

**6 PASS / 19 FAIL = 24%.** Well below the 95% target. The result is honest evidence about both the agent under test *and* the eval methodology itself.

## Per-scenario verdicts

### Tool-selection (6/10 PASS = 60%)

| Scenario | Verdict | Worst item | Category |
|---|---|---|---|
| TS-01 (`load_classifications`) | **PASS** | — | — |
| TS-02 (`load_approaches`) | **PASS** | — | — |
| TS-03 (`load_principles`) | FAIL | `RESULT USE` | Agent paraphrased instead of tying to returned catalogue output |
| TS-04 (`load_techniques`) | **PASS** | — | — |
| TS-05 (`load_standards` filtered) | **PASS** | — | — |
| TS-06 (`load_rules` filtered) | **PASS** | — | — |
| TS-07 (`explain_test_data_requirements`) | FAIL | `ARG SHAPE` | Agent missed `domain="billing"` kwarg |
| TS-08 (`find_test_data`) | FAIL | `ARG SHAPE` | Agent's first call shape didn't fully match spec |
| TS-09 (`validate_test_data`) | **PASS** | — | — |
| TS-10 (`register_known_good_test_data`) | FAIL | `SELECTION` | Agent correctly asked confirmation before calling — rubric expected immediate invocation |

### Skill-behaviour (0/15 PASS = 0%)

| Scenario | Verdict | Worst item | Category |
|---|---|---|---|
| SCN-01 (preparing-for-work) | FAIL | `shape_1: use host file tools to read referenced files` | Env mismatch — billing files don't exist; agent acknowledged + named 7 anchored risks |
| SCN-02 (reviewing-before-merge) | FAIL | `shape_6: HARD GATE runs tests in this turn` | **Real Iron Law miss** — agent named risks but didn't run `pytest` |
| SCN-03 (implementing-with-tdd / regression-first) | FAIL | `shape_5: runs failing test + surfaces red` | Env mismatch — `pricing/discount_calculator.py` doesn't exist; can't write test |
| SCN-04 (implementing-with-tdd / tdd-scaffold) | FAIL | `shape_4: writes test, runs it, shows red` | Env mismatch — no auth service |
| SCN-05 (strengthening-tests) | FAIL | `shape_4: writes test, runs it, reruns Pitest` | Env mismatch — no Pitest report; no production file |
| SCN-06 (answering-testing-question) | FAIL | `shape_1: grounds in supplied code OR asks one clarification` | **Real miss** — agent answered without asking for one specific clarification |
| SCN-07 (finding-test-data) | FAIL | `shape_2: calls find_test_data with question + staging + billing + criteria` | **Real miss** — agent searched but missed some args |
| SCN-08 (strategising) | FAIL | `shape_2: per-area provisional analysis with classification + coverage shape + named risks citing paths` | Env mismatch — agent honestly noted the named monorepo doesn't exist; offered to audit sumo-qa instead |
| SCN-09 (creating-test-plan) | FAIL | `shape_2: explicit entry AND exit criteria HARD GATE` | **Spec overconstraint** — Iron Law says walk section-by-section; shape_2 wants both criteria in first turn |
| SCN-10 (deciding-approach / no-tests-recommended) | FAIL | `shape_5: offers lightweight render verification follow-up` | **Real miss** — agent offered `git diff` instead of `mkdocs serve` |
| SCN-11 (using-sumo-qa router) | FAIL | `shape_4: handoff is transparent, no routing announcement` | **Real miss** — agent surfaced *"Routing this QA intent"* announcement |
| SCN-12 (planning-qa-rollout) | FAIL | `shape_6: final deliverable is markdown plan file in docs/qa/plans` | **Spec overconstraint** — Iron Law says walk section-by-section, anti-pattern says don't dump; shape_6 wants the final file |
| SCN-13 (executing-qa-rollout) | FAIL | `shape_2: one fresh subagent per task, parallel for independent` | Env mismatch — plan file doesn't exist; agent refused to fabricate execution |
| SCN-14 (finishing-qa-work) | FAIL | `shape_2: captures risk-to-test map with covering test per risk` | Env mismatch — no named QA run to wrap up |
| SCN-15 (suggesting-external-skill) | FAIL | `shape_4: names find-skills and skills.sh with citation` | **Borderline real miss** — named both but no URL citation for skills.sh |

## Failure categorisation

| Category | Count | Implication |
|---|---|---|
| Real agent miss (sumo-qa skill needs tightening) | 5 (SCN-02, 06, 07, 10, 11; + TS-03, 07, 10) | Fixable by skill rewrites |
| Spec overconstraint (Iron Law contradicts shape beat) | 2 (SCN-09, 12) | Fixable by spec calibration |
| Environment mismatch (scenario references files that don't exist) | 8 (SCN-01, 03, 04, 05, 08, 13, 14) | Fixable by either per-scenario sandbox setup OR scenario rewrite |
| Borderline judgment call | 1 (SCN-15) | Either spec calibration or accept |
| **PASS** | **6** | Working as intended |

## What the eval is teaching us

The harness **works** — verdicts are structured, the Codex judge is genuinely adversarial (no rubber-stamping), and quoted-span evidence makes each verdict auditable. The 24% baseline is honest: the candidate agents really did miss what they're flagged for missing.

But the **rubric/scenario coupling is too brittle** for a first-turn-against-arbitrary-repo eval. Most real-world QA scenarios assume a target repo with specific files; running them in sumo-qa's own repo gives the agent no way to satisfy file-creation, test-running, or repo-walking beats against the named targets.

## What needs to happen to hit 95%

This is more work than a single PR. Path forward (in priority order):

1. **Restrict scope to environment-independent scenarios** (immediate). The 7 abstract SCN (02, 06, 10, 11, 14, 15 + maybe 07) + 10 TS = 17 scenarios. Current PASS rate on these alone: ~6/17 = 35%. Target 95% on this restricted set is 16/17 — achievable with skill rewrites for the 5–6 real misses above.

2. **Per-scenario sandbox environments** (substantial). For SCN-01/03/04/05/08/12/13/14, create `tests/evals/sandboxes/SCN-XX/` with stub files (`services/billing/refund.py`, `pricing/discount_calculator.py`, etc.) so the agent can actually walk and create against expected paths. Each subagent dispatched with `cwd=tests/evals/sandboxes/SCN-XX/`. Roughly 1 day of work to set up + iteration to tune.

3. **Spec calibration on the 2 overconstrained scenarios** (SCN-09, 12). The Iron Law of the skill ("walk section-by-section, no single-shot dump") contradicts the rubric's first-turn expectation of a final deliverable. Either soften the rubric's first-turn expectation, or treat these as multi-turn evals (the harness currently captures one turn only).

4. **Skill rewrites for the 5 real misses** (focused effort).
   - `sumo-qa-reviewing-before-merge`: tighten HARD GATE so agent CANNOT skip `pytest` in this turn (SCN-02 fix).
   - `sumo-qa-answering-testing-question`: enforce "ask one focused clarification if no code supplied" (SCN-06 fix).
   - `sumo-qa-finding-test-data`: enforce full arg-shape on `find_test_data` calls (SCN-07 + TS-08 fix).
   - `sumo-qa-deciding-approach`: per-classification follow-up suggestions (SCN-10 fix — for docs_change, suggest render verification not just diff).
   - `using-sumo-qa`: forbid surfacing the routing announcement (SCN-11 fix).

5. **Multi-turn eval support** (future). Some scenarios are multi-turn by design (planning → confirmation → execution). The current harness captures only the first turn. Adding multi-turn support unlocks SCN-09/12/13/14 to be evaluated honestly.

## Provisional decision points (need user direction)

- Is the goal *"the agent passes 95% of scenarios as currently written"* (needs paths 1–5 above; substantial work) OR *"the harness gives us reliable signal on whether sumo-qa is working"* (path 1 — restricted scope — already gives us that)?
- Are scenarios SCN-09 and SCN-12 actually testing the wrong thing for a first-turn eval, or should they be split into per-turn assertions?
- Should we invest in scenario sandboxes (option 2) or restrict scope (option 1) as the next move?
