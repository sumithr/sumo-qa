---
name: sumo-qa-deciding-approach
description: Use as the FIRST step on any QA intent. Loads classifications, approaches, rules, and standards via the sumo_qa_load_* tools, then reasons over the user's intent to pick the canonical approach. Routes to the matching sub-skill.
---

# Deciding the QA approach

**Announce at start:** *"Picking the QA approach for this change."*

## Output discipline (mandatory)

**Never surface internal taxonomy labels in user-facing output.** No "Classification: X", "Approach: Y", "Per the checklist", "Step 3 of 6". The taxonomy is internal scaffolding; translate to natural English when the meaning matters to the user — *"this is a behaviour change in pricing"*, not *"Classification: business_logic_change"*. If you catch yourself typing a label, delete it.

Inherits the global discipline from `using-sumo-qa` (knowledge authority hierarchy, internal scaffolding stays internal, specialty-tool fit).

## Output economy (mandatory)

Spend output tokens on findings, not framing.

- **Don't preamble the work.** The host already shows tool calls — present findings, don't narrate *"I'll first read X, then Y, then deliver Z."*
- **One question per turn.** Don't follow a question with *"shall I proceed or clarify first?"* — the question IS the gate.
- **No self-narration.** *"Let me now..."* / *"I'm going to..."* → just do it.
- **Don't restate the user's input.** They know what they asked.
- **Section headings only when there are genuinely multiple sections.** A 3-line scope check doesn't need a `## Scope` heading.
- **Tables only when comparing >2 things on >2 axes.** Otherwise prose is shorter.
- **No closing pleasantries.** No *"happy to dig deeper"* / *"let me know if you want X"* — the next-skill handoff at the bottom of every skill is where routing lives.

## The Iron Law
SHAPE FIRST, then REACHABILITY. Decide single-change vs repo-wide vs `no-tests-recommended` *before* picking a per-change approach — wrong shape means wrong-shaped tests. When the shape is single-change, check reachability/load-bearing *before* picking a test-writing approach — orphan code routes to `recommend-removal`, not test scaffolding.

## When to Use

`using-sumo-qa` routes to this skill on every QA-shaped intent. This skill ALWAYS runs before any other QA skill. Even simple intents pass through it — the canonical approaches include `no-tests-recommended` and `verify-existing` for cases that don't merit new tests.

## Checklist
You MUST create a TodoWrite item per checklist item and complete in order:

1. Read the user's intent verbatim and any supplied target paths.
2. Call `sumo_qa_load_classifications()` and `sumo_qa_load_approaches()`. Read both catalogues.
3. Call `sumo_qa_load_principles()` if a principle citation is needed in the output.
4. Reason about classification: which catalogue entry applies? Cite the words / paths internally.
5. Reason about shape: single change vs repo-wide / strategy ask vs config tweak vs docs-only? Strategy-shaped asks ("audit", "strategy", "pyramid", "rollout") route to `strategy-orchestration` — do NOT force per-change output.
6. Run the removability gate BEFORE picking a test-writing approach. If the user has named target paths and the code is orphaned — zero internal callers, zero CI/workflow references, zero README/docs references, and no entry-point declaration (`pyproject [project.scripts]`, `package.json scripts`, etc.) points at it — set the approach to `recommend-removal` regardless of the file's natural classification. Surface the reachability evidence in the rationale. If reachability is genuinely ambiguous (external cron, hand-invoked tooling, public CLI installed by users), ask ONE clarifying question instead of guessing. Do NOT collapse this into `no-tests-recommended` — that approach is for behaviour-less change shapes (docs, typos); `recommend-removal` is for dead production-shaped code that should be deleted.
7. Pick the approach. The catalogue is authoritative; use `n/a` for approach only when no catalogue approach fits and capture the non-canonical surface in `rationale`.
8. If a real ambiguity remains (e.g. user said "test the thing" with no paths and no domain), ask ONE clarifying question. Otherwise, do not ask.
9. Return INTERNALLY using the Routing-payload shape below — routing data the next skill consumes, NOT user output. Route to the named sub-skill silently; the sub-skill produces what the user sees.

## Process Flow

See the Checklist above — that's the flow.

## Routing-payload shape

Return exactly these fields internally:

`{classification, approach, rationale, next_action: {skill}}`

- `next_action.skill` is NEVER `n/a`: use a real sumo-qa skill name when routing, or `none` only for the STOP cases where `approach` is `no-tests-recommended` or `recommend-removal`.
- `classification` is `n/a` only for `strategy-orchestration` intents, `recommend-removal` intents (the action is universal, not change-shaped), or non-canonical intents routed to `sumo-qa-suggesting-external-skill`.
- For every catalogue classification, use the verbatim entry: `test_change`, `docs_change`, `config_change`, `data_migration`, and all other real classifications are never `n/a`.
- `approach` is `n/a` only when no canonical approach fits and routing goes to `sumo-qa-suggesting-external-skill`. Strategy intents use `approach: "strategy-orchestration"`, not `n/a`.
- Capture non-canonical surface detail in `rationale`, not in `classification` or `approach`. Do not use `null` or invented values.

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

## Fallback to external skills

When **no canonical approach fits** the intent, decide whether the intent involves a tool, framework, or QA surface that sumo-qa's native skills don't cover — e.g. Playwright/Cypress E2E, accessibility audits, k6/Locust load tests, Pact contract tests, mutation testing, flaky-test quarantine. If yes → return `classification: "n/a"`, `approach: "n/a"`, and `next_action: {skill: "sumo-qa-suggesting-external-skill"}` with the inferred surface in the internal rationale. If no (the intent fits a native sub-skill once you look closer) → continue with the native routing.

`sumo-qa-suggesting-external-skill` will drive external-skill search, install, and execution handoff through sumo-qa MCP tools, with `[y/N]` confirmation before install. Don't pre-emptively warn the user — just route.

## Red Flags

| Thought | Reality |
|---|---|
| "This is obviously TDD" | Maybe. Read the user's words and inferred classification first. "Refactor" implies behaviour-preserving — that's `coverage-first-then-refactor`, not `tdd-scaffold`. |
| "I'll skip loading the catalogues this once" | Catalogue is the source of truth. Inventing approaches from training data is the failure mode this skill exists to prevent. |
| "User said 'design our strategy' — I'll still scaffold tests" | Strategy asks route to `strategy-orchestration`. Don't force per-change output. |
| "Description says docs-only change but I'll add tests anyway" | `no-tests-recommended` is honest senior-QA. Adding tests where none are needed wastes signal. |
| "Mutation testing follow-up needs new prod code" | No — that's `strengthen-test-coverage`. Production code stays unchanged. |
| "I'll ask the user 3 clarifying questions to be sure" | Ask ONE if needed. More than one means the skill is hoarding context; the LLM should infer. |
| "User named a file and asked for tests — let's scaffold" | Check reachability FIRST. Orphan code (zero callers + zero CI refs + zero docs refs + no entry-point declaration) routes to `recommend-removal`. Scaffolding tests on dead code is wasted signal — the PR #68 install.sh failure mode. |
| "Orphan code is just no-tests-recommended" | No. `no-tests-recommended` is for docs/typos / behaviour-less change. `recommend-removal` is for dead production-shaped code where the right move is deletion. They are NOT interchangeable. |

## Examples

### Good

User: "create a test plan for refactoring the pricing pipeline".
- Load classifications + approaches.
- Internally: refactor of pricing logic — behaviour-preserving, so characterization tests pin behaviour before any code moves.
- Cite ISTQB Principle 4 (defects cluster — refactor risks introducing bugs at extraction boundaries).
- Route to `sumo-qa-creating-test-plan`.

User: "audit our test coverage across the repo and design where to invest QA effort next quarter".
- Load classifications + approaches.
- Internally return `{classification: "n/a", approach: "strategy-orchestration", rationale: "Repo-wide QA strategy ask, not a single change-shaped intent.", next_action: {skill: "sumo-qa-strategising"}}`.
- Route to `sumo-qa-strategising`.

User: "add end-to-end browser tests with Playwright for checkout".
- Load classifications + approaches.
- Internally return `{classification: "n/a", approach: "n/a", rationale: "Playwright E2E is a non-canonical external QA surface.", next_action: {skill: "sumo-qa-suggesting-external-skill"}}`.
- Route to `sumo-qa-suggesting-external-skill`.

User: "Help me write tests for ./install.sh — but nothing in the repo references it, no CI uses it, no docs mention it, no entry point points at it."
- Load classifications + approaches.
- Reachability gate fires: zero callers, zero CI refs, zero docs refs, no entry-point declaration → the script is orphaned.
- Internally return `{classification: "n/a", approach: "recommend-removal", rationale: "install.sh is orphaned — zero internal callers, no CI/docs/entry-point references. Recommend deletion rather than scaffolding tests on dead code.", next_action: {skill: "none"}}`.
- STOP. Surface the deletion recommendation (file + reachability evidence + supplanting alternative if known) in the user-facing reply; no sub-skill handoff.

### Bad

User: "create a test plan for refactoring the pricing pipeline". Pick `tdd-scaffold` because "test plan" sounds like adding tests. Wrong — refactor needs characterization tests first. SHAPE FIRST was violated by ignoring "refactoring" in the intent.

User: "Help me write tests for ./install.sh — but nothing in the repo references it, no CI uses it, no docs mention it." Pick `tdd-scaffold` because the developer said "write tests". Wrong — the removability gate should fire BEFORE the approach pick. Orphan code → `recommend-removal`, not test-writing. This is the PR #68 failure mode.

## Next skill in the chain

Routes to exactly ONE of the following, based on the approach picked:

- When the intent is *"plan QA for this story"* → `sumo-qa-preparing-for-work` to name the risks and propose the smallest useful test set before any code is written.
- When the approach is `tdd-scaffold`, `regression-first`, or `coverage-first-then-refactor` → `sumo-qa-implementing-with-tdd` to walk red → hand-off → green with confirmation gates.
- When the approach is `strengthen-test-coverage` → `sumo-qa-strengthening-tests` to kill mutation survivors one at a time (production code stays unchanged).
- When the approach is `verify-existing` or the intent is review-shaped → `sumo-qa-reviewing-before-merge` to read the diff, name risks, run the suite, deliver the verdict.
- When the user asks for a formal test plan with entry/exit criteria → `sumo-qa-creating-test-plan`.
- When the intent is test-data-shaped → `sumo-qa-finding-test-data` to route between explain / find / validate / register.
- When the intent is a generic testing question → `sumo-qa-answering-testing-question` to cite a principle and technique.
- When the approach is `strategy-orchestration` → `sumo-qa-strategising` to walk the repo and design a phased rollout.
- When the work has 3+ independent tasks needing dispatch → `sumo-qa-planning-qa-rollout` to turn the work into a bite-sized, dispatchable plan.
- When no canonical approach fits AND the intent involves a tool / framework / surface sumo-qa doesn't natively cover → `sumo-qa-suggesting-external-skill` with `classification` and `approach` set to `n/a`.
- When the approach is `recommend-removal` → stop. No next-skill handoff. Surface the deletion recommendation (file + reachability evidence + supplanting alternative if known) in the user-facing reply.
- When the approach is `no-tests-recommended` → stop. No next-skill handoff.
