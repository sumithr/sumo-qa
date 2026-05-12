# Worked examples — sumo-qa in action

Ten polished interaction transcripts showing what sumo-qa looks like when a user actually asks it to do real QA work. These are the demo references — if you're showing this tool to your team, lead with these.

Each example covers a distinct QA scenario, follows the same shape (Demo arc → multi-turn interaction with internal-thinking blockquotes → "Why this is senior QA" footer), and demonstrates one or more discipline beats sumo-qa enforces that a generic AI would skip.

| # | Scenario | Skill activated | Demo beat |
|---|---|---|---|
| [01](01-plan-qa-for-story.md) | Plan QA for a new story before coding | `qa-preparing-for-work` | Walks the repo before asking; risks anchored to file:line. |
| [02](02-review-my-changes.md) | Review uncommitted changes before merging | `qa-reviewing-before-merge` | HARD GATE on fresh test evidence; risk-to-test coverage map; refuses to declare safe-to-merge with an uncovered risk. |
| [03](03-fix-bug-regression-first.md) | Fix a production bug regression-first | `qa-implementing-with-tdd` (regression-first) | Won't write test + production code in the same turn; surfaces the red output as proof. |
| [04](04-add-tests-tdd-scaffold.md) | Add tests for a new feature (TDD-scaffold) | `qa-implementing-with-tdd` (tdd-scaffold) | One red→green cycle at a time; refuses to scaffold all 5 tests up front. |
| [05](05-strengthen-tests-mutation.md) | Strengthen tests against mutation survivors | `qa-strengthening-tests` | Production code stays unchanged; walks one mutant at a time with tautology checks. |
| [06](06-generic-testing-question.md) | "How do I test this?" — generic question | `qa-answering-testing-question` | Cites an ISTQB principle by number, names a technique, picks a tool by fit. 4 sentences, not a 20-line essay. |
| [07](07-find-test-data.md) | Find a known-good test data record | `qa-finding-test-data` | Fresh-validates in this turn; surfaces stale entries explicitly; confirmation gate before catalogue writes. |
| [08](08-audit-and-strategy.md) | Audit coverage + design QA strategy | `sumo-qa-strategising` | Walks the repo with file tools; phased rollout with named gates, not a calendar; honest residual-risk list. |
| [09](09-formal-test-plan.md) | Formal test plan with entry/exit criteria | `qa-creating-test-plan` | HARD GATE — no plan without measurable entry AND exit criteria. |
| [10](10-no-tests-needed.md) | Trivial change — typo in a doc | `qa-deciding-approach` (terminates) | Restraint — picks `no-tests-recommended` and stops. Doesn't manufacture work. |

## What to point at in a demo

- **[02 — review-my-changes](02-review-my-changes.md)** is the highest-impact opener. It shows the AI refusing to declare safe-to-merge, naming a real risk with no covering test, and producing a concrete suggested-fix path. *"Most AIs would have said this is safe. Mine caught the gap."*
- **[03 — regression-first bug fix](03-fix-bug-regression-first.md)** is the strongest demonstration of TDD discipline visibly enforced — the agent refuses to bundle the test and the production fix, surfaces the red output, and hands off cleanly.
- **[06 — generic testing question](06-generic-testing-question.md)** is the shortest, sharpest example. Use it as the "before-and-after" beat: contrast the 4-sentence catalogue-anchored answer against the generic-AI checklist that says nothing.
- **[10 — no tests needed](10-no-tests-needed.md)** is the surprising one. The wow factor here is RESTRAINT — most AI assistants over-test. This one correctly says "no tests needed" for a typo and stops.

## How these were produced

For each scenario, the relevant skill file (`skills/<name>/SKILL.md`) defines the discipline. An agent followed the skill literally on the scenario prompt; the resulting transcript was captured here. These are point-in-time validations that the skills produce the interaction quality the scenario specs in [`../SCENARIOS.md`](../SCENARIOS.md) describe.

They're **not regenerated on every commit** (would cost API credits each time). The skills' Iron Laws, HARD GATEs, anti-pattern callouts, and red-flag tables are what enforce the discipline in production. These transcripts are the visible proof that the discipline produces good interactions, and the demo material you can show without running the tool live.

To regenerate or extend a worked example after changing a skill, dispatch an agent with the scenario prompt + the updated skill and let it role-play. Pull the result into `worked-examples/`.
