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
- `sumo_qa_planning_qa_rollout` — turn a QA chunk into a written plan of bite-sized tasks
- `sumo_qa_executing_qa_rollout` — dispatch a signed-off plan task-by-task to fresh subagents
- `sumo_qa_finishing_qa_work` — capture evidence and write a PR-ready summary
- `sumo_qa_suggesting_external_skill` — fallback when no native skill fits the intent
- `sumo_qa_closing_qa_gaps` — close a named uncovered-behavior gap, one evidenced loop at a time

The skills carry the senior-QA discipline (Iron Laws, checklists, Red Flags).
Knowledge catalogues are accessed via the `sumo_qa_load_*` tools — use them
for principles, techniques, classifications, approaches, and specialty tool
fits before relying on training-data knowledge.

Repo-map accelerators: when a `.sumo-qa/repo-map.json` artifact is present,
`sumo_qa_scan_repo`, `sumo_qa_analyze_diff_impact`, and `sumo_qa_query_repo_map`
provide fast, deterministic evidence over the codebase (inventory, changed-file
impact, ranked search) for the review, strategy, and prepare-for-work skills.
`sumo_qa_generate_qa_report` composes the persisted `.sumo-qa` artifacts into
the static local QA report (`.sumo-qa/qa-report.html`) when the user asks for
a QA report or dashboard.

When creating GitHub issues, use the closest template in `.github/ISSUE_TEMPLATE/`
and include every required field in the issue body. For implementation tasks
raised by an AI agent, use `.github/ISSUE_TEMPLATE/ai-task.yml` unless a more
specific template fits better.
