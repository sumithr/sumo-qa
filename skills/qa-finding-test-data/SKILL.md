---
name: qa-finding-test-data
description: Use when the user asks about test data — what data to test X, find a known-good record, validate an entry, register new known-good data. Routes between sumo_qa_explain_test_data_requirements, sumo_qa_find_test_data, sumo_qa_validate_test_data, and sumo_qa_register_known_good_test_data.
---

# Finding test data

**Announce at start:** *"I'm using qa-finding-test-data to route this between explain / find / validate / register and surface fresh-validated evidence."*

## Output discipline (mandatory)

**Never surface internal taxonomy labels in user-facing output.** No "Classification: X", "Approach: Y", "Per the checklist", "Step 3 of 6". The taxonomy is internal scaffolding; translate to natural English when the meaning matters to the user — *"this is a behaviour change in pricing"*, not *"Classification: business_logic_change"*. If you catch yourself typing a label, delete it.

Inherits the global discipline from `using-sumo-qa` (knowledge authority hierarchy, internal scaffolding stays internal, specialty-tool fit).

## The Iron Law

**STALE IS A DEFECT. NEVER INVENT ENTRIES NOT IN THE CATALOGUE.**

A catalogued entry not re-validated against the source system in this turn is no better than an invented one — validation is the proof, not ceremony.

## When to Use

User intents that trigger this skill:

- "what test data do I need for X"
- "find me a known-good record for X"
- "is this record / account / fixture still valid"
- "save this as known-good test data"
- "I need a locked account for the failed-login test"
- "I need a pending invoice for the due-date boundary test"

## Checklist

You MUST create a TodoWrite item per checklist item and complete in order. Steps 1–2 are AI-only homework (route the request, gather inputs from prior conversation). The user's confirmation gate only applies to **register** (step 5b) — writing to the shared catalogue is a side effect that should always pause for confirmation.

1. **Pick the route** *(no user question — derive from intent)*. The four routes are internal dispatch data, NOT a label to echo at the user:
   - **Explain requirements:** "what data do I need" → `sumo_qa_explain_test_data_requirements`
   - **Find:** "find me a record" → `sumo_qa_find_test_data`
   - **Validate:** "is this still valid" → `sumo_qa_validate_test_data`
   - **Register:** "save this as known-good" → `sumo_qa_register_known_good_test_data`
2. **Gather inputs from intent + prior conversation** *(no user question if the conversation has them)*. Question, environment, domain, criteria, entry path — pull from what's already been said. Only ask if a genuinely required field is missing, and ask ONCE.
3. **For explain:** call the tool. Return the requirements as text in natural English.
4. **For find:** call the tool with the gathered criteria. If matches: pipe each into validate (step 5a). If no matches: say so explicitly — do NOT invent and do NOT silently broaden the criteria.
5. **For validate:**
   - **5a (from find or direct):** call `sumo_qa_validate_test_data` against the source system in this turn. A cached or memorised result is not fresh. Report state with timestamp + the validation evidence.
   - **5b (register):** confirm with the user before writing to the catalogue. Show the entry, the validation evidence, and ask: *"Register this as known-good?"* Only write on explicit yes.
6. **If an entry fails validation:** mark it stale, surface the failure to the user, do NOT silently substitute another entry. The user decides whether to find an alternative or register a new one.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags

| Thought | Reality |
|---|---|
| "I'll just make up a SKU that probably works" | Iron Law violated. Catalogue entries only. |
| "Validation is expensive — assume it's still good" | Stale is a defect. Always validate against the source system in this turn, especially for shared catalogues. |
| "User said 'find me one' — I'll skip validation" | Validate. The whole point of the catalogue is freshness. |
| "Register this as known-good without testing it first" | Don't. Register only after the user has confirmed the entry was used successfully — and confirm again before writing to the catalogue. |
| "If no entry matches, I'll fabricate one" | Surface the gap. The user might need to register a new entry — let them decide. |
| "Found entry failed validation — let me silently grab the next one" | No. Surface the failure to the user with the entry that went stale; let them pick the alternative. Silent substitution hides drift in the catalogue. |

## Examples

### Good (find → validate → surface)

> **User:** *"find me a refund-eligible order for the refund-flow test."*
>
> **AI (user-facing):** *"Found `ORD-77821` — refund-eligible, validated against staging just now (2026-05-12 09:14). `ORD-77900` is in the catalogue too but is now stale (already refunded on 2026-05-10); flagging it so we can register a replacement later."*

The user sees the result + freshness evidence, not the dispatch labels.

### Bad (inventing)

> **User:** *"find me a refund-eligible order."*
>
> **AI:** *"Try `ORD-12345` — that should work for refund testing."*

Inventing an entry. Iron Law violated.

## Next skill in the chain

Terminal skill — no next-skill handoff. Returns the data (with freshness evidence) to the caller, which is usually a TDD / review / strengthening flow already mid-conversation.
