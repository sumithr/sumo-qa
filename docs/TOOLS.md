# MCP Tools

The sumo-qa MCP exposes **33 entry points**: 14 skill tools + 7 knowledge loaders + 4 test-data tools + 8 qaskills/Node-install tools. All are thin — each is file IO, a small deterministic operation, or a subprocess shim around the qaskills CLI. No inference, no host-LLM sampling. The host LLM reasons over what they return.

## Skill tools (14)

Each returns the full body of a `skills/<name>/SKILL.md` file. The host LLM treats the returned markdown as the procedure to follow (Iron Law + checklist + flowchart + Red Flags + examples). Tool names mirror directory names with `-` swapped for `_`.

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
| `sumo_qa_planning_qa_rollout` | Turn a QA chunk into a bite-sized, parallel-dispatchable plan |
| `sumo_qa_executing_qa_rollout` | Dispatch the plan task-by-task to fresh subagents with two-stage review |
| `sumo_qa_finishing_qa_work` | Close the loop — fresh suite + risk-to-test map + PR-ready summary |
| `sumo_qa_suggesting_external_skill` | Fallback when no native fit: discover + install a [qaskills.sh](https://qaskills.sh/) skill (gated on `[y/N]`) |

In JetBrains AI Assistant these are slash commands (`/sumo_qa_deciding_approach`). In Claude Code, the same skills are also surfaced by the native skill loader as hyphenated commands (`/sumo-qa-deciding-approach`); whether the underscored MCP-tool form additionally appears in the Claude Code slash menu depends on the Claude Code version. VS Code Copilot and Junie pick them by description in Agent / agentic mode.

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

Manage the local known-good test data catalogue under `knowledge/test_data/`. File IO + local validation; current validators do not call downstream APIs.

| Tool | Purpose |
|---|---|
| `sumo_qa_explain_test_data_requirements(question, environment, domain)` | Returns required data shape, preconditions, edge cases, and "what NOT to use" guidance as text |
| `sumo_qa_find_test_data(environment, domain, scenario_tags, known_valid_for, product_id, sku, limit, offset)` | Ranked catalogue matches with confidence + freshness; paginated |
| `sumo_qa_validate_test_data(entry_id?, entry?)` | Local validation of a known-good entry (schema + freshness + ownership); no downstream calls |
| `sumo_qa_register_known_good_test_data(entry)` | Writes a new known-good entry to `knowledge/test_data/<domain>/known_good.yaml` |

## qaskills / Node-install tools (8)

Subprocess shims around `npx @qaskills/cli` plus the user's OS package manager. Used by `sumo-qa-suggesting-external-skill` when no native sumo-qa skill fits the user's intent. Each install action is gated by an explicit `[y/N]` from the user — these tools never elevate sudo and never silently install.

| Tool | Purpose |
|---|---|
| `sumo_qa_search_external_skills(query)` | Run `qaskills search`; return cleaned CLI text for the LLM to read |
| `sumo_qa_get_external_skill_info(name)` | Run `qaskills info <name>`; return cleaned CLI text |
| `sumo_qa_install_external_skill(name, scope)` | Run `qaskills add <name>` then relocate to `~/.claude/skills/` (or `<repo>/.claude/skills/` for project scope). **Caller must have explicit user `[y/N]` consent first.** |
| `sumo_qa_check_external_skill_installed(name)` | Filesystem check for an already-installed qaskill (project scope wins over global) |
| `sumo_qa_load_external_skills_registry()` | Return `trusted_publishers` / `blocked_publishers` from `skills/sumo-qa-suggesting-external-skill/registry.json` |
| `sumo_qa_check_node_available()` | True/false on whether `npx` is on PATH |
| `sumo_qa_detect_node_installer()` | Pick the OS package manager for installing Node (brew / winget / apt-get / dnf) |
| `sumo_qa_install_node()` | Run the detected installer. **Caller must have explicit user `[y/N]` consent first.** Refuses to elevate; returns the manual `sudo` command on Linux. |

## Why the surface is so small

The discipline (when to ask the user, when to call which tool, what to assert, how to cite a principle) lives in the [skill files](../skills/). The host LLM follows the skill literally. The MCP tools just provide the source of truth.

This is the architectural difference from the pre-restructure version, which had 10 heavy MCP tools each producing 1500-token structured JSON output via host-LLM sampling. That model broke on hosts with smaller token caps or less robust SSE handling — the thin-tool design above replaced it.
