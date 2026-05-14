# Scenario 08 — Audit test coverage + design QA strategy

> **Summary:** *"the AI walked the repo, named per-area risks anchored to file paths, and gave a phased rollout with gates — not 'aim for 80% coverage'. This is what 'QA strategy' actually looks like."*
>
> Shows: repo walk before any question, per-area classification + named risks anchored to file paths, specialty-tool fit per surface, risk × gap prioritisation, risk-shaped pyramid (not uniform), phased rollout with named gates (not a calendar), residual risks named honestly, written deliverable on confirmation.

---

## Turn 1 — User

> Audit our test coverage across the customer-platform monorepo and design a QA strategy. We've got 4 services and a shared lib.

---

## Turn 2 — sumo-qa

*(internal: invokes `sumo-qa-deciding-approach`. Intent shape: repo-wide / policy-shaped — `strategy-orchestration`. Routes to `sumo-qa-strategising`.)*

*(internal: Iron Law — walk the repo first. Uses host's file tools to inventory `services/`, `shared/`, each `tests/` directory, root CI config, any coverage reports. Does NOT ask the user "what services do you have?".)*

> *Walked the tree:*
>
> - `services/auth/` — Python (FastAPI), 31 tests under `services/auth/tests/`, contract tests present in `tests/contracts/` but `git log` shows last touched 8 months ago.
> - `services/billing/` — Python, `services/billing/calculator.py` is 280 lines of pure-function pricing logic; 12 unit tests under `services/billing/tests/unit/`; no mutation-testing config (`mutmut`/`cosmic-ray` absent from `pyproject.toml`); no `tests/property/` dir.
> - `services/search/` — Python, HTTP layer + an integration test suite hitting a downstream indexer; `services/search/tests/integration/` has 8 tests; `tests/contracts/` directory is empty.
> - `services/notifications/` — Python, event-driven (consumes from a queue per `services/notifications/handlers/`); 18 unit tests; no e2e against a real queue (no `docker-compose.test.yml`, no `tests/e2e/`).
> - `shared/` — Python library: `shared/money.py`, `shared/clock.py`, `shared/idempotency.py`. 6 unit tests total. Imported by all 4 services (`grep -r "from shared"` confirms).
> - Root: `Makefile` runs `make test` → fans out to per-service `pytest`. CI is GitHub Actions (`.github/workflows/ci.yml`). No coverage report artefact in the workflow.

*(internal: loads `sumo_qa_load_principles()`, `sumo_qa_load_classifications()`, `sumo_qa_load_specialty_tools()`.)*

I've walked the monorepo. Here's the inventory before I dig into per-area risks — one thing to confirm before I go deeper.

**Inventory (5 areas, not 4 — `shared/` is consumed by all four services and is doing real work):**

| Area | Stack | Tests on disk | Coverage shape (provisional) |
|---|---|---|---|
| `services/auth/` | Python / FastAPI | 31 unit + stale contracts (`tests/contracts/`, last touched 8 months ago) | HTTP-contract-heavy, contracts rotting |
| `services/billing/` | Python (pure logic) | 12 unit, no mutation config, no property tests | Unit-thin on pure logic — biggest gap |
| `services/search/` | Python + downstream indexer | 8 integration, `tests/contracts/` empty | Integration-only, no consumer-side contract |
| `services/notifications/` | Python, queue-driven | 18 unit, no e2e against real queue | Unit-heavy, async surface untested end-to-end |
| `shared/` | Python lib, imported by all 4 | 6 unit | Lowest blast-radius coverage relative to consumers |

CI is `make test` → per-service pytest; no coverage artefact published; contract-test directory exists for `auth` and `search` but is stale / empty respectively.

**One thing to confirm before I walk per-area risks:** are all 5 areas in scope (including `shared/`), or just the 4 services your team owns end-to-end? And anything I missed — a separate frontend repo, an SDK, anything not under `services/` or `shared/`?

---

## Turn 3 — User

> All 5 in scope — we own the whole monorepo. No frontend in this repo; there's a portal team but they're outside scope. Team is 8 engineers, weekly release, no formal regulator but billing has PCI scope on the calculator path.

---

## Turn 4 — sumo-qa

Good — PCI on the calculator path changes how heavily I'll weight billing. Here are per-area named risks. Each anchored to a file or framework construct; tell me which to add / remove / re-anchor before I move to tool fit.

> **`shared/` — domain lib, fan-out blast radius**
> - **R1.1** `shared/money.py:18` — rounding-mode default is `ROUND_HALF_EVEN` (banker's rounding) but billing's calculator assumes `ROUND_HALF_UP` in two places (`calculator.py:142`, `:201`). No test pins which behaviour is canonical. PCI-adjacent.
> - **R1.2** `shared/idempotency.py` — `make_key()` derives from arg ordering; if a caller swaps named-arg order between releases, key changes silently. No regression test pinning this.
> - **R1.3** Version drift — `shared/` is imported as a path dep, not a versioned package. A breaking change ripples to all 4 consumers in one PR with no compile-time signal.
>
> **`services/billing/` — pure-logic, PCI scope**
> - **R2.1** `services/billing/calculator.py:apply_charges` is 8 branches deep and has 4 unit tests, no mutation testing. High likelihood of surviving mutants on the inner conditionals (`>`/`>=`, off-by-one on tier boundaries).
> - **R2.2** `services/billing/calculator.py:227` — currency-conversion order-of-operations (convert-then-round vs round-then-convert) is encoded implicitly. No test asserts which order is contractually correct; one of those is wrong by 1p on edge cases.
> - **R2.3** `services/billing/refund.py:apply_partial` — partial-refund precision relies on `shared/money.py` rounding (see R1.1). Cross-area coupling.
>
> **`services/auth/` — HTTP-contract-heavy, contracts rotting**
> - **R3.1** `tests/contracts/` last touched 8 months ago — `auth` ships a JWT shape that the portal team consumes. No CI gate failing on a contract drift; the contracts are decorative.
> - **R3.2** `services/auth/middleware/rate_limit.py` — 100 req/min/IP, sliding window. No boundary test at the 100→101 transition; no test for clock-skew under load.
>
> **`services/search/` — integration-only, no consumer-side contract**
> - **R4.1** `services/search/client/indexer.py` — talks to a downstream indexer over HTTP. No `tests/contracts/` for the response shape; if the indexer team renames a field, we discover in prod.
> - **R4.2** `services/search/handlers/query.py:retry` — retry-on-partial-failure path has no idempotency test. Re-issuing a `POST /index/bulk` after a partial 5xx could double-index.
>
> **`services/notifications/` — async, unit-heavy, no real-queue e2e**
> - **R5.1** `services/notifications/handlers/dispatch.py` — message-handler ordering when two consumers are scaled out. No test exercising this; relies on broker FIFO assumption.
> - **R5.2** DLQ flow (`handlers/dlq.py`) — entirely untested. A poison message would silently park.
> - **R5.3** No e2e against a real queue — all tests stub the broker. Schema-fuzz / contract drift on the message envelope is invisible.

Match how the team would describe these? Add / remove / re-anchor anything before I move to specialty-tool fit?

---

## Turn 5 — User

> Spot on. One add: on auth, the rate-limit is also enforced by an edge proxy in prod — the in-service limiter is defence-in-depth, so R3.2 is real but lower severity. On notifications, R5.2 (DLQ) is the one that's bitten us before.

---

## Turn 6 — sumo-qa

Noted — R3.2 demoted, R5.2 bumped. Here's the specialty-surface fit per area. I'm matching tools to the actual surface, not by familiarity, and I'm offering to install + seed for the Phase 1 picks once we agree on prioritisation.

| Area | Specialty surface visible | Best-fit tool | Why this one |
|---|---|---|---|
| `shared/` | Pure functions w/ algebraic invariants (rounding, idempotency-key stability) | **Hypothesis** (property-based) + **mutmut** | Rounding and key-derivation are exactly the surface property-based testing exists for. Mutation testing tells us whether the property tests are actually doing work. |
| `services/billing/` | Branch-heavy pure logic, PCI-adjacent | **mutmut** (mutation) + **Hypothesis** for invariant-style tests on `calculator.py` | `apply_charges` is the textbook mutation-testing target — 8-branch function, low unit count. PCI scope means mutation evidence is auditable. |
| `services/auth/` | HTTP contract (JWT shape, error shapes) | **Schemathesis** (OpenAPI-driven) for contract regression; **Pact** only if portal team will run consumer side | Contracts exist but are stale. Schemathesis off the OpenAPI spec is the cheapest restart; Pact is heavier and needs the other side to participate. |
| `services/search/` | HTTP boundary to indexer + retry semantics | **Schemathesis** on the indexer client + a recorded-response test (`vcrpy` or `responses`) for retry/idempotency paths | The indexer is owned by another team. A consumer-side contract test is the only signal we'll get before prod. |
| `services/notifications/` | Async / queue, DLQ flow, multi-consumer ordering | **Testcontainers** for a real broker in CI + targeted **schema fuzz** on the message envelope | Stubbing the broker is exactly what hid R5.1 + R5.2. A real broker in CI is the only honest test. |

A few I'm explicitly NOT recommending: no Cypress / Playwright (no UI in this repo); no k6 (no perf target named as a quality characteristic yet — adding load tests "in case" is theatre); no SCA/SAST tooling decisions here — that's security review's lane.

If you confirm prioritisation in the next step, I can run the install + seed for the Phase 1 picks now: `mutmut` + a baseline `Hypothesis` test against `shared/money.py` rounding, and `Testcontainers` wiring for the notifications DLQ test. That's a real working baseline by end of the session, not slideware.

Any tool I should drop, swap, or add before we prioritise?

---

## Turn 7 — User

> Looks right. Keep going.

---

## Turn 8 — sumo-qa

Prioritisation by `risk × current-coverage-gap` — ISTQB Principle 2, exhaustive testing is impossible, so we go where the gap is widest and the blast radius is largest. PCI scope on billing and the bitten-us-before DLQ flow rise to the top.

| Rank | Area | Risk weight | Coverage gap | Phase |
|---|---|---|---|---|
| 1 | `services/billing/` (calculator + refund) | High (PCI, branch-heavy) | Wide (12 unit, no mutation, no property) | **Phase 1** |
| 2 | `shared/` (money, idempotency) | High (fan-out to all 4 services) | Wide (6 unit, no property) | **Phase 1** |
| 3 | `services/notifications/` DLQ + ordering | High (already bit us — R5.2) | Wide (stubbed broker only) | **Phase 2** |
| 4 | `services/search/` indexer contract | Medium (external boundary, but failure is loud) | Medium (integration tests exist) | **Phase 2** |
| 5 | `services/auth/` contracts refresh | Medium (edge proxy is defence-in-depth — R3.2 demoted) | Medium (stale, not absent) | **Phase 3** |

Target pyramid, risk-shaped (not uniform — the whole point):

> **`shared/`** — heavy property + mutation (unit-style); no integration; no e2e of its own (its consumers test it transitively).
>
> **`services/billing/`** — heavy unit + property + mutation; one thin integration suite at the HTTP boundary; no e2e.
>
> **`services/notifications/`** — moderate unit; **integration against a real broker via Testcontainers is the load-bearing layer**, not unit; one e2e for the DLQ round-trip.
>
> **`services/search/`** — moderate unit; consumer-side contract (Schemathesis) is the load-bearing layer; one integration smoke.
>
> **`services/auth/`** — moderate unit; **refreshed HTTP contracts are the load-bearing layer**; rate-limit boundary unit test (R3.2 — defence-in-depth, light).

Does the ordering and the pyramid shape match where you'd invest first? Anything to shift?

---

## Turn 9 — User

> Yes, agreed. Show me the phased rollout.

---

## Turn 10 — sumo-qa

Phases are a sequence with **named gates**, not a calendar. Each phase only ends when its gate is satisfied — moving to the next phase before the gate is just deferring the problem.

> **Phase 1 — Stop the PCI bleed + pin the fan-out lib**
> *Scope:* `services/billing/calculator.py`, `services/billing/refund.py`, `shared/money.py`, `shared/idempotency.py`.
> *Deliverables:*
> - `mutmut` configured against `services/billing/` and `shared/`; baseline mutation score recorded in CI.
> - `Hypothesis` property tests pinning: rounding-mode contract for `shared/money.py`, idempotency-key stability for `shared/idempotency.py`, currency-conversion order-of-operations for `calculator.py:227`.
> - Targeted unit tests for the 8 branches in `apply_charges` (R2.1).
> - CI publishes coverage + mutation-score artefacts on every PR touching these paths.
> *Gate to exit Phase 1:* mutation score ≥ 75% on `services/billing/calculator.py` AND `shared/money.py`; zero surviving mutants on any rounding or idempotency-key path; the rounding-mode contract test names the canonical rounding mode (no implicit assumption left).
>
> **Phase 2 — Make async honest + pin the external boundary**
> *Scope:* `services/notifications/` (especially DLQ + multi-consumer ordering), `services/search/client/indexer.py`.
> *Deliverables:*
> - `Testcontainers` broker in CI for notifications; integration tests for DLQ poison-message flow (R5.2) and multi-consumer ordering (R5.1).
> - `Schemathesis` contract test for the search-indexer client; recorded-response idempotency test for the retry path (R4.2).
> - Schema-fuzz on the notification message envelope.
> *Gate to exit Phase 2:* DLQ round-trip integration test green against a real broker in CI; a deliberately-mutated indexer response shape fails the search contract test in CI (proof the gate actually catches drift).
>
> **Phase 3 — Refresh the rotting contracts**
> *Scope:* `services/auth/` HTTP contracts + the light rate-limit boundary test.
> *Deliverables:*
> - `tests/contracts/` for auth regenerated from the current OpenAPI spec; Schemathesis run in CI on PRs that touch `services/auth/`.
> - One boundary unit test at the 100→101 sliding-window edge for the in-service rate limiter (R3.2 — defence-in-depth).
> *Gate to exit Phase 3:* a deliberate change to the JWT response shape on a branch fails the contract test in CI; auth's contract tests have a "last touched" age < 1 sprint.
>
> **Cross-cutting (lives across all phases):** publish per-PR coverage + mutation deltas in the CI summary; team rule that any PR touching `services/billing/calculator.py` or `shared/money.py` requires a green mutation-score check.

Phase shape look right? Anything to split or merge before I name residual risks?

---

## Turn 11 — User

> Looks right. Residuals please, then write it up.

---

## Turn 12 — sumo-qa

Residual risks — what this strategy explicitly does NOT cover, and why. Every strategy has them; pretending otherwise is consulting fiction.

> **RR1 — Performance / load testing.** No phase introduces it. Reason: no quality characteristic for throughput or latency is currently named as at-risk. If billing's calculator becomes a hot path or notifications backs up under burst, this becomes Phase 4 — not before. Adding generic load tests now is theatre.
>
> **RR2 — Cross-service end-to-end tests.** Out of scope. Reason: this is a 4-service monorepo with 8 engineers; contract tests at each boundary are cheaper signal than maintaining an e2e harness. Re-evaluate if the contract tests stop catching real defects.
>
> **RR3 — Portal-side (external consumer) contract participation.** The portal team consumes `auth`'s JWT shape; they're outside scope. Phase 3 hardens our side (Schemathesis off our OpenAPI), but if the portal doesn't run their consumer-side test, drift detection is still half-blind. Recommend a one-meeting alignment with that team after Phase 3 — not a deliverable here.
>
> **RR4 — Security testing (SAST / DAST / dependency scanning).** Deliberately not in this strategy. Different discipline, different cadence, different owner; lumping it in would dilute both. Recommend a separate security-strategy pass with the security review skill.

If that's honest, I'll assemble the document.

---

## Turn 13 — User

> Honest. Write it up.

---

## Turn 14 — sumo-qa

Assembling the confirmed sections (inventory → prioritisation → specialty fit → pyramid → phased rollout → residual). I'll write to `docs/qa-strategy.md` — that path doesn't exist yet (checked) so this is a new file, not an overwrite.

Confirm and I'll write it now, then run the Phase 1 install + seed I offered earlier (`mutmut` + baseline `Hypothesis` test on `shared/money.py` rounding + Testcontainers wiring stub).

*(awaits confirmation; on yes → writes `docs/qa-strategy.md`, then proceeds to install Phase 1 tooling and seed the first test against R1.1 / R2.2 — the rounding contract — red-first, hands off for the green phase.)*

---

## Why this is senior QA

- **Walked the repo before asking anything.** Inventory came from the file system — 5 areas, not the 4 the user mentioned, because `shared/` is doing real work. A junior consultant would have asked "what services do you have?". This one read the tree.
- **Risks anchored to file + construct.** Not *"add more unit tests on billing"* — `services/billing/calculator.py:227 — currency-conversion order-of-operations not pinned by test`. Every risk cites a path the user can `cat`.
- **Tool fit per surface, not per habit.** No Cypress where there's no UI. No k6 where no perf target is named. `Testcontainers` only where a stubbed broker is the actual blind spot. The agent says explicitly what it is NOT recommending and why.
- **Risk-shaped pyramid, not uniform.** `shared/` is property-heavy with no integration of its own. `notifications/` is integration-heavy because the unit layer cannot test the failure mode that bit them. The pyramid bends to the risk surface.
- **Phases are sequences with named gates, not a calendar.** Phase 1 doesn't end at "two weeks"; it ends at *"mutation score ≥ 75% on calculator.py AND money.py, zero surviving mutants on any rounding or idempotency-key path"*. Phase 2 ends with a deliberately-mutated indexer response failing CI — proof the gate works.
- **Confirmation gates between every section.** Scope → per-area risks → tool fit → prioritisation → pyramid → rollout → residual. Each one was a separate turn, each one the user could redirect — and the user *did* redirect (R3.2 demoted, R5.2 bumped). A single-turn dump cannot absorb that signal.
- **Residual risks named honestly.** Performance, cross-service e2e, portal-side participation, security — explicitly out of scope, with reasons. Not "none — this strategy is comprehensive".
- **The deliverable is real work, not a deck.** Writes `docs/qa-strategy.md` on confirmation, then offers to install Phase 1 tooling and seed the first red test against the named rounding-mode risk. Strategy lands in code, not in a wiki page.

This is what *"senior QA strategy"* looks like in practice: the repo gets walked, the risks have file paths, the gates are evidence-shaped, and Phase 1 starts before the conversation ends.
