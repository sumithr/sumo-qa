# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The canonical first-hop contract for QA-shaped requests (issue #247).

One rule, stated once, carried verbatim by every surface that tells a host how
to enter sumo-qa: the MCP server instructions, `.github/copilot-instructions.md`,
the `using-sumo-qa` skill body, the trigger-routing fixture header, and the
conformance fixture header. The conformance validator enforces the same chain
on captured transcripts, and a guard test fails when any surface drifts from
this text.
"""

from __future__ import annotations

ENTRY_ROUTER = "using_sumo_qa"
APPROACH_DECIDER = "sumo_qa_deciding_approach"

# The order every QA-shaped request walks before its routed skill.
ROUTER_CHAIN = (ENTRY_ROUTER, APPROACH_DECIDER)

# Pre-routing surfaces (server and Copilot instructions) also carry this: the
# weakest candidate (claude-haiku-4-5) answered an underspecified TDD ask with
# a clarifying question and never reached the router (#247 live runs).
CLARIFY_AFTER_ROUTING = (
    "An underspecified QA request still takes the first hop before you ask the "
    "user anything; the routed skill asks the one clarifying question it needs."
)

FIRST_HOP_RULE = (
    "First hop: every QA-shaped request, including a development-framed one "
    'such as "I\'m adding X, how should I test it?", "what tests do I need?" '
    'or "write the failing tests first", calls `using_sumo_qa` before any '
    "other sumo-qa tool and before any QA advice, then "
    "`sumo_qa_deciding_approach`, then the one skill it routes to. No "
    "specialist skill is entered directly."
)
