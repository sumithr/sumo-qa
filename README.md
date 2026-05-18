<p align="center">
  <img src="assets/logo.png" alt="sumo-qa — strong QA, crouching rikishi mark" width="520" />
</p>

# sumo-qa MCP

[![tests](https://github.com/sumithr/sumo-qa/actions/workflows/test.yml/badge.svg)](https://github.com/sumithr/sumo-qa/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/sumo-qa?cacheSeconds=300&v=0.3.2)](https://pypi.org/project/sumo-qa/) <!-- x-release-please-version -->
[![Python](https://img.shields.io/pypi/pyversions/sumo-qa?cacheSeconds=300&v=0.3.2)](https://pypi.org/project/sumo-qa/) <!-- x-release-please-version -->
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue)](LICENSE)

An MCP server and skills library that gives AI coding agents a senior-QA workflow. Works with Claude Code, Cursor, Codex, OpenCode, JetBrains AI Assistant + Junie, and VS Code + GitHub Copilot.

> [!IMPORTANT]
> sumo-qa is an advisor, not an oracle. Like any AI tool it can be wrong. Your judgment and your team's standards are the final word.

> ### 🚀 New here? **[5-minute demo →](DEMO.md)**
> One install line, one prompt on your repo, the workflow runs on real code.

## Why it exists

Ask a stock AI assistant to QA a change and you get the junior answer: "add unit tests, consider edge cases, maybe test performance." That's a checklist.

sumo-qa makes the agent work the way a senior QA does:

- Names 3–7 risks tied to specific files and lines, not categories
- Picks one design technique per risk from an ISTQB-grounded catalogue (boundary-value, decision-table, property-based, mutation)
- Runs your test suite fresh in the current turn before any "safe to merge" claim
- Holds TDD's red phase before any production code is written
- Keeps production code locked while strengthening tests against mutation survivors
- Won't ship a plan without measurable entry and exit criteria

The discipline lives in 14 [skill files](skills/) (1 router + 13 sub-skills). The host LLM follows them literally, and each one has an Iron Law and a HARD-GATE callout the LLM can't talk past. Skills route automatically from natural-language prompts; you don't need to remember to invoke them.

## Install

```bash
pip install sumo-qa && sumo-qa-install --claude-code
```

Other hosts: swap `--claude-code` for `--vscode --workspace <path-to-repo>`, `--jetbrains`, or drop the flag to configure every host on the machine. Works the same on macOS, Linux, and Windows (pip generates `.exe` wrappers, so no `python3` invocation).

Restart your host or open a fresh chat afterwards.

Per-host flags, schema differences, and troubleshooting: [docs/INSTALL.md](docs/INSTALL.md).

### Verify it's wired

In any host, ask:

> load the QA classifications

You should get 10 names back: api_contract_change, business_logic_change, security_change, performance_change, frontend_change, infrastructure_change, test_change, docs_change, config_change, data_migration. If you do, you're wired.

### Update

```bash
pip install --upgrade sumo-qa && sumo-qa-install
```

Restart the host. The SessionStart hook re-injects the latest content; skills and knowledge refresh from the upgraded package.

## What's included

| Layer | What |
|---|---|
| **14 skills** ([`skills/`](skills/)) | Iron-Law procedures: deciding approach, preparing for work, TDD scaffolding, diff review, strengthening tests, finding test data, answering testing questions, repo strategy — plus the planning → parallel subagent execution → finishing chain. |
| **24 MCP entry points** | 14 skill tools, 6 knowledge loaders, 4 test-data tools. Thin file IO, no inference. |
| **4 knowledge catalogues** ([`knowledge/`](knowledge/)) | Classifications, approaches, principles, techniques. The agent picks from these instead of recalling from training data. Editable as plain markdown. Specialty-tool picks are deliberately not catalogued — the discipline is observe the risk surface, web-search current options for the user's stack, cite when naming a tool. |

## Host support

Every host calls the same MCP server and reads the same SKILL.md files. What differs is how each host exposes them — that's a host-API difference, not a sumo-qa choice.

These hosts are verified end-to-end with `sumo-qa-install`:

| Host | Slash | Setup |
|---|---|---|
| **Claude Code** | `/sumo-qa-deciding-approach` (hyphens) | `sumo-qa-install --claude-code` |
| **VS Code + Copilot** (Agent mode, Claude Sonnet 4.5 or equivalent) | Natural language | `sumo-qa-install --vscode --workspace <repo>` writes `.vscode/mcp.json` |
| **JetBrains AI Assistant** | `/sumo_qa_deciding_approach` (underscores) | One-time UI setup; `sumo-qa-install --jetbrains` prints the fields to paste |
| **JetBrains Junie** | Natural language | Drop the JSON `sumo-qa-install` prints into `~/.junie/mcp/sumo-qa.json` (global) or `<repo>/.junie/mcp/` (per project) |

In Claude Code, type `/` then `sumo-qa-` to see all 14 skills as hyphenated entries (symlinked into `~/.claude/skills/`). The same skills are also registered through MCP with underscores (`/sumo_qa_load_classifications`, `/sumo_qa_find_test_data`); both routes call the same SKILL.md.

Natural language works everywhere. *"Review my changes"*, *"plan QA for this story"*, *"load the QA classifications"* — the agent routes by tool description. Slash and natural-language paths produce the same result.

**Other MCP hosts** (Cursor, Codex, OpenCode, etc.): `pip install sumo-qa` ships a standard stdio MCP server, so it should work with anything that speaks MCP. Follow your host's MCP-server setup docs and point it at the absolute path from `sumo-qa-install --help`. Not verified end-to-end by us, so we don't ship instructions.

## See it in action

Ten transcripts showing the workflow on real code — diff reviews refusing to call safe-to-merge from stale CI, TDD cycles with the red output surfaced verbatim, mutation survivors walked one at a time, formal test plans gated on entry/exit criteria, and the case where the right answer is "no tests needed, stop here":

- [tests/scenarios/worked-examples/](tests/scenarios/worked-examples/) — start with [02 — review my changes](tests/scenarios/worked-examples/02-review-my-changes.md) for a representative end-to-end
- [tests/scenarios/SCENARIOS.md](tests/scenarios/SCENARIOS.md) — the scenario specs (prompt → expected shape → anti-patterns the skill prevents)

## When sumo-qa doesn't fit

If your QA intent has no native fit (Playwright E2E, accessibility audits, k6 load testing), sumo-qa offers (`[y/N]`) to install Vercel Labs' [find-skills](https://github.com/vercel-labs/skills) meta-skill, which then searches and installs from [skills.sh](https://www.skills.sh/).

- No companion MCP shim. All CLI invocations go through the host LLM's `Bash` tool inside the skill.
- Node.js is required (for `npx`). If it's missing, sumo-qa prints the install URL and stops. It doesn't elevate via sudo.
- find-skills handles scope (global vs project-local), registry search, and install; sumo-qa's discipline wraps the response.

## License

[Apache 2.0](LICENSE). See [NOTICE](NOTICE) for attribution requirements that apply to forks and redistributors.

## More docs

- [AGENTS.md](AGENTS.md) — AI-agent bootstrap and per-host setup
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — three layers, host delivery, knowledge authority
- [docs/SKILLS.md](docs/SKILLS.md) — every skill with its Iron Law
- [docs/TOOLS.md](docs/TOOLS.md) — every MCP entry point
- [docs/INSTALL.md](docs/INSTALL.md) — per-host install detail and troubleshooting
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — env vars
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — local dev
- [docs/TEST-DATA.md](docs/TEST-DATA.md) — known-good test-data catalogue
- [docs/PERSONA.md](docs/PERSONA.md) — optional Sumo-sensei voice (off by default)
