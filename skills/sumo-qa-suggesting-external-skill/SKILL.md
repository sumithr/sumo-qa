---
name: sumo-qa-suggesting-external-skill
description: Use when sumo-qa-deciding-approach routes here (no native sumo-qa sub-skill fits a QA surface) OR when an ingestion source needs converting to markdown before it can be ingested. Finds, installs, and executes an external skill for any capability sumo-qa lacks natively, through sumo-qa MCP tools, with [y/N] confirmation before each install and fallback to the next candidate on failure. Never invoked cold — always via the deciding-approach fallback or the ingestion conversion entry.
---

# Suggesting an external skill

**Announce at start:** *"Checking external skills through sumo-qa — no native sumo-qa capability fits."*

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: **output discipline** (never surface internal taxonomy labels — including `entry_kind` — say *"this needs a PDF-to-markdown converter first"*, not *"entry_kind: conversion"*), **output economy** (spend output on findings not framing; no preamble or self-narration; one question per turn; no closing pleasantries), knowledge authority hierarchy, internal scaffolding stays internal, and specialty-tool fit.

## The Iron Law

**The sumo-qa MCP server owns external-skill lifecycle.** Search, install, local lookup, and execution handoff go through `sumo_qa_search_external_skills`, `sumo_qa_install_external_skill`, `sumo_qa_check_external_skill_installed`, and `sumo_qa_execute_external_skill`. Install is always gated on the user's explicit `y`. Never run `sudo` from this flow.

## When to Use

Entered two ways, never cold; the mode is carried by `entry_kind`:

1. **`entry_kind: qa`** — `sumo-qa-deciding-approach` found no native approach fits and the intent needs a tool/framework/QA surface sumo-qa doesn't natively cover (Playwright/Cypress E2E, accessibility audits, k6/Locust load, Pact contract tests, type checking, flaky-test quarantine).
2. **`entry_kind: conversion`** — an ingestion source (PDF/PPTX/URL/docx reported `unsupported_source`) needs converting to markdown first. The gap is a *converter*, not a test tool.

Any install is gated by the per-candidate `[y/N]` prompt below; no global switch.

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

4. **Permission gate (one question, per candidate).** Present the best candidate with source, skill name, install scope, and agent. For `entry_kind: conversion`, open the gate by stating in plain English that the source can't be ingested as-is and needs converting to markdown first, and that once converted you'll re-ingest the markdown with the right `content_type`. Then ask:

   *"Install `<skill>` from `<source>` for `<agent>` in `<scope>` scope, then execute it for this gap? [y/N]"*

   Worked `conversion` example: *"This PDF can't be ingested directly — it needs converting to markdown first. Install `pdf-to-markdown` from `vercel-labs/skills` for `<agent>` in `project` scope, then run it to produce the markdown and re-ingest with the right `content_type`? [y/N]"*

   On `n` → acknowledge the decline in one line and stop the whole flow — e.g. *"Understood — not installing an external skill for this. Stopping here."* Do not re-offer, and do not fall back to transcribing the source (a decline is not a failure to retry around). On `y` → continue.

5. **Install through MCP.** Call `sumo_qa_install_external_skill` with `confirmed=true`. On an `isError` envelope, first tell the user in one line that this candidate's install failed and you're moving on — e.g. *"The `<failed-skill>` install failed — trying the next candidate."* — then re-prompt consent for the next credible candidate (step 4). A fallback turn is NOT a fresh entry — do NOT reuse the step-4 entry opener (*"This PDF can't be ingested directly…"*); OPEN with the failure report, THEN the new offer. Worked `conversion` fallback (note the opener): *"The `pdf-to-markdown` install failed — trying the next candidate. Install `pdf-md-pro` from `acme/skills` for `<agent>` in `project` scope, then run it to produce the markdown and re-ingest with the right `content_type`? [y/N]"* Cap at **3 attempts total**, counting the local-install attempt in step 1 and each search candidate. Once the cap is exhausted, stop with the **all-failed terminal** — which is *distinct* from the no-match terminal in step 3: report that every candidate was tried and each install failed (cap reached), NOT that no converter exists. Pinned `conversion` phrasing: *"All the converter candidates failed to install — no converter could be set up for this source. Stopping."*

6. **Execute through MCP.** Call `sumo_qa_execute_external_skill` with the installed skill name and original intent. This returns the external skill's `skill_body` — a handoff to follow in this conversation, not a finished result. On an `isError`, first tell the user the converter installed but failed to run — e.g. *"`<skill>` installed but failed to run on this file — trying the next candidate."* — then advance to the next candidate (step 4) within the same 3-attempt cap. Emit BOTH beats — the failure report THEN the new offer; worked `conversion` execute-fallback: *"`pdf-to-markdown` installed but failed to run on this file — trying the next candidate. Install `pdf-md-pro` from `acme/skills` for `<agent>` in `project` scope, then run it to produce the markdown and re-ingest with the right `content_type`? [y/N]"* On success the turn is no longer an offer — it is a commitment to follow the returned steps, so do NOT re-offer an install:
   - `entry_kind: qa` → follow the returned `skill_body` to set up the tool and create the first automated tests.
   - `entry_kind: conversion` → state that you will follow the converter's returned steps now to produce the markdown, then re-ingest — e.g. *"The converter returned its steps; following them now to produce the markdown, then re-ingesting it with the right `content_type`."* Only once that produces the markdown, hand back to the ingestion the user was already doing. Do not claim the markdown already exists, and do not call sumo-qa's ingest tool from inside this skill — return to that flow.

   Sumo-qa's confirmation discipline still applies to dependency installs and file writes requested by the external skill.

## Red Flags

| Thought | Reality |
|---|---|
| "I'll run `npx skills ...` directly from the host shell" | No. The sumo-qa MCP server owns search, install, and execution handoff. |
| "I'll install the skill and tell the user after" | No. Permission gate before every install. Always. |
| "Search failed, but I remember a skill name" | No. Use current MCP search results or say no match. |
| "I'll read and transcribe the PDF myself" | No. A non-native source needs a converter skill found through this flow — never hand-transcribe it. |
| "The user said no, but I'll offer the next candidate anyway" | No. A decline stops the whole flow. |
| "Execute already returned a `skill_body`, so I'll offer to install the converter" | No. Install and execute already happened — state you'll follow the returned steps to produce the markdown, then re-ingest. Don't regress to an install offer. |
| "All attempts failed, so I'll say no converter exists" | No. That's the no-match terminal. After the cap, report that every candidate was tried and each failed — distinct from never finding one. |
| "The external skill returned instructions, so sumo-qa discipline no longer applies" | Sumo-qa still owns confirmation gates, test evidence, and risk-to-test mapping. |
| "I'll silently edit host MCP config files" | No silent config edits. Surface the needed JSON or command and stop. |

## Process Flow

See the Checklist above — that's the flow.

## Next skill in the chain

- Executed for a `qa` gap → follow the returned `skill_body`, then use the relevant native sumo-qa skill for test evidence and review.
- Executed for a `conversion` gap → follow the converter's `skill_body` to produce the markdown, then return to the ingestion flow and re-ingest with the right `content_type`.
- Terminals (all stop): no credible match (`qa` → native fallback only if one fits; `conversion` → report no converter exists); 3-attempt cap reached (all-failed — distinct from no-match; `conversion` never transcribes); user declined.
