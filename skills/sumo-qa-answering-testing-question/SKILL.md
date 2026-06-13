---
name: sumo-qa-answering-testing-question
description: Use when the user asks a generic testing question — "how do I test this?", "what should I check for X?" — that doesn't fit a more specific QA skill. Cites a principle or technique from the loaded catalogue rather than producing generic advice.
---

# Answering a testing question

**Announce at start:** *"Answering with a cited principle and technique."*

## Before answering — check fit (Redirect discipline)

FIRST step. Redirect — don't answer with catalogue principles — when the question is really:

- *"Are my PR tests good enough / safe to merge / review my changes"* → `sumo-qa-reviewing-before-merge` (it inspects the diff, names risks, runs the suite, delivers a gated verdict — the right tool here, not catalogue citation).
- *"plan QA for [story/ticket]"* → `sumo-qa-preparing-for-work` (lightweight) or `sumo-qa-creating-test-plan` (formal).
- *"write me a failing test for [bug]"* → `sumo-qa-implementing-with-tdd`.
- *"mutation flagged survivors / kill these mutants"* → `sumo-qa-strengthening-tests`.
- *"where is the test data for X / validate this record"* → `sumo-qa-finding-test-data`.

ONLY answer directly when the question is genuinely generic (*"what is the ISTQB principle for X?"*, *"how do boundary tests work?"*) and fits none of those. **Anti-pattern:** answering a PR-review / plan-QA / write-a-test / mutation-survivor / test-data question with catalogue principles instead of redirecting.

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: **output discipline** (never surface internal taxonomy labels — say *"behaviour change in pricing"*, not *"Classification: business_logic_change"*), **output economy** (spend output on findings not framing; no preamble or self-narration; one clarifying question only when blocked; no closing pleasantries), knowledge authority hierarchy, internal scaffolding stays internal, and specialty-tool fit.

<HARD-GATE>
Principle citations MUST quote the loaded principles catalogue's exact heading wording. NEVER extend a principle name with technique-level descriptors. Examples of FORBIDDEN fake principles:
- "defects cluster at boundaries" — extends real "Defects cluster" with boundary-value-technique wording
- "exhaustive testing is impossible without risk-based prioritisation" — extends "Exhaustive testing is impossible" with technique-level addition
- "early testing reduces cost" — interpretive paraphrase of "Test early"

Principle wording is FIXED. If a thought needs technique-level wording, cite the technique by name AS WELL AS the principle by name — never combine the two into a hybrid principle.
</HARD-GATE>

## The Iron Law
NO ANSWER WITHOUT A CITED PRINCIPLE AND TECHNIQUE — both verbatim from `sumo_qa_load_principles()` and `sumo_qa_load_techniques()`, never paraphrased, renamed, or fused into a hybrid (see the HARD-GATE). When a specialty surface is implied, follow the discovery discipline from `using-sumo-qa` — reason from the surface, web-search current options, cite when naming a tool. Sumo-qa intentionally does NOT carry a tool catalogue.

## When to Use

`sumo-qa-deciding-approach` routes here when the intent is question-shaped but fits no more-specific skill — *"how do I test this service?"*, *"what should I check for X?"*, *"any QA suggestions for this design?"*, *"what's the right test type?"*. For *"create a plan"* / *"prep for work"* / *"review my changes"* → the more specific skills.

## Checklist
Track these as an ordered work list, in order:

1. Read the question verbatim.
2. Read any code/paths/specs the user supplied (host's file tools).
3. Call `sumo_qa_load_principles()` and `sumo_qa_load_techniques()`. Read both catalogues.
4. Identify the QA shape the question implies: what's the actual concern (correctness / regression / coverage / risk surface)?
5. Pick at least one principle (cite by number or name) and at least one technique whose shape matches the question — both verbatim from the loaded catalogues. Use these surface→technique mappings before defaulting; don't default to "Testing shows the presence of defects" (catalogue-valid but generic — it characterises no specific risk surface). **Verbatim copy rule:** reproduce catalogue wording byte-for-byte, including spaces around `/`, parentheses, and punctuation — write *"MC-DC (modified condition / decision coverage)"*, NOT *"...modified condition/decision coverage..."*. Normalising whitespace fails grounding.
   - **Pure-function / invariant / "no matter what input" question** → technique: property-based testing (NOT decision tables — those fit rule matrices, not invariants over generated inputs). Principle: `Exhaustive testing is impossible; use risk and prioritisation.` (generated inputs cover a space you can't enumerate) or `Defects cluster` (invariants break where ranking ties / sentinel scores cluster).
   - **Safety-critical / regulated / healthcare / aviation / finance domain** → technique: MC-DC, decision tables, review (walkthrough / technical review / inspection), or static analysis. NOT state transition testing unless the user describes a state machine. Principle: `Testing is context-dependent` (regulated context drives the technique mix) or `Early testing saves time and money — shift left.` (safety-critical defects are 10x cheaper caught in review than production).
   - **"Is X worth it?" effort/value question about mutation testing** → technique: mutation testing, framed as a targeted risk tradeoff (not a blanket mandate); the answer MUST contain the literal phrases *"assertion gap"* and *"equivalent mutant"* (or *"equivalent mutants"*) and explain surviving mutants are signals to inspect — either an assertion gap (real test weakness) OR an equivalent mutant (suppress in config). Omitting either phrase fails relevance. Principle: `Pesticide paradox` (green tests stop finding defects — mutation refreshes assertions) or `Exhaustive testing is impossible; use risk and prioritisation.` (focus mutation on critical logic).
   - **Boundary / threshold / range question** → technique: boundary value analysis + equivalence partitioning. Principle: `Defects cluster` (off-by-one and limit defects cluster at boundaries — that's why the technique exists).
   - **Security-relevant surface (auth/authorisation, secrets/token, input sanitisation, rate limiting, a "security checklist / what tools" question)** → run the grounded security-relevance pass from `using-sumo-qa`: name the CONCRETE failure mode the described change actually creates (a non-owner reaching a protected path, a reset token that never expires or is replayable, an unsanitised input reaching a sink) and map it to a normal next action (a negative-path test, a review, static/dynamic analysis). Technique: `decision tables` (valid/expired/tampered/replayed conditions), `state transition testing` (token lifecycle), `boundary value analysis` (TTL/expiry), `error guessing`, `review`, or `static analysis` — verbatim from the catalogue. Principle: `Testing is context-dependent` or `Early testing saves time and money — shift left.` NEVER recite a vulnerability checklist or dump vendor/tool names; if the user asks for a "checklist" or "tool list", REFRAME to the concrete failure modes and pick any tool by the discovery discipline (grounded in the stack). If the change has no grounded security surface, do not raise security at all.
6. If the question implies a specialty surface, follow the discovery discipline from `using-sumo-qa` (observe the surface, reason from first principles, web-search current options, recommend with citation; "I don't know" is acceptable — no internal tool catalogue). Offer to install and scaffold the first tests; confirm before installing deps.
7. Synthesise: 3-7 sentences naming the principle/technique/tool; conversational, not a JSON blob.
8. If the question is a prep/plan/review/strategy in disguise, stop and route to the matching skill.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags

| Thought | Reality |
|---|---|
| "Just say 'add unit tests and integration tests'" | Generic. Pick a technique from the catalogue (boundary value, decision table, etc.). |
| "Mention security as a consideration" / "dump the OWASP checklist they asked for" | Name the CONCRETE grounded failure mode the change creates and map it to a next action (test/review/static/dynamic check); reframe a "checklist/tool list" request rather than dumping one. Bare "consider security", a vulnerability-category list, or a vendor/tool-name dump is not senior-QA. If no grounded security surface, don't raise it. |
| "I'll cite a principle by paraphrasing — saves loading the catalogue" | Principles are catalogue-authoritative. Use the catalogue's wording. (Tool brand picks are different — those come from your knowledge of the ecosystem.) |
| "I'll restrict myself to tool categories I already know" | Wrong. Specialty tooling exists for functional surfaces too, and new categories emerge constantly. Reason from the surface, web-search current options, recommend with citation. There's no internal catalogue to fall back on. |
| "User asked a planning question — I'll answer inline" | Route to `sumo-qa-preparing-for-work` or `sumo-qa-creating-test-plan`. Don't reinvent. |
| "Answer should be 20+ sentences for completeness" | 3-7 sentences. Senior QA answers concisely. |

## Examples

### Good — risk-shaped surface

User: "how should I test a new feature that re-orders user feeds?"
Answer cites ISTQB Principle 4 (defects cluster — feed ordering is a hotspot), names decision-table for the ordering rules and equivalence-partitioning for feed sizes, suggests k6 if scale matters, and asks the user to confirm scale before adding performance work.

### Good — "is X worth it?" mutation-testing question

User: "Is mutation testing worth the effort for our small Go service?"
Answer cites `Pesticide paradox` (green tests stop finding defects — mutation refreshes assertions), names `mutation testing` verbatim, then anchors three claims: (1) focus on critical logic, not a blanket mandate; (2) surviving mutants are signals to inspect, not auto-triggers to rewrite production code; (3) each survivor is either an assertion gap (real) or an equivalent mutant (suppress in config) — the developer's call. Suggests Gremlins (Go mutation tooling) and asks which package carries the most release risk before scoping a run.

### Good — "give me the security checklist / tool list" (refuse the dump, reframe to grounded gaps)

User: "Give me the full security testing checklist and the list of security tools for my new password-reset email flow."
Do NOT hand over a generic checklist or a vendor tool list. Reframe to the CONCRETE failure modes the password-reset flow actually creates: a reset token that never expires or is replayable (single-use not enforced), or valid-email enumeration via the response. Name `decision tables` (valid / expired / already-used / replayed token) and `state transition testing` (token lifecycle ISSUED → CONSUMED → EXPIRED), cite `Testing is context-dependent`, and map each to a next action — a negative-path test that an expired or already-used token is rejected, plus a review of the enumeration response. Pick any scanner by the discovery discipline (grounded in the stack), or ask ONE question about the stack first — never recite OWASP categories or a tool roster.

### Bad

"You should add unit tests, integration tests, and consider edge cases. Maybe test performance too." — no cited principle, no named technique, no specialty tool named by fit.

### Bad — security checklist dump

"Run the OWASP Top 10 checklist: injection, broken auth, XSS, CSRF… and use ZAP, Burp, and a SAST scanner." — a vulnerability-category recital plus a vendor tool roster, neither grounded in the password-reset flow's concrete failure modes. The reframe to token-expiry / single-use / replay / enumeration is what senior QA owes here.

## Next skill in the chain

Terminal skill — the answer is the deliverable. A disguised plan/review/strategy ask → stop and route (see redirect discipline above).
