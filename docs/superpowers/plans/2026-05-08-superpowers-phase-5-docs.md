# Superpowers Restructure — Phase 5 (Docs + Install Polish) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Update README and all `docs/*.md` to reflect the new architecture. Delete obsolete docs that described the heavy-tool path. Final verification that the new MCP works end-to-end.

**Architecture:** Pure documentation work. The README points at `AGENTS.md` (the AI-agent bootstrap) and gives humans the same path. `docs/` shrinks to only docs that describe the surviving architecture.

**Branch:** `feat/superpowers-restructure` (continues from Phase 4, commit `bb8e8fc`).

---

## File Structure

### Modified

| Path | Change |
|---|---|
| `README.md` | Slim to ~30 lines: 1-paragraph intro, "AI agents: read AGENTS.md" + "Humans: run install.py or follow AGENTS.md", host table, link to specs/docs |
| `docs/TOOLS.md` | Rewrite for the 11-tool surface (4 test-data + 7 knowledge loaders); drop heavy-tool references |
| `docs/SKILLS.md` | Rewrite for the 10 skills, with Iron Laws and trigger phrasing |
| `docs/ARCHITECTURE.md` | Rewrite: 3-layer architecture (skills + knowledge tools + catalogues); host delivery (Claude Code symlinks, IntelliJ + Copilot MCP prompts) |
| `docs/CONFIGURATION.md` | Slim: env vars list (`QA_STANDARDS_PATH`, `QA_RULES_PATH`, `QA_TEST_DATA_PATH`, `QA_DISABLE_HOST_SAMPLING` → delete since sampling is gone, `SUMO_QA_DEBUG_DIR`) |
| `docs/DEVELOPMENT.md` | Slim: pytest, install.py, branch workflow |
| `docs/INSTALL.md` | Slim: point at AGENTS.md + install.py |
| `docs/TEST-DATA.md` | Keep mostly as-is; verify still accurate |

### Deleted

| Path | Reason |
|---|---|
| `docs/QA_WORKFLOW.md` | Host-agnostic discipline doc — superseded by skill markdown that every host reads (Claude Code via symlink, others via MCP prompts) |
| `docs/WORKFLOW-LOOP.md` | Plan→scaffold→red→green→review per-approach doc — superseded by `skills/qa-implementing-with-tdd/SKILL.md` |
| `docs/APPROACHES.md` | Canonical approaches catalogue — superseded by `knowledge/approaches.md` (the file the LLM actually loads) |
| `docs/ISTQB-GROUNDING.md` | Senior-QA persona / principles doc — superseded by `knowledge/principles.md` |
| `docs/SPECIALTY-ROUTING.md` | Specialty + tool fit catalogue — superseded by `knowledge/specialty_tools.md` |

---

## Setup

### Task 0: Baseline

- [ ] **Step 0.1: Confirm starting state.**

```bash
git branch --show-current
uv run pytest 2>&1 | tail -3
ls docs/
```

Expected: branch `feat/superpowers-restructure`, 140 passed / 0 skipped / 1 xfailed, 11 markdown files + `superpowers/` directory under `docs/`.

---

## Group A: Delete obsolete docs

### Task 1: Delete 5 docs superseded by skills/ + knowledge/ catalogues

- [ ] **Step 1.1:**

```bash
git rm docs/QA_WORKFLOW.md \
       docs/WORKFLOW-LOOP.md \
       docs/APPROACHES.md \
       docs/ISTQB-GROUNDING.md \
       docs/SPECIALTY-ROUTING.md
```

- [ ] **Step 1.2: Verify nothing in the repo still references them.**

```bash
grep -rn "QA_WORKFLOW\.md\|WORKFLOW-LOOP\.md\|APPROACHES\.md\|ISTQB-GROUNDING\.md\|SPECIALTY-ROUTING\.md" --include="*.md" --include="*.py" . 2>/dev/null | grep -v "docs/superpowers/"
```

Expected: empty result (the only matches should be in `docs/superpowers/` spec/plan/iteration history — those are fine).

If any non-superpowers file references the deleted docs, update or delete those references in this same commit.

- [ ] **Step 1.3: Commit.**

```bash
git add -A
git commit -m "docs: delete 5 docs superseded by skills/ and knowledge/ catalogues"
```

---

## Group B: Rewrite the surviving docs

### Task 2: Rewrite `README.md`

- [ ] **Step 2.1: Replace README with this content:**

````markdown
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
````

- [ ] **Step 2.2: Commit.**

```bash
git add README.md
git commit -m "docs(README): rewrite for new architecture; point at AGENTS.md"
```

---

### Task 3: Rewrite `docs/TOOLS.md`

- [ ] **Step 3.1: Replace with this content:**

````markdown
# MCP Tools

The sumo-qa MCP exposes 11 tools, all thin: each is file IO or a small
deterministic operation. No inference, no sampling. The host LLM picks
from the returned data; the tool only provides it.

## Knowledge providers (7)

Each returns a markdown catalogue as plain text. The host LLM reasons over the
returned content. The classification-filter tools (`load_standards`, `load_rules`)
filter by metadata declared in the file's frontmatter — no keyword matching.

| Tool | Returns |
|---|---|
| `sumo_qa_load_classifications()` | The 10 canonical change classifications (api_contract_change, business_logic_change, …, data_migration) |
| `sumo_qa_load_approaches()` | The 8 canonical QA approaches (tdd-scaffold, regression-first, …, spike-first-then-tests) |
| `sumo_qa_load_principles()` | ISTQB Foundation principles, Advanced certifications, ISO/IEC 25010 quality characteristics |
| `sumo_qa_load_techniques()` | Test design techniques (black-box, white-box, experience-based, static, property-based, mutation) |
| `sumo_qa_load_specialty_tools()` | Specialty + tool fit catalogue (Pitest, OWASP ZAP, Pact, k6, Hypothesis, axe-core, etc.) |
| `sumo_qa_load_standards(classification?)` | Team's loaded standards packs; optional metadata-based filter by classification |
| `sumo_qa_load_rules(classification?)` | Team's loaded change rules; optional metadata-based filter |

## Test-data tools (4)

Manage the local known-good test data catalogue under `knowledge/test_data/`.
File-IO + validation against source systems where applicable.

| Tool | Purpose |
|---|---|
| `sumo_qa_explain_test_data_requirements(question, environment, domain)` | Returns the data requirements as text |
| `sumo_qa_find_test_data(question, environment, domain, criteria)` | Looks up matching catalogue entries |
| `sumo_qa_validate_test_data(path)` | Checks a known-good entry against its source system |
| `sumo_qa_register_known_good_test_data(...)` | Writes a new known-good entry |

## Why the surface is so small

The discipline (when to ask the user, when to call which tool, what to assert, how
to cite a principle) lives in the [skill files](../skills/). The host LLM follows
the skill literally. Tools just provide the source of truth.

This is the architectural difference from the pre-restructure version, which had 10 heavy MCP tools each producing 1500-token structured JSON output via host-LLM sampling. That model broke on hosts with smaller token caps or less robust SSE handling. See [`docs/superpowers/specs/2026-05-08-superpowers-restructure-design.md`](superpowers/specs/2026-05-08-superpowers-restructure-design.md) for the full rationale.
````

- [ ] **Step 3.2: Commit.**

```bash
git add docs/TOOLS.md
git commit -m "docs(TOOLS): rewrite for the 11-tool post-restructure surface"
```

---

### Task 4: Rewrite `docs/SKILLS.md`

- [ ] **Step 4.1: Replace with this content:**

````markdown
# Skills

The sumo-qa MCP ships 10 skills under [`skills/`](../skills/). Each is a single
`SKILL.md` file the host LLM follows literally: YAML frontmatter, an Iron Law, a
checklist, a graphviz process flow, a Red Flags table, examples.

Hosts that support superpowers-style skill auto-loading (Claude Code) load the
files directly from `~/.claude/skills/sumo-qa/`. Other hosts (IntelliJ AI
Assistant, VS Code + Copilot) get the same content via MCP `prompts/get`.

## The 10 skills

| Skill | When to use | Iron Law |
|---|---|---|
| [using-sumo-qa](../skills/using-sumo-qa/SKILL.md) | Entry router on every QA intent | NO QA WORK WITHOUT FIRST DECIDING THE APPROACH. |
| [qa-deciding-approach](../skills/qa-deciding-approach/SKILL.md) | First step on every QA intent — picks the canonical approach | SHAPE FIRST. |
| [qa-preparing-for-work](../skills/qa-preparing-for-work/SKILL.md) | Plan QA for a story before coding starts | NO TEST IDEA WITHOUT A NAMED RISK. |
| [qa-creating-test-plan](../skills/qa-creating-test-plan/SKILL.md) | Formal test plan with entry/exit criteria | NO PLAN WITHOUT EXPLICIT ENTRY AND EXIT CRITERIA. |
| [qa-implementing-with-tdd](../skills/qa-implementing-with-tdd/SKILL.md) | Plan → red → user implements → green → review | RED PHASE FIRST. NO PRODUCTION CODE BEFORE A FAILING TEST. |
| [qa-reviewing-before-merge](../skills/qa-reviewing-before-merge/SKILL.md) | "Review my changes / is this safe to merge" | NEVER CLAIM SAFE-TO-MERGE WITHOUT FRESH VERIFICATION EVIDENCE. |
| [qa-strengthening-tests](../skills/qa-strengthening-tests/SKILL.md) | Mutation-testing follow-up | PRODUCTION CODE STAYS UNCHANGED. |
| [qa-finding-test-data](../skills/qa-finding-test-data/SKILL.md) | Test data discovery / validation / registration | STALE IS A DEFECT. NEVER INVENT ENTRIES NOT IN THE CATALOGUE. |
| [qa-answering-testing-question](../skills/qa-answering-testing-question/SKILL.md) | Generic "how do I test this?" / "what should I check for X?" | NO ANSWER WITHOUT A CITED PRINCIPLE OR TECHNIQUE. |
| [sumo-qa-strategising](../skills/sumo-qa-strategising/SKILL.md) | Repo-wide QA strategy / audit / pyramid design | WALK THE REPO FIRST. |

## Global discipline (declared in using-sumo-qa, inherited by all sub-skills)

- **Knowledge authority hierarchy:** loaded knowledge files (via `sumo_qa_load_*` tools) are authoritative. Training data is a fallback that must be flagged. Web search is a fallback for post-training-cutoff topics. "I don't know" is acceptable; inventing a technique, tool, or principle is not.
- **Citations live in reasoning, not output:** the LLM thinks in terms of cited evidence (which words in the user's intent, which file paths, which catalogue entries) but the user-facing output omits the citations unless asked.
- **Specialty + tool fit applies broadly:** any tool that meaningfully improves quality fits — Pitest on pure functions, Hypothesis for property-based tests, Pact for REST contracts, OWASP ZAP for HTTP DAST, axe-core for a11y. Empty list is acceptable.

## Conformance

Every SKILL.md is structurally validated by `tests/test_skill_conformance.py`:
frontmatter parses with name matching the directory, description ≥30 chars,
descriptions unique across skills, Iron Law section present, Checklist with ≥4
numbered items, Process Flow with a graphviz `dot` block, Red Flags table
present.

## Editing a skill

Skills are plain markdown. Edit `skills/<name>/SKILL.md`; the change propagates
to every host on next reload (Claude Code reads the symlinked file; IntelliJ /
Copilot fetch the MCP prompt fresh on each invocation). Conformance tests run
in CI to catch structural drift.
````

- [ ] **Step 4.2: Commit.**

```bash
git add docs/SKILLS.md
git commit -m "docs(SKILLS): rewrite for the 10-skill post-restructure surface"
```

---

### Task 5: Rewrite `docs/ARCHITECTURE.md`

- [ ] **Step 5.1: Replace with this content:**

````markdown
# Architecture

Three layers, clean separation:

## 1. Skills (markdown) — the orchestration layer

Each skill is a single `skills/<name>/SKILL.md` with:

- YAML frontmatter (`name` + `description`) used by hosts to auto-trigger
- An Iron Law — non-negotiable rule for the skill
- A When-to-Use paragraph
- A Checklist (numbered items the host LLM works through; each becomes a TodoWrite todo)
- A Process Flow (graphviz `dot` block)
- A Red Flags table (rationalisations to reject)
- Good/Bad examples

All senior-QA discipline lives here. There is no Python file that decides
which approach a change needs, or what techniques apply to a risk, or which
specialty tool fits an HTTP surface. The host LLM does that work, guided by
the skill.

## 2. MCP tools (Python) — atomic knowledge providers

11 tools, all thin: each is file IO. Seven knowledge loaders (`sumo_qa_load_*`)
return markdown catalogues as text. Four test-data tools read/write the local
known-good catalogue under `knowledge/test_data/`.

See [TOOLS.md](TOOLS.md) for the full list.

## 3. Knowledge & data

Plain markdown under `knowledge/`:

- `classifications.md` — 10 canonical change classifications
- `approaches.md` — 8 canonical QA approaches
- `principles.md` — ISTQB Foundation, Advanced, ISO/IEC 25010
- `techniques.md` — black-box / white-box / experience / static / property-based / mutation
- `specialty_tools.md` — specialty + tool fit catalogue
- `test_data/` — known-good test data entries

Plus team-loaded `standards/packs/*.yml` and `standards/rules/change_rules.yaml`.

## Host delivery

| Host | How skills reach it | Duplication |
|---|---|---|
| Claude Code | `install.py` symlinks `skills/` → `~/.claude/skills/sumo-qa/`. Auto-loads on QA-shaped intents via SKILL.md frontmatter description. | None (symlink) |
| IntelliJ AI Assistant | MCP server reads `skills/*/SKILL.md` at startup and registers each as an MCP prompt. AI Assistant surfaces prompts in chat. | None (server reads canonical files at request time) |
| VS Code + GitHub Copilot | Same MCP prompts as IntelliJ. `.github/copilot-instructions.md` (~5 lines) tells Copilot to fetch them. | None (instructions file is a pointer, not a copy) |

## Knowledge authority hierarchy

A global rule declared in `using-sumo-qa`:

1. **Loaded knowledge files** (`sumo_qa_load_*` tools). Authoritative.
2. **Training data** — fallback only; must be flagged when used.
3. **Web search** — fallback for post-training-cutoff topics; citation required.
4. **"I don't know"** — the only acceptable answer when 1, 2 and 3 fail. Hallucinating a technique/tool/principle is forbidden.

This means catalogue files are the LLM's source of truth, not its training-data recall.

## Token-weight discipline

A typical end-to-end flow (e.g. `qa-creating-test-plan`):

| Layer | Typical token cost |
|---|---|
| Skill body (loaded once via MCP prompt or symlink) | ~1500 tokens |
| Catalogue loads (`load_classifications`, `load_approaches`, `load_techniques`, `load_specialty_tools`) | ~2300 tokens total |
| Total MCP-call surface | ~2300 tokens |
| Old heavy-path single call | ~3000+ tokens of structured JSON (the IntelliJ SSE failure mode) |

The new path is enforced by `tests/test_token_weight_regression.py` and `tests/test_phase3_e2e_skill_path.py`. No single MCP call returns more than ~700 tokens; no full flow exceeds 2600 tokens.

## How a typical request flows

```
User: "create a test plan for refactoring the pricing pipeline"
    │
    ▼
Host LLM auto-loads `using-sumo-qa` (Iron Law: decide approach first)
    │
    ▼
Routes to `qa-deciding-approach`:
    - calls sumo_qa_load_classifications, _approaches, _rules, _standards
    - reasons: classification = business_logic_change + refactor modifier
    - approach = coverage-first-then-refactor (skill flowchart, LLM applies)
    - no user question — intent + cited words covered it
    │
    ▼
Routes to `qa-creating-test-plan` (Iron Law: NO PLAN WITHOUT EXPLICIT ENTRY/EXIT CRITERIA):
    - reads actual files via host file tools
    - identifies 3-7 named risks anchored in evidence
    - calls sumo_qa_load_techniques, picks one per risk
    - calls sumo_qa_load_specialty_tools, picks Pitest for mutation coverage
    - synthesises plan inline (conversational, sectioned)
```

No single MCP call returns a heavy JSON blob. The LLM does the synthesis, guided by the skill's checklist, anchored to catalogue text.
````

- [ ] **Step 5.2: Commit.**

```bash
git add docs/ARCHITECTURE.md
git commit -m "docs(ARCHITECTURE): rewrite for three-layer post-restructure design"
```

---

### Task 6: Slim `docs/CONFIGURATION.md`

- [ ] **Step 6.1: Replace with this content:**

````markdown
# Configuration

All optional. Defaults work out of the box after `python install.py`.

| Env var | Default | Purpose |
|---|---|---|
| `QA_STANDARDS_PATH` | bundled `_data/standards/packs` / repo `standards/packs` | Override the team's loaded standards packs |
| `QA_RULES_PATH` | bundled `_data/standards/rules/change_rules.yaml` / repo `standards/rules/change_rules.yaml` | Override the team's loaded change rules |
| `QA_TEST_DATA_PATH` | bundled `_data/knowledge/test_data` / repo `knowledge/test_data` | Override the known-good test data catalogue |
| `QA_KNOWLEDGE_PATH` | bundled `_data/knowledge` / repo `knowledge` | Override the canonical knowledge catalogues (classifications, approaches, principles, techniques, specialty_tools) |
| `SUMO_QA_DEBUG_DIR` | unset | Directory to capture per-tool-call args + output as JSON for debugging / grading |

## Example: custom team standards

```json
{
  "mcpServers": {
    "sumo-qa": {
      "command": "sumo-qa-mcp",
      "env": {
        "QA_STANDARDS_PATH": "/abs/path/to/team-standards/packs",
        "QA_RULES_PATH": "/abs/path/to/team-standards/rules/change_rules.yaml",
        "QA_TEST_DATA_PATH": "/abs/path/to/team-test-data"
      }
    }
  }
}
```

## Debugging

```json
{
  "mcpServers": {
    "sumo-qa": {
      "command": "sumo-qa-mcp",
      "env": {
        "SUMO_QA_DEBUG_DIR": "/tmp/sumo-qa-debug"
      }
    }
  }
}
```

Each tool call writes a JSON file under `SUMO_QA_DEBUG_DIR` capturing the args and output. Useful for grading skill-driven output and reproducing host-side issues.
````

- [ ] **Step 6.2: Commit.**

```bash
git add docs/CONFIGURATION.md
git commit -m "docs(CONFIGURATION): slim env-var list to surviving paths"
```

---

### Task 7: Slim `docs/DEVELOPMENT.md`

- [ ] **Step 7.1: Replace with this content:**

````markdown
# Development

Local dev guide for sumo-qa.

## Prerequisites

- Python 3.10+ (capped at <3.14 per `pyproject.toml`)
- [uv](https://docs.astral.sh/uv/) — install via `curl -LsSf https://astral.sh/uv/install.sh | sh` (or PowerShell equivalent on Windows)

## Setup

```bash
git clone <repo>
cd qa-shift-left-mcp
uv tool install --from . sumo-qa --reinstall
```

For development without installing to the user tool dir, use `uv run`:

```bash
uv run pytest
uv run sumo-qa-mcp --help
```

## Test suite

```bash
uv run pytest
```

The full suite covers:

- `test_knowledge_loaders.py` — 7 catalogue loaders return canonical entries
- `test_skill_conformance.py` — every `skills/*/SKILL.md` has the required structure
- `test_skill_prompts.py` — every skill registers as an MCP prompt
- `test_phase3_e2e_skill_path.py` — end-to-end smoke through the new surface
- `test_token_weight_regression.py` — per-call and per-flow token budgets (the IntelliJ-SSE regression test)
- `test_server.py` — tool registration
- `test_tdm.py` — test-data tools
- `test_tools.py` — service factory
- `test_standards.py`, `test_rules.py` — file loading
- `test_debug_capture.py` — `SUMO_QA_DEBUG_DIR` capture

## Branch workflow

Feature work goes on a feature branch off `main`. Plans and specs land under
`docs/superpowers/`. Iteration notes go under `docs/superpowers/iteration-runs/`.
Don't push without explicit review approval.

## Editing skills

Plain markdown. Edit `skills/<name>/SKILL.md`. Conformance tests catch structural
drift (Iron Law section, Checklist ≥4 items, graphviz dot block, Red Flags table).

## Editing knowledge catalogues

Plain markdown under `knowledge/`. The LLM picks from what these files say.
Adding a new technique, classification, or specialty tool = editing one file.

## Adding a new skill

1. Create `skills/<new-name>/SKILL.md` following the template in `docs/SKILLS.md`.
2. `register_skills_as_prompts` (server startup) picks it up automatically.
3. Conformance tests parametrise over `skills/*/SKILL.md` — they run on the new skill too.
4. If the skill is meant to auto-trigger in Claude Code, the frontmatter `description` is what the host LLM uses to route.

## Reinstalling locally

```bash
uv tool install --from . sumo-qa --reinstall
```

Picks up server.py changes. For skill edits, no reinstall needed — Claude Code reads
`~/.claude/skills/sumo-qa/` via the symlink that `install.py` set up, and the MCP server
reads `skills/*/SKILL.md` fresh on each prompt request.
````

- [ ] **Step 7.2: Commit.**

```bash
git add docs/DEVELOPMENT.md
git commit -m "docs(DEVELOPMENT): slim for post-restructure repo state"
```

---

### Task 8: Slim `docs/INSTALL.md`

- [ ] **Step 8.1: Replace with this content:**

````markdown
# Install

## One-line (recommended)

```bash
python install.py
```

Runs on Windows, macOS, and Linux. Does:

1. Installs `sumo-qa-mcp` via `uv tool install`
2. Symlinks `skills/` into `~/.claude/skills/sumo-qa/` if Claude Code is detected (copies on Windows without developer mode)
3. Prints the MCP config snippet to paste into your host

If `uv` isn't installed, the script tells you how to install it for your OS.

## AI agent setup

If you're running an AI agent (Claude Code, Copilot CLI, etc.) in this repo, just point it at [AGENTS.md](../AGENTS.md). It walks through the per-host setup, detects which host it's in, runs what it can with its existing tools, and hands off steps it can't do (e.g. IntelliJ Settings UI) to you.

## Manual (per host)

### Claude Code

```bash
ln -sfn "$(pwd)/skills" ~/.claude/skills/sumo-qa   # macOS / Linux
# Windows (PowerShell, developer mode on):
# New-Item -ItemType SymbolicLink -Path "$env:USERPROFILE\.claude\skills\sumo-qa" -Target "$(Get-Location)\skills"
```

Add to `~/.config/claude/claude_desktop_config.json` (macOS/Linux) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "sumo-qa": { "command": "sumo-qa-mcp" }
  }
}
```

### IntelliJ AI Assistant

Settings → Tools → AI Assistant → Model Context Protocol → Add server with command `sumo-qa-mcp`. Skills auto-register as MCP prompts at startup.

### VS Code + GitHub Copilot

Edit `.vscode/mcp.json`:

```json
{
  "mcpServers": {
    "sumo-qa": { "command": "sumo-qa-mcp" }
  }
}
```

`.github/copilot-instructions.md` already tells Copilot to fetch the sumo-qa prompts.

## Verify

Ask your host to call `sumo_qa_load_classifications()`. If the response contains the 10 canonical classification names, you're done.
````

- [ ] **Step 8.2: Commit.**

```bash
git add docs/INSTALL.md
git commit -m "docs(INSTALL): rewrite for cross-platform install.py + per-host paths"
```

---

### Task 9: Verify `docs/TEST-DATA.md` still accurate

- [ ] **Step 9.1: Read it.**

```bash
cat docs/TEST-DATA.md
```

- [ ] **Step 9.2: If it references any deleted module (e.g. `tools.py` heavy methods), update those references. Otherwise leave as-is.**

The 4 test-data tools survive Phase 4 unchanged, so this doc likely needs no changes. Skim and confirm.

- [ ] **Step 9.3: If you made changes, commit. Otherwise skip.**

```bash
git add docs/TEST-DATA.md
git commit -m "docs(TEST-DATA): refresh references for post-restructure surface"
```

---

## Group C: Final verification

### Task 10: Verify install.py end-to-end

- [ ] **Step 10.1: Run install.py.**

```bash
python install.py 2>&1 | tail -20
```

Expected: prints "sumo-qa installer — detected OS: <OS>", installs the MCP, symlinks (or copies) skills, prints the config snippet. Exit cleanly.

- [ ] **Step 10.2: Verify `sumo-qa-mcp` is on PATH.**

```bash
which sumo-qa-mcp
sumo-qa-mcp --help 2>&1 | head -5
```

- [ ] **Step 10.3: Verify the symlink exists if Claude Code config dir is present.**

```bash
ls -la ~/.claude/skills/sumo-qa/ 2>&1 | head -3
```

Expected: shows the 10 skill directories (resolved through the symlink).

If symlink doesn't exist, check whether `~/.claude/` exists — `install.py` skips if it doesn't.

---

### Task 11: Phase 5 completion doc

- [ ] **Step 11.1: Write `docs/superpowers/iteration-runs/round-12-phase-5-docs.md`:**

```markdown
# Phase 5 — Docs + Install Polish (complete)

Branch: `feat/superpowers-restructure`. <N> new commits since Phase 4 completion (`bb8e8fc`).

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

## Final state

- `uv run pytest`: <N> passed, 0 failed, 1 xfailed (acknowledged Task 12 deferral).
- MCP server: 11 tools, 10 prompts.
- Branch local-only (5 phases, ~<commit count> commits since spec).

## All 5 phases of the superpowers restructure are now complete.

Outstanding follow-up: Task 12 (standards pack annotation) needs a small targeted
plan to relax `_RawPack` schema + split packs to fit token budget. Doesn't block
review or merge of this branch.
```

- [ ] **Step 11.2: Commit.**

```bash
git add docs/superpowers/iteration-runs/round-12-phase-5-docs.md
git commit -m "docs(iteration): Phase 5 docs + install complete"
```

---

## Phase 5 done

After Tasks 1-11:
- 5 obsolete docs deleted.
- 7 surviving docs rewritten for the new architecture.
- README points at AGENTS.md.
- install.py verified end-to-end.
- Completion doc written.

**All 5 phases of the superpowers restructure are complete.** Branch is ready for review on `feat/superpowers-restructure`. Don't push without explicit user approval.
