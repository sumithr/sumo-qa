# MCP Tools

The sumo-qa MCP exposes **28 entry points**: 14 skill tools + 6 knowledge loaders + 4 test-data tools + 4 external-skill lifecycle tools. All are thin — each is file IO, small deterministic logic, or a Skills CLI subprocess. No inference, no host-LLM sampling. The host LLM reasons over what they return.

## Skill tools (14)

Each returns the full body of a `skills/<name>/SKILL.md` file. The host LLM treats the returned markdown as the procedure to follow (Iron Law + checklist + flowchart + Red Flags + examples).

The skill bodies are host-neutral: they declare capability obligations (ordered work tracker, structured user-choice prompt, fresh delegated worker — see `using-sumo-qa` → *Shared vocabulary*) rather than naming any one host's specific tools. Adapters surface the same bodies through host-specific UIs (Claude Code slash commands, JetBrains MCP slash commands, Copilot agentic-mode tool selection, etc.).

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
| `sumo_qa_suggesting_external_skill` | Drive external-skill search / install / execution when no native fit exists |

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

## External-skill lifecycle

When no native sumo-qa fit is found, `sumo-qa-suggesting-external-skill` searches, installs, and executes external skills through sumo-qa MCP tools:

```mermaid
%%{init: {'theme':'base', 'themeVariables': {
  'fontFamily':'Charter, "Iowan Old Style", Georgia, serif',
  'fontSize':'13px',
  'primaryTextColor':'#1B1B1B',
  'lineColor':'#1B1B1B'
}}}%%
flowchart LR
    Intent(["QA intent<br/><i>no native fit</i>"])
    Search["<b>search</b><br/><i>sumo_qa_search_external_skills</i>"]
    Gate{"<b>[y/N]</b>"}
    Install["<b>install</b><br/><i>sumo_qa_install_external_skill</i>"]
    Locate["<b>locate &amp; load</b><br/><i>check_installed · execute</i>"]
    Out(["external SKILL.md<br/>in the conversation"])
    Stop(["stop"])

    Intent ==> Search ==> Gate
    Gate -->|y| Install ==> Locate ==> Out
    Gate -->|N| Stop

    classDef io fill:#FAF7F2,stroke:#1B1B1B,stroke-width:2px,color:#1B1B1B
    classDef step fill:#FAF7F2,stroke:#1B1B1B,stroke-width:2.5px,color:#1B1B1B
    classDef gate fill:#7A1F1F,stroke:#1B1B1B,stroke-width:2px,color:#FAF7F2
    classDef stop fill:#F0EAE0,stroke:#8A7B5C,stroke-width:1.5px,color:#1B1B1B
    classDef done fill:#E8EDDF,stroke:#3F4A2E,stroke-width:2px,color:#1B1B1B

    class Intent io
    class Search,Install,Locate step
    class Gate gate
    class Stop stop
    class Out done
```

| Tool | Purpose |
|---|---|
| `sumo_qa_search_external_skills` | Run `skills find <query>` and return ANSI-stripped CLI output verbatim — no structured parsing, so Skills CLI format drift doesn't break the flow |
| `sumo_qa_check_external_skill_installed` | Locate an installed `SKILL.md` in project or global agent skill paths |
| `sumo_qa_install_external_skill` | Install a named skill through `npx skills add` after explicit user confirmation |
| `sumo_qa_execute_external_skill` | Load the installed `SKILL.md` and return the execution handoff payload |

Install still requires a user `[y/N]` gate in the skill. The host does not shell out to `npx` directly for this flow.

## Why the surface is so small

The discipline (when to ask the user, when to call which tool, what to assert, how to cite a principle) lives in the [skill files](../skills/). The host LLM follows the skill literally. The MCP tools just provide the source of truth.

This is the architectural difference from the pre-restructure version, which had 10 heavy MCP tools each producing 1500-token structured JSON output via host-LLM sampling. That model broke on hosts with smaller token caps or less robust SSE handling — the thin-tool design above replaced it.
