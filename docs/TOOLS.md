# MCP Tools

The sumo-qa MCP exposes **24 entry points**: 14 skill tools + 6 knowledge loaders + 4 test-data tools. All are thin — each is file IO or a small deterministic operation. No inference, no host-LLM sampling. The host LLM reasons over what they return.

## Skill tools (14)

Each returns the full body of a `skills/<name>/SKILL.md` file. The host LLM treats the returned markdown as the procedure to follow (Iron Law + checklist + flowchart + Red Flags + examples).

| Tool | Returns SKILL.md for |
|---|---|
| `using_sumo_qa` | Entry router — Iron Law: NO QA WORK WITHOUT FIRST DECIDING THE APPROACH |
| `sumo_qa_deciding_approach` | Pick the canonical approach for the work |
| `sumo_qa_preparing_for_work` | Lightweight QA prep brief |
| `sumo_qa_creating_test_plan` | Formal phased test plan with entry / exit criteria |
| `sumo_qa_implementing_with_tdd` | Red → green → review walk |
| `sumo_qa_reviewing_before_merge` | Review local diff, run tests, surface verdict |
| `sumo_qa_strengthening_tests` | Mutation testing follow-up |
| `sumo_qa_finding_test_data` | Test-data discovery / validation / registration |
| `sumo_qa_answering_testing_question` | Generic "how do I test this?" |
| `sumo_qa_strategising` | Repo-wide QA strategy / audit |
| `sumo_qa_planning_qa_rollout` | Turn a chunk of QA work into a bite-sized dispatchable plan |
| `sumo_qa_executing_qa_rollout` | Dispatch a written QA plan task-by-task via subagents |
| `sumo_qa_finishing_qa_work` | Capture evidence, produce PR-ready summary, close the loop |
| `sumo_qa_suggesting_external_skill` | Offer find-skills / skills.sh discovery when no native fit exists |

In JetBrains AI Assistant these are slash commands (`/sumo_qa_deciding_approach`). In Claude Code the equivalent slash commands come from the native skill files (`/sumo-qa-deciding-approach`, hyphens) — the MCP tools are still callable but only via natural language ("decide the QA approach for this refactor"). VS Code Copilot and Junie pick them by description in Agent / agentic mode.

See [SKILLS.md](SKILLS.md) for the Iron Law per skill.

## Knowledge loaders (6)

Each returns a markdown catalogue as plain text. The host LLM reasons over the returned content. The classification-filter tools (`load_standards`, `load_rules`) accept a single classification or comma-separated classifications. Standards filtering is metadata-based from pack frontmatter; rules filtering returns matching entries. No keyword matching.

| Tool | Returns |
|---|---|
| `sumo_qa_load_classifications()` | The 10 canonical change classifications (api_contract_change, business_logic_change, …, data_migration) |
| `sumo_qa_load_approaches()` | The 8 canonical QA approaches (tdd-scaffold, regression-first, …, spike-first-then-tests) |
| `sumo_qa_load_principles()` | ISTQB Foundation principles, Advanced certifications, ISO/IEC 25010 quality characteristics |
| `sumo_qa_load_techniques()` | Test design techniques (black-box, white-box, experience-based, static, property-based, mutation) |
| `sumo_qa_load_standards(classification?)` | Team's loaded standards packs; optional metadata-based filter by one or more classifications |
| `sumo_qa_load_rules(classification?)` | Team's loaded change rules; optional filter by one or more classifications |

Specialty-tool picks are intentionally NOT catalogued — the discipline (in `using-sumo-qa`) is to observe the risk surface, web-search current options for the user's stack, and cite when naming a tool. A static catalogue would anchor toward yesterday's brands and create a false floor where novel surfaces never trigger discovery.

## Test-data tools (4)

Manage the local known-good test data catalogue under `knowledge/test_data/`. File IO + validation against source systems where applicable.

| Tool | Purpose |
|---|---|
| `sumo_qa_explain_test_data_requirements(question, environment, domain)` | Returns the data requirements as text |
| `sumo_qa_find_test_data(question, environment, domain, criteria)` | Looks up matching catalogue entries |
| `sumo_qa_validate_test_data(path)` | Checks a known-good entry against its source system |
| `sumo_qa_register_known_good_test_data(...)` | Writes a new known-good entry |

## External-skill discovery (no MCP entry points)

When no native sumo-qa fit is found, `sumo-qa-suggesting-external-skill` offers (with `[y/N]`) to install Vercel Labs' [`find-skills`](https://github.com/vercel-labs/skills) meta-skill, which then drives end-to-end discovery and install from [skills.sh](https://www.skills.sh/). This flow uses the host LLM's native `Bash` tool — there are no companion Python shims and no additional MCP entry points. Sumo-qa stays one MCP server. See [`skills/sumo-qa-suggesting-external-skill/SKILL.md`](../skills/sumo-qa-suggesting-external-skill/SKILL.md) for the canonical procedure.

## Why the surface is so small

The discipline (when to ask the user, when to call which tool, what to assert, how to cite a principle) lives in the [skill files](../skills/). The host LLM follows the skill literally. The MCP tools just provide the source of truth.

This is the architectural difference from the pre-restructure version, which had 10 heavy MCP tools each producing 1500-token structured JSON output via host-LLM sampling. That model broke on hosts with smaller token caps or less robust SSE handling — the thin-tool design above replaced it.
