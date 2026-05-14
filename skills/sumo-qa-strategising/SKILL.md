---
name: sumo-qa-strategising
description: Use for repo-wide / policy-shaped asks — "audit our test coverage", "design our QA strategy from scratch", "where should we invest QA effort first", "design our test pyramid". Walks repo inventory → per-area risks → specialty fit → prioritisation → pyramid → phased rollout → residual risks, one section at a time with confirmation gates. Walks the repo with the host's file tools first.
---

# Strategising sumo-qa work

Help the user produce a risk-prioritised, repo-anchored QA strategy by walking the strategy one section at a time: inventory the actual repo, surface per-area risks, fit specialty tools, prioritise, design the pyramid, phase the rollout. The user has org context (team size, release cadence, regulatory pressure, current pain points) the AI can't infer from code alone — surface it through questions, don't assume it.

**Announce at start:** *"Walking the repo for a phased QA strategy."*

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

<HARD-GATE>
Do NOT emit a strategy in one message. Walk the sections one at a time: inventory → risks → tools → prioritisation → pyramid → rollout → residual. A strategy dumped in one turn is generic consulting; a strategy built collaboratively is implementable.
</HARD-GATE>

## The Iron Law

**WALK THE REPO FIRST.** No repo-wide plan without using the host's file tools to map the actual codebase — strategy that doesn't cite specific service names, module paths, and existing test directories is generic consulting nonsense.

## When to Use

`sumo-qa-deciding-approach` routes here on `strategy-orchestration`. User intents:

- "design our QA strategy"
- "audit our test coverage"
- "design our test pyramid"
- "where should we invest QA effort first"
- "rollout our QA approach to other services"
- "minimum viable QA setup for a new service"

NOT for single-change asks. If the user says "review my changes" or "create a test plan for X" → wrong skill.

## Checklist

You MUST work through these in order. Steps 1–3 are AI-only homework (no user questions). The user's confirmation gates steps 4 onward.

1. **Walk the repo** *(no user question)* — use the host's file tools. Inventory: services / top-level modules / test directories / CI config / coverage reports. Note languages, frameworks, seams (HTTP routes, message handlers, scheduled jobs, UI, DB migrations). Use the recipe in `knowledge/repo_walk.md` for the exact commands and data shape to gather, so successive strategy runs produce consistent inventory data on the same repo state.

2. **Load the catalogues** *(no user question)* — call `sumo_qa_load_principles()`, `sumo_qa_load_classifications()`, `sumo_qa_load_specialty_tools()`. Internal only; don't dump them raw.

3. **Per-area provisional analysis** *(no user question)* — for each major area: classify it, estimate the existing coverage shape (unit-heavy / integration-heavy / e2e-heavy / no tests), provisionally name 2–3 risks anchored to file paths or framework constructs.

4. **Confirm scope + inventory, only for the AMBIGUOUS parts** — present what you found and ask one targeted scope question (e.g. *"all 4 services in scope, or just the ones we own — and is there a service I missed?"*). If exploration left nothing ambiguous, skip and move on.

5. **Present per-area inventory + provisional risks, confirm** — compact table or list, one row per area: classification(s), current coverage shape, top 2–3 named risks each citing a path or framework construct. NOT generic. Ask: *"do these inventories + risk calls match the team's lived experience?"*

6. **Identify specialty surfaces + tool fit, confirm** — for each confirmed area, name the specialty surface(s) and recommend the best-fit tool anchored to the user's stack. `sumo_qa_load_specialty_tools()` is a category-fit primer, not a brand whitelist. Verify with web search if unsure a tool still exists. For Phase 1 picks, offer to install and set up the tool yourself and seed first tests against the highest-risk area. Empty list is acceptable per area.

7. **Propose prioritisation, confirm** — rank areas by `risk × current-coverage-gap`. High risk + low coverage = Phase 1. Low risk + good coverage = leave alone. Cite ISTQB Principle 2 (exhaustive testing is impossible — prioritise).

8. **Design target pyramid shape, confirm** — propose the rough mix per area: unit / component / integration / contract / e2e / performance / security / a11y. Scaled to actual risk surface, not uniform.

9. **Propose phased rollout, confirm** — propose 2–4 phases, each with area scope, deliverables, "minimum viable" QA setup, gates at the end of each phase. NOT a calendar — a sequence with named gates.

10. **Residual risks accepted, confirm** — name 2–4 risks NOT being addressed and why (out of scope, accepted cost, mitigated elsewhere, deferred). Ask: *"is this honest?"*

11. **Final strategy document** — assemble confirmed sections into one document (inventory, prioritisation, specialty fit, target pyramid, phased rollout, residual risks). Offer to write to a file (e.g. `docs/qa-strategy.md`) or surface inline. Confirm before writing.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags — STOP and rework

| Thought | Reality |
|---|---|
| "I'll skip walking the repo — the user already described it" | Walk the repo. The user's description and the actual code rarely match. |
| "I'll ask the user to list their services / modules / test dirs" | Read them. The repo answers. Ask only what code can't show (team size, regulatory pressure, etc). |
| "Recommend more unit tests everywhere" | Generic. The target pyramid is risk-shaped, not uniform. |
| "Use Cypress / Playwright / Pact everywhere" | Pick by fit, not familiarity. Match the tool to the actual specialty surface. |
| "I'll restrict tool recommendations to the names in `specialty_tools.md`" | The primer is a category check, not a brand whitelist. Recommend best-fit; verify with web search if uncertain. |
| "Phase 1: add tests everywhere" | Phases are risk-shaped. Phase 1 hits highest risk × biggest gap. |
| "Performance testing for the whole repo" | Only where performance is a quality characteristic at risk. Generic perf tests are theatre. |
| "Strategy is just 'aim for 80% coverage'" | Coverage % isn't a strategy. Risk-prioritised coverage IS a strategy. |
| "I'll present inventory + risks + tools + pyramid + rollout in one message" | Single-shot dump. Iron Law violated. Walk one section at a time. |
| "Residual risks: none" | Every strategy has them. None = you didn't think about what's NOT covered. |
| "Generic recommendation: introduce a QA Center of Excellence" | Anchor to this repo. CoE-shaped advice is irrelevant to a 4-service monorepo with 8 engineers. |

## Examples

### Good (explore first, walk one section at a time)

> **User:** "Design our QA strategy for the customer-platform monorepo."
>
> **AI (steps 1–3, internal):** walks `services/`, finds 4 services (auth, billing, search, notifications); reads each `tests/` dir; sees CI runs `make test`. Loads catalogues. Provisional: billing is pure-function-heavy, no mutation testing. Search has HTTP + integration tests but no contract tests.
>
> **AI (step 4, scope):** *"Walked the repo: 4 deployable services under `services/`, each with its own `tests/` dir; CI runs `make test`. No coverage report detected. **All 4 in scope, or just the ones your team owns — and is there a service or shared lib I missed?**"*
>
> *(continues one section per turn through inventory, specialty fit, prioritisation, pyramid, rollout, residual)*

### Bad (single-shot strategy dump)

> **User:** "Design our QA strategy for the customer-platform monorepo."
>
> **AI:** *"Strategy: add more unit tests across all services. Aim for 80% coverage. Add Cypress for the UI. Phase 1: unit tests. Phase 2: integration. Phase 3: e2e."*
>
> No repo walk, no risk anchoring, no specialty fit, no per-area phases. Iron Law violated.

## Next skill in the chain

When the strategy is signed off → `sumo-qa-planning-qa-rollout` to turn Phase 1 into bite-sized, dispatchable tasks, then `sumo-qa-executing-qa-rollout` to run them with two-stage review per task.
