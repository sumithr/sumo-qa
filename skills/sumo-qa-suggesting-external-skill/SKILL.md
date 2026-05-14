---
name: sumo-qa-suggesting-external-skill
description: Use when the current QA intent requires a specialty surface (e2e, accessibility, performance, contract, mutation, flaky-test quarantine) that no built-in sumo-qa skill covers. Searches the trusted registry for an installable external skill, presents the best match with trust and install information, and gates install on explicit user confirmation.
---

# Suggesting an external skill

**Announce at start:** *"Checking the registry for a specialist skill."*

## Output discipline (mandatory)

**Never surface internal taxonomy labels in user-facing output.** No "Classification: X", "Approach: Y", "Per the checklist", "Step 3 of 6". The taxonomy is internal scaffolding; translate to natural English when the meaning matters to the user — *"this is a behaviour change in pricing"*, not *"Classification: business_logic_change"*. If you catch yourself typing a label, delete it.

Inherits the global discipline from `using-sumo-qa` (knowledge authority hierarchy, internal scaffolding stays internal, specialty-tool fit).

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

**NEVER INSTALL WITHOUT EXPLICIT USER CONFIRMATION.** The registry search and suggestion are silent internal work. The user sees a single proposal with the trust signal and the install command. Install runs only after they say yes.

Never silently elevate privileges — `sudo` must not be used. The install helper uses the user's own package manager without privilege escalation.

## When to Use

`sumo-qa-deciding-approach` routes here when the intent names a specialty surface that has no matching built-in skill:

- "write some e2e tests with Playwright"
- "run an accessibility audit"
- "set up contract tests with Pact"
- "add mutation testing"
- "quarantine flaky tests"
- "load-test this endpoint"

Do NOT route here for TDD, coverage strengthening, test-plan creation, or review — those have dedicated built-in skills.

## Checklist

You MUST create a TodoWrite item per checklist item and complete in order:

1. Read the user's intent verbatim and identify the specialty category (e2e, accessibility, performance, contract, mutation, flaky).
2. Call `sumo_qa_search(query=<category keyword>)`. Read the results — trust signal, publisher, description.
3. Filter to trusted publishers only (from `registry.json:trusted_publishers`). If no trusted result matches, tell the user honestly and stop.
4. Pick the single best match. If multiple trusted results exist, rank by fit to the user's stack (infer from project files — `package.json`, `pyproject.toml`, etc.).
5. Check whether the skill is already installed: call `sumo_qa_is_installed_locally(name=<skill_name>)`. If already installed, skip the install offer and route to the skill directly.
6. Present to the user: skill name, one-sentence description, publisher, trust status, and the install command (`sumo-qa add <name>`). Do NOT auto-install. Do NOT run any shell command. Wait for explicit confirmation.
7. On user confirmation, call `sumo_qa_add(name=<skill_name>, scope="project")`. Surface the result: path installed, whether a Node runtime was needed.
8. Route to the newly installed skill.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags

| Thought | Reality |
|---|---|
| "I'll install the skill in the background — the user will appreciate it" | Iron Law violated. Explicit confirmation is mandatory. |
| "I know this publisher is fine — no need to check trusted_publishers" | Always filter by `trusted_publishers`. Community trust is not assumed from name familiarity. |
| "I'll suggest the most popular tool regardless of the registry" | Registry is the gate. Only suggest what the registry returns for trusted publishers. |
| "Two results match equally — I'll list both and ask the user to pick" | Pick one using stack fit. Listing both violates one-question-per-turn. |
| "I'll use sudo to install the Node runtime" | Never. The node_install helper uses the user's own package manager only. |
| "Skill is already installed — I'll still offer to install" | `sumo_qa_is_installed_locally()` is step 5. Skip the offer; route directly. |

## Examples

### Good

User: "can we add playwright e2e tests?"
- `sumo_qa_search("e2e playwright")` → one trusted result: `thetestingacademy/sumo-qa-e2e-playwright`.
- `sumo_qa_is_installed_locally("sumo-qa-e2e-playwright")` → false.
- Present: *"Found `sumo-qa-e2e-playwright` by thetestingacademy (trusted). Adds Playwright e2e scaffolding to this project. Install with `sumo-qa add sumo-qa-e2e-playwright`?"*
- User: "yes" → `sumo_qa_add(...)` → route to `sumo-qa-e2e-playwright`.

### Bad

User: "can we add playwright e2e tests?"
AI runs `sumo_qa_add(...)` without asking. Iron Law violated — install without confirmation.

## Next skill in the chain

- On successful install + user confirmation → route to the newly installed external skill.
- When no trusted match is found → stop; tell the user clearly and suggest they check the registry manually.
- When the intent is ambiguous between a built-in and an external skill → route back to `sumo-qa-deciding-approach` with the clarified intent.
