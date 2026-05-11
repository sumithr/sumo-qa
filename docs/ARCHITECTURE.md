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
