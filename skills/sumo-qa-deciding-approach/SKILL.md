---
name: sumo-qa-deciding-approach
description: Use as the FIRST step on any QA intent. Loads classifications + approaches (the two needed to route), then reasons over the user's intent to pick the canonical approach and routes to the matching sub-skill (which loads any further catalogues on demand).
---

# Deciding the QA approach

**Announce at start:** *"Picking the QA approach for this change."*

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: **output discipline** (never surface internal taxonomy labels — say *"behaviour change in pricing"*, not *"Classification: business_logic_change"*), **output economy** (spend output on findings not framing; no preamble or self-narration; one question per turn; no closing pleasantries), knowledge authority hierarchy, internal scaffolding stays internal, and specialty-tool fit.

## The Iron Law
SHAPE FIRST, then REACHABILITY. Decide single-change vs repo-wide vs `no-tests-recommended` *before* picking a per-change approach — wrong shape means wrong-shaped tests. When the shape is single-change, check reachability/load-bearing *before* picking a test-writing approach — orphan code routes to `recommend-removal`, not test scaffolding.

## When to Use

`using-sumo-qa` routes here on every QA-shaped intent; this skill ALWAYS runs before any other QA skill. Even simple intents pass through — `no-tests-recommended` and `verify-existing` exist for cases that don't merit new tests.

## Checklist
Track these as an ordered work list (use the host's task primitive if available, otherwise a numbered inline tracker) and complete in order:

1. Read the user's intent verbatim and any supplied target paths.
2. Call `sumo_qa_load_classifications()` and `sumo_qa_load_approaches()` — the only catalogues this router loads (see *Catalogue responsibilities*).
3. Reason about classification: which catalogue entry applies? Cite the words / paths internally.
4. Reason about shape: single change vs repo-wide / strategy ask vs config tweak vs docs-only? Strategy-shaped asks ("audit", "strategy", "pyramid", "rollout") route to `strategy-orchestration` — do NOT force per-change output.
5. Run the removability gate BEFORE picking a test-writing approach. If the user named target paths and the code is orphaned — zero internal callers, zero CI/workflow refs, zero README/docs refs, no entry-point declaration (`pyproject [project.scripts]`, `package.json scripts`, etc.) — set the approach to `recommend-removal` regardless of natural classification, and surface the reachability evidence in the rationale. If reachability is genuinely ambiguous (external cron, hand-invoked tooling, public CLI), ask ONE clarifying question. Do NOT collapse this into `no-tests-recommended` (that's for behaviour-less changes — docs, typos); `recommend-removal` is for dead production-shaped code that should be deleted.
6. Pick the approach. The catalogue is authoritative; use `n/a` for approach only when no catalogue approach fits and capture the non-canonical surface in `rationale`.
7. If a real ambiguity remains (e.g. user said "test the thing" with no paths and no domain), ask ONE clarifying question. Otherwise, do not ask.
8. Return INTERNALLY using the Routing-payload shape below — routing data the next skill consumes, NOT user output. Route to the named sub-skill silently; it produces what the user sees.

## Process Flow

See the Checklist above — that's the flow.

## Routing-payload shape

Return exactly these fields internally:

`{classification, approach, rationale, next_action: {skill}}`

- `next_action.skill` is NEVER `n/a`: use a real sumo-qa skill name, or `none` only for the STOP cases (`approach` is `no-tests-recommended` or `recommend-removal`).
- When routing to `sumo-qa-suggesting-external-skill`, `next_action` ALSO carries `entry_kind: "qa"` (the conversion entry supplies `"conversion"`; the skill never infers the mode).
- `classification` is `n/a` only for `strategy-orchestration`, `recommend-removal` (action is universal, not change-shaped), or non-canonical external-skill intents. Every catalogue classification uses its verbatim entry (`test_change`, `docs_change`, `config_change`, `data_migration`, …) — never `n/a`.
- `approach` is `n/a` only when no canonical approach fits and routing goes to `sumo-qa-suggesting-external-skill`; strategy intents use `approach: "strategy-orchestration"`. Capture non-canonical detail in `rationale` — never `null` or invented values.

Anti-patterns:
- BAD: `classification: "n/a"` for a `test_change` intent (mutation-testing follow-up, raise coverage, strengthen weak assertions). USE: `classification: "test_change"`.
- BAD: `next_action.skill: "n/a"` for a STOP case. USE: `next_action.skill: "none"`.

## Routing table (approach → next skill)

| Approach | Next skill |
|---|---|
| strategy-orchestration | sumo-qa-strategising |
| tdd-scaffold | sumo-qa-implementing-with-tdd |
| regression-first | sumo-qa-implementing-with-tdd |
| coverage-first-then-refactor | sumo-qa-implementing-with-tdd |
| strengthen-test-coverage | sumo-qa-strengthening-tests |
| verify-existing | sumo-qa-reviewing-before-merge |
| no-tests-recommended | (stop — no sub-skill needed) |
| recommend-removal | (stop — propose deletion, no sub-skill) |
| spike-first-then-tests | sumo-qa-preparing-for-work (deliverable mode) |
| n/a (no canonical approach fits; intent involves a non-native tool/surface) | sumo-qa-suggesting-external-skill |

For "create a test plan" / "plan QA for this story" intents, after approach is picked, route to `sumo-qa-creating-test-plan` or `sumo-qa-preparing-for-work` per user phrasing. For "how do I test this?" intents that don't fit any specific approach, route to `sumo-qa-answering-testing-question`.

## Catalogue responsibilities (lazy-load contract)

This router loads ONLY `load_classifications` + `load_approaches` (step 2). Every other catalogue is the routed sub-skill's responsibility, loaded on demand:

- `sumo-qa-implementing-with-tdd` / `sumo-qa-strengthening-tests` → `load_techniques`.
- `sumo-qa-reviewing-before-merge` → `load_classifications` + `load_standards` + `load_rules`.
- `sumo-qa-creating-test-plan` → `load_standards` + `load_rules` + `load_techniques` + `load_principles`.
- `sumo-qa-preparing-for-work` → `load_standards` + `load_rules` + `load_techniques`.
- `sumo-qa-strategising` → `load_principles` + `load_classifications`.
- `sumo-qa-answering-testing-question` → `load_principles` + `load_techniques`.

This router does NOT load `load_principles` — the routing payload's `rationale` is internal scratch (not user output), and the sub-skill that cites a principle in its user-facing output is the one that loads it.

## Fallback to external skills

When **no canonical approach fits**, decide whether the intent involves a tool, framework, or QA surface sumo-qa's native skills don't cover — Playwright/Cypress E2E, accessibility audits, k6/Locust load tests, Pact contract tests, flaky-test quarantine. If yes → return `classification: "n/a"`, `approach: "n/a"`, `next_action: {skill: "sumo-qa-suggesting-external-skill", entry_kind: "qa"}` with the inferred surface in the rationale. If no (it fits a native sub-skill on closer look) → continue native routing.

`sumo-qa-suggesting-external-skill` drives external-skill search/install/handoff via sumo-qa MCP tools, with `[y/N]` confirmation before install. Don't pre-warn the user — just route.

## Red Flags

| Thought | Reality |
|---|---|
| "This is obviously TDD" | Maybe. Read the user's words and inferred classification first. "Refactor" implies behaviour-preserving — that's `coverage-first-then-refactor`, not `tdd-scaffold`. |
| "I'll skip loading the catalogues this once" | Catalogue is the source of truth. Inventing approaches from training data is the failure mode this skill exists to prevent. |
| "User said 'design our strategy' — I'll still scaffold tests" | Strategy asks route to `strategy-orchestration`. Don't force per-change output. |
| "Description says docs-only change but I'll add tests anyway" | `no-tests-recommended` is honest senior-QA. Adding tests where none are needed wastes signal. |
| "Mutation testing follow-up needs new prod code" | No — that's `strengthen-test-coverage`. Production code stays unchanged. |
| "I'll ask the user 3 clarifying questions to be sure" | Ask ONE if needed. More than one means the skill is hoarding context; the LLM should infer. |
| "User named a file and asked for tests — scaffold" / "orphan code is just no-tests-recommended" | Check reachability FIRST. Orphan code (zero callers/CI/docs refs + no entry-point declaration) → `recommend-removal` — NOT scaffolding, and NOT `no-tests-recommended` (that's for docs/typos / behaviour-less change). Scaffolding tests on dead code is wasted signal — the PR #68 install.sh failure mode. |

## Examples

### Good

*(Every scenario starts by loading classifications + approaches.)*

User: "create a test plan for refactoring the pricing pipeline".
- Internally: refactor of pricing logic — behaviour-preserving, so characterization tests pin behaviour before any code moves.
- Route to `sumo-qa-creating-test-plan` (which loads its own catalogues — `standards`, `rules`, `techniques` — and is the place to ground any principle citation in user-facing output).

User: "audit our test coverage across the repo and design where to invest QA effort next quarter".
- Internally return `{classification: "n/a", approach: "strategy-orchestration", rationale: "Repo-wide QA strategy ask, not a single change-shaped intent.", next_action: {skill: "sumo-qa-strategising"}}`.

User: "add end-to-end browser tests with Playwright for checkout".
- Internally return `{classification: "n/a", approach: "n/a", rationale: "Playwright E2E is a non-canonical external QA surface.", next_action: {skill: "sumo-qa-suggesting-external-skill", entry_kind: "qa"}}`.

User: "Help me write tests for ./install.sh — nothing references it, no CI uses it, no docs mention it, no entry point points at it."
- Reachability gate fires: zero callers/CI/docs refs, no entry-point declaration → orphaned.
- Internally return `{classification: "n/a", approach: "recommend-removal", rationale: "install.sh orphaned — no callers/CI/docs/entry-point refs; recommend deletion over scaffolding tests on dead code.", next_action: {skill: "none"}}`.
- STOP. Surface the deletion recommendation (file + reachability evidence + supplanting alternative if known); no sub-skill handoff.

### Bad

User: "create a test plan for refactoring the pricing pipeline". Pick `tdd-scaffold` because "test plan" sounds like adding tests. Wrong — refactor needs characterization tests first. SHAPE FIRST was violated by ignoring "refactoring" in the intent.

(The orphaned-`install.sh` case is the other classic miss — picking `tdd-scaffold` on the word "tests" instead of firing the removability gate first → `recommend-removal`. PR #68 failure mode.)

## Next skill in the chain

Route to exactly ONE skill. For approach-based routing, use the **Routing table** above (`tdd-scaffold`/`regression-first`/`coverage-first-then-refactor` → `sumo-qa-implementing-with-tdd`; `strengthen-test-coverage` → `sumo-qa-strengthening-tests`; `verify-existing` → `sumo-qa-reviewing-before-merge`; `strategy-orchestration` → `sumo-qa-strategising`; `n/a` external surface → `sumo-qa-suggesting-external-skill`). Intent-shaped routing on top of that:

- *"plan QA for this story"* → `sumo-qa-preparing-for-work`; a formal test plan with entry/exit criteria → `sumo-qa-creating-test-plan`.
- generic *"how do I test X"* → `sumo-qa-answering-testing-question`; test-data-shaped → `sumo-qa-finding-test-data`.
- work with 3+ independent dispatchable tasks → `sumo-qa-planning-qa-rollout`.

STOP cases have no handoff: `no-tests-recommended`, and `recommend-removal` (surface the deletion recommendation — file + reachability evidence + supplanting alternative if known — in the user-facing reply).
