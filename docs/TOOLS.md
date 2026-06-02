# MCP Tools

The sumo-qa MCP exposes a small, thin tool surface: skill tools, knowledge loaders, a capabilities-discovery tool, repo-map tools, a risk-to-test ledger formatter, test-data tools, an ingestion tool, and external-skill lifecycle tools. Each is file IO, small deterministic logic, or a Skills CLI subprocess — no inference, no host-LLM sampling. The host LLM reasons over what they return. For the live tool surface, see your host's MCP tool list; the skills live under [`skills/`](../skills/). (`sumo_qa_capabilities` is a compact map of the core QA workflows — discovery, not the full tool inventory.)

## Skill tools

Each returns the full body of a `skills/<name>/SKILL.md` file. The host LLM treats the returned markdown as the procedure to follow (Iron Law + checklist + flowchart + Red Flags + examples).

The skill bodies are host-neutral: they declare capability obligations (ordered work tracker, structured user-choice prompt, fresh delegated worker — see `using-sumo-qa` → *Shared vocabulary*) rather than naming any one host's specific tools. Adapters surface the same bodies through host-specific UIs (Claude Code slash commands, JetBrains MCP slash commands, Copilot agentic-mode tool selection, etc.).

Each skill registers as a tool named after its directory with hyphens turned to underscores (`using-sumo-qa` → `using_sumo_qa`, `sumo-qa-deciding-approach` → `sumo_qa_deciding_approach`).

In JetBrains AI Assistant these are slash commands (`/sumo_qa_deciding_approach`). In Claude Code the equivalent slash commands come from the native skill files (`/sumo-qa-deciding-approach`, hyphens) — the MCP tools are still callable but only via natural language ("decide the QA approach for this refactor"). VS Code Copilot and Junie pick them by description in Agent / agentic mode.

See [SKILLS.md](SKILLS.md) for the Iron Law per skill.

## Progressive skill loading

A read-only, deterministic, local-only pair of tools that lets a host fetch just the slice of a skill it needs (the routing summary, one section, or one module) instead of the whole `SKILL.md` body. The zero-argument skill tools above are unchanged — `mode="full"` returns the same body byte-for-byte. No extraction, no network, no caching.

| Tool | What it returns |
|---|---|
| `sumo_qa_list_skill_manifests()` | A JSON string of compact metadata for every bundled skill: `skill_name`, `tool_name`, `description`, `content_hash` (sha256), `estimated_tokens_full`, `sections[]` (id, heading, level, estimated_tokens, required) and `modules[]` (id, path, estimated_tokens). Section ids are stable heading slugs (duplicates get `-2`/`-3` suffixes); `required` flags the structural sections (frontmatter, Iron Law, Checklist, Flow, Red Flags, HARD-GATE) when present. |
| `sumo_qa_load_skill_context(skill_name, mode, section=None, module=None)` | A JSON string for one slice. `mode` is `manifest` (routing summary + section/module lists), `section` (one section's text), `module` (one module's text), or `full` (the whole body, identical to the skill tool). Invalid skill/mode/section/module, a missing required arg, or a path-traversal attempt returns a JSON error envelope listing the valid choices — it never raises. |

### Which path to use — canonical vs compact

The four modes form a retrieval ladder. Climb only as far as the work needs:

| Path | Mode | Canonical? | Use it when |
|---|---|---|---|
| **Manifest (all skills)** | `sumo_qa_list_skill_manifests()` | No — routing aid | Choosing which skill applies. Metadata for every skill at once — including each skill's `sections[]`/`modules[]` *index* arrays (ids + token weights), but never the section/module *bodies*. The shipped full-index payload is ~11,000 approx tokens (guarded under a 13,000 ceiling); a host that wants the leanest routing slice can project away the `sections[]`/`modules[]` arrays (that compact projection is ~2,073 tokens). |
| **Manifest (one skill)** | `load_skill_context(skill, "manifest")` | No — routing aid | You've chosen a skill and want its section/module map (ids, token weights, which sections are `required`) before pulling any body. |
| **Section / Module** | `load_skill_context(skill, "section"/"module", …)` | **Yes** — verbatim slice | You need one part of a skill (its Iron Law, one checklist, one lazy module) and not the rest. The returned text is byte-for-byte from the file. |
| **Full** | `load_skill_context(skill, "full")` or the zero-arg skill tool | **Yes** — verbatim body | You are about to **execute** the skill. When exact procedure wording matters — Iron Law, HARD-GATE, the operational checklist a workflow follows step-by-step — load the full body. |

**Canonical means verbatim.** `section`, `module`, and `full` return text copied straight from `SKILL.md` (or a module file); a host may cite or follow them as the authoritative instruction. The two **manifest** paths are *compact navigation aids* — they summarise structure and token weights to help a host route, and are **not** a substitute for the procedure text. Do not treat a manifest description or section list as the instruction to follow; once a skill is actually being executed, load the section(s) or the full body so the model has the exact wording. The same rule governs the knowledge catalogues: a compact summary is for recall, the loaded catalogue text is what you cite.

**Cumulative-cost win.** The point of the ladder is session-cumulative cost. A host that revisits a skill many times pays the routing slice (manifest + a required section or two) on each visit instead of the whole body every time — for the heaviest skills the manifest-plus-routing slice is well over 50% lighter than the full body, and across a mixed session the cumulative saving is large. The `tests/test_token_weight_regression.py` and `tests/test_skill_modules.py` budgets lock that in. Two distinct all-skill-manifest budgets exist, for two distinct artifacts: the **shipped `sumo_qa_list_skill_manifests` output** (the full index *with* every skill's `sections[]`/`modules[]` arrays, the payload hosts actually fetch) is ~11,000 approx tokens and guarded under a **13,000** full-index ceiling; the **compact routing projection** (that same metadata with the `sections[]`/`modules[]` arrays projected away) is ~2,073 tokens and guarded under a separate **2,500** budget. Modules stay under 1,500, and the partial path must stay below the full-body cumulative cost.

## Knowledge loaders

Each returns a markdown catalogue as plain text. The host LLM reasons over the returned content. The classification-filter tools (`load_standards`, `load_rules`) accept a single classification or comma-separated classifications. Standards filtering is metadata-based from pack frontmatter; rules filtering returns matching entries. No keyword matching.

| Tool | Returns |
|---|---|
| `sumo_qa_load_classifications()` | The canonical change classifications |
| `sumo_qa_load_approaches()` | The canonical QA approaches |
| `sumo_qa_load_principles()` | ISTQB Foundation principles, Advanced certifications, ISO/IEC 25010 quality characteristics |
| `sumo_qa_load_techniques()` | Test design techniques (black-box, white-box, experience-based, static, property-based, mutation) |
| `sumo_qa_load_standards(classification?)` | Team's loaded standards packs; optional metadata-based filter by one or more classifications |
| `sumo_qa_load_rules(classification?)` | Team's loaded change rules; optional filter by one or more classifications |

Specialty-tool picks are intentionally NOT catalogued — the discipline (in `using-sumo-qa`) is to observe the risk surface, web-search current options for the user's stack, and cite when naming a tool. A static catalogue would anchor toward yesterday's brands and create a false floor where novel surfaces never trigger discovery.

## Capabilities discovery

A compact, read-only "what can sumo-qa do?" map: the core QA workflows, each with a sample prompt, the skill it routes to, and a one-line outcome. Typed output (`CapabilitiesOutput`), under 500 approximate tokens. Discovery only — it does **not** replace the `using-sumo-qa` entry router or `sumo_qa_deciding_approach`, and carries no internal classification labels.

| Tool | What it returns |
|---|---|
| `sumo_qa_capabilities()` | The core QA workflows, each as `{workflow, sample_prompt, target_skill, outcome}` routing to an existing skill |

## Repo-map tools

A QA-native map of the repo (`.sumo-qa/repo-map.json`) plus the consumers that turn it into review/planning/strategy signal. All return compact, typed summaries — never the full artifact. See [REPO-MAP.md](REPO-MAP.md) for the schema and the diff vs live-scan semantics. The review / preparing-for-work / strategising skills prefer the map when present and fall back to a repo walk when absent.

| Tool | What it returns |
|---|---|
| `sumo_qa_scan_repo(root, generator_version=None, write_to=None)` | Compact per-type node / edge / command / warning counts for the repo; optionally writes the full `.sumo-qa/repo-map.json` artifact (`RepoMapScanOutput`). Writer; read-only when `write_to` is omitted. |
| `sumo_qa_analyze_diff_impact(root, base_ref=None, changed_files=None, ...)` | Maps changed files onto the map: changed/affected nodes, likely related tests, the risk surface (changed sources with no mapped test), `probable_mapping_gap` (risk surface is a missed convention, not zero coverage), unmapped files, and staleness vs HEAD (`DiffImpactOutput`). On the first run of an unmapped repo it persists a repo-map to `artifact_path` (`persisted_map_path`) unless that is `None`; also writes a `diff-impact.json` overlay when `write_overlay=True`. |
| `sumo_qa_query_repo_map(root, query, limit=10, types=None, ...)` | Bounded, ranked search of the map by path / node id / component / tag / category / evidence type / command, each match carrying id, path, type, tags, and a match reason plus an artifact freshness summary (`RepoMapQueryOutput`). Read-only. |

## Risk-to-test ledger

A deterministic formatter for the risk-to-test traceability ledger — a structured appendix to the markdown-first verdict, not a replacement. The host LLM identifies the risks (the skills already require this); this tool only validates the supplied rows and renders them. No inference. See [RISK-LEDGER.md](RISK-LEDGER.md) for the row schema, the evidence-status vocabulary, and when not to use it.

| Tool | What it returns |
|---|---|
| `sumo_qa_format_risk_ledger(rows, max_rows=25)` | Validates host-supplied risk rows (`risk_id`, `risk`, `source_anchor`, `test`, `evidence_status`, `residual`, optional `repo_map_node_id`) and renders the markdown ledger table plus a one-line compact summary, the row count, and the uncovered-blocker count (`FormatRiskLedgerOutput`). Read-only; the table truncates past `max_rows` to stay inside the host token budget. |

## Context bundle

A deterministic formatter/validator for the host-neutral issue/PR context bundle — an optional *input* contract that hands review/planning a compact record of issue/PR summary, changed files, test/CI evidence, and user constraints. It is never a network requirement and never a GitHub dependency: every field can be filled from manual text, local git state, or an optional host integration, and a partial/empty bundle is first-class (the skill falls back to direct repo inspection). Go-stale facts (CI, tests) carry their own source + freshness; only a *fresh pass* is safety-supporting, and a stale/unknown/absent fact is rendered with an explicit "do not claim safety from it" warning. The review / preparing-for-work skills prefer the bundle when present. See [CONTEXT-BUNDLE.md](CONTEXT-BUNDLE.md) for the schema, the freshness vocabulary, and the conflict semantics.

| Tool | What it returns |
|---|---|
| `sumo_qa_format_context_bundle(bundle, local_head_sha=None, max_files=40)` | Validates a host-supplied bundle (`issue_summary`, `pr_summary`, `head_sha`, `changed_files`, `test_evidence`/`ci_status` with `result`/`freshness`/`source`, `user_constraints` — all optional but `schema_version`) and renders a host-neutral markdown brief plus a one-line summary, the changed-file count, the stale and not-safety-supporting evidence fields, and a bundle-vs-local-state conflict message when `head_sha` differs from `local_head_sha` (`FormatContextBundleOutput`). Read-only; no inference, no network call. |

## Test-data tools

Manage the local known-good test data catalogue under `knowledge/test_data/`. File IO + validation against source systems where applicable.

| Tool | Purpose |
|---|---|
| `sumo_qa_explain_test_data_requirements(question, environment, domain)` | Returns deterministic test-data requirements (entity / state / preconditions / edges / what-not); enriches existing fields with scenario-specific items when the question contains obvious signals (`locked`, `refund`, `discontinued`, `due-date`, `stale`, …) |
| `sumo_qa_find_test_data(question, environment, domain, criteria)` | Looks up matching catalogue entries |
| `sumo_qa_validate_test_data(path)` | Checks a known-good entry against its source system |
| `sumo_qa_register_known_good_test_data(...)` | Writes a new known-good entry |

## Ingestion

Add or replace team QA knowledge/standards/rules at runtime, without cloning the repo. Validates native files and writes a normalized copy into a user-writable pack (`project` = `<cwd>/.sumo-qa`, `global` = XDG data dir). Loader precedence: explicit env var > project > global > bundled > repo. See [CONFIGURATION.md](CONFIGURATION.md#adding-custom-knowledge-without-cloning-the-repo). Also exposed as the `sumo-qa-ingest` console script.

| Tool | Purpose |
|---|---|
| `sumo_qa_ingest_knowledge_pack(source, scope, content_type?)` | Validate + materialize a native pack; non-native sources (PDF/PPTX/URL) return an `unsupported_source` result routing through the `sumo-qa-suggesting-external-skill` flow to convert + re-ingest |

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
