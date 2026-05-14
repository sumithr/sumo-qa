---
name: sumo-qa-suggesting-external-skill
description: Use ONLY when sumo-qa-deciding-approach explicitly routes here (no native sumo-qa sub-skill fits the intent AND SUMO_QA_EXTERNAL_SKILLS=1). Discovers, installs, and invokes a skill from the qaskills.sh directory on the user's behalf, with an optional Node-install offer, a trusted-publisher gate, and an optional MCP-config offer. Never run directly from `using-sumo-qa` — always via the deciding-approach fallback.
---

# Suggesting an external (qaskills.sh) skill

**Announce at start:** *"Checking qaskills.sh for a matching skill — no native sumo-qa fit found."*

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

**GATE FIRST.** If `SUMO_QA_EXTERNAL_SKILLS=1` is not set, stop immediately with: *"qaskills integration is gated off. Set `SUMO_QA_EXTERNAL_SKILLS=1` to enable the trial."* — never run any qaskills tool when the gate is off.

**Never install without explicit user confirmation.** Search and inspection are silent internal work; install is gated on the user's explicit `y`. Never silently call `sudo`.

## When to Use

`sumo-qa-deciding-approach` routes here when, internally:

1. No native approach in the canonical catalogue fits the user's intent.
2. The env var `SUMO_QA_EXTERNAL_SKILLS=1` is set (default off).
3. The intent involves a tool, framework, or QA surface that sumo-qa's native skills don't cover — e.g. Playwright/Cypress E2E, accessibility audits, k6/Locust load tests, Pact contract tests, mutation testing, flaky-test quarantine.

If the env var is not set, this skill must not run.

## Checklist

You MUST create a TodoWrite item per checklist item and complete in order. The tools return **raw text from the qaskills CLI** — you read it directly, you don't ask Python to pre-digest it.

1. **Local check first.** Reframe the intent as a probable qaskill slug (e.g. *"set up Playwright E2E"* → `playwright-e2e`) and call `sumo_qa_check_external_skill_installed(name)`. If installed → use your `Read` tool on the returned `skill_md_path` and invoke that skill. Stop.

2. **Node availability.** Call `sumo_qa_check_node_available()`. If `available` is False:
   - Call `sumo_qa_detect_node_installer()`. If `installer` is `null`, surface the `reason` and stop — the user has to install Node themselves.
   - Otherwise ask: *"Node isn't installed. Want me to install it via `<command>`? [y/N]"* (the command is in `detect_installer.command`). On `y` call `sumo_qa_install_node()`. If `installed: True`, continue. If `installed: False` and a sudo-required `reason` is present, print it verbatim and stop — never elevate.

3. **Search.** Call `sumo_qa_search_external_skills(query)` with the user's intent. The `output` field is the qaskills CLI's human-readable text. Read it. Each entry looks like:
   ```
   ●  <Title> by <publisher> ★ <score>
   │    <description>
   │    Tags: <tags>  Installs: <n>
   │    Install: npx qaskills add <slug>
   ```
   Pick the 1–3 candidates most relevant to the user's intent — title, description, and tags carry the signal. The `<slug>` on the `Install:` line is what you pass to subsequent tools.

4. **Trust gate.** Call `sumo_qa_load_external_skills_registry()` to get `trusted_publishers` and `blocked_publishers`. For each candidate:
   - publisher in `blocked_publishers` → drop it silently.
   - publisher in `trusted_publishers` → "trusted" (auto-eligible).
   - otherwise → "untrusted" (offerable, with explicit warning).

5. **Permission gate.** One question: *"Want me to install `<slug>` by `<publisher>` (score `<score>`)? [y / N / show me more]"*. If the candidate is untrusted, prefix the prompt with *"Publisher not in sumo-qa's trusted allowlist — proceed with caution."*. If user picks "show me more", call `sumo_qa_get_external_skill_info(name=<slug>)` and surface the full `output` text (which includes version, license, frameworks, languages, web URL). Re-ask.

6. **Scope question.** One question: *"Install global (`~/.claude/skills/`, available across every project) or project-local (`<repo>/.claude/skills/`, only this repo)?"*

7. **Install.** Call `sumo_qa_install_external_skill(name=<slug>, scope=<global|project>)`. On error, surface the `actionable_hint` and stop.

8. **MCP refs scan.** Use your `Read` tool on the `skill_md_path` returned by step 7. Read the installed SKILL.md. If it references any MCP server (look for patterns like `playwright-mcp`, `mcp-server-<name>`, `mcpServers:` blocks, or text describing an MCP integration), surface a one-line offer: *"This skill works with `<mcp-name>`. Want the JSON block to add it to your MCP config? [y/N]"*. If accepted, print the JSON for the user to paste — never silently edit any config file.

9. **Hand off.** Invoke the freshly-installed qaskill via the Skill tool. Sumo-qa's Iron Law discipline still wraps the response.

## Trust decisions

| Decision | Behaviour |
|---|---|
| trusted | Offer as primary candidate. Still requires the user's `y`. |
| untrusted | Offer with explicit "publisher not in sumo-qa's allowlist" warning; "show me more" option must be available. |
| blocked | Do not offer. Move to next match. |

## Error handling

| Failure | Behaviour |
|---|---|
| Any tool returns `{"disabled": True}` | Print *"qaskills integration is gated off. Set `SUMO_QA_EXTERNAL_SKILLS=1` to enable the trial."* and stop. |
| `sumo_qa_check_node_available` returns `available: False` AND `sumo_qa_detect_node_installer` returns `installer: null` | Print the `reason` and a manual install link (https://nodejs.org). Stop. |
| `sumo_qa_install_node` returns `installed: False` with sudo-required `reason` | Print the reason verbatim (which includes the exact `sudo <cmd>` to run). Stop. Never elevate. |
| Tool returns `isError` with Node-missing hint | Surface the hint verbatim; do not retry. |
| Search returns no entries you can use | *"No qaskill match for this intent — falling back to sumo-qa's native scaffolding."* Route to `sumo-qa-implementing-with-tdd`. |
| Install fails | Surface `actionable_hint`; stop. Do not auto-retry. |

## Red Flags

| Thought | Reality |
|---|---|
| "The publisher looks familiar, I'll skip the trust step" | Trust step is non-negotiable. The allowlist exists because qaskills.sh is third-party content. |
| "I'll just install it and tell the user after" | No. Permission gate before install. Always. |
| "The qaskill writes tests, so I'll skip sumo-qa-implementing-with-tdd" | The native sub-skill carries sumo-qa's discipline. Hand off to it; the qaskill is reference patterns. |
| "I'll edit `~/.claude.json` to add the MCP server" | No silent config edits. Print the JSON for the user to paste. |
| "Node isn't there — I'll just call sudo apt install nodejs directly" | Never elevate from a tool call. If sudo is required, print the command and stop. |
| "The search output is hard to parse, let me ask a tool to give me structured fields" | The tools return raw text on purpose. You're the parser. Read the lines, pick the slug from the `Install:` line. |

## Process Flow

See the Checklist above — that's the flow.

## Next skill in the chain

- Successful install + hand-off → invoke the just-installed qaskill, wrapped by `sumo-qa-implementing-with-tdd` discipline.
- No match → `sumo-qa-implementing-with-tdd` for native scaffolding.
- Gated off → stop.
