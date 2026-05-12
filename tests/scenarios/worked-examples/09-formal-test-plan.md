# Scenario 09 — Create a formal test plan

> **Demo arc:** *"the AI didn't give a 'do the tests, sign off' plan. It walked the user through measurable entry criteria, phased gates, exit criteria — and even named what risks it's NOT going to cover and why."*
>
> Shows: the Iron Law of this skill made visible (no plan without explicit entry/exit), section-by-section pacing with confirmation gates, measurable entry criteria anchored to the search-relevance domain (NDCG, golden query set, shadow-traffic harness), phases that end at named gates not calendar dates, residual risks named honestly with mitigation reasoning.

---

## Turn 1 — User

> Create a formal test plan for the Q3 search-relevance launch. We need entry/exit criteria the team can sign off on.

---

## Turn 2 — sumo-qa

*(internal: invokes `qa-deciding-approach`. Intent reads as a formal, sign-offable artefact — heavier than `qa-preparing-for-work`. Routes to `qa-creating-test-plan`. Loads `sumo_qa_load_classifications`, `sumo_qa_load_standards`, `sumo_qa_load_techniques`, `sumo_qa_load_specialty_tools`.)*

*(internal: walks the repo for the scope. Finds `search/relevance/Ranker.kt`, `search/relevance/features/*.kt`, `search/eval/GoldenQuerySet.kt`, the `shadow-traffic` harness under `infra/shadow/`, existing `RankerTest.kt` and `GoldenQuerySetTest.kt`. Reads CI config — there's a `search-relevance` pipeline that runs NDCG@10 on every PR.)*

Before I draft anything, I want to flag the iron rule of this skill so you know what I'm refusing to do:

> **No test plan from me without explicit, measurable entry and exit criteria.** Not "team is ready", not "tests pass" — concrete preconditions and concrete ship-gates the team can argue against in a release review.

I'll walk us through the plan one section at a time — scope, risks, entry criteria, phases, exit criteria, residual risks — and ask for your confirmation between each. A single-shot dump is a wishlist; this is a plan.

Here's what I found in the repo so I can scope this honestly:

**Scope I can see:**

| Surface | Where it lives |
|---|---|
| Core ranker | `search/relevance/Ranker.kt` — the BM25 + learned-features blend you're shipping |
| Feature extractors | `search/relevance/features/*.kt` — 7 features, 2 of them new this quarter (`recencyDecay`, `personalisedAffinity`) |
| Golden query set | `search/eval/GoldenQuerySet.kt` + `resources/golden-queries.json` (340 labelled queries) |
| Offline eval | `search/eval/NDCGEvaluator.kt` — runs NDCG@1/@5/@10 in CI |
| Shadow-traffic harness | `infra/shadow/` — replays live traffic against new + old ranker, diffs results |
| Existing tests | `RankerTest.kt` (unit), `GoldenQuerySetTest.kt` (offline-eval gate at NDCG@10 ≥ 0.72) |

**One thing I need to pin before risks:** the launch plan I can see in CI talks about "Q3 launch" but the rollout knob in `infra/shadow/RolloutConfig.kt` has three stages — shadow → 5% canary → 100%. **Is the plan you want me to write covering all three stages through to 100%, or just up to the canary gate? That changes the exit criteria materially.**

---

## Turn 3 — User

> All three stages, through 100%. The canary gate is where most of the argument happens with stakeholders, but the plan needs to cover what "done" looks like at 100%.

---

## Turn 4 — sumo-qa

Good — that's the shape I'll plan to. Here are the named risks I've drawn from the code and the launch surface. Anchored to file paths and domain terms; tell me if any are wrong-shaped or if I'm missing one before we move to entry criteria.

> **R1 — `features/RecencyDecay.kt`** — new feature, half-life parameter is tuned offline on the golden set but the live query-time distribution skews older than the golden set. **Risk:** offline NDCG looks fine; live click-through-rate on news-shaped queries regresses because recency is over-weighted for evergreen intents.
>
> **R2 — `features/PersonalisedAffinity.kt`** — new feature, uses the user-affinity vector that's been live in recommendations but never in search. **Risk:** cold-start users (no affinity history) get a zero-vector contribution that biases the blend toward popularity; signed-out traffic regresses.
>
> **R3 — `Ranker.kt:84` (blend weights)** — weights are constants tuned on the golden set; not feature-flagged independently of the rollout knob. **Risk:** if a weight needs an emergency tweak during canary, the only lever is a full rollback. No per-feature kill switch.
>
> **R4 — `GoldenQuerySet.kt`** — 340 labelled queries, last refreshed 11 months ago. **Risk:** golden-set drift; the offline NDCG gate may be passing against yesterday's intent distribution. A green offline number doesn't guarantee a green live number.
>
> **R5 — `infra/shadow/` harness** — replays live traffic but doesn't replay session state or user-affinity at the time of the original query. **Risk:** shadow diffs under-report the personalisation impact (R2's blast radius), because the shadow runs see "fresh" affinity, not the affinity the live user actually had.
>
> **R6 — observability** — `Ranker.kt` emits a single `ranker.score` metric but no per-feature contribution. **Risk:** if NDCG regresses at canary, we can't tell which feature is responsible without a code change. Slows MTTR.

Match how you'd describe the risk surface? Anything to add, remove, or re-anchor?

---

## Turn 5 — User

> Spot on, and you've named two I hadn't articulated (R5 and R6). Keep all six. Move on.

---

## Turn 6 — sumo-qa

### Entry criteria — what must be true before we START testing

These are the iron-rule half of the plan: each is observable, with a number or a yes/no the team can verify. No "team is ready" — that's not a criterion, that's a hope.

| # | Entry criterion | How it's checked |
|---|---|---|
| E1 | Golden query set refreshed within the last 30 days; ≥ 340 labelled queries; intent-distribution drift vs. live traffic within 10% per intent bucket | `search/eval/QuerySetFreshness.kt` script (exists, currently unused in CI) |
| E2 | Baseline NDCG@10 ≥ 0.72 on the refreshed golden set, reproducible on a clean CI run | `GoldenQuerySetTest.kt` — already the merge gate; rerun post-refresh |
| E3 | All P0 search-index integration tests green on the target index version | `search-relevance` CI pipeline, P0 tag filter |
| E4 | Shadow-traffic A/B harness deployed in staging, replaying ≥ 24h of production query stream with affinity-snapshot replay enabled (closes R5) | `infra/shadow/` health endpoint + a one-off replay-fidelity check |
| E5 | Per-feature contribution metric (`ranker.feature_contribution{feature=...}`) emitted by `Ranker.kt` and visible in the search-relevance dashboard (closes R6) | Dashboard panel exists + non-zero datapoints in the last hour |
| E6 | Per-feature kill switch wired for `recencyDecay` and `personalisedAffinity` independently of the rollout knob (closes R3) | Feature-flag config review + one staging toggle-off / toggle-on round-trip |

A few of these (E4, E5, E6) are pre-work the team needs to do before testing starts — not just observations. That's deliberate: those risks have to be mitigated *before* we put traffic on this thing, not after we find the regression.

**Does this entry-criteria list match what your team would sign off on at a release readiness review? Anything aspirational here that I should drop, or anything I've missed?**

---

## Turn 7 — User

> E1–E6 are all defensible. Add one: we need legal sign-off on the personalisation feature for signed-in EU traffic before we even shadow-test it. Call it E7.

---

## Turn 8 — sumo-qa

Added. E7 is good — it's the kind of entry criterion that's easy to leave implicit and then trip over at the last minute.

| # | Entry criterion | How it's checked |
|---|---|---|
| E7 | Legal sign-off on `personalisedAffinity` for signed-in EU traffic, recorded in the launch ticket | Linked approval in the rollout ticket; absence blocks E4 from starting on EU shadow traffic |

### Phases — each ends at a named gate, not a calendar date

> Calendar dates lie; gates don't. The phase ends when its named condition is true, not when the date arrives.

| Phase | Deliverables | Gate to exit |
|---|---|---|
| **P1 — Analysis & refresh** | Refreshed golden query set; documented intent-distribution snapshot vs. live; per-feature kill-switch config; per-feature contribution metric live in staging | **All entry criteria E1–E7 met.** |
| **P2 — Offline evaluation** | NDCG@1/@5/@10 on refreshed golden set; A/B offline comparison (old ranker vs. new) with per-intent-bucket breakdown; bias audit on cold-start segment (R2) | **NDCG@10 ≥ baseline + 0.02 on refreshed set AND no intent bucket regresses by > 0.03 AND cold-start NDCG@10 not worse than old ranker by > 0.01.** |
| **P3 — Shadow traffic** | 7 days of shadow replay against ≥ 24h of live traffic per day, with affinity-snapshot replay; per-feature contribution audit; latency p95 + p99 comparison | **Shadow CTR-proxy within ±2% of live AND p95 latency delta ≤ 5ms AND no feature contributes > 40% of total score on any intent bucket (concentration check).** |
| **P4 — 5% canary** | Live canary on 5% of traffic, 72h minimum, with per-feature contribution telemetry and per-segment NDCG-proxy dashboards | **Canary NDCG-proxy ≥ baseline on every monitored segment for 72h continuous AND zero P0/P1 search incidents attributable to the ranker AND per-feature kill-switches verified actuatable in production.** |
| **P5 — 100% rollout** | Full rollout; golden-set refresh cadence handed to BAU; ranker-tuning runbook published | **All P4 conditions held for an additional 72h post-100% AND on-call runbook for "ranker NDCG regression" reviewed and signed by the on-call rotation.** |

**Phase shape look right? Anything to split, merge, or add — particularly around the canary→100% transition, since you mentioned that's where stakeholder argument lives?**

---

## Turn 9 — User

> Phase shape is right. One adjustment: P4's "72h continuous" should be 72h *business-hours* continuous — weekends have a different traffic mix and we've been bitten by that. Otherwise ship it.

---

## Turn 10 — sumo-qa

Noted — P4 gate updated to *"72h continuous business-hours window"*. Good catch; weekend-mix as a confound is exactly the kind of thing I couldn't have inferred from the code.

### Exit criteria — what must be true to call the launch DONE

These are the gates at 100% rollout. Tautologies like "tests pass" are forbidden — every exit criterion below is observable and arguable.

| # | Exit criterion |
|---|---|
| X1 | Every named risk R1–R6 has at least one passing test or live monitor that would catch its specific failure mode (mapping in the appendix of the written plan) |
| X2 | NDCG@10 on the refreshed golden set is ≥ baseline + 0.02 AND no intent bucket has regressed by > 0.03 |
| X3 | Live NDCG-proxy at 100% rollout has held ≥ baseline on every monitored segment (signed-in, signed-out, EU, non-EU, cold-start) for ≥ 72h business-hours post-rollout |
| X4 | Zero P0 and zero P1 incidents attributable to the ranker during canary + first 72h business-hours at 100% |
| X5 | Per-feature kill-switches actuated at least once in production (planned drill) and verified to take effect within 60s |
| X6 | Search latency p95 delta ≤ 5ms and p99 delta ≤ 15ms vs. the pre-launch baseline |
| X7 | Runbook for "NDCG regression at p50/p95/p99 ranker.score" reviewed and signed by the on-call rotation, with the per-feature kill-switch procedure documented and dry-run once |

**Do these match what you'd defend in a release-review meeting? In particular: X5 (planned kill-switch drill in production) is the one I expect pushback on — fine to drop if the team won't sign off on a live drill, but the alternative is to accept R3 as a residual.**

---

## Turn 11 — User

> Keep X5 — we'll do the drill. Move to residuals.

---

## Turn 12 — sumo-qa

### Residual risks — what we are NOT covering, and why

Every plan has these. Naming them is the honest part of the work; pretending they don't exist is what gets a launch into a post-mortem.

> **RR1 — Long-tail query intent drift over months, not weeks.** The plan covers a 30-day golden-set freshness window; queries whose intent meaning shifts gradually (e.g. a product name that becomes a brand) won't be caught until the next refresh cycle. **Mitigation accepted:** quarterly golden-set refresh cadence is in the BAU handover (P5 deliverable). **Why accepted:** the cost of a continuous-drift detector exceeds the expected harm at our query volume; revisit if R1-style regressions recur.
>
> **RR2 — Adversarial / SEO-gaming response to the new `recencyDecay` weighting.** Once recency matters more, content producers will adjust. We are not testing for adversarial-content patterns in this plan. **Mitigation accepted:** the trust & safety team owns adversarial-content monitoring; flagged to them via the launch ticket, but explicitly out of scope here. **Why accepted:** they have specialised tooling we don't; duplicating it in this plan would be wasted effort.
>
> **RR3 — Affinity-vector model drift upstream.** The `personalisedAffinity` feature consumes a vector produced by the recommendations team. If their model retrains and shifts vector semantics, our blend weights become wrong. **Mitigation:** alerting on a `affinity.vector_distribution_shift` metric, owned by the recommendations team. **Why accepted (with mitigation):** we don't own that model; coupling our launch to their retraining cadence would extend the plan indefinitely.

**Is this honest? Anything you'd add, or any of these you'd argue belongs in the in-scope exit criteria rather than the residuals?**

---

## Turn 13 — User

> Honest. RR2 in particular is one I'd usually see waved away. Write the plan.

---

## Turn 14 — sumo-qa

Assembling the confirmed sections into one document. Proposed location:

> **`docs/test-plans/2026-q3-search-relevance.md`**

Structure: scope → named risks (R1–R6) → entry criteria (E1–E7) → phases (P1–P5) with named gates → exit criteria (X1–X7) → residual risks (RR1–RR3) → appendix mapping each named risk to its covering test or monitor.

**Shall I write it to that path, or would you prefer it inline here / under a different docs path (e.g. `docs/launches/` or a Confluence draft)?**

---

## Why this is "senior QA" — what to point at in the demo

- **The Iron Law made visible at turn 2.** The agent could have started drafting a plan immediately; instead it surfaces the hard rule (no plan without measurable entry/exit) before writing a single section. The user knows what they're going to get and what they're not.
- **Scope confirmed with one focused question** — *"all three rollout stages, or just up to canary?"* — anchored to a file (`RolloutConfig.kt`) the agent actually read. Not *"tell me about your rollout"*.
- **Risks anchored to file paths and domain mechanics.** *"`features/PersonalisedAffinity.kt` — cold-start users get a zero-vector contribution that biases the blend toward popularity"* — that's specific enough to argue with. *"Edge cases in personalisation"* would not be.
- **Entry criteria are measurable, and three of them (E4, E5, E6) are pre-work, not just observations.** Senior QA recognises that "the shadow harness exists" and "the shadow harness replays affinity correctly" are different criteria, and the second one mitigates a specific named risk (R5).
- **Phases end at named gates, not calendar dates.** *"Canary NDCG-proxy ≥ baseline on every monitored segment for 72h business-hours continuous"* — falsifiable, defendable in a release review. *"Canary phase: 1 week"* would not be.
- **User-supplied context (business-hours weekend mix, E7 legal sign-off) is integrated, not just acknowledged.** The agent surfaces what it found; the user supplies what only they know; the plan reflects both.
- **Residual risks named honestly with mitigation reasoning.** RR1, RR2, RR3 are each *"we are not covering this AND here is why that is the right call AND here is what catches it if it bites us"*. That's the part most plans skip.
- **Section-by-section confirmation gates.** Six confirmation moments across the plan (scope → risks → entry → phases → exit → residuals). The user can redirect at any one; a single-shot dump cannot be redirected without rewriting the whole document.

This is what *"shift-left QA"* looks like at the formal-plan altitude: the gates are real, the criteria are arguable, and the residual risks are named on the page — not discovered in a post-mortem.
