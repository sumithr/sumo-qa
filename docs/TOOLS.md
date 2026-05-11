# MCP Tools

The sumo-qa MCP exposes 11 tools, all thin: each is file IO or a small
deterministic operation. No inference, no sampling. The host LLM picks
from the returned data; the tool only provides it.

## Knowledge providers (7)

Each returns a markdown catalogue as plain text. The host LLM reasons over the
returned content. The classification-filter tools (`load_standards`, `load_rules`)
filter by metadata declared in the file's frontmatter — no keyword matching.

| Tool | Returns |
|---|---|
| `sumo_qa_load_classifications()` | The 10 canonical change classifications (api_contract_change, business_logic_change, …, data_migration) |
| `sumo_qa_load_approaches()` | The 8 canonical QA approaches (tdd-scaffold, regression-first, …, spike-first-then-tests) |
| `sumo_qa_load_principles()` | ISTQB Foundation principles, Advanced certifications, ISO/IEC 25010 quality characteristics |
| `sumo_qa_load_techniques()` | Test design techniques (black-box, white-box, experience-based, static, property-based, mutation) |
| `sumo_qa_load_specialty_tools()` | Specialty + tool fit catalogue (Pitest, OWASP ZAP, Pact, k6, Hypothesis, axe-core, etc.) |
| `sumo_qa_load_standards(classification?)` | Team's loaded standards packs; optional metadata-based filter by classification |
| `sumo_qa_load_rules(classification?)` | Team's loaded change rules; optional metadata-based filter |

## Test-data tools (4)

Manage the local known-good test data catalogue under `knowledge/test_data/`.
File-IO + validation against source systems where applicable.

| Tool | Purpose |
|---|---|
| `sumo_qa_explain_test_data_requirements(question, environment, domain)` | Returns the data requirements as text |
| `sumo_qa_find_test_data(question, environment, domain, criteria)` | Looks up matching catalogue entries |
| `sumo_qa_validate_test_data(path)` | Checks a known-good entry against its source system |
| `sumo_qa_register_known_good_test_data(...)` | Writes a new known-good entry |

## Why the surface is so small

The discipline (when to ask the user, when to call which tool, what to assert, how
to cite a principle) lives in the [skill files](../skills/). The host LLM follows
the skill literally. Tools just provide the source of truth.

This is the architectural difference from the pre-restructure version, which had 10 heavy MCP tools each producing 1500-token structured JSON output via host-LLM sampling. That model broke on hosts with smaller token caps or less robust SSE handling. See [`docs/superpowers/specs/2026-05-08-superpowers-restructure-design.md`](superpowers/specs/2026-05-08-superpowers-restructure-design.md) for the full rationale.
