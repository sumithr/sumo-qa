---
name: sumo-qa-suggesting-external-skill
description: Use ONLY when sumo-qa-deciding-approach explicitly routes here (no native sumo-qa sub-skill fits the user's intent). Finds, installs, and executes external skills through sumo-qa MCP tools, with [y/N] confirmation before install. Never run directly from `using-sumo-qa` — always via the deciding-approach fallback.
---

# Suggesting an external skill

**Announce at start:** *"Checking external skills through sumo-qa — no native sumo-qa fit found."*

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

**The sumo-qa MCP server owns external-skill lifecycle.** Search, install, local lookup, and execution handoff go through `sumo_qa_search_external_skills`, `sumo_qa_install_external_skill`, `sumo_qa_check_external_skill_installed`, and `sumo_qa_execute_external_skill`. Install is still gated on the user's explicit `y`. Never run `sudo` from this flow.

## When to Use

`sumo-qa-deciding-approach` routes here when, internally:

1. No native approach in the canonical catalogue fits the user's intent.
2. The intent involves a tool, framework, or QA surface that sumo-qa's native skills don't cover — e.g. Playwright/Cypress E2E, accessibility audits, k6/Locust load tests, Pact contract tests, type checking, flaky-test quarantine.

Consent for any install is always the per-action `[y/N]` prompt in the checklist below. No global on/off switch.

## Checklist

You MUST work through these steps in order. External lifecycle operations are MCP tool calls, not host-shell `npx` calls.

1. **Check local install first.** Call `sumo_qa_check_external_skill_installed` if the router or user named a likely skill. If found, call `sumo_qa_execute_external_skill` with the user's original intent and follow the returned `skill_body`. Stop.

2. **Search externally.** Call `sumo_qa_search_external_skills` with a concise query built from the QA surface and stack, e.g. `python type checking mypy`, `playwright e2e`, `pact contract testing`. Read the returned `raw_output` as the user would in a terminal — one candidate per line, typically in the form `<owner>/<repo>@<skill>`. The MCP intentionally does not parse this text; the Skills CLI output shape may evolve.

3. **No match fallback.** If search returns no credible match, say so and route to `sumo-qa-implementing-with-tdd` or `sumo-qa-strengthening-tests` only if native scaffolding still makes sense. Do not invent a skill.

4. **Permission gate (one question).** Present the best candidate with source, skill name, install scope, and agent. Ask:

   *"Install `<skill>` from `<source>` for `<agent>` in `<scope>` scope, then execute it for this testing gap? [y/N]"*

   On `n` → stop. On `y` → continue.

5. **Install through MCP.** Call `sumo_qa_install_external_skill` with `confirmed=true`. On an `isError` envelope, surface the error message and actionable hint. Stop.

6. **Execute through MCP.** Call `sumo_qa_execute_external_skill` with the installed skill name and original intent. Follow the returned `skill_body` to set up the tool and create the first automated tests. Sumo-qa's confirmation discipline still applies to dependency installs and file writes requested by that external skill.

## Error handling

| Failure | Behaviour |
|---|---|
| `sumo_qa_search_external_skills` returns `isError` | Surface the error and actionable hint. Stop. |
| Search returns no credible match | *"No external skill match for this intent."* Route native only if a native path still fits. |
| `sumo_qa_install_external_skill` returns `isError` | Surface the error and actionable hint. Stop. |
| `sumo_qa_execute_external_skill` returns `isError` | Surface the error and actionable hint. Stop. |

## Red Flags

| Thought | Reality |
|---|---|
| "I'll run `npx skills ...` directly from the host shell" | No. The sumo-qa MCP server owns search, install, and execution handoff. |
| "I'll install the skill and tell the user after" | No. Permission gate before every install. Always. |
| "Search failed, but I remember a skill name" | No. Use current MCP search results or say no match. |
| "The external skill returned instructions, so sumo-qa discipline no longer applies" | Sumo-qa still owns confirmation gates, test evidence, and risk-to-test mapping. |
| "I'll silently edit host MCP config files" | No silent config edits. Surface the needed JSON or command and stop. |

## Process Flow

See the Checklist above — that's the flow.

## Next skill in the chain

- External skill executed through MCP → follow returned `skill_body`, then use the relevant native sumo-qa skill for test evidence and review.
- No external match → native fallback only when a native path still fits.
- User declined install or MCP search/install failed → stop.
