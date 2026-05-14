<p align="center">
  <img src="assets/logo.png" alt="sumo-qa — strong QA, crouching rikishi mark" width="520" />
</p>

# sumo-qa MCP

[![tests](https://github.com/sumithr/sumo-qa/actions/workflows/test.yml/badge.svg)](https://github.com/sumithr/sumo-qa/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/sumo-qa?cacheSeconds=300)](https://pypi.org/project/sumo-qa/)
[![Python](https://img.shields.io/pypi/pyversions/sumo-qa?cacheSeconds=300)](https://pypi.org/project/sumo-qa/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue)](LICENSE)

A senior-QA MCP server + skills library that delivers ISTQB-grade testing discipline to AI coding agents across **Claude Code, Cursor, Codex, OpenCode, JetBrains AI Assistant + Junie, and VS Code + GitHub Copilot**. The discipline lives in [skill files](skills/) the host LLM follows literally; MCP tools provide canonical knowledge catalogues; a SessionStart hook auto-injects the `using-sumo-qa` router so the agent reliably runs the workflow without you having to remember to invoke it.

> [!IMPORTANT]
> **sumo-qa is an advisor, not an oracle.** Like all AI tools, it can be wrong — do not rely on its output 100%. Use your own judgment and your team's standards as the final word. sumo-qa loads you with discipline, named risks, and design techniques faster than you'd assemble them by hand; the engineer at the keyboard still makes the call.

> ### 🚀 New here? **[5-minute demo →](DEMO.md)**
> Install with one line, run one prompt on your real repo, see the senior-QA workflow happen on actual code. No staged data, no scripted output.

## Why sumo-qa?

Most AI coding assistants approach QA the way a junior engineer would: *"add unit tests, consider edge cases, maybe test performance too."* That's a checklist, not testing. sumo-qa makes the AI work like a senior QA — risks named against specific lines, design techniques (boundary-value, decision-table, property-based, mutation) picked from a loaded ISTQB-grounded catalogue, test suites run fresh in *this* turn before any "safe to merge" claim.

The discipline is enforced by [13 skill files](skills/) the host LLM follows literally — each one with an Iron Law (TDD's red phase before any production code; mutation-strengthening keeps production code locked; no plan ships without measurable entry AND exit criteria) and a HARD-GATE callout the LLM can't talk itself past. A SessionStart hook auto-injects the entry router on every conversation, so the workflow kicks in without you having to remember to invoke it.

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
| **13 skills** (`skills/*/SKILL.md`) | Iron-Law-enforced procedures the host LLM follows. Cover deciding approach, preparing for work, scaffolding TDD, reviewing diffs, strengthening tests, finding test data, answering testing questions, repo-wide strategising — **plus planning + subagent execution + finishing chain** (planning → dispatch parallel subagents → capture evidence + PR-ready summary). |
| **24 MCP entry points** | 13 skill tools + 7 knowledge loaders + 4 test-data tools. Thin file IO; no inference. |
| **5 knowledge catalogues** (`knowledge/*.md`) | 4 authoritative catalogues (classifications, approaches, principles, techniques) — the LLM picks from these, not from training-data recall. Plus 1 category-fit primer (specialty_tools) where the LLM picks tool brands from its training knowledge and the file confirms the category fits. Editable as plain markdown. |

## Host support

Each host surfaces the same skills and tools differently — that's a host-API difference, not a sumo-qa choice. All routes call the same MCP server and read the same SKILL.md content.

The hosts below have been verified end-to-end with `sumo-qa-install`:

| Host | Slash invocation | Setup |
|---|---|---|
| **Claude Code** | `/qa-deciding-approach` (hyphens) | `sumo-qa-install --claude-code` |
| **VS Code + Copilot** (Agent mode, Claude Sonnet 4.5 or equivalent) | Natural language; Copilot picks tools by description | `sumo-qa-install --vscode --workspace <repo>` writes `<repo>/.vscode/mcp.json` |
| **JetBrains AI Assistant** | `/qa_deciding_approach` (underscores) | One-time **Settings → Tools → AI Assistant → Model Context Protocol → Add server** with absolute binary path. `sumo-qa-install --jetbrains` prints the fields to paste. |
| **JetBrains Junie** | Natural language; Junie picks tools by description | Drop the JSON `sumo-qa-install` prints into `~/.junie/mcp/sumo-qa.json` (global) or `<repo>/.junie/mcp/` (per-project) |

In Claude Code, MCP tools are NOT slash-invocable directly — use natural language (e.g. *"load the QA classifications"*) and the AI picks the right tool. In JetBrains AI Assistant, every tool IS slash-invocable. Both paths work; both end up calling the same skill body.

**Other MCP-capable hosts** (Cursor, Codex, OpenCode, etc.): the `sumo-qa` binary you get from `pip install sumo-qa` exposes a standard stdio MCP server, so it should work with any host that speaks MCP — follow that host's own MCP-server setup docs and point it at the absolute path printed by `sumo-qa-install --help`. We haven't verified those end-to-end ourselves, so we don't ship instructions for them.

**Quick test in any host:** ask in chat *"load the QA classifications"*. Should return 10 names: api_contract_change, business_logic_change, security_change, performance_change, frontend_change, infrastructure_change, test_change, docs_change, config_change, data_migration. If yes, you're wired correctly.

## See it in action

Ten polished worked examples showing what sumo-qa actually looks like in conversation — diff reviews refusing to declare safe-to-merge, TDD cycles with the red output surfaced verbatim, mutation survivors walked one-at-a-time, formal test plans gated on measurable entry/exit criteria, and the surprising one where it correctly says *"no tests needed"* and stops:

- **[tests/scenarios/worked-examples/](tests/scenarios/worked-examples/)** — see [02 — review-my-changes](tests/scenarios/worked-examples/02-review-my-changes.md) for a representative end-to-end transcript.
- **[tests/scenarios/SCENARIOS.md](tests/scenarios/SCENARIOS.md)** — the underlying scenario specs (user prompt → expected interaction shape → anti-patterns the skill prevents).

## License

Licensed under the [Apache License, Version 2.0](LICENSE). See [NOTICE](NOTICE) for attribution requirements that apply to forks and redistributors.

## Docs

- [AGENTS.md](AGENTS.md) — AI-agent bootstrap and per-host setup
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — three layers, host delivery, knowledge authority
- [docs/SKILLS.md](docs/SKILLS.md) — the 13 skills with their Iron Laws
- [docs/TOOLS.md](docs/TOOLS.md) — the 24 MCP entry points
- [docs/INSTALL.md](docs/INSTALL.md) — per-host install detail, schema differences, troubleshooting
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — env vars
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — local dev
- [docs/TEST-DATA.md](docs/TEST-DATA.md) — known-good test-data catalogue
- [docs/PERSONA.md](docs/PERSONA.md) — optional in-character voice (Sumo-sensei). Off by default; ask the agent to enable mid-conversation.
