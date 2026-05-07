---
name: qa-deciding-approach
description: Use as the FIRST step on any QA intent. Calls sumo_qa_decide_approach to AI-reason over QA principles + the team's loaded standards + the change shape. The decision is open-ended — the AI may pick from canonical approaches or invent a new one for the situation. Routes to whichever sub-skill the recommended_approach.next_action.tool names.
---

## When to load

The host model loads this skill on **any QA-shaped intent** — code review, test scaffolding, "plan QA", "fix bug", "refactor", "what tests do I need", "increase coverage", "kill surviving mutants", "should I write tests for X". This is the precondition to every other QA skill.

Do NOT load it for:
- Pure information requests with no associated change ("explain what equivalence partitioning is")
- Already-decided flows (the user explicitly says "scaffold the tests for X" *and* the approach is unambiguously TDD-scaffold)

## The Iron Law

```
ONE sumo_qa_decide_approach CALL, THEN FOLLOW WHATEVER IT RETURNS — DO NOT GUESS, DO NOT KEYWORD-MATCH
```

The decider AI-reasons over QA principles + the team's standards + the actual change shape (when the host supports MCP sampling), or falls back to a deterministic safety net (when sampling isn't available). Either way, **trust the recommended_approach** — don't second-guess based on your own keyword reading of the intent.

## Why the AI path matters

Static keyword matching fails on inputs like:
- *"increase test coverage on the BundleVariantValidator POC branch — Pitest test strength at 86%, 6 surviving mutations, no production code changes"*

A senior QA reading that sentence reasons:
1. "No production code changes" → not a tdd-scaffold case (no new behaviour)
2. "Pitest test strength" + "surviving mutations" → mutation-testing follow-up
3. "POC branch" → additive change, no refactor planned
4. Therefore: strengthen-test-coverage with rationale citing Foundation principle 5 (pesticide paradox)

The AI does this reasoning natively when sampling is available. The deterministic fallback covers the typical canonical cases. Both produce a `recommended_approach` with `approach`, `rationale`, `next_action`, `techniques`, `specialty_needs`, `alternatives`, `confidence`, and `reasoned_by` (`"ai"` or `"deterministic"`).

## Checklist

1. **Gather the intent text** — the user's actual ask, verbatim. Don't paraphrase.
2. **Gather target paths if mentioned** — file paths, components, modules.
3. **Call `sumo_qa_decide_approach(intent_text=..., target_paths=[...])`**. The MCP attempts AI reasoning first; falls back deterministically if sampling fails.
4. **Read the returned `recommended_approach`**:
   - `approach`: name of the chosen discipline (canonical or AI-invented)
   - `rationale`: cites at least one principle / standard
   - `next_action`: which MCP tool to call next, or `null` if no tool fires
   - `follow_up`: what to do regardless of which tool fires
   - `techniques`: ISTQB techniques most relevant
   - `specialty_needs`: extra capabilities to pull in (Cypress, k6, mutation tools, etc.)
   - `alternatives`: when to pick something else
   - `confidence`: low / medium / high
   - `reasoned_by`: `"ai"` (sampling succeeded) or `"deterministic"` (fallback)
5. **Tell the user the approach in one line**:
   ```
   APPROACH: <approach> (<confidence>, reasoned_by=<ai|deterministic>) — <rationale>
   Next: <next_action.tool> (or "no tool — <follow_up snippet>")
   ```
6. **Branch on `next_action.tool`**:
   - `sumo_qa_scaffold_tests` → load `qa-implementing-with-tdd` (or `qa-strengthening-tests` if the approach name is `strengthen-test-coverage`)
   - `sumo_qa_review_local_change` → load `qa-reviewing-before-merge`
   - `null` → tell the user the follow-up; do not call further tools
   - **other / AI-invented** → use the follow_up text as the workflow; the `techniques` and `specialty_needs` are your shopping list for what to do next
7. **Wait for confirmation OR `low` confidence**. If confidence is `low`, ask one focused question to disambiguate.

## Red Flags — STOP

| Thought | Reality |
|---------|---------|
| "I'll skip sumo_qa_decide_approach because the prompt says 'review my changes'" | Decide first. The change might be a config tweak, a docs change, or a bug-reproducer-needed case. The AI considers context you may not. |
| "The AI returned an approach I don't recognise; I'll fall back to tdd-scaffold" | Trust the AI's reasoning if the rationale cites a principle. Open-ended approaches are the point — every repo and team is different. |
| "reasoned_by: deterministic, so the decision is wrong" | Wrong. The deterministic decider catches the most common cases correctly. Override only if the rationale clearly contradicts your reading of the intent. |
| "Confidence is low, I'll guess" | `low` confidence is a signal to ASK ONE QUESTION, not silently assume. |
| "Two approaches both fit; I'll do both" | Pick one based on the rationale. Doing both wastes time. |
| "User already said 'scaffold tests', skip the decide step" | Decide and announce. If the AI says "you said scaffold but the change shape is X, which is `regression-first`", saving the user from a wrong-shaped scaffold IS the value. |
| "I'll just keyword-match the intent in my head and skip the call" | That's the failure mode this whole skill exists to prevent. The MCP costs ~50ms; your guesswork costs the user a wrong-shaped output. |

## Examples

### AI path produces a non-canonical approach

User: *"our service has a flaky integration test that fails 1 in 20 runs against the staging Kafka cluster — figure out what to do"*

The AI might return:
```
approach: "stabilise-flaky-integration-test"
rationale: "Foundation principle 6 (testing is context-dependent): a flaky test against a shared environment is a different shape than a deterministic-fail bug. Diagnose first (timing, ordering, leakage), only then decide whether to fix the test, the production code, or both."
next_action: { "tool": "sumo_qa_review_local_change" }
follow_up: "Use the review to surface what the test asserts; classify flakiness root cause (timing / shared-state / nondeterministic-data); then either tighten the assertion, add retry-with-backoff, or restructure the test fixture."
techniques: ["state transition testing", "error guessing on race conditions", "test-execution sequence analysis"]
specialty_needs: [{"approach": "Test isolation tooling", ...}]
confidence: "medium"
reasoned_by: "ai"
```

The skill follows this. It doesn't fall back to "well, that's not in my list of 7" — `stabilise-flaky-integration-test` is a valid AI-invented approach and the rationale cites a principle.

### Deterministic fallback path

Host doesn't support sampling. User says: *"refactor the order pipeline to extract the validation step"*.

→ AI sampling skipped or fails. Deterministic decider fires. Returns `coverage-first-then-refactor` (high confidence) with `reasoned_by: "deterministic"`.

→ Skill announces, branches to `qa-implementing-with-tdd`'s coverage-first branch. Same outcome as if AI had reasoned.

### Disagreement between AI and deterministic

The deterministic-fallback hint is included in the AI's prompt. The AI may agree or override. Either way, the AI's choice wins (when sampling succeeded). The deterministic suggestion is just a tiebreaker for thin inputs.

## Final rule

```
QA intent → call sumo_qa_decide_approach exactly once → trust the AI-reasoned (or deterministic-fallback) decision → announce → route or stop.
```
