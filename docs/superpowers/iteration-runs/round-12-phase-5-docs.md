# Phase 5 — Docs + Install Polish (complete)

Branch: `feat/superpowers-restructure`. 9 new commits since Phase 4 completion (`bb8e8fc`).

## What landed

Docs deleted (superseded by skills + knowledge):
- `docs/QA_WORKFLOW.md`
- `docs/WORKFLOW-LOOP.md`
- `docs/APPROACHES.md` (superseded by `knowledge/approaches.md`)
- `docs/ISTQB-GROUNDING.md` (superseded by `knowledge/principles.md`)
- `docs/SPECIALTY-ROUTING.md` (superseded by `knowledge/specialty_tools.md`)

Docs rewritten:
- `README.md` — points at AGENTS.md, gives humans `python install.py`
- `docs/TOOLS.md` — 11-tool surface (7 knowledge + 4 test-data)
- `docs/SKILLS.md` — 10 skills with Iron Laws and trigger phrasing
- `docs/ARCHITECTURE.md` — three-layer architecture + host delivery + knowledge authority
- `docs/CONFIGURATION.md` — env vars list
- `docs/DEVELOPMENT.md` — local dev workflow
- `docs/INSTALL.md` — per-host paths + AGENTS.md pointer

Docs verified unchanged:
- `docs/TEST-DATA.md`

## Install verified

`python install.py` runs cleanly. `sumo-qa-mcp` on PATH. Skills symlink in place (or
copy on Windows without developer mode).

Caught and fixed a bug in `install.py` during verification: it called
`uv tool install --from <repo> sumo-qa-mcp` but `sumo-qa-mcp` is the executable name,
not the package name. The package is `sumo-qa`. Now installs cleanly with `--reinstall`
so re-running the installer is idempotent.

## Final state

- `uv run pytest`: 140 passed, 0 failed, 1 xfailed (acknowledged Task 12 deferral).
- MCP server: 11 tools, 10 prompts.
- Branch local-only.

## All 5 phases of the superpowers restructure are now complete.

Outstanding follow-up: Task 12 (standards pack annotation) needs a small targeted
plan to relax `_RawPack` schema + split packs to fit token budget. Doesn't block
review or merge of this branch.
