---
id: SCN-11
scenario_type: skill
expected_skill: using-sumo-qa
anti_patterns:
  - Generates a plan, review, or scaffold inline without routing through `sumo-qa-deciding-approach` first.
  - Surfaces *"Routing to sumo-qa-deciding-approach"* as if it were a chat message.
  - Skips loading the global discipline (then violates output economy or surfaces internal taxonomy labels).
  - Treats `using-sumo-qa` as a heavy entry point that demands its own scenario-shaped output — it's a router, not a deliverable.
---

## User prompt

Help me QA this thing — I added a new pricing function `apply_seasonal_discount` in `pricing/seasonal.py`.

## Expected interaction shape

1. The host LLM treats `using-sumo-qa` as the entry router for any QA-shaped intent — not as a content-bearing skill.
2. Loads the global discipline (knowledge authority hierarchy, output discipline, internal scaffolding stays internal, specialty-tool-fit discovery).
3. Hands off to `sumo-qa-deciding-approach` — does NOT attempt to plan, review, or scaffold inline.
4. The handoff happens *transparently* — the user sees the deciding-approach output, not a "switching to sumo-qa-deciding-approach" announcement.
5. The classification + approach decision is internal scaffolding; the user-facing first response is shaped by whichever sub-skill the routing lands on (here: `sumo-qa-preparing-for-work` for a new pricing function with no review-shaped or strategy-shaped framing).

## Anti-patterns

- Generates a plan, review, or scaffold inline without routing through `sumo-qa-deciding-approach` first.
- Surfaces *"Routing to sumo-qa-deciding-approach"* as if it were a chat message.
- Skips loading the global discipline (then violates output economy or surfaces internal taxonomy labels).
- Treats `using-sumo-qa` as a heavy entry point that demands its own scenario-shaped output — it's a router, not a deliverable.
