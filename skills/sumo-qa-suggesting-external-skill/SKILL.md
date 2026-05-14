---
name: sumo-qa-suggesting-external-skill
description: Use ONLY when sumo-qa-deciding-approach explicitly routes here (no native sumo-qa sub-skill fits the user's intent). Offers (with [y/N] confirmation) to install Vercel Labs' find-skills meta-skill, which then drives end-to-end discovery and install from skills.sh. Never run directly from `using-sumo-qa` — always via the deciding-approach fallback.
---

# Suggesting an external (skills.sh) skill

**Announce at start:** *"Checking skills.sh for a matching skill — no native sumo-qa fit found."*

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

**Never install without explicit user confirmation.** Search and inspection are silent internal work; install is gated on the user's explicit `y`. Never silently call `sudo`. Never silently edit MCP config files — print the JSON for the user to paste.

## When to Use

`sumo-qa-deciding-approach` routes here when, internally:

1. No native approach in the canonical catalogue fits the user's intent.
2. The intent involves a tool, framework, or QA surface that sumo-qa's native skills don't cover — e.g. Playwright/Cypress E2E, accessibility audits, k6/Locust load tests, Pact contract tests, mutation testing, flaky-test quarantine.

Consent for any install is always the per-action `[y/N]` prompt in the checklist below. No global on/off switch.

## Checklist

You MUST work through these steps in order. All CLI invocations use the host LLM's native `Bash` tool — no companion Python shims, no new MCP tools.

1. **Check find-skills locally first.** Use your `Read` tool to check whether `~/.claude/skills/find-skills/SKILL.md` exists. If it exists → invoke `find-skills` via the Skill tool, passing the user's original intent. find-skills handles discovery + install from [skills.sh](https://www.skills.sh/) end-to-end. Stop — sumo-qa's discipline still wraps the response.

2. **Node availability.** Run `which npx` via Bash. If the output is empty, print one paragraph explaining the user needs Node.js installed (https://nodejs.org) and stop. Never silently elevate via sudo.

3. **Permission gate (one question).** Ask:

   *"find-skills isn't installed locally. Want me to install it via `npx --yes skills add https://github.com/vercel-labs/skills --skill find-skills -a claude-code -y`? [y/N]"*

   On `n` → stop. On `y` → continue.

4. **Install find-skills.** Run this command verbatim via Bash:

   ```
   npx --yes skills add https://github.com/vercel-labs/skills --skill find-skills -a claude-code -y
   ```

   On non-zero exit → surface stderr and stop. Do not retry automatically.

5. **Hand off.** Invoke the freshly-installed `find-skills` via the Skill tool, passing the user's original intent. find-skills drives discovery + install from skills.sh; sumo-qa's discipline still wraps the response.

## Error handling

| Failure | Behaviour |
|---|---|
| `which npx` returns empty | Print one paragraph pointing at https://nodejs.org. Stop. Never auto-install Node via sudo. |
| find-skills install exits non-zero | Surface stderr verbatim. Stop. Do not auto-retry. |
| find-skills finds no match for intent | *"No skills.sh match for this intent — falling back to sumo-qa's native scaffolding."* Route to `sumo-qa-implementing-with-tdd`. |

## Red Flags

| Thought | Reality |
|---|---|
| "I'll add a companion MCP tool to wrap npx" | No. Sumo-qa is one MCP server; CLI invocations live in this SKILL, not in Python shims. Adding a new MCP entry point here is the architectural failure mode this design exists to prevent. |
| "I'll just install find-skills and tell the user after" | No. Permission gate before every install. Always. |
| "find-skills writes tests, so I'll skip sumo-qa-implementing-with-tdd" | The native sub-skill carries sumo-qa's discipline. Hand off to it; the external skill is reference patterns. |
| "Node isn't there — I'll just call sudo apt install nodejs directly" | Never elevate from a tool call. If sudo is required, print the command and stop. |
| "I'll build a Python wrapper around the skills CLI output" | No. Return raw text from CLI tools; let the LLM parse natural-language output. No Python parsers as middleware. |
| "I'll silently edit `~/.claude.json` to add the MCP server" | No silent config edits. Print the JSON for the user to paste. |

## Process Flow

See the Checklist above — that's the flow.

## Next skill in the chain

- find-skills installed and invoked → find-skills drives the rest; sumo-qa discipline wraps the final response.
- No match found by find-skills → `sumo-qa-implementing-with-tdd` for native scaffolding.
- User declined install or Node unavailable → stop.
