---
name: qa-answering-testing-question
description: Use when the user asks a generic testing question — "how do I test this?", "what should I check for X?" — that doesn't fit a more specific QA skill. Cites a principle or technique from the loaded catalogue rather than producing generic advice.
---

# Answering a testing question

**Announce at start:** *"Answering with a cited principle and technique."*

## Output discipline (mandatory)

**Never surface internal taxonomy labels in user-facing output.** No "Classification: X", "Approach: Y", "Per the checklist", "Step 3 of 6". The taxonomy is internal scaffolding; translate to natural English when the meaning matters to the user — *"this is a behaviour change in pricing"*, not *"Classification: business_logic_change"*. If you catch yourself typing a label, delete it.

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
NO ANSWER WITHOUT A CITED PRINCIPLE OR TECHNIQUE.

Every answer ties to a named ISTQB principle and a named test design technique from the loaded catalogue; specialty tools come from your ecosystem knowledge, with `specialty_tools.md` confirming the category fits.

## When to Use

`qa-deciding-approach` routes here when the user's intent is question-shaped but doesn't fit a more specific skill:

- "how do I test this service?"
- "what should I check for X feature?"
- "any QA suggestions for this design?"
- "what's the right test type for this?"

For "create a plan" / "prep for work" / "review my changes" → use the more specific skills.

## Checklist
You MUST create a TodoWrite item per checklist item and complete in order:

1. Read the user's question verbatim.
2. Read any code/paths/specs the user supplied (host's file tools).
3. Call `sumo_qa_load_principles()` and `sumo_qa_load_techniques()`. Read both catalogues.
4. Identify the QA shape the question implies: what's the actual concern (correctness / regression / coverage / risk surface)?
5. Pick at least one principle that shapes the answer (cite by number or name). Pick at least one technique that fits the concern.
6. If the question implies a specialty surface (security, performance, contract, a11y, UI, etc.), recommend the best-fit tool from your knowledge of the ecosystem anchored to the user's stack. `sumo_qa_load_specialty_tools()` is a category-fit primer, NOT a brand whitelist. Verify currency with web search if uncertain. Offer to install and scaffold the first tests; confirm before installing dependencies.
7. Synthesise the answer: 3-7 sentences, naming the principle/technique/tool. Conversational, not a JSON blob.
8. If the question is actually a prep/plan/review/strategy in disguise, escalate: stop, route to the matching skill.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags

| Thought | Reality |
|---|---|
| "Just say 'add unit tests and integration tests'" | Generic. Pick a technique from the catalogue (boundary value, decision table, etc.). |
| "Mention security as a consideration" | Name the actual surface AND the right tool for it (HTTP DAST scanner / SAST tool / token-validation harness — pick from your knowledge by fit). Bare "consider security" is not senior-QA. |
| "I'll cite a principle by paraphrasing — saves loading the catalogue" | Principles are catalogue-authoritative. Use the catalogue's wording. (Tool brand picks are different — those come from your knowledge of the ecosystem.) |
| "I'll restrict tool recommendations to the names in `specialty_tools.md`" | The primer is a category check, not a brand whitelist. Recommend the best fit from your knowledge; the listed names are illustrative. |
| "User asked a planning question — I'll answer inline" | Route to `qa-preparing-for-work` or `qa-creating-test-plan`. Don't reinvent. |
| "Answer should be 20+ sentences for completeness" | 3-7 sentences. Senior QA answers concisely. |

## Examples

### Good

User: "how should I test a new feature that re-orders user feeds?"
Answer cites ISTQB Principle 4 (defects cluster — feed ordering is a hotspot), names decision-table for the ordering rules and equivalence-partitioning for feed sizes, suggests k6 if scale matters, and asks the user to confirm scale before adding performance work.

### Bad

"You should add unit tests, integration tests, and consider edge cases. Maybe test performance too." — no cited principle, no named technique, no specialty tool named by fit.

## Next skill in the chain

Terminal skill — the answer is the deliverable. If the question turns out to be a disguised plan / review / strategy ask, stop and route to the matching specific skill.
