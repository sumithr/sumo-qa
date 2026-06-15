---
name: sumo-qa-creating-test-plan
description: Use when the user asks for a formal test plan, entry/exit criteria, or a phased QA approach for a piece of work. Walk the user through scope → risks → entry criteria → phases → exit criteria → residual risks one section at a time, getting confirmation before each step. Heavier than sumo-qa-preparing-for-work; use when the work is tracked or formally reviewed.
---

# Creating a Test Plan

Help the user turn a piece of upcoming work into a phased ISTQB-style test plan through natural collaborative dialogue. Walk through scope, risks, criteria, and phases one section at a time, confirming with them after each, until the full plan is on the page. The user has domain context the AI can't infer — surface it through questions, don't assume it.

**Announce at start:** *"Building the formal test plan."*

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: **output discipline** (never surface internal taxonomy labels — say *"behaviour change in pricing"*, not *"Classification: business_logic_change"*), **output economy** (spend output on findings not framing; no preamble or self-narration; one question per turn; no closing pleasantries), knowledge authority hierarchy, internal scaffolding stays internal, and specialty-tool fit.

<HARD-GATE>
Do NOT emit a test plan in a single message. Walk through the sections one at a time, getting the user's confirmation or correction between each. A test plan dumped in one turn is a wishlist; a test plan built collaboratively is reviewable.
</HARD-GATE>

## The Iron Law

**NO PLAN WITHOUT EXPLICIT ENTRY AND EXIT CRITERIA.** A document missing either is a wishlist, not a plan.

## When to Use

User intents that trigger this skill:

- "create a test plan for X"
- "draft the formal QA plan I should follow"
- "give me entry/exit criteria for X"
- "I'm starting a major feature — plan QA properly"

Distinct from `sumo-qa-preparing-for-work` (lighter prep brief, no formal entry/exit gates) — use this when the work is tracked, formally reviewed, or large enough to warrant phased execution.

## Checklist

You MUST work through these in order. Steps 1–3 are AI-only homework (no user questions). The user's confirmation gates steps 4 onward.

1. **Extract scope hints from intent** *(no user question)* — re-read the user's intent verbatim. Identify keywords / paths / domain terms that point at where the work lives.

2. **Walk the repo for the scope** *(no user question)* — use the host's file tools. Find where the production code lives, existing tests, related callers, classification signal. Don't ask the user where things are.

3. **Load the catalogues** *(no user question)* — call `sumo_qa_load_standards`, `sumo_qa_load_rules`, `sumo_qa_load_techniques`, `sumo_qa_load_principles`. Internal only. (Principles ground the user-facing plan's risk rationale — e.g. ISTQB Principle 4 "defects cluster" for refactor risk.)

4. **Confirm scope, only for the AMBIGUOUS parts** — present a short paragraph of what you FOUND (file paths, callers, existing tests). Then ask ONE focused question for whatever the code DIDN'T make clear. If exploration left nothing ambiguous, skip the question and move to step 5.

5. **Propose named risks (one message, ask after)** — 3–7 named risks, each anchored in evidence you actually saw (file path, class name, domain term). NOT generic. Run the grounded security-relevance pass from `using-sumo-qa`: if the work touches auth/authorisation, secrets, input sanitisation, rate limiting, audit logging, or a security-relevant config/dependency movement, name the CONCRETE security failure mode as one of the risks (security co-applies — if the initial catalogue load only covered the primary classification, also load `sumo_qa_load_standards(classification="security_change")` and `sumo_qa_load_rules(classification="security_change")` for its probes) and map it to a phase/technique like any other; if there is no grounded security surface, OMIT security — no generic warning, no vulnerability checklist, no vendor/tool-name dump. Ask: *"do these match how you'd describe the risks?"*

6. **Pick technique per risk** — name one technique per risk from the techniques catalogue. Present as a table: risk → technique. Ask: *"do these technique choices fit?"*

7. **Recommend specialty tools (if any), and offer to set them up** — follow the discovery discipline from `using-sumo-qa`: observe the risk surface, reason from first principles about what shape of testing fits, web-search current options for the user's stack, recommend with citation. Sumo-qa intentionally does NOT carry a tool catalogue. "I don't know" is acceptable. Offer to install and scaffold the first tests against the named risks. Confirm before installing dependencies. Empty list is acceptable.

8. **Entry criteria — what must be true to START testing** — 3–5 observable preconditions (API spec frozen, test data loaded, feature flag default off, etc.).

9. **Phases + deliverables** — propose analysis / design / execution / completion phases with concrete deliverables per phase.

10. **Exit criteria — what must be true to SHIP** — observable exit criteria (all named risks have ≥1 passing test, no Sev-1/2 open, perf under p95 budget). Tautologies like "tests pass" are forbidden.

11. **Residual risks accepted at exit** — name 1–3 risks you're NOT covering and why (out of scope, accepted cost, mitigated elsewhere).

12. **Final plan** — assemble the confirmed sections into one document. Offer to write to a file (e.g. `docs/qa-plans/<topic>.md`) or surface inline. Confirm before writing. **Optionally** append a structured risk-to-test ledger: project the confirmed risk→technique table into `sumo_qa_format_risk_ledger` (one row per risk, `evidence_status: planned`, `residual: open` for risks the plan covers and `accepted` for the residual risks named in step 11). It is a traceable appendix to the markdown plan, not a replacement; the plan emits with no code change or test run. For a **release-readiness** plan, you can also project the exit-criteria state into a readiness scorecard via `sumo_qa_format_qa_scorecard`: at plan time every risk is `planned`, so the tool DERIVES `insufficient_evidence` (nothing has run yet) — an honest "not ready until the exit criteria are met" baseline, never a fake "ready". The same scorecard, re-run with real evidence at ship time, is what `sumo-qa-finishing-qa-work` and `sumo-qa-reviewing-before-merge` surface.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags — STOP and rework

| Thought | Reality |
|---|---|
| "I'll draft the whole plan and they can react" | Iron-Law-adjacent failure. Walk through one section at a time. |
| "I'll ask the user where the code lives instead of looking" | The code is in the repo. Read it. Ask only for what the code didn't make clear. |
| "I'll list 4 clarifying questions in one message to be thorough" | Overwhelming. ONE primary question per turn. |
| "Skip exit criteria — they'll know when it's done" | Then it's not a plan. Iron Law violated. |
| "Entry criteria: 'tests are green'" | Tautology. Entry criteria are about the world before testing — feature complete, data available, environments stand up. |
| "Add a phase called 'edge cases'" | Phases are analysis / design / execution / completion. "Edge cases" is a phase only in a junior QA's plan. |
| "Residual risks: 'none'" | Every plan has residual risks. Naming "none" means you didn't think about what could still go wrong post-ship. |
| "Mutation testing on a UI redesign" | Wrong tool fit. Pick from the catalogue based on the actual risk surface. |
| "Tests cover all behaviour" | "All behaviour" is not measurable. Exit criteria must be observable. |
| "User said create a plan — I'll just create it without asking" | The user has context you don't. Walk through the sections; their corrections shape the plan. |

## Examples

### Good (explore first, ask only what's ambiguous)

> **User:** "Create a test plan for the new tax-calculation feature."
>
> **AI (after internal repo walk):** *"Found the tax engine at `tax/TaxEngine.kt` with jurisdiction handlers under `tax/jurisdictions/`. Called from `pricing/Calculator.kt` upstream; `invoicing/InvoiceBuilder.kt` consumes it. Existing tests cover 4 jurisdictions. **Is scope just the tax engine, or also the upstream pricing-pipeline integration?**"*

### Bad (single-shot dump)

> **AI:** *"Here's a plan: Phases — planning, testing, deployment. Tests — happy path, edge cases, integration. Entry — code complete. Exit — tests pass. Done."*
>
> Generic phases, no risks named, tautological exit, no collaboration. Iron Law violated.

## Next skill in the chain

When the plan is signed off → `sumo-qa-planning-qa-rollout` to break the phases into bite-sized, dispatchable tasks ready for subagent execution.

If the user wants to act on a single phase directly rather than dispatch it → route to the matching execution skill instead (`sumo-qa-implementing-with-tdd` for new behaviour / regressions, `sumo-qa-strengthening-tests` for mutation follow-up, `sumo-qa-reviewing-before-merge` for review-shaped phases).
