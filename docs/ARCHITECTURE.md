# Architecture

Three layers, clean separation:

```mermaid
%%{init: {'theme':'base', 'themeVariables': {
  'fontFamily':'Charter, "Iowan Old Style", Georgia, serif',
  'fontSize':'15px',
  'primaryTextColor':'#1B1B1B',
  'lineColor':'#1B1B1B'
}}}%%
flowchart LR
    LLM{{"Host LLM"}}

    subgraph Inputs ["sumo-qa content"]
        direction TB
        Knowledge[("Knowledge")]
        Standards[("Standards")]
    end

    Skills["<b>Skills</b>"]
    Output(["Output"])

    Knowledge -- cited by --> Skills
    Standards -- cited by --> Skills
    LLM == follows ==> Skills
    Skills == produces ==> Output

    classDef host fill:#7A1F1F,stroke:#1B1B1B,stroke-width:2px,color:#FAF7F2
    classDef skills fill:#FAF7F2,stroke:#1B1B1B,stroke-width:2.5px,color:#1B1B1B
    classDef data fill:#F0EAE0,stroke:#8A7B5C,stroke-width:1.5px,color:#1B1B1B
    classDef out fill:#E8EDDF,stroke:#3F4A2E,stroke-width:2px,color:#1B1B1B
    classDef group fill:none,stroke:#8A7B5C,stroke-width:1px,color:#5C4D00,stroke-dasharray: 4 4

    class LLM host
    class Skills skills
    class Knowledge,Standards data
    class Output out
    class Inputs group

    linkStyle 0,1 stroke:#8A7B5C,stroke-width:1.2px,stroke-dasharray:5 4
    linkStyle 2,3 stroke:#1B1B1B,stroke-width:2.5px
```

<sub>MCP tools (Python) are the transport between the Host LLM and the markdown content — omitted here for clarity. See [TOOLS.md](TOOLS.md).</sub>

## 1. Skills (markdown) — the orchestration layer

Each skill is a single `skills/<name>/SKILL.md` with:

- YAML frontmatter (`name` + `description`) used by hosts to auto-trigger
- An Iron Law — non-negotiable rule for the skill
- A When-to-Use paragraph
- A Checklist (numbered items the host LLM works through; each is tracked as an entry in the host's ordered work tracker)
- A Process Flow section
- A Red Flags table (rationalisations to reject)
- Good/Bad examples

All senior-QA discipline lives here. There is no Python file that decides
which approach a change needs, or what techniques apply to a risk, or which
specialty tool fits an HTTP surface. The host LLM does that work, guided by
the skill.

## 2. MCP tools (Python) — atomic knowledge providers

The tools are all thin. Skill tools (one per SKILL.md) and knowledge loaders (`sumo_qa_load_*`)
return markdown catalogues as text. A read-only progressive-loading pair (`sumo_qa_list_skill_manifests`, `sumo_qa_load_skill_context`) indexes each SKILL.md's sections/modules and serves a single slice (manifest / section / module / full) as a JSON string so a host can load just the routing summary or one section rather than the whole body; `mode="full"` returns the same bytes as the skill tool. `sumo_qa_list_skill_manifests` is a *compact* all-skill routing aid by default (`detail="compact"` — per-skill metadata only, no section/module arrays); the full all-skill index is an explicit `detail="full_index"` opt-in, while the per-skill manifest/section/module/full slices of `sumo_qa_load_skill_context` are the progressive-loading ladder a host climbs once it has chosen a skill. Each partial slice carries a `content_hash` (sha256 of the returned text) and `estimated_tokens`; a caller can pass `known_hash` to get a derived `changed` flag (body omitted when unchanged). This change-detection is stateless — there is no server-side session cache, because MCP session identity is not reliable across the supported hosts, so re-hashing the live slice per call is preferred over a cache keyed on an unstable identity. The same index is additionally exposed as additive MCP resources/resource-templates (`sumoqa://skills`, `sumoqa://skills/{name}/manifest|sections/{id}|modules/{id}|full`) whose bodies are byte-for-byte the loader output, for hosts that surface resources; the model-callable tools stay the canonical, unchanged path. A capabilities-discovery tool (`sumo_qa_capabilities`) returns a compact, typed map of the core QA workflows. Repo-map tools build and consume the QA-native `.sumo-qa/repo-map.json` artifact, each returning a compact typed summary rather than the full map. A risk-to-test ledger formatter (`sumo_qa_format_risk_ledger`) validates host-supplied risk rows and renders the structured verdict appendix — no inference, file/format plumbing only. A context-bundle formatter (`sumo_qa_format_context_bundle`) validates a host-neutral issue/PR context bundle and renders its brief plus its freshness/conflict signals — an optional review/planning *input*, never a network call or GitHub dependency. A QA-readiness-scorecard composer (`sumo_qa_format_qa_scorecard`) reuses those two artifacts plus optional coverage/mutation signals to *derive* a readiness recommendation (ready / ready_with_accepted_residuals / blocked / insufficient_evidence) — an evidence summary, not a predictive quality score; it invents no numeric score and refuses a ready state while a risk is an uncovered blocker or evidence is stale. A QA-artifact exporter (`sumo_qa_export_test_cases`) deterministically renders host-supplied, already-structured test cases into versioned JSON, a markdown table, or (for flat outlines) CSV — markdown stays the default human-facing output, exports are side-effect free, and there is no vendor lock-in or new mandatory dependency. Test-data tools read/write the local
known-good catalogue under `knowledge/test_data/`. An ingestion tool materialises runtime knowledge packs into a user-writable location. External-skill lifecycle tools search, install, locate, and load external skills through the Skills CLI while preserving the skill-level confirmation gate. The search tool returns ANSI-stripped CLI output verbatim — no structured parsing — so Skills CLI format drift doesn't break the flow.

See [TOOLS.md](TOOLS.md) for the full list.

## 3. Knowledge & data

Plain markdown under `knowledge/`:

- `classifications.md` — 10 canonical change classifications
- `approaches.md` — 9 canonical QA approaches
- `principles.md` — ISTQB Foundation, Advanced, ISO/IEC 25010
- `techniques.md` — black-box / white-box / experience / static / property-based / mutation
- `test_data/` — known-good test data entries

Specialty-tool picks are intentionally NOT catalogued. The discipline (declared in `using-sumo-qa`) is to observe the risk surface, web-search current options for the user's stack, and cite when naming a tool. A static catalogue would anchor toward yesterday's brands and create a false floor where novel surfaces never trigger discovery.

Plus team-loaded `standards/packs/*.yml` and `standards/rules/change_rules.yaml`.

## Degraded mode (MCP server unavailable)

When the MCP server can't launch — most commonly because `uvx` isn't on PATH in the plugin install path — three layers surface the failure (SessionStart hook system-message, `/mcp` failed status, `bin/sumo-qa-doctor` actionable error). What still works and what doesn't is intentionally asymmetric:

- **Skills still load.** They're static markdown read from the plugin's `skills/<name>/SKILL.md` at session start by the plugin loader, totally independent of MCP runtime state. A uv-less user gets the QA discipline scaffolding (Iron Law, approach gates, output economy) even though the tools are dead.
- **Knowledge catalogues remain readable via filesystem fallback.** The host LLM has Read/Grep tools and the plugin source is on disk (the `--plugin-dir` checkout or the `~/.claude/plugins/cache/...` marketplace copy), so when asked *"list the sumo-qa testing classifications"* the LLM may bypass the dead `sumo_qa_load_classifications` tool and read `knowledge/classifications.md` directly. The data is authoritative (same file the MCP server would have served); the LLM should and does cite the path. This is accepted graceful degradation, not a bug — but skill chains that traverse multiple `sumo_qa_*` tools don't fall back this way.
- **Compute-style tools genuinely cannot fall back.** `sumo_qa_deciding_approach`, `sumo_qa_finding_test_data`, the install-an-external-skill flow — anything that's logic rather than catalogue lookup — produces no useful output when MCP is down. Failure here is loud and unambiguous; install uv and the user's back online.

## Host delivery

Different hosts surface MCP entries through different UIs and (in some cases) different config schemas. `sumo-qa-install` (shipped as a console script via `pip install sumo-qa`) handles each correctly; the same MCP server and SKILL.md content reach every host.

| Host | Setup | Slash convention | Schema |
|---|---|---|---|
| **Claude Code** | `sumo-qa-install --claude-code` symlinks each `skills/<name>/` to `~/.claude/skills/<name>/` (per-skill, NOT a wrapper — Claude Code doesn't recurse). Writes `claude_desktop_config.json`. | Skills appear in `/` with hyphens (`/sumo-qa-deciding-approach`, from the native skill loader). MCP tools (knowledge loaders, test-data) appear with underscores (`/sumo_qa_load_classifications`). Skills appear in both forms because they're registered as MCP tools too; calling either form reaches the same SKILL.md. Natural language works universally. | `{ "mcpServers": { ... } }` |
| **JetBrains AI Assistant** | One-time **Settings → Tools → AI Assistant → Model Context Protocol → Add server** with absolute binary path. `sumo-qa-install --jetbrains` prints the exact fields. External XML writes don't reliably register the runtime coroutine in IDEA 2026.1 — must go through the UI. | `/sumo_qa_deciding_approach` (underscores, from MCP tools). Every MCP entry is slash-invocable. | XML at `~/Library/Application Support/JetBrains/<ide>/options/llm.mcpServers.xml` (managed by UI) |
| **JetBrains Junie** | JSON file at `~/.junie/mcp/sumo-qa.json` (global) or `<repo>/.junie/mcp/` (per-project) | Natural language; Junie picks tools by description | `{ "mcpServers": { ... } }` (same as Claude Desktop) |
| **VS Code + Copilot** | `sumo-qa-install --vscode --workspace /path/to/repo` writes `<repo>/.vscode/mcp.json`. Use Agent mode + Claude Sonnet 4.5 or GPT-5 full. | Natural language; Copilot picks tools by description | `{ "servers": { "<name>": { "type": "stdio", "command": "...", "args": [] } } }` — **different from Claude Desktop's schema** |

All routes ultimately call the same `sumo-qa` binary which reads the same `skills/*/SKILL.md` files and the same `knowledge/*.md` catalogues. Skill content is one source of truth.

### Plugin-format adapters (Claude Code / Codex)

Hosts that consume plugin manifests (`.claude-plugin/plugin.json` for Claude Code, `.codex-plugin/plugin.json` for Codex) read first-class folders that live at the repo root. Both folders, plus `.mcp.json` and `hooks/hooks*.json`, are generated from a single canonical source — `pyproject.toml`'s `[tool.sumo-qa.plugin]` overlay — by `python -m plugin_packaging.plugin_generator sync`. Drift is gated in CI: the next PR that edits the overlay or the generator without re-running sync fails the `plugin-packaging` workflow.

Adding a new host (Cursor, OpenCode, …) is one new template under `plugin_packaging/templates/` plus the per-host description line in `[tool.sumo-qa.plugin]`. See [host-adapters.md](host-adapters.md) for the full architecture, including how the wheel-vs-repo path resolution interacts with `force-include`.

The `sumo-qa-install` console script consumes the same canonical source at runtime through a frozen snapshot bundled in the wheel at `sumo_qa/_data/plugin_metadata.json`. Every host-config write site (Claude Desktop, VS Code, JetBrains) sources its server name + command from `sumo_qa.plugin_metadata.PluginMetadata.from_bundle()` — no host-specific literals duplicated across the codebase.

## Knowledge authority hierarchy

A global rule declared in `using-sumo-qa`:

1. **Loaded knowledge files** (`sumo_qa_load_*` tools). Authoritative.
2. **Training data** — fallback only; must be flagged when used.
3. **Web search** — fallback for post-training-cutoff topics; citation required.
4. **"I don't know"** — the only acceptable answer when 1, 2 and 3 fail. Hallucinating a technique/tool/principle is forbidden.

This means catalogue files are the LLM's source of truth, not its training-data recall.

## Token-weight discipline

A typical end-to-end flow (e.g. `sumo-qa-creating-test-plan`):

| Layer | Typical token cost |
|---|---|
| Skill body (loaded once via MCP prompt or symlink) | ~1500 tokens |
| Catalogue loads (`load_classifications`, `load_approaches`, `load_techniques`) | ~2400 tokens total |
| Total MCP-call surface | ~2400 tokens |
| Old heavy-path single call | ~3000+ tokens of structured JSON (the IntelliJ SSE failure mode) |

The new path is enforced by `tests/test_token_weight_regression.py` and `tests/test_phase3_e2e_skill_path.py`. No single per-catalogue MCP call returns more than the ~1500-token per-call budget; the heaviest full flow (create-test-plan, five catalogue loads) stays within its per-flow budget.

## How a typical request flows

```mermaid
%%{init: {'theme':'base', 'themeVariables': {
  'fontFamily':'Charter, "Iowan Old Style", Georgia, serif',
  'fontSize':'15px',
  'primaryTextColor':'#1B1B1B',
  'lineColor':'#1B1B1B'
}}}%%
flowchart TD
    U(["User prompt"])
    R{{"<b>using-sumo-qa</b><br/><i>router</i>"}}
    D["<b>deciding-approach</b>"]
    P["<b>creating-test-plan</b>"]
    O(["Test plan<br/><i>entry &amp; exit criteria</i>"])

    U ==> R ==> D ==> P ==> O

    classDef io fill:#FAF7F2,stroke:#1B1B1B,stroke-width:2px,color:#1B1B1B
    classDef router fill:#7A1F1F,stroke:#1B1B1B,stroke-width:2px,color:#FAF7F2
    classDef step fill:#FAF7F2,stroke:#1B1B1B,stroke-width:2.5px,color:#1B1B1B
    classDef done fill:#E8EDDF,stroke:#3F4A2E,stroke-width:2px,color:#1B1B1B
    class U io
    class R router
    class D,P step
    class O done

    linkStyle 0,1,2,3 stroke:#1B1B1B,stroke-width:2.5px
```

No single MCP call returns a heavy JSON blob. The LLM does the synthesis, guided by the skill's checklist, anchored to catalogue text.

---

Licensed under the Apache License 2.0. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE) at the repo root.
