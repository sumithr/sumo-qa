<p align="center">
  <img src="assets/logo.png" alt="sumo-qa — strong QA, crouching rikishi mark" width="520" />
</p>

# sumo-qa MCP

[![tests](https://github.com/sumithr/sumo-qa/actions/workflows/test.yml/badge.svg)](https://github.com/sumithr/sumo-qa/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/sumo-qa?cacheSeconds=300&v=0.2.2)](https://pypi.org/project/sumo-qa/) <!-- x-release-please-version -->
[![Python](https://img.shields.io/pypi/pyversions/sumo-qa?cacheSeconds=300&v=0.2.2)](https://pypi.org/project/sumo-qa/) <!-- x-release-please-version -->
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue)](LICENSE)

A senior-QA MCP server + skills library that delivers ISTQB-grade testing discipline to AI coding agents across **Claude Code, Cursor, Codex, OpenCode, JetBrains AI Assistant + Junie, and VS Code + GitHub Copilot**. The discipline lives in [skill files](skills/) the host LLM follows literally; MCP tools provide canonical knowledge catalogues. Skills auto-trigger from their YAML descriptions on QA-shaped natural language — the workflow kicks in without you having to remember to invoke it.

> [!IMPORTANT]
> **sumo-qa is an advisor, not an oracle.** Like all AI tools, it can be wrong — do not rely on its output 100%. Use your own judgment and your team's standards as the final word. sumo-qa loads you with discipline, named risks, and design techniques faster than you'd assemble them by hand; the engineer at the keyboard still makes the call.

> ### 🚀 New here? **[5-minute demo →](DEMO.md)**
> Install with one line, run one prompt on your real repo, see the senior-QA workflow happen on actual code. No staged data, no scripted output.

## Why sumo-qa?

Most AI coding assistants approach QA the way a junior engineer would: *"add unit tests, consider edge cases, maybe test performance too."* That's a checklist, not testing. sumo-qa makes the AI work like a senior QA — risks named against specific lines, design techniques (boundary-value, decision-table, property-based, mutation) picked from a loaded ISTQB-grounded catalogue, test suites run fresh in *this* turn before any "safe to merge" claim.

The discipline is enforced by 14 [skill files](skills/) the host LLM follows literally (1 entry router + 13 sub-skills) — each one with an Iron Law (TDD's red phase before any production code; mutation-strengthening keeps production code locked; no plan ships without measurable entry AND exit criteria) and a HARD-GATE callout the LLM can't talk itself past. Skills auto-trigger from their YAML `description:` field on QA-shaped requests in natural language; when sumo-qa is loaded as a Claude Code / Cursor plugin, the bundled SessionStart hook additionally pre-injects the entry router into the conversation's system context as a stronger guarantee.

Read [DEMO.md](DEMO.md) for the 5-minute install-and-run-this-prompt walkthrough.

## Install

**One line — install and wire it into your host of choice:**

```bash
pip install sumo-qa && sumo-qa-install --claude-code
```

Swap `--claude-code` for `--vscode --workspace <path-to-repo>` (VS Code + Copilot), `--jetbrains` (JetBrains AI Assistant), or drop the flag entirely to configure every host detected on this machine. Works identically on Windows / macOS / Linux — `pip` generates `.exe` wrappers on Windows, so no `python3` invocation to deal with. Restart your host (or open a fresh chat) once it's done.

Per-host flags, schema differences, and troubleshooting: [docs/INSTALL.md](docs/INSTALL.md).

### Updating

```bash
pip install --upgrade sumo-qa && sumo-qa-install
```

Then restart the host. The SessionStart hook re-injects new content; bundled skills + knowledge refresh from the upgraded package.

## What you get

| Layer | What it is |
|---|---|
| **14 skills** (`skills/*/SKILL.md`) | Iron-Law-enforced procedures the host LLM follows. Cover deciding approach, preparing for work, scaffolding TDD, reviewing diffs, strengthening tests, finding test data, answering testing questions, repo-wide strategising — **plus planning + subagent execution + finishing chain** (planning → dispatch parallel subagents → capture evidence + PR-ready summary). |
| **24 MCP entry points** | 14 skill tools + 6 knowledge loaders + 4 test-data tools. Thin file IO; no inference. |
| **4 knowledge catalogues** (`knowledge/*.md`) | Classifications, approaches, principles, techniques — the LLM picks from these, not from training-data recall. Editable as plain markdown. Specialty-tool picks are intentionally NOT catalogued: the discipline is observe the risk surface, web-search current options for the user's stack, cite when naming a tool. |

## Host support

Each host surfaces the same skills and tools differently — that's a host-API difference, not a sumo-qa choice. All routes call the same MCP server and read the same SKILL.md content.

The hosts below have been verified end-to-end with `sumo-qa-install`:

| Host | Slash invocation | Setup |
|---|---|---|
| **Claude Code** | `/sumo-qa-deciding-approach` (hyphens) | `sumo-qa-install --claude-code` |
| **VS Code + Copilot** (Agent mode, Claude Sonnet 4.5 or equivalent) | Natural language; Copilot picks tools by description | `sumo-qa-install --vscode --workspace <repo>` writes `<repo>/.vscode/mcp.json` |
| **JetBrains AI Assistant** | `/sumo_qa_deciding_approach` (underscores) | One-time **Settings → Tools → AI Assistant → Model Context Protocol → Add server** with absolute binary path. `sumo-qa-install --jetbrains` prints the fields to paste. |
| **JetBrains Junie** | Natural language; Junie picks tools by description | Drop the JSON `sumo-qa-install` prints into `~/.junie/mcp/sumo-qa.json` (global) or `<repo>/.junie/mcp/` (per-project) |

**Slash-invocation in Claude Code.** After `sumo-qa-install --claude-code`, type `/` and start typing `sumo-qa-`:

- The 14 skills appear as native Claude Code skills with hyphens (`/sumo-qa-deciding-approach`, `/sumo-qa-creating-test-plan`, …) — `sumo-qa-install` symlinks them into `~/.claude/skills/`.
- The skills are also registered through MCP, and the MCP knowledge loaders + test-data tools show with underscores (`/sumo_qa_load_classifications`, `/sumo_qa_find_test_data`, …). You may see both the hyphen and underscore forms of each skill — they call the same SKILL.md and behave identically.

**Natural language always works.** *"review my changes"*, *"plan QA for this story"*, *"load the QA classifications"* — the agent routes by tool description. Slash and natural-language paths produce the same result.

In **JetBrains AI Assistant** every entry point is slash-invocable with underscores (`/sumo_qa_deciding_approach`, `/sumo_qa_load_classifications`). In **VS Code + Copilot** and **Junie**, neither host routes via slash menu — use natural language; both pick tools by description.

**Other MCP-capable hosts** (Cursor, Codex, OpenCode, etc.): the `sumo-qa` binary you get from `pip install sumo-qa` exposes a standard stdio MCP server, so it should work with any host that speaks MCP — follow that host's own MCP-server setup docs and point it at the absolute path printed by `sumo-qa-install --help`. We haven't verified those end-to-end ourselves, so we don't ship instructions for them.

**Quick test in any host:** ask in chat *"load the QA classifications"*. Should return 10 names: api_contract_change, business_logic_change, security_change, performance_change, frontend_change, infrastructure_change, test_change, docs_change, config_change, data_migration. If yes, you're wired correctly.

## See it in action

Ten polished worked examples showing what sumo-qa actually looks like in conversation — diff reviews refusing to declare safe-to-merge, TDD cycles with the red output surfaced verbatim, mutation survivors walked one-at-a-time, formal test plans gated on measurable entry/exit criteria, and the surprising one where it correctly says *"no tests needed"* and stops:

- **[tests/scenarios/worked-examples/](tests/scenarios/worked-examples/)** — see [02 — review-my-changes](tests/scenarios/worked-examples/02-review-my-changes.md) for a representative end-to-end transcript.
- **[tests/scenarios/SCENARIOS.md](tests/scenarios/SCENARIOS.md)** — the underlying scenario specs (user prompt → expected interaction shape → anti-patterns the skill prevents).

## External-skill discovery

If your QA intent has no native sumo-qa fit (e.g. *"set up Playwright E2E tests"*, *"add an accessibility audit"*, *"run k6 load tests"*), sumo-qa offers (with `[y/N]`) to install Vercel Labs' [`find-skills`](https://github.com/vercel-labs/skills) meta-skill, which then drives end-to-end discovery and install from [skills.sh](https://www.skills.sh/).

- No companion MCP shim — sumo-qa stays one MCP server. All CLI invocations happen through the host LLM's native `Bash` tool inside the SKILL itself.
- Node.js (and therefore `npx`) is required. If it isn't installed, sumo-qa prints the install URL (https://nodejs.org) and stops — it never auto-elevates via sudo.
- find-skills handles scope (global vs project-local), registry search, and install end-to-end; sumo-qa's discipline wraps the final response.

## License

Licensed under the [Apache License, Version 2.0](LICENSE). See [NOTICE](NOTICE) for attribution requirements that apply to forks and redistributors.

## Docs

- [AGENTS.md](AGENTS.md) — AI-agent bootstrap and per-host setup
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — three layers, host delivery, knowledge authority
- [docs/SKILLS.md](docs/SKILLS.md) — the 14 skills with their Iron Laws
- [docs/TOOLS.md](docs/TOOLS.md) — the 24 MCP entry points
- [docs/INSTALL.md](docs/INSTALL.md) — per-host install detail, schema differences, troubleshooting
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — env vars
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — local dev
- [docs/TEST-DATA.md](docs/TEST-DATA.md) — known-good test-data catalogue
- [docs/PERSONA.md](docs/PERSONA.md) — optional in-character voice (Sumo-sensei). Off by default; ask the agent to enable mid-conversation.
