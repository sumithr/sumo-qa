---
name: sumo-qa-suggesting-external-skill
description: Use when sumo-qa-deciding-approach routes here (no native sumo-qa sub-skill fits a QA surface) OR when an ingestion source needs converting to markdown before it can be ingested. Finds, installs, and executes an external skill for any capability sumo-qa lacks natively, through sumo-qa MCP tools, with [y/N] confirmation before each install and fallback to the next candidate on failure. Never invoked cold — always via the deciding-approach fallback or the ingestion conversion entry.
---

# Suggesting an external skill

**Announce at start:** *"Checking external skills through sumo-qa — no native sumo-qa capability fits."*

## Output discipline (mandatory)

**Never surface internal taxonomy labels in user-facing output.** No "Classification: X", "Approach: Y", "Per the checklist", "Step 3 of 6", "entry_kind: conversion". The taxonomy is internal scaffolding; translate to natural English when the meaning matters to the user — *"this needs a PDF-to-markdown converter first"*, not *"entry_kind: conversion"*. If you catch yourself typing a label, delete it.

Inherits the global discipline from `using-sumo-qa` (knowledge authority hierarchy, internal scaffolding stays internal, specialty-tool fit).

## Output economy (mandatory)

Spend output tokens on findings, not framing.

- **Don't preamble the work.** Spend user-visible output on findings, evidence, and gates — don't narrate *"I'll first read X, then Y, then deliver Z."*
- **One question per turn.** Don't follow a question with *"shall I proceed or clarify first?"* — the question IS the gate.
- **No self-narration.** *"Let me now..."* / *"I'm going to..."* → just do it.
- **Don't restate the user's input.** They know what they asked.
- **Section headings only when there are genuinely multiple sections.**
- **Tables only when comparing >2 things on >2 axes.** Otherwise prose is shorter.
- **No closing pleasantries.** No *"happy to dig deeper"* — the next-skill handoff is where routing lives.

## The Iron Law

**The sumo-qa MCP server owns external-skill lifecycle.** Search, install, local lookup, and execution handoff go through `sumo_qa_search_external_skills`, `sumo_qa_install_external_skill`, `sumo_qa_check_external_skill_installed`, and `sumo_qa_execute_external_skill`. Install is always gated on the user's explicit `y`. Never run `sudo` from this flow.

## When to Use

This skill is entered two ways, never cold. The caller mode is carried by `entry_kind`:

1. **`entry_kind: qa`** — `sumo-qa-deciding-approach` determined no native approach fits and the intent involves a tool, framework, or QA surface sumo-qa doesn't natively cover (Playwright/Cypress E2E, accessibility audits, k6/Locust load tests, Pact contract tests, type checking, flaky-test quarantine).
2. **`entry_kind: conversion`** — an ingestion source (a PDF/PPTX/URL/docx reported `unsupported_source`) needs converting to markdown before it can be ingested. The capability gap is a *converter*, not a test tool.

Consent for any install is always the per-candidate `[y/N]` prompt in the checklist below. No global on/off switch.

## Checklist

You MUST work through these steps in order. External lifecycle operations are MCP tool calls, not host-shell `npx` calls.

1. **Check local install first.** Call `sumo_qa_check_external_skill_installed` if the router or user named a likely skill. If found, call `sumo_qa_execute_external_skill` with the original intent and follow the returned `skill_body`. If that execute returns an `isError`, do NOT stop — fall through to step 2 and search for an alternative.

2. **Search externally.** Call `sumo_qa_search_external_skills` with a concise query built from the capability needed:
   - `entry_kind: qa` → the QA surface and stack, e.g. `python type checking mypy`, `playwright e2e`, `pact contract testing`.
   - `entry_kind: conversion` → the converter needed, e.g. `pdf to markdown`, `pptx to markdown`, `docx to markdown`, `web page to markdown`.

   Read the returned `raw_output` as the user would in a terminal — one candidate per line, typically `<owner>/<repo>@<skill>`. The MCP intentionally does not parse this text; you pick the most credible candidate, and the next-most on failure.

3. **No credible match — caller-aware terminal.** If search returns no credible candidate:
   - `entry_kind: qa` → say so and route to `sumo-qa-implementing-with-tdd` or `sumo-qa-strengthening-tests` only if native scaffolding still makes sense.
   - `entry_kind: conversion` → report that no converter skill is available and stop. Do NOT read and hand-transcribe the source yourself.

   Do not invent a skill.

4. **Permission gate (one question, per candidate).** Present the best candidate with source, skill name, install scope, and agent. Ask:

   *"Install `<skill>` from `<source>` for `<agent>` in `<scope>` scope, then execute it for this gap? [y/N]"*

   On `n` → stop the whole flow (the user is declining external-skill install for this intent — a decline is not a failure to retry around). On `y` → continue.

5. **Install through MCP.** Call `sumo_qa_install_external_skill` with `confirmed=true`. On an `isError` envelope, advance to the next credible candidate from step 2 and return to step 4 (re-prompt consent). Cap at **3 attempts total** across candidates; once the cap is exhausted, apply the caller-aware all-failed terminal (the same one as step 3).

6. **Execute through MCP.** Call `sumo_qa_execute_external_skill` with the installed skill name and original intent. On an `isError`, treat it like an install failure — advance to the next candidate (step 4) within the same 3-attempt cap. On success:
   - `entry_kind: qa` → follow the returned `skill_body` to set up the tool and create the first automated tests.
   - `entry_kind: conversion` → the source is now markdown; hand back to the ingestion the user was already doing and re-run it with the right `content_type` for the catalogue. (Do not call sumo-qa's ingest tool from inside this skill — return to that flow.)

   Sumo-qa's confirmation discipline still applies to dependency installs and file writes requested by the external skill.

## Error handling

| Failure | Behaviour |
|---|---|
| `sumo_qa_search_external_skills` returns `isError` | Surface the error and actionable hint. Stop. |
| Search returns no credible match | Caller-aware terminal (step 3): `qa` → native only if it fits; `conversion` → report can't-convert, stop, never transcribe. |
| `sumo_qa_install_external_skill` returns `isError` | Advance to the next candidate (re-prompt consent), within the 3-attempt cap. Cap exhausted → caller-aware terminal. |
| `sumo_qa_execute_external_skill` returns `isError` | Advance to the next candidate (re-prompt consent), within the 3-attempt cap. Cap exhausted → caller-aware terminal. |
| User answers `n` at any candidate | Stop the whole flow. |

## Red Flags

| Thought | Reality |
|---|---|
| "I'll run `npx skills ...` directly from the host shell" | No. The sumo-qa MCP server owns search, install, and execution handoff. |
| "I'll install the skill and tell the user after" | No. Permission gate before every install. Always. |
| "Search failed, but I remember a skill name" | No. Use current MCP search results or say no match. |
| "I'll read and transcribe the PDF myself" | No. A non-native source needs a converter skill found through this flow — never hand-transcribe it. |
| "The first candidate's install failed, so I'll give up" | No. Advance to the next candidate (cap 3 attempts) before the caller-aware terminal. |
| "The user said no, but I'll offer the next candidate anyway" | No. A decline stops the whole flow. |
| "The external skill returned instructions, so sumo-qa discipline no longer applies" | Sumo-qa still owns confirmation gates, test evidence, and risk-to-test mapping. |
| "I'll silently edit host MCP config files" | No silent config edits. Surface the needed JSON or command and stop. |

## Process Flow

See the Checklist above — that's the flow.

## Next skill in the chain

- External skill executed for a `qa` gap → follow returned `skill_body`, then use the relevant native sumo-qa skill for test evidence and review.
- External skill executed for a `conversion` gap → return to the ingestion flow and re-ingest the converted markdown with the right `content_type`.
- No external match → caller-aware terminal: `qa` native fallback only when a native path still fits; `conversion` reports can't-convert and stops.
- User declined install, or MCP search/install/execute failed past the 3-attempt cap → stop.
