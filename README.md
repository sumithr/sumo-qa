# sumo-qa MCP

A senior-QA MCP server that delivers ISTQB-grade testing discipline to AI coding agents in
Claude Code, JetBrains IDEs (AI Assistant + Junie), and VS Code + GitHub Copilot. The discipline
lives in [skill files](skills/) the host LLM follows literally; MCP tools provide canonical
knowledge catalogues; nothing runs through heavy single-shot sampling.

## Setup

**Default install (all detected hosts):**

```bash
python3 install.py
```

**Just one host:**

```bash
python3 install.py --claude-code             # Claude Code only
python3 install.py --vscode                  # VS Code workspace (run from inside it)
python3 install.py --vscode --workspace /path/to/repo
python3 install.py --jetbrains               # prints JetBrains Settings UI steps
python3 install.py --vscode --skip-mcp-install   # don't reinstall uv tool
```

Re-runs are idempotent. Runs on Windows, macOS, and Linux. Installs the MCP via
`uv`, configures host-specific MCP entries, and prints any manual steps remaining.

**AI agents:** read [AGENTS.md](AGENTS.md) — bootstraps automatically per host.

## What you get

| Layer | What it is |
|---|---|
| **10 skills** (`skills/*/SKILL.md`) | Iron-Law-enforced procedures the host LLM follows. Cover deciding approach, planning, scaffolding TDD, reviewing diffs, strengthening tests, finding test data, answering testing questions, repo-wide strategising. |
| **21 MCP entry points** | 10 skill tools + 7 knowledge loaders + 4 test-data tools. Thin file IO; no inference. |
| **5 knowledge catalogues** (`knowledge/*.md`) | Authoritative — the LLM picks from these, not from training-data recall. Editable as plain markdown. |

## Host support

Each host surfaces the same skills and tools differently — that's a host-API difference, not a sumo-qa choice. All routes call the same MCP server and read the same SKILL.md content.

| Host | Slash invocation | Setup |
|---|---|---|
| **Claude Code** | `/qa-deciding-approach` (hyphens) | `install.py --claude-code` symlinks each skill into `~/.claude/skills/<name>/` |
| **JetBrains AI Assistant** | `/qa_deciding_approach` (underscores) | One-time **Settings → Tools → AI Assistant → Model Context Protocol → Add server** with absolute binary path. `install.py --jetbrains` prints the fields to paste. |
| **JetBrains Junie** | Natural language; Junie picks tools by description | Drop the JSON `install.py` prints into `~/.junie/mcp/sumo-qa.json` (global) or `<repo>/.junie/mcp/` (per-project) |
| **VS Code + Copilot** (Agent mode, Claude Sonnet 4.5 or equivalent) | Natural language; Copilot picks tools by description | `install.py --vscode --workspace <repo>` writes `<repo>/.vscode/mcp.json` |

In Claude Code, MCP tools are NOT slash-invocable directly — use natural language (e.g. *"load the QA classifications"*) and the AI picks the right tool. In JetBrains AI Assistant, every tool IS slash-invocable. Both paths work; both end up calling the same skill body.

**Quick test in any host:** ask in chat *"load the QA classifications"*. Should return 10 names: api_contract_change, business_logic_change, security_change, performance_change, frontend_change, infrastructure_change, test_change, docs_change, config_change, data_migration. If yes, you're wired correctly.

## Docs

- [AGENTS.md](AGENTS.md) — AI-agent bootstrap and per-host setup
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — three layers, host delivery, knowledge authority
- [docs/SKILLS.md](docs/SKILLS.md) — the 10 skills with their Iron Laws
- [docs/TOOLS.md](docs/TOOLS.md) — the 21 MCP entry points
- [docs/INSTALL.md](docs/INSTALL.md) — per-host install detail, schema differences, troubleshooting
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — env vars
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — local dev
- [docs/TEST-DATA.md](docs/TEST-DATA.md) — known-good test-data catalogue
- [docs/superpowers/](docs/superpowers/) — design spec, implementation plans, iteration history

## Status

Branch `feat/superpowers-restructure`, validated end-to-end on Claude Code, IntelliJ + Junie + Claude Opus 4.7, IntelliJ AI Assistant + GPT-5.5, and VS Code Copilot + Claude Sonnet 4.5. Architecture spec: [`docs/superpowers/specs/2026-05-08-superpowers-restructure-design.md`](docs/superpowers/specs/2026-05-08-superpowers-restructure-design.md).
