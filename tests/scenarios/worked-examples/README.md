# Worked examples — sumo-qa in action

Ten interaction transcripts showing what sumo-qa looks like in conversation when a user asks it to do real QA work.

Each example covers a distinct QA scenario and follows the same shape: a one-line summary, the multi-turn interaction (with internal-thinking blockquotes for the agent's reasoning), and a closing "Why this is senior QA" footer that names the discipline beats the agent applied.

| # | Scenario | Skill activated | Key discipline beat |
|---|---|---|---|
| [01](01-plan-qa-for-story.md) | Plan QA for a new story before coding | `sumo-qa-preparing-for-work` | Walks the repo before asking; risks anchored to file:line. |
| [02](02-review-my-changes.md) | Review uncommitted changes before merging | `sumo-qa-reviewing-before-merge` | HARD GATE on fresh test evidence; risk-to-test coverage map; refuses to declare safe-to-merge with an uncovered risk. |
| [03](03-fix-bug-regression-first.md) | Fix a production bug regression-first | `sumo-qa-implementing-with-tdd` (regression-first) | Won't write test + production code in the same turn; surfaces the red output as proof. |
| [04](04-add-tests-tdd-scaffold.md) | Add tests for a new feature (TDD-scaffold) | `sumo-qa-implementing-with-tdd` (tdd-scaffold) | One red→green cycle at a time; refuses to scaffold all 5 tests up front. |
| [05](05-strengthen-tests-mutation.md) | Strengthen tests against mutation survivors | `sumo-qa-strengthening-tests` | Production code stays unchanged; walks one mutant at a time with tautology checks. |
| [06](06-generic-testing-question.md) | "How do I test this?" — generic question | `sumo-qa-answering-testing-question` | Cites an ISTQB principle by number, names a technique, picks a tool by fit. 4 sentences, not a 20-line essay. |
| [07](07-find-test-data.md) | Find a known-good test data record | `sumo-qa-finding-test-data` | Fresh-validates in this turn; surfaces stale entries explicitly; confirmation gate before catalogue writes. |
| [08](08-audit-and-strategy.md) | Audit coverage + design QA strategy | `sumo-qa-strategising` | Walks the repo with file tools; phased rollout with named gates, not a calendar; honest residual-risk list. |
| [09](09-formal-test-plan.md) | Formal test plan with entry/exit criteria | `sumo-qa-creating-test-plan` | HARD GATE — no plan without measurable entry AND exit criteria. |
| [10](10-no-tests-needed.md) | Trivial change — typo in a doc | `sumo-qa-deciding-approach` (terminates) | Restraint — picks `no-tests-recommended` and stops. Doesn't manufacture work. |

## Notable examples

- **[02 — review-my-changes](02-review-my-changes.md)** — the agent refuses to declare safe-to-merge when a named risk has no covering test, and suggests the exact regression test that would close the gap.
- **[03 — regression-first bug fix](03-fix-bug-regression-first.md)** — TDD discipline visibly enforced: the agent refuses to bundle the test and the production fix in one turn, surfaces the red output as proof, and hands off cleanly.
- **[06 — generic testing question](06-generic-testing-question.md)** — the shortest example. A 4-sentence catalogue-anchored answer that cites an ISTQB principle by number, names a specific design technique, and recommends a specialty tool by fit.
- **[10 — no tests needed](10-no-tests-needed.md)** — the restraint case. For a documentation typo, the agent correctly picks `no-tests-recommended` and stops, rather than manufacturing test work.

## How these were produced

For each scenario, the relevant skill file (`skills/<name>/SKILL.md`) defines the discipline. An agent followed the skill literally on the scenario prompt; the resulting transcript was captured here. These are point-in-time validations that the skills produce the interaction quality the scenario specs in [`../SCENARIOS.md`](../SCENARIOS.md) describe.

They are **not regenerated on every commit**. The skills' Iron Laws, HARD-GATE callouts, anti-pattern callouts, and red-flag tables are what enforce the discipline at runtime. These transcripts document the resulting interaction style for readers who want to see it without installing the tool.

To regenerate or extend an example after changing a skill, dispatch an agent with the scenario prompt plus the updated skill and let it role-play. Pull the result into `worked-examples/`.

## Coverage gap (open follow-up)

The 10 worked examples cover skills #1–10 in `SCENARIOS.md`. Scenarios #11–15 (router invocation, planning-rollout, executing-rollout, finishing-work, suggesting-external-skill) were added to the spec by the LLM-evals design pass; their worked examples are an open follow-up — write them by dispatching an agent against each scenario prompt with the matching skill loaded.

## Related design docs

- [`../SCENARIOS.md`](../SCENARIOS.md) — 17 skill behaviour scenarios (input, expected interaction shape, anti-patterns).
- [`../TOOL-SELECTION.md`](../TOOL-SELECTION.md) — 10 atomic-tool selection scenarios (which tool the host LLM should pick for which intent) + a transitive map for the 15 skill-tool selections.
- [`../LLM-EVALS.md`](../LLM-EVALS.md) — design for turning the scenario specs above into LLM-as-judge evals (rubric templates, cadence, costs, open design questions).
