# QA tasks via sumo-qa MCP

**Hard rule:** for any QA-shaped request — testing, test plan, test strategy,
test approach, regression scope, risk-based testing, exploratory testing,
code review for safety-to-merge, scaffolding tests, TDD, mutation testing,
finding or validating test data, QA audit, test pyramid design — you MUST
call `sumo_qa_using_sumo_qa` (the entry router) before answering. Do not
produce QA advice from general training-data knowledge. When citing
principles, techniques, classifications, or approaches, load them first
via the `sumo_qa_load_*` tools and cite the loaded catalogue verbatim;
say "not in the catalogue" rather than supplementing from memory.

For QA-shaped requests in this repo (test plans, code review, scaffolding
tests, finding test data, deciding QA approach), fetch the relevant prompt
from the `sumo-qa` MCP and follow its checklist.

Available skills (each registered as an MCP prompt with the same name,
hyphens replaced by underscores):

- `using_sumo_qa` — entry router; load this first for any QA intent
- `sumo_qa_deciding_approach` — pick the QA approach for the work
- `sumo_qa_preparing_for_work` — plan QA before coding starts
- `sumo_qa_creating_test_plan` — produce entry/exit criteria, phases, deliverables
- `sumo_qa_implementing_with_tdd` — red-green-refactor cycle
- `sumo_qa_reviewing_before_merge` — review local diff
- `sumo_qa_strengthening_tests` — mutation-testing follow-up
- `sumo_qa_finding_test_data` — known-good test data discovery and validation
- `sumo_qa_answering_testing_question` — generic "how do I test this?"
- `sumo_qa_strategising` — repo-wide QA strategy

The skills carry the senior-QA discipline (Iron Laws, checklists, Red Flags).
Knowledge catalogues are accessed via the `sumo_qa_load_*` tools — use them
for principles, techniques, classifications, approaches, and specialty tool
fits before relying on training-data knowledge.

When creating GitHub issues, use the closest template in `.github/ISSUE_TEMPLATE/`
and include every required field in the issue body. For implementation tasks
raised by an AI agent, use `.github/ISSUE_TEMPLATE/ai-task.yml` unless a more
specific template fits better.
