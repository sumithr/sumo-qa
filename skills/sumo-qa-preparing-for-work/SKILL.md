---
name: sumo-qa-preparing-for-work
description: Use when the user asks to plan QA for a story, ticket, or piece of work before coding starts. Identifies named risks anchored in the change shape, then proposes a smallest useful test set tied to those risks. Lighter-weight than sumo-qa-creating-test-plan; no formal entry/exit criteria.
---

# Preparing for QA work

**Announce at start:** *"Naming risks and the smallest test set."*

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: **output discipline** (never surface internal taxonomy labels — say *"behaviour change in pricing"*, not *"Classification: business_logic_change"*), **output economy** (spend output on findings not framing; no preamble or self-narration; one question per turn; no closing pleasantries), knowledge authority hierarchy, internal scaffolding stays internal, and specialty-tool fit.

## The Iron Law
NO TEST IDEA WITHOUT A NAMED RISK. Every test you propose ties to a specific risk you identified.

## When to Use

User intents that trigger this skill:

- "plan QA for this story"
- "I'm starting work on X — what should I test?"
- "what could break with this change?"
- "QA prep for ticket ABC-123"

Distinct from `sumo-qa-creating-test-plan` (formal entry/exit criteria, phases, deliverables) and from `sumo-qa-deciding-approach` (which only picks the approach). This skill produces a risk-shaped prep brief: named risks + smallest useful test set + named techniques + specialty fits if relevant.

## Checklist
Track these as an ordered work list (use the host's task primitive if available, otherwise a numbered inline tracker) and complete in order:

1. Read the user's intent and target paths.
2. Call `sumo_qa_load_standards(classification=...)` and `sumo_qa_load_rules(classification=...)` using the classification the previous `sumo-qa-deciding-approach` step settled on.
3. Read the actual files in scope using the host's file tools. Do NOT ask the user for file content the host can read directly.
4. Identify 3-7 named risks. Each risk MUST be specific (not "input validation breaks" but "currency conversion at the GBP→USD boundary rounds incorrectly when the rate is supplied with >6 decimal places"). Anchor each in a file path or domain term from the user's words, and do not invent thresholds, rules, states, or edge cases that are not present in the supplied change or code. When the intent is refactor/move/extract without behaviour change, name preservation risks: rendered values, exact formatting, thresholds, rounding, disabled states, and public contract must remain unchanged. Do not merely restate the production formulae as generic calculation risks.

   **Anchor-fit rule (pinned):** the cited line must be *semantically* about the risk, not merely the nearest plausible-looking line. If the risk is about behaviour X and the cited code does Y, you have a stapled anchor — delete the risk. Before listing a risk, ask: *"if I removed this line, would the risk still make sense?"* If yes, the anchor is wrong.

   **Stapled-anchor example (BAD):** Risk: *"discount must be correctly calculated when subtotal is at the tax threshold"* citing `const tax = subtotal * 0.0825`. The cited line computes tax, not discount, and the sketch defines no tax threshold — this is a fabricated edge case wearing a real line number.

   **Grounded example (GOOD):** Risk: *"valid promo code does not subtract from total"* citing `const total = subtotal + tax + shipping;` — the cited line is the exact site where the discount must be applied.

   **Surface-signal rule (pinned):** when the change touches a recognisable surface — schema/model validation, request/response or IPC protocol, CI/config/deploy, async/retry/idempotency, auth/token — name the risk from the *surface*, not the library. Two changes on the same surface get the same probes (a removed field over any transport → *"an existing consumer still referencing it keeps working or fails loudly, not silently"*); the loaded rules (`sumo_qa_load_rules`) carry these per surface — apply them tech-agnostically, going library-specific only when the user or repo supplied the library. Cover the surface's *distinct* probes (don't restate one in three costumes), and make each test assert a concrete outcome — the input and what must hold — not that a consumer *"accesses"* a value (async retry → *"a redelivered message double-charges unless an idempotency key makes the side effect run exactly once"*; contract → *"an old-shaped payload is still accepted or explicitly version-gated"*).
5. Call `sumo_qa_load_techniques()`. Pick one technique per named risk. Use the catalogue's wording.
6. Recommend specialty tools (if any), and offer to set them up — follow the discovery discipline from `using-sumo-qa`: observe the risk surface, reason from first principles about what shape of testing fits, web-search current options for the user's stack, recommend with citation. Sumo-qa intentionally does NOT carry a tool catalogue. "I don't know" is acceptable. Offer to install and scaffold the first tests against the named risks. Confirm before installing dependencies. Empty list is acceptable.
7. Produce a smallest useful test set: 3-7 tests, each tied to a named risk. No generic *"test happy path"*. **Concreteness rule (pinned):** if the change-shape supplies a numeric reproduction, a worked example, or specific inputs/outputs (e.g. *"qty 2+3 currently shows 2, must show 5"*), the corresponding test idea MUST reuse those exact numbers. Restating the risk in test-shape (*"verify that the item count displays the correct total"*) is not a test idea — it's the risk again. A test idea names inputs and the observable outcome.
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
| "I'll restrict myself to tool categories I already know" | Wrong. Specialty tooling exists for functional surfaces too, and new categories emerge constantly. Reason from the surface, web-search current options, recommend with citation. There's no internal catalogue to fall back on. |
| "Change is in framework X, so the probes are X-specific" / "same surface, so write the risk once" | Same surface → the same *probe set*, not one X-specific probe. Name the contract/idempotency/config risk pattern and cover its distinct probes; go library-specific only when the user or repo named the library. |

## Examples

### Good

User: "I'm adding a refund endpoint to the payments service. What should I test?"
- Risks: (1) refund amount exceeds original charge. (2) refund issued twice for the same charge (idempotency on `charge_id`). (3) partial refund recorded but downstream ledger update fails. (4) refund of an already-refunded charge isn't blocked.
- Techniques: boundary value analysis; state transition testing; decision table; state transition testing.
- Tools: Pact (consumer-driven contract test) + Hypothesis (property-based idempotency).

### Good (refactor — *"extract this without changing behaviour"*)

User: *"I'm refactoring the cart totals into a useCartTotals helper without changing checkout behaviour."*
- Risks: (1) `subtotal.toFixed(2)` rendering changes (e.g. `12.5` instead of `12.50`) — visible at the `data-testid="subtotal"` node. (2) `item-count` text contents change after the move — visible at `{cart.items.length} items`. (3) `$50` shipping threshold flips inclusive/exclusive after the extract — visible at `subtotal >= 50 ? 0 : 6.99`. (4) Checkout `disabled` state stops depending on `cart.items.length === 0`.
- Techniques: snapshot / golden output; DOM-render assertion; boundary value analysis; state transition testing.

### Bad (refactor)

*"Risks: subtotal calculation correct, tax calculation correct, shipping calculation correct."* — These restate the production formulae, not the preservation contract. A refactor's risk is that the *observable outputs* drift; naming the formulae as risks tells you nothing about what to assert.

### Bad

"Test that the endpoint returns 200 on success. Test that it handles invalid amounts. Test edge cases. Test the happy path." — No named risks, no anchors, no specific values.

## Next skill in the chain

When the prep brief is signed off → `sumo-qa-implementing-with-tdd` to walk red → green for the agreed risks (the most common path).

When the work has 3+ independent tasks the user wants to dispatch across subagents → `sumo-qa-planning-qa-rollout` to turn the brief into a bite-sized, dispatchable plan first.
