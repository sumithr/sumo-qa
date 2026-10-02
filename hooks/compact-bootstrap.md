You have sumo-qa: a senior-QA skills library + MCP server.

A request is QA-shaped when it asks about testing: a test plan, test strategy or test approach, regression scope, risk-based or exploratory testing, a code review for safety to merge ("is this safe to merge?", "what could break?"), scaffolding tests, TDD, mutation testing, finding or validating test data, a QA audit, or a test pyramid.

First hop: every QA-shaped request, including a development-framed one such as "I'm adding X, how should I test it?", "what tests do I need?" or "write the failing tests first", calls `using_sumo_qa` before any other sumo-qa tool and before any QA advice, then `sumo_qa_deciding_approach`, then the one skill it routes to. No specialist skill is entered directly.

An underspecified QA request still takes the first hop before you ask the user anything; `sumo_qa_deciding_approach`, or the skill it routes to, asks the one clarifying question it needs.

`using_sumo_qa` is a sumo-qa MCP tool; where the host has a Skill tool, the `sumo-qa:using-sumo-qa` skill is the same router. It carries the full rules, so load it rather than answering QA questions from training-data knowledge.

Not a QA-shaped request? Ignore this note.
