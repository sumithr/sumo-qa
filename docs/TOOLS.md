# MCP Tools

The sumo-qa MCP exposes **24 entry points**: 13 skill tools + 7 knowledge loaders + 4 test-data tools. All are thin — each is file IO or a small deterministic operation. No inference, no host-LLM sampling. The host LLM reasons over what they return.

## Skill tools (10)

Each returns the full body of a `skills/<name>/SKILL.md` file. The host LLM treats the returned markdown as the procedure to follow (Iron Law + checklist + flowchart + Red Flags + examples).

| Tool | Returns SKILL.md for |
|---|---|
| `using_sumo_qa` | Entry router — Iron Law: NO QA WORK WITHOUT FIRST DECIDING THE APPROACH |
| `qa_deciding_approach` | Pick the canonical approach for the work |
| `qa_preparing_for_work` | Lightweight QA prep brief |
| `qa_creating_test_plan` | Formal phased test plan with entry / exit criteria |
| `qa_implementing_with_tdd` | Red → green → review walk |
| `qa_reviewing_before_merge` | Review local diff, run tests, surface verdict |
| `qa_strengthening_tests` | Mutation testing follow-up |
| `qa_finding_test_data` | Test-data discovery / validation / registration |
| `qa_answering_testing_question` | Generic "how do I test this?" |
| `sumo_qa_strategising` | Repo-wide QA strategy / audit |

In JetBrains AI Assistant these are slash commands (`/qa_deciding_approach`). In Claude Code the equivalent slash commands come from the native skill files (`/qa-deciding-approach`, hyphens) — the MCP tools are still callable but only via natural language ("decide the QA approach for this refactor"). VS Code Copilot and Junie pick them by description in Agent / agentic mode.

See [SKILLS.md](SKILLS.md) for the Iron Law per skill.

## Knowledge loaders (7)

Each returns a markdown catalogue as plain text. The host LLM reasons over the returned content. The classification-filter tools (`load_standards`, `load_rules`) filter by metadata declared in the file's frontmatter — no keyword matching.

| Tool | Returns |
|---|---|
| `sumo_qa_load_classifications()` | The 10 canonical change classifications (api_contract_change, business_logic_change, …, data_migration) |
| `sumo_qa_load_approaches()` | The 8 canonical QA approaches (tdd-scaffold, regression-first, …, spike-first-then-tests) |
| `sumo_qa_load_principles()` | ISTQB Foundation principles, Advanced certifications, ISO/IEC 25010 quality characteristics |
| `sumo_qa_load_techniques()` | Test design techniques (black-box, white-box, experience-based, static, property-based, mutation) |
| `sumo_qa_load_specialty_tools()` | Category-fit primer: when does each specialty surface (mutation / contract / DAST / a11y / load / property-based / LLM / mobile) apply. NOT a brand whitelist — the LLM recommends best-fit tools from its knowledge of the ecosystem, with this file as a category-check frame. |
| `sumo_qa_load_standards(classification?)` | Team's loaded standards packs; optional metadata-based filter by classification |
| `sumo_qa_load_rules(classification?)` | Team's loaded change rules; optional metadata-based filter |

## Test-data tools (4)

Manage the local known-good test data catalogue under `knowledge/test_data/`. File IO + validation against source systems where applicable.

| Tool | Purpose |
|---|---|
| `sumo_qa_explain_test_data_requirements(question, environment, domain)` | Returns the data requirements as text |
| `sumo_qa_find_test_data(question, environment, domain, criteria)` | Looks up matching catalogue entries |
| `sumo_qa_validate_test_data(path)` | Checks a known-good entry against its source system |
| `sumo_qa_register_known_good_test_data(...)` | Writes a new known-good entry |

## Why the surface is so small

The discipline (when to ask the user, when to call which tool, what to assert, how to cite a principle) lives in the [skill files](../skills/). The host LLM follows the skill literally. The MCP tools just provide the source of truth.

This is the architectural difference from the pre-restructure version, which had 10 heavy MCP tools each producing 1500-token structured JSON output via host-LLM sampling. That model broke on hosts with smaller token caps or less robust SSE handling. See [`docs/superpowers/specs/2026-05-08-superpowers-restructure-design.md`](superpowers/specs/2026-05-08-superpowers-restructure-design.md) for the full rationale.
