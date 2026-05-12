---
name: qa-preparing-for-work
description: Use when the user asks to plan QA for a story, ticket, or piece of work before coding starts. Identifies named risks anchored in the change shape, then proposes a smallest useful test set tied to those risks. Lighter-weight than qa-creating-test-plan; no formal entry/exit criteria.
---

# Preparing for QA work

**Announce at start:** *"I'm using qa-preparing-for-work to name the risks and propose the smallest useful test set before any code is written."*

## Output discipline (mandatory)

**Never surface internal taxonomy labels in user-facing output.** No "Classification: X", "Approach: Y", "Per the checklist", "Step 3 of 6". The taxonomy is internal scaffolding; translate to natural English when the meaning matters to the user — *"this is a behaviour change in pricing"*, not *"Classification: business_logic_change"*. If you catch yourself typing a label, delete it.

Inherits the global discipline from `using-sumo-qa` (knowledge authority hierarchy, internal scaffolding stays internal, specialty-tool fit).

## The Iron Law
NO TEST IDEA WITHOUT A NAMED RISK. Every test you propose ties to a specific risk you identified.

## When to Use

User intents that trigger this skill:

- "plan QA for this story"
- "I'm starting work on X — what should I test?"
- "what could break with this change?"
- "QA prep for ticket ABC-123"

Distinct from `qa-creating-test-plan` (formal entry/exit criteria, phases, deliverables) and from `qa-deciding-approach` (which only picks the approach). This skill produces a risk-shaped prep brief: named risks + smallest useful test set + named techniques + specialty fits if relevant.

## Checklist
You MUST create a TodoWrite item per checklist item and complete in order:

1. Read the user's intent and target paths.
2. Call `sumo_qa_load_standards(classification=...)` and `sumo_qa_load_rules(classification=...)` using the classification the previous `qa-deciding-approach` step settled on.
3. Read the actual files in scope using the host's file tools. Do NOT ask the user for file content the host can read directly.
4. Identify 3-7 named risks. Each risk MUST be specific (not "input validation breaks" but "currency conversion at the GBP→USD boundary rounds incorrectly when the rate is supplied with >6 decimal places"). Anchor each in a file path or domain term from the user's words.
5. Call `sumo_qa_load_techniques()`. Pick one technique per named risk. Use the catalogue's wording.
6. Recommend specialty tools (if any), and offer to set them up — pick from your knowledge of the ecosystem anchored to the user's stack and the actual risks. `sumo_qa_load_specialty_tools()` is a category-fit primer, NOT a brand whitelist. Verify currency with web search if uncertain. Offer to install and scaffold the first tests against the named risks. Confirm before installing dependencies. Empty list is acceptable.
7. Produce a smallest useful test set: 3-7 tests, each tied to a named risk. No generic "test happy path".
8. Output: conversational prose, sectioned (risks, tests, techniques, specialty tools, open assumptions). No JSON blob.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags

| Thought | Reality |
|---|---|
| "Add tests for edge cases" | What edge cases? Name them with specific values. |
| "Test happy path and sad path" | Generic. Every change has a happy path. Name the specific behaviour and the specific failure mode. |
| "I'll list 15 risks to be thorough" | 3-7 is the senior-QA bar. More means you're confabulating, not reasoning. |
| "I don't need to read the files — I can infer from the intent" | You can infer the SHAPE; you can't infer the actual data flow, domain terms, or edge cases without reading. |
| "The user didn't ask for techniques — I'll skip those" | Every named risk gets a named technique. The technique is what makes the test actionable. |
| "Mutation testing for a UI tweak" | Wrong tool fit. Pick by risk surface, not by familiarity. |
| "I'll restrict tool recommendations to the names in `specialty_tools.md`" | The primer is a category check, not a brand whitelist. Recommend the best fit from your knowledge of the ecosystem; the names in the file are illustrative. |

## Examples

### Good

User: "I'm adding a refund endpoint to the payments service. What should I test?"
- Risks: (1) refund amount exceeds original charge. (2) refund issued twice for the same charge (idempotency on `charge_id`). (3) partial refund recorded but downstream ledger update fails. (4) refund of an already-refunded charge isn't blocked.
- Techniques: boundary value analysis; state transition testing; decision table; state transition testing.
- Tools: Pact (consumer-driven contract test) + Hypothesis (property-based idempotency).

### Bad

"Test that the endpoint returns 200 on success. Test that it handles invalid amounts. Test edge cases. Test the happy path." — No named risks, no anchors, no specific values.

## Next skill in the chain

When the prep brief is signed off → `qa-implementing-with-tdd` to walk red → green for the agreed risks (the most common path).

When the work has 3+ independent tasks the user wants to dispatch across subagents → `qa-planning-qa-rollout` to turn the brief into a bite-sized, dispatchable plan first.
