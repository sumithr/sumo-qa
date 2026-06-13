# Canonical QA approaches

Eleven canonical approaches the host LLM picks from when deciding the shape
of QA work. The LLM may invent a new approach if the situation genuinely
needs one, but it must explain why none of these eleven fit.

## strategy-orchestration
Repo-wide / policy-shaped ask: "design a test strategy", "audit our coverage",
"design our pyramid", "rollout to other services", "minimum viable QA setup".
Do NOT force per-change output. Next step is loading the
`sumo-qa-strategising` skill.

## tdd-scaffold
Greenfield-ish change adding behaviour. Plan -> scaffold -> red ->
implement -> green. Fits when production code is being written for new
functionality.

## regression-first
Bug fix on existing code. Reproduce the defect as one failing test, fix it,
confirm green, run targeted regression. Fits when the user describes a
specific defect on existing behaviour.

## coverage-first-then-refactor
Behaviour-preserving refactor (rename, extract method, split module, restructure
without changing outputs). Audit existing coverage and add characterization
tests BEFORE refactoring. Tests pin current behaviour so the refactor doesn't
silently change outputs.

## strengthen-test-coverage
Strengthen existing tests on UNCHANGED production code. Mutation-testing
follow-up, raise-coverage tasks, killing weak assertions. Production code
stays still. Equivalent mutants get suppressed in tool config rather than
chased with tautological tests.

## verify-existing
Config-only or trivial tweak that doesn't merit new tests. Run the existing
suite plus a smoke test. Fits when a config bump or mechanical edit needs
confirmation, not new coverage.

## no-tests-recommended
Pure docs / typos / comments. Build + lint, no QA test work. The honest
senior-QA answer when the change has no behavioural surface.

## spike-first-then-tests
Exploratory prototype. Defer test discipline until the design settles. The
deliverable is a captured-conditions-and-fit record, not scaffolded tests.

## recommend-removal
Orphan code: zero callers, no CI/docs/test refs, no entry-point
declaration. Propose deletion, not tests. Cite reachability in the
rationale. If ambiguous (external cron, public CLI), ask one question
first. STOP.

## closed-loop-gap-fix
QA evidence (review, mutation run, graded scenario) already names a
concrete uncovered behaviour gap; close it one evidenced loop per gap --
red, minimum change, green + regression, ledger update -- pausing on
insufficient repo context. Next step is loading the
`sumo-qa-closing-qa-gaps` skill.

## triage-test-failure
A test is failing or flaky and the cause is not yet known. Read the failure
output, classify the cause (product regression, test bug, fixture/data,
environment/dependency, timing/order, external service), and name the
smallest next isolation/reproduction step BEFORE any fix. Diagnosis only --
reruns only with a stated hypothesis; production code is touched only once a
concrete product-behaviour gap is confirmed (then route to `regression-first`
/ `closed-loop-gap-fix`). Next step is loading the
`sumo-qa-triaging-test-failures` skill.
