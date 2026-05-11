# sumo-qa MCP

A senior-QA MCP server that delivers ISTQB-grade testing discipline to AI coding agents in
Claude Code, IntelliJ AI Assistant, and VS Code + GitHub Copilot. The discipline lives in
[skill files](skills/) the host LLM follows literally; MCP tools provide canonical
knowledge catalogues; nothing runs through heavy single-shot sampling.

## Setup

**AI agents:** read [AGENTS.md](AGENTS.md) — bootstraps automatically per host.

**Humans:**
```bash
python install.py
```

Runs on Windows, macOS, and Linux. Installs the MCP server via `uv`, symlinks skills
into Claude Code's skills directory if present, and prints the MCP config snippet to
paste into your host's settings.

## What you get

| Layer | What it is |
|---|---|
| **10 skills** (`skills/*/SKILL.md`) | Iron-Law-enforced procedures the host LLM follows. Cover deciding approach, planning, scaffolding TDD, reviewing diffs, strengthening tests, finding test data, answering testing questions, repo-wide strategising. |
| **11 MCP tools** | 7 knowledge loaders (classifications, approaches, principles, techniques, specialty tools, standards, rules) + 4 test-data tools. Thin file-IO; no inference. |
| **5 knowledge catalogues** (`knowledge/*.md`) | Authoritative — the LLM picks from these, not from training-data recall. Editable as plain markdown. |

## Host coverage

| Host | Skill delivery |
|---|---|
| Claude Code | Skills symlinked into `~/.claude/skills/sumo-qa/`; auto-load on QA-shaped intents |
| IntelliJ AI Assistant | Skills exposed as MCP prompts; invoke by name (`qa_creating_test_plan`, etc.) |
| VS Code + GitHub Copilot | Skills exposed as MCP prompts; `.github/copilot-instructions.md` points Copilot at them |

## Docs

- [AGENTS.md](AGENTS.md) — AI-agent bootstrap (the canonical setup walkthrough)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — three layers, host delivery, knowledge authority
- [docs/SKILLS.md](docs/SKILLS.md) — the 10 skills with their Iron Laws
- [docs/TOOLS.md](docs/TOOLS.md) — the 11 MCP tools
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — env vars
- [docs/INSTALL.md](docs/INSTALL.md) — manual install
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — local dev
- [docs/TEST-DATA.md](docs/TEST-DATA.md) — known-good test-data catalogue
- [docs/superpowers/](docs/superpowers/) — design spec, implementation plans, iteration history

## Status

Branch `feat/superpowers-restructure`, local only. Built via a 5-phase superpowers-style restructure (see [`docs/superpowers/specs/2026-05-08-superpowers-restructure-design.md`](docs/superpowers/specs/2026-05-08-superpowers-restructure-design.md)).
