---
name: sumo-qa-answering-testing-question
description: Use when the user asks a generic testing question — "how do I test this?", "what should I check for X?" — that doesn't fit a more specific QA skill. Cites a principle or technique from the loaded catalogue rather than producing generic advice.
---

# Answering a testing question

**Announce at start:** *"Answering with a cited principle and technique."*

## Before answering — check fit (Redirect discipline)

This is the FIRST step the candidate takes before answering with catalogue principles.

- "Are my PR tests good enough?" / "Is this safe to merge?" / "Review my changes" → redirect to `sumo-qa-reviewing-before-merge`. Say: "This is a PR-review-adequacy question. Loading sumo-qa-reviewing-before-merge — it inspects the diff, surfaces named risks, runs the suite, and delivers a gated verdict. That is the right tool here, not catalogue citation."
- "How should I plan QA for [story/ticket]?" → redirect to `sumo-qa-preparing-for-work` (lightweight) or `sumo-qa-creating-test-plan` (formal).
- "Write me a failing test for [bug]" → redirect to `sumo-qa-implementing-with-tdd`.
- "Mutation testing flagged survivors" / "kill these mutants" → redirect to `sumo-qa-strengthening-tests`.
- "Where is the test data for X?" / "validate this record" → redirect to `sumo-qa-finding-test-data`.

ONLY answer directly when the question is genuinely generic (e.g. "what is the ISTQB principle for X?", "how do boundary tests work?") and does not fit any of those domains.

**Anti-pattern:** Do NOT answer a PR-review, plan-QA, write-a-test, mutation-survivor, or test-data question with catalogue principles. Redirect to the matching sumo-qa skill instead.

## Output discipline (mandatory)

**Never surface internal taxonomy labels in user-facing output.** No "Classification: X", "Approach: Y", "Per the checklist", "Step 3 of 6". The taxonomy is internal scaffolding; translate to natural English when the meaning matters to the user — *"this is a behaviour change in pricing"*, not *"Classification: business_logic_change"*. If you catch yourself typing a label, delete it.

## Output economy (mandatory)

Spend output tokens on findings, not framing.

- **Don't preamble the work.** Spend user-visible output on findings, evidence, and gates — don't narrate *"I'll first read X, then Y, then deliver Z."*
- **One question per turn, only when blocked.** Ask a clarifying question only when the answer cannot proceed without it; don't follow a usable answer with *"shall I proceed or clarify first?"* — the question IS the gate.
- **No self-narration.** *"Let me now..."* / *"I'm going to..."* → just do it.
- **Don't restate the user's input.** They know what they asked.
- **Section headings only when there are genuinely multiple sections.** A 3-line scope check doesn't need a `## Scope` heading.
- **Tables only when comparing >2 things on >2 axes.** Otherwise prose is shorter.
- **No closing pleasantries.** No *"happy to dig deeper"* / *"let me know if you want X"* — the next-skill handoff at the bottom of every skill is where routing lives.

<HARD-GATE>
Principle citations MUST quote the loaded principles catalogue's exact heading wording. NEVER extend a principle name with technique-level descriptors. Examples of FORBIDDEN fake principles:
- "defects cluster at boundaries" — extends real "Defects cluster" with boundary-value-technique wording
- "exhaustive testing is impossible without risk-based prioritisation" — extends "Exhaustive testing is impossible" with technique-level addition
- "early testing reduces cost" — interpretive paraphrase of "Test early"

Principle wording is FIXED. If a thought needs technique-level wording, cite the technique by name AS WELL AS the principle by name — never combine the two into a hybrid principle.
</HARD-GATE>

## The Iron Law
NO ANSWER WITHOUT A CITED PRINCIPLE AND TECHNIQUE. Citations must use the exact loaded catalogue names/wording from `sumo_qa_load_principles()` and `sumo_qa_load_techniques()`. Do not paraphrase, rename, or combine principle wording with technique wording — e.g. do not turn `Defects cluster` plus boundary-value text into a fake principle like 'defects cluster at boundaries'.

Every answer ties to a named ISTQB principle and a named test design technique from the loaded catalogue. When a specialty surface is implied, follow the discovery discipline from `using-sumo-qa` — reason from the surface, web-search current options, cite when naming a tool. Sumo-qa intentionally does NOT carry a tool catalogue.

## When to Use

`sumo-qa-deciding-approach` routes here when the user's intent is question-shaped but doesn't fit a more specific skill:

- "how do I test this service?"
- "what should I check for X feature?"
- "any QA suggestions for this design?"
- "what's the right test type for this?"

For "create a plan" / "prep for work" / "review my changes" → use the more specific skills.

## Checklist
Track these as an ordered work list (use the host's task primitive if available, otherwise a numbered inline tracker) and complete in order:

1. Read the user's question verbatim.
2. Read any code/paths/specs the user supplied (host's file tools).
3. Call `sumo_qa_load_principles()` and `sumo_qa_load_techniques()`. Read both catalogues.
4. Identify the QA shape the question implies: what's the actual concern (correctness / regression / coverage / risk surface)?
5. Pick at least one principle that shapes the answer (cite by number or name). Pick at least one technique whose shape matches the user's question — verbatim from `knowledge/techniques.md`. Use these surface→technique mappings before reaching for a familiar default:
   Each bullet pairs the **technique** with the **principle** that anchors it for that surface — pick from the principle list shown, do not default to "Testing shows the presence of defects" (it's catalogue-valid but generic; it doesn't characterise any specific risk surface). **Verbatim copy rule:** technique and principle names must reproduce the catalogue wording byte-for-byte, including spaces around `/`, parentheses, and punctuation. Write *"MC-DC (modified condition / decision coverage)"* — NOT *"MC-DC (modified condition/decision coverage)"*. Paraphrasing or normalising whitespace fails grounding.
   - **Pure-function / invariant / "no matter what input" question** → technique: property-based testing (NOT decision tables — those fit rule matrices, not invariants over generated inputs). Principle: `Exhaustive testing is impossible; use risk and prioritisation.` (generated inputs are how you cover a space you can't enumerate) or `Defects cluster` (invariants are violated where ranking ties / sentinel scores cluster).
   - **Safety-critical / regulated / healthcare / aviation / finance domain** → technique: MC-DC, decision tables, review (walkthrough / technical review / inspection), or static analysis. NOT state transition testing unless the user specifically describes a state machine. Principle: `Testing is context-dependent` (safety-critical / regulated context drives technique mix) or `Early testing saves time and money — shift left.` (defects in safety-critical code are 10x cheaper caught in review than in production).
   - **"Is X worth it?" effort/value question about mutation testing** → technique: mutation testing, framed as a targeted risk tradeoff (not a blanket mandate); the answer MUST contain the literal phrases *"assertion gap"* and *"equivalent mutant"* (or *"equivalent mutants"*) and MUST explain that surviving mutants are signals to inspect — they are either an assertion gap (real test weakness) OR an equivalent mutant (suppress in config). Omitting either phrase collapses the framing into vague advice and fails relevance. Principle: `Pesticide paradox` (the same green tests stop finding defects — mutation refreshes assertions) or `Exhaustive testing is impossible; use risk and prioritisation.` (focus mutation effort on critical logic, not the whole repo).
   - **Boundary / threshold / range question** → technique: boundary value analysis + equivalence partitioning. Principle: `Defects cluster` (off-by-one and limit defects cluster at boundaries — that's why this technique exists).
6. If the question implies a specialty surface, follow the discovery discipline from `using-sumo-qa` — observe the surface, reason from first principles about what shape of testing fits, web-search current options for the user's stack, recommend with citation. Sumo-qa intentionally does NOT carry a tool catalogue. "I don't know" is acceptable. Offer to install and scaffold the first tests; confirm before installing dependencies.
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
| "I'll restrict myself to tool categories I already know" | Wrong. Specialty tooling exists for functional surfaces too, and new categories emerge constantly. Reason from the surface, web-search current options, recommend with citation. There's no internal catalogue to fall back on. |
| "User asked a planning question — I'll answer inline" | Route to `sumo-qa-preparing-for-work` or `sumo-qa-creating-test-plan`. Don't reinvent. |
| "Answer should be 20+ sentences for completeness" | 3-7 sentences. Senior QA answers concisely. |
| "I'll mash 'Defects cluster' with boundary wording to make my point smoother" | FORBIDDEN. Cite the real principle ("Defects cluster") AND the technique ("boundary value analysis") separately. The hybrid "defects cluster at boundaries" is a fake principle that doesn't exist in the catalogue. |

## Examples

### Good — risk-shaped surface

User: "how should I test a new feature that re-orders user feeds?"
Answer cites ISTQB Principle 4 (defects cluster — feed ordering is a hotspot), names decision-table for the ordering rules and equivalence-partitioning for feed sizes, suggests k6 if scale matters, and asks the user to confirm scale before adding performance work.

### Good — "is X worth it?" mutation-testing question

User: "Is mutation testing worth the effort for our small Go service?"
Answer cites `Pesticide paradox` (green tests stop finding defects — mutation refreshes assertions), names `mutation testing` verbatim, then anchors three load-bearing claims explicitly: (1) **focus on critical logic, not as a blanket mandate** across the whole service; (2) **surviving mutants are signals to inspect**, not auto-triggers to rewrite production code; (3) each survivor is **either an assertion gap (real) or an equivalent mutant (suppress in config)** — the call belongs to the developer. Suggests Gremlins (Go mutation tooling) and asks which package carries the most release risk before scoping a run.

### Bad

"You should add unit tests, integration tests, and consider edge cases. Maybe test performance too." — no cited principle, no named technique, no specialty tool named by fit.

## Next skill in the chain

Terminal skill — the answer is the deliverable. If the question turns out to be a disguised plan / review / strategy ask, stop and route to the matching specific skill.
