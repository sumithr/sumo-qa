# sumo-qa Superpowers Restructure — Design

**Date:** 2026-05-08
**Branch:** `feat/superpowers-restructure`
**Status:** Design approved; ready for implementation plan.

## Goal

Replace sumo-qa's heavy single-shot MCP-tool architecture with a superpowers-style architecture in which **skills (markdown) carry the senior-QA discipline**, **MCP tools are thin knowledge providers and side-effect helpers**, and **the host LLM does all inference**. This fixes the IntelliJ AI Assistant SSE failure on `create_test_plan`, mirrors the upstream `obra/superpowers` conventions the user has been pointing at, and shrinks the per-flow token weight enough to work on context-constrained hosts.

## Context

### Triggering bug

`sumo_qa_create_test_plan` fails in IntelliJ AI Assistant with `ai.grazie.api.gateway.client.api.llm.LlmAPIClient ... ContinuousSSEException`. The crash is in JetBrains' Grazie LLM gateway dropping its SSE stream — but the root cause we control is sumo-qa's tool design: it asks the host LLM to produce a 1500-token structured JSON output in a single shot via heavy MCP sampling. Hosts with tighter token caps or less robust SSE handling break.

A token-cap workaround (`QA_DISABLE_HOST_SAMPLING=true`) makes the output dumber without fixing the underlying problem, and tells us the architecture itself is wrong for context-constrained hosts.

### What "like superpowers" actually means

`obra/superpowers` (https://github.com/obra/superpowers) is built around skills, not heavy tools:

- Each skill is a single `SKILL.md` with YAML frontmatter (`name`, `description`), an Iron Law (e.g. `NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST`), a checklist (turned into TodoWrite items), a graphviz flowchart, and a Red Flags table.
- The host LLM follows the skill literally. Dialogue with the user (one question at a time) happens at the host-LLM level, guided by the skill's checklist.
- MCP / external tools play a small role: atomic helpers, not heavy "do-everything" calls. The TDD skill never says "call tool X to write a test" — it says "write the test, run it, watch it fail."

Sumo-qa today inverts this: 7 thin skills that just point at heavy MCP tools doing 150-line system prompts plus 2-300-line per-tool sampling prompts. This restructure flips the layering to match upstream.

### Constraints

1. **Host portfolio (narrowed to 3):** Claude Code, IntelliJ AI Assistant, VS Code + GitHub Copilot. The earlier draft included Cursor / Codex / OpenCode / Gemini packaging; that has been dropped to reduce duplication.
2. **Cross-platform:** Windows, macOS, Linux all supported. No bash-only install paths.
3. **Self-bootstrapping:** an AI agent in any of the three hosts can read the repo and set itself up by following `AGENTS.md`.
4. **Single source of truth:** skill content lives in exactly one place. No host-specific copies of the same content.
5. **Senior-istqb-grade preserved:** the 11-scenario eval bar (11/11 senior-grade across 7 iteration rounds) still applies. The grader changes; the bar does not.
6. **No deterministic inference in code:** the host LLM does ALL classification, approach selection, risk identification, technique selection, specialty-tool fit. No keyword tables, no phrase matching, no hardcoded rule trees in Python. Tools provide knowledge; skills tell the LLM how to think; the LLM decides.

## Architecture

### Three layers, clean separation

1. **Skills (markdown).** The orchestration layer. Each skill is `skills/<name>/SKILL.md` with YAML frontmatter, an Iron Law block, a checklist, a graphviz process flow, a Red Flags table, and examples. All senior-QA discipline lives here.

2. **MCP tools (Python, atomic).** The deterministic primitive layer. Each tool does one small thing: return a knowledge catalogue as text, or read/write the test-data catalogue. No heavy sampling. No 1500-token structured outputs. Tool descriptions are 2-3 sentences each.

3. **Knowledge & data files.** Catalogues stored as markdown under `src/sumo_qa/knowledge/`; team standards / rules under their existing paths. Both skills and tools draw from this layer.

### Knowledge authority hierarchy

A global rule, declared in `using-sumo-qa` so every sub-skill inherits it:

1. **Loaded knowledge files** (`sumo_qa_load_*` tools). Authoritative. The host LLM picks from these without blending in training-data recall.
2. **Training data** — fallback only when the catalogue is silent. The LLM must explicitly flag the answer as "not in the loaded catalogue".
3. **Web search** — fallback when training is uncertain or the topic is post-training-cutoff. Citation required.
4. **"I don't know"** — the only acceptable answer when 1, 2 and 3 all fail. Hallucinating a technique, tool, principle, or specialty fit is forbidden.

This prevents the LLM from inventing canonical-sounding QA artefacts that aren't in the controlled catalogue.

### Internal reasoning vs. user-facing output

Skills tell the host LLM to *think* with citations (which words in the user's intent led to which inference, which file paths grounded which risk). The user-facing output omits citations to save tokens. Citations land only in `SUMO_QA_DEBUG_DIR` capture, where they are available for grading and debugging.

### End-to-end example

User intent: *"create a test plan for refactoring the pricing pipeline"*.

1. Host LLM auto-loads `using-sumo-qa` (Iron Law: decide approach first).
2. Routes to `qa-deciding-approach`. Calls `sumo_qa_load_classifications`, `sumo_qa_load_approaches`, `sumo_qa_load_rules`, `sumo_qa_load_standards` — all small text returns. Reasons internally: classification = `business_logic_change`, modifier = `refactor` (behaviour-preserving), approach = `coverage-first-then-refactor`. No question to user — intent already covers it.
3. Routes to `qa-creating-test-plan` (Iron Law: NO PLAN WITHOUT EXPLICIT ENTRY AND EXIT CRITERIA). Skill checklist: gather scope, basis, phases, criteria, residual risks. Each item gated by "is X already known from intent / files / catalogue?".
4. Scope unknown → asks the user one question. Gets paths.
5. Reads the actual files itself via the host's file tools. Identifies named risks.
6. Calls `sumo_qa_load_techniques()`, picks characterisation testing for the refactor risks. Calls `sumo_qa_load_specialty_tools()`, picks Pitest as the mutation tool fit.
7. Synthesises the plan inline, sectioned (scope / entry / phases / exit / residual risk). Conversational, not a JSON blob.

Total MCP-call tokens: well under 2000 across the whole flow. Compare to today's single `sumo_qa_create_test_plan` call: ~2000-3000 tokens of structured JSON output that breaks IntelliJ.

## Skill set

Ten skills total. Six rewrites of skills that already ship; four new (absorbing the deleted heavy-tool flows).

| # | Skill | Status | Iron Law |
|---|---|---|---|
| 1 | `using-sumo-qa` | rewrite | NO QA WORK WITHOUT FIRST DECIDING THE APPROACH. Entry router. Declares the global knowledge-authority hierarchy and the "no citations in output" rule. |
| 2 | `qa-deciding-approach` | rewrite | SHAPE FIRST. Decide single-change vs repo-wide vs no-tests before picking a per-change approach. Cite at least one ISTQB principle for the choice. |
| 3 | `qa-preparing-for-work` | new | NO TEST IDEA WITHOUT A NAMED RISK. Every suggested test ties to a specific risk anchored in the user's intent or paths the host has read. |
| 4 | `qa-creating-test-plan` | new | NO PLAN WITHOUT EXPLICIT ENTRY AND EXIT CRITERIA. A document missing either is a wishlist, not a plan. |
| 5 | `qa-implementing-with-tdd` | rewrite | RED PHASE FIRST. NO PRODUCTION CODE BEFORE A FAILING TEST. Mirrors upstream superpowers' TDD Iron Law. Absorbs the deleted scaffold-tests flow. |
| 6 | `qa-reviewing-before-merge` | rewrite | NEVER CLAIM SAFE-TO-MERGE WITHOUT FRESH VERIFICATION EVIDENCE. Mirrors upstream verification-before-completion. |
| 7 | `qa-strengthening-tests` | rewrite | PRODUCTION CODE STAYS UNCHANGED. Only test code moves. Equivalent mutants get suppressed in tool config, not "killed" by tautological tests. |
| 8 | `qa-finding-test-data` | rewrite | STALE IS A DEFECT. NEVER INVENT ENTRIES. Test data the catalogue can't validate is treated as broken. |
| 9 | `qa-answering-testing-question` | new | NO ANSWER WITHOUT A CITED PRINCIPLE OR TECHNIQUE. Generic "you should test that" responses fail the senior-QA bar. |
| 10 | `sumo-qa-strategising` | rewrite | WALK THE REPO FIRST. No repo-wide plan without using the host's file tools to map the actual codebase. |

### Skill structure (every skill)

Mirrors upstream `obra/superpowers` conventions verbatim:

```markdown
---
name: <skill-name>
description: <when to use this skill, written so the host LLM auto-triggers correctly>
---

# <Title>

## The Iron Law
NO X WITHOUT Y.

## When to Use
<one paragraph>

## Checklist
You MUST create a TodoWrite item per checklist item and complete in order:
1. <item>
2. <item>
...

## Process Flow
```dot
digraph <name> { ... }
```

## Red Flags
| Thought | Reality |
|---|---|
| <rationalisation>     | <reality check> |
| ...                   | ...             |

## Examples
<good vs bad, drawn from the QA domain>
```

Skill conformance tests (Section "Testing") enforce that every skill carries every section.

### Specialty + tool fit applies to any quality improvement

The `qa-creating-test-plan` checklist (and similar checklists in other skills) prompts the LLM to pick from `sumo_qa_load_specialty_tools()` whenever any tool would meaningfully improve quality — not only non-functional surfaces. Pitest on pure functions, Hypothesis for property-based tests of in-process logic, Pact for REST contracts, OWASP ZAP for HTTP DAST, axe-core for a11y, k6 for performance — all in the same catalogue. Empty list is acceptable when nothing genuinely applies.

## MCP tool surface

Eleven tools total. Seven knowledge providers (no inference, just file reads), four test-data tools (file IO that already exists).

### Knowledge providers

```python
sumo_qa_load_standards(classification: str | None = None) -> str
sumo_qa_load_rules(classification: str | None = None) -> str
sumo_qa_load_classifications() -> str
sumo_qa_load_approaches() -> str
sumo_qa_load_principles() -> str
sumo_qa_load_techniques() -> str
sumo_qa_load_specialty_tools() -> str
```

The two `classification`-parameter tools filter via metadata-based file selection: each pack/rule has frontmatter declaring which canonical classifications it applies to, and the tool returns the matching subset. The tool does not match keywords against content. The classification is supplied by the host LLM, not inferred in code.

The other five take no parameters and return the full catalogue. Each catalogue is small enough (50-500 lines) that the LLM can reasonably read all of it.

### Test-data tools (kept as today)

```python
sumo_qa_explain_test_data_requirements(...)
sumo_qa_find_test_data(...)
sumo_qa_validate_test_data(...)
sumo_qa_register_known_good_test_data(...)
```

These were already light. They stay.

### Tool description shape

```python
@mcp.tool(annotations=_read_only)
def sumo_qa_load_techniques() -> str:
    """Return the catalogue of test design techniques (black-box, white-box,
    experience-based, static) as plain text. The host LLM decides which
    technique fits a given risk; this tool only provides the catalogue."""
    return _read_text(KNOWLEDGE_DIR / "techniques.md")
```

No `Field(...)` schema with examples. No `outputSchema`. No structured Pydantic response. No `_build_*_sampling_prompt`. The tool is a 3-line function that reads a markdown file and returns it.

### Knowledge catalogue layout

```
src/sumo_qa/knowledge/
  classifications.md      # 10 canonical classifications + definitions
  approaches.md           # 8 canonical approaches + when each fits
  principles.md           # ISTQB Foundation + Advanced + ISO 25010
  techniques.md           # black-box / white-box / experience / static
  specialty_tools.md      # specialty + tool fit catalogue
  rules/                  # current rules dir (unchanged)
  standards/              # current standards dir (unchanged)
```

Editing the knowledge means editing markdown. No code changes to add a new technique, a new specialty tool, or a new approach.

### Token weight comparison

| Today | After |
|---|---|
| `sumo_qa_create_test_plan`: 150-line system prompt + 62-line builder + heavy schema + `max_tokens=1024` JSON output → ~2000-3000 tokens round-trip per call | `sumo_qa_load_techniques()`: 0 tokens system prompt, ~0 input tokens, ~500-1500 tokens of catalogue text returned. **No LLM call from the server side.** Tokens-per-call drops by ~70% on heavy flows. |

## Multi-host packaging

### Single source of truth

`skills/<name>/SKILL.md` is the canonical location. Every host reads from it; nothing duplicates the content.

### Three delivery channels

| Host | How skills reach it | Duplication |
|---|---|---|
| Claude Code | `install.py` symlinks `skills/` → `~/.claude/skills/sumo-qa`. Auto-loads on QA-shaped intents via the SKILL.md frontmatter description. | None (symlink). On Windows without developer mode, falls back to `shutil.copytree` and re-syncs on every `install.py` run. |
| IntelliJ AI Assistant | MCP server reads `skills/*/SKILL.md` at startup and registers each as an MCP prompt. AI Assistant surfaces prompts in its chat — user invokes by name. | None (server reads canonical files at request time). |
| VS Code + GitHub Copilot | Same MCP prompts as IntelliJ. Plus a tiny `.github/copilot-instructions.md` (~5 lines) that points Copilot at the prompts. | None (instructions file is a pointer, not a content copy). |

### Repo layout

```
qa-shift-left-mcp/
  skills/                            ← canonical SKILL.md files
    using-sumo-qa/SKILL.md
    qa-deciding-approach/SKILL.md
    qa-preparing-for-work/SKILL.md
    qa-creating-test-plan/SKILL.md
    qa-implementing-with-tdd/SKILL.md
    qa-reviewing-before-merge/SKILL.md
    qa-strengthening-tests/SKILL.md
    qa-finding-test-data/SKILL.md
    qa-answering-testing-question/SKILL.md
    sumo-qa-strategising/SKILL.md

  src/sumo_qa/
    knowledge/                       ← catalogues
    server.py                        ← also registers skills/ as MCP prompts
    ...

  AGENTS.md                          ← self-bootstrap entry for AI agents
  install.py                         ← cross-platform installer (Windows/macOS/Linux)
  install.sh                         ← thin wrapper invoking install.py for Unix users
  .github/copilot-instructions.md    ← ~5-line MCP-prompt pointer
```

### MCP prompt registration

```python
# src/sumo_qa/skill_prompts.py
SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

def register_skills_as_prompts(mcp):
    for skill_dir in SKILLS_DIR.iterdir():
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.is_file():
            continue
        name = skill_dir.name.replace("-", "_")
        frontmatter = _parse_frontmatter(skill_path)

        @mcp.prompt(name=name, description=frontmatter["description"])
        def _skill_prompt(_path=skill_path) -> str:
            return _path.read_text()
```

The prompt content IS the skill file content, read fresh on each request. Editing a skill propagates to every host on next invocation.

### Self-bootstrap via `AGENTS.md`

Any AI agent told *"set up sumo-qa from this repo"* reads `AGENTS.md` and follows the four-step bootstrap:

1. Detect host (Claude Code / IntelliJ / VS Code Copilot) by available tools and config paths.
2. Install the MCP server: `uv tool install --from . sumo-qa-mcp`.
3. Register the MCP and load skills (host-specific instructions, with per-OS path tables).
4. Verify by calling `sumo_qa_load_classifications()` and confirming a catalogue returns.

The agent runs the parts it can with its bash + edit + write tools, and explicitly hands off the rest to the user (e.g. *"Settings → Tools → AI Assistant → MCP → Add server `sumo-qa-mcp`"* on IntelliJ, where the agent can't programmatically edit Settings).

### Cross-platform install

`install.py` (Python, cross-platform) replaces `install.sh` (bash). Detects `platform.system()`, builds OS-appropriate paths via `pathlib.Path`, falls back to `shutil.copytree` on Windows boxes that don't permit symlinks. The MCP server itself is already cross-platform (Python + `pathlib`); no changes there. The MCP-prompts channel works identically on every OS — that's the failsafe when the symlink/copy story has friction.

`install.sh` stays as a thin bash wrapper that just invokes `install.py` for Unix users who expect a `./install.sh` entry.

## Migration plan

Five phases, each ending green. Old path stays callable until Phase 4 to keep verification grounded.

### Phase 1 — scaffolding (additive)

- Create `skills/`, `src/sumo_qa/knowledge/`, `AGENTS.md`, `install.py`, `.github/copilot-instructions.md`.
- Populate `knowledge/*.md` with content extracted from the existing `prompts.py`, `classification.py`, `specialty_routing.py`, `approach_decision.py` — content moves wholesale; QA discipline isn't rewritten yet.
- Add the 7 new `sumo_qa_load_*` MCP tools alongside the existing 10.
- Register `skills/` as MCP prompts (skills are still empty stubs at this stage; that is acceptable).
- Write tests for the new tools.
- Result: old path still works; new path is in place but unused.

### Phase 2 — write the 10 skills

- Each skill follows the upstream superpowers structure verbatim.
- Six existing skills are rewritten to replace thin "call this MCP tool" content with full Iron-Law-plus-checklist-plus-flowchart content.
- Four new skills are written from scratch.
- Result: skills load in Claude Code; MCP prompts are populated for IntelliJ + Copilot.

### Phase 3 — verify the new path on all three hosts

- Run the 11 ISTQB scenarios via the new skill-driven path in Claude Code (automated, AI-graded).
- Manual smoke-test on IntelliJ AI Assistant and VS Code Copilot (2-3 prompts each).
- New eval suite (Section "Testing") runs green: 11/11 senior-istqb-grade.
- Result: new path proven senior-grade across all three hosts. Phase 4 gated on this.

### Phase 4 — delete the heavy path

Single reviewable commit.

**Deleted outright:**

| File / Module | Reason |
|---|---|
| `src/sumo_qa/prompts.py` (`SENIOR_QA_SYSTEM_PROMPT`) | Discipline moves to skill markdown |
| `src/sumo_qa/approach_decision.py` | Deterministic decider — moves to skill |
| `src/sumo_qa/scaffolder.py` | Heavy scaffold tool deleted |
| `src/sumo_qa/render_preview.py`, `render_cli.py` | Rendered structured output that no longer exists |
| `src/sumo_qa/rubric.py` | 10-dim grader for structured output that no longer exists |
| `src/sumo_qa/specialty_routing.py` | Knowledge moves to `knowledge/specialty_tools.md` |
| `src/sumo_qa/classification.py` | Knowledge moves to `knowledge/classifications.md` |
| `src/sumo_qa/local_diff.py` | Review skill uses host file tools instead |
| Heavy Pydantic models in `src/sumo_qa/models.py` | Structured outputs gone |
| All `_build_*_sampling_prompt` builders in `src/sumo_qa/tools.py` | Heavy sampling gone |
| The 6 heavy tool registrations in `src/sumo_qa/server.py` | Replaced by skill-driven flows |
| Sampling-prompt code paths in `src/sumo_qa/llm.py` | Reduced to a tiny stub or deleted entirely |
| ~60% of `tests/` that target the above | Heavy-path tests obsolete |

**Rewritten in place (kept but heavily slimmed):**

| File / Module | Change |
|---|---|
| `src/sumo_qa/server.py` | Drop the 6 heavy tool registrations; keep the 7 new `sumo_qa_load_*` knowledge tools and 4 test-data tools added in Phase 1; ensure `skills/*/SKILL.md` is registered as MCP prompts |
| `src/sumo_qa/tools.py` | Drop everything except the test-data flows; becomes a tiny module |
| `src/sumo_qa/knowledge.py` | Simplify to "read a markdown file from `knowledge/` and return it" |
| `src/sumo_qa/standards.py`, `src/sumo_qa/rules.py` | Slim to file-IO + frontmatter parsing — no inference |
| `src/sumo_qa/models.py` | Drop heavy structured response models; keep only data models still used by test-data tools |

**Kept as-is (already correct):**

- `src/sumo_qa/debug_capture.py` — `SUMO_QA_DEBUG_DIR` capture still useful for grading
- `src/sumo_qa/tdm_catalogue.py`, `tdm_models.py`, `tdm_service.py`, `tdm_validation.py` — test-data tools were already light
- Test-data fixtures and existing TDM tests

Result: one clean commit excises the old architecture without leaving dead code.

### Phase 5 — docs & cross-platform install polish

- Rewrite `README.md` to point at `AGENTS.md`.
- Rewrite `docs/TOOLS.md`, `docs/SKILLS.md`, `docs/ARCHITECTURE.md`.
- Delete or merge `docs/WORKFLOW-LOOP.md`, `docs/QA_WORKFLOW.md`.
- Confirm `install.py` works on Windows / macOS / Linux end-to-end.
- Result: user-facing surface matches the new architecture.

### Risk mitigations

- Branch `feat/superpowers-restructure`, off main until all five phases are approved.
- Eval gating: every phase ends with the new eval suite green.
- Phase 4 (delete commit) gated on Phase 3's verification result.
- Old path callable until Phase 4 — if Phase 3 surfaces a senior-grade regression, we iterate on skills rather than deleting heavy tools.
- No silent deletions: every deleted file is named in the Phase 4 commit message with the reason.

## Testing & eval

### Five test layers

1. **Skill conformance (unit, fast).** Every `skills/*/SKILL.md` validates: frontmatter parses, Iron Law section present, Checklist section with at least 4 items, Process Flow with graphviz dot, Red Flags table, frontmatter `name` matches directory name, descriptions are unique.

2. **Knowledge-tool unit tests.** Each `sumo_qa_load_*` returns the expected catalogue (asserting key entries are present — e.g. `boundary value analysis` in `load_techniques`, `Pitest` in `load_specialty_tools`, ten classifications in `load_classifications`). Filtered loads (`load_standards` / `load_rules` with `classification`) honour the metadata filter. Team override env vars (`QA_STANDARDS_PATH`, `QA_RULES_PATH`) still work.

3. **MCP prompt registration (integration).** After server startup, `prompts/list` returns 10 prompts. Each `prompts/get` returns content equal to the corresponding `SKILL.md`. Prompt descriptions match skill frontmatter.

4. **End-to-end senior-QA grade — the 11-scenario eval, regraded.** Scenarios stay (`evaluation/repo_scenarios.py`). The grader changes from reading structured JSON output to AI-grading conversational transcripts via subagents — same 10 dimensions (principle citation, smallest useful test set, named techniques, risk-based focus, facts vs assumptions, no waived evidence, decisive routing, specialty awareness, domain specificity, no generic advice), checked semantically on prose. Bar: 11/11 senior-istqb-grade.

5. **Token-weight regression test.** `test_create_test_plan_flow_stays_under_token_budget`: full `qa-creating-test-plan` flow against a recorded scenario; assert total MCP-call tokens < 2000. `test_no_individual_mcp_call_exceeds_1500_tokens_returned`: no single call can break IntelliJ's SSE the way it did. This is the test that would have caught the original bug.

### Manual cross-host verification (Phase 3)

- Claude Code: automated 11/11 scenarios, all senior-grade.
- IntelliJ AI Assistant: the original "create a test plan" prompt that broke runs cleanly; no SSE crash; output is sectioned and senior-grade.
- VS Code Copilot: same prompt via MCP prompts works.

Each host: 2-3 sample prompts run by hand, results recorded in `docs/superpowers/iteration-runs/round-8-multi-host-verification.md`.

### CI

Skill conformance + unit tests + MCP-prompt integration + token-weight regression on every PR. Eval suite (11 scenarios, AI-graded) on every PR; PR cannot land without 11/11 senior-grade.

### What this preserves vs. changes

| Preserved | Changed |
|---|---|
| 11 ISTQB scenarios | Grader (JSON → prose) |
| 10-dimension senior-QA rubric | Where each dimension is checked (structured fields → prose) |
| AI-graded subagent grader pattern | Pointed at new output shape |
| 11/11 senior-grade bar | Same |
| `SUMO_QA_DEBUG_DIR` capture | Captures the host LLM's reasoning + tool calls instead of structured JSON |
| Token-weight measurement | Now an explicit regression gate, not an observation |

## Out of scope

- Cursor / Codex CLI / OpenCode / Gemini / Factory Droid plugin packaging (narrowed to 3 hosts).
- Generated `QA_WORKFLOW.md` from skills (dropped with the multi-host narrowing — `QA_WORKFLOW.md` itself is deleted in Phase 5).
- Replacing the AI-graded subagent eval with a fully deterministic grader.
- Extending the test-data catalogue or its tools (kept as today).
- Adding new specialty domains (mobile testing, AI/LLM eval) beyond what already exists in `specialty_routing.py` content moving into `specialty_tools.md`.

## Success criteria

- IntelliJ AI Assistant `create_test_plan` request runs cleanly without SSE crash.
- 11/11 senior-istqb-grade on the regraded eval suite.
- All five test layers green in CI.
- `install.py` succeeds on Windows / macOS / Linux end-to-end.
- AI agent can read `AGENTS.md` and self-bootstrap on each of the three hosts (with explicit handoff for steps the agent cannot perform).
- Total MCP-call tokens for the `qa-creating-test-plan` flow under 2000.
- No content duplicated across hosts; `skills/` is the only place skill content lives.
