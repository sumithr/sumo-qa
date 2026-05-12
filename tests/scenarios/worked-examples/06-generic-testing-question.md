# Scenario 06 — Generic testing question

> **Demo arc:** *"the AI gave a 4-sentence answer that cited an ISTQB principle by number, named a specific design technique, and recommended a specialty tool — instead of 'add unit tests and consider edge cases'."*
>
> Shows: catalogue-anchored reasoning, one focused clarification (not an interrogation), concise senior-QA answer, specialty tool picked by fit not by reflex.

---

## Turn 1 — User

> How should I test a service that re-orders user feeds based on engagement signals?

---

## Turn 2 — sumo-qa

*(internal: invokes `qa-deciding-approach`. Intent is question-shaped — not a plan, not a review, not a diff. Routes to `qa-answering-testing-question`.)*

*(internal: calls `sumo_qa_load_principles()` + `sumo_qa_load_techniques()`. Reads both catalogues.)*

*(internal: shape of the concern is — (a) correctness of the ordering rules themselves, (b) regression on existing ordering as new signals are added, (c) performance once the feed gets large. Re-ranking on engagement signals is a classic defect-cluster hotspot — Principle 4. Multiple input conditions combining into one output order → decision table. Feed sizes vary widely → equivalence partitioning. Scale is implied but not confirmed — one clarifying question is fair before naming a perf tool.)*

Two shapes of risk here, and a third that depends on your scale. **Principle 4 — defects cluster** — re-ranking logic is a textbook hotspot, because every new signal interacts with every existing rule, so regressions accumulate silently. I'd reach for a **decision table** to enumerate the signal combinations against the expected ordering (recency × engagement × author-affinity, whatever your inputs are) — that catches the rule-interaction bugs that ad-hoc unit tests miss. For the input-size dimension, **equivalence partitioning** on feed sizes (empty / single-item / typical / pathologically-large) covers the shape without exploding combinatorially.

One quick check before I name a perf tool: **does this service rank feeds at request time for many concurrent users, or is the ordering precomputed in a batch job?** If it's request-time at scale, I'd add **k6** for load-shape testing on the ranking endpoint — Principle 4 again, defects under contention cluster in re-ranking code. If it's batch, you don't need k6; you need a regression fixture that pins the output ordering for a known corpus.

---

## Why this is "senior QA" — what to point at in the demo

- **Cited principle by number.** *"Principle 4 — defects cluster"* — not a vague *"this is a risky area"*. The principle is doing actual work in the recommendation.
- **Named technique from the catalogue.** *"Decision table for the rule interactions; equivalence partitioning for feed sizes"* — two techniques, each tied to the specific risk shape. Not *"consider edge cases"*.
- **Specialty tool picked by fit, gated on context.** k6 is named *only if* the scale dimension is real. The agent doesn't reflex-recommend a tool for every question; it asks the one clarifying question that decides whether the tool applies.
- **3-7 sentences.** Senior QA answers concisely. No 20-sentence essay, no JSON blob, no false sectioning.
- **One clarifying question, not four.** Batch-vs-request-time is the single ambiguity that changes the recommendation. The agent asks that one and answers around it.

---

## What a generic AI would have said

> *"You should add unit tests, integration tests, and consider edge cases. Maybe test performance too. Don't forget to mock external dependencies and aim for high coverage."*

No cited principle. No named technique. No specialty tool picked by fit. No clarification — just a checklist any junior could recite from memory. **That's the bar sumo-qa is built to clear.**
