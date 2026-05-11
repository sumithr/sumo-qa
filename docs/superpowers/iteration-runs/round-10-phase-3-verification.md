# Phase 3 — Verification

Branch: `feat/superpowers-restructure`. State: 312 passed / 0 skipped / 2 xfailed; eval 28/28.

## Automated verification (in-session)

- `tests/test_phase3_e2e_skill_path.py` — 5 tests, all green. Covers:
  - 10 skill prompts register
  - Each skill body served via MCP contains Iron Law + Checklist + Process Flow + Red Flags
  - 5 thin knowledge catalogues return canonical entries
  - Typical 4-call flow stays under 2500-token budget (actual: ~2255 tokens; was ~3000+ in the old heavy-path single call)
  - Heavy tools + knowledge tools coexist (Phase 4 deletion gate)
- `tests/test_skill_conformance.py` — 71 tests, all green
- `tests/test_knowledge_loaders.py` — 10 tests, all green
- `tests/test_skill_prompts.py` — 3 tests, all green
- `tests/test_token_weight_regression.py` — 2 passed + 2 xfail (acknowledged-heavy paths)
- `uv run sumo-qa-eval` — 28/28 (legacy eval against heavy tools still green)

## Manual host smoke-tests (run by the user when those hosts are available)

These verify the new skill-driven path produces senior-istqb-grade output on each
target host. The user runs them; results are recorded here.

### Claude Code

After symlinking `skills/` into `~/.claude/skills/sumo-qa` (via `install.py` or manual `ln`), restart Claude Code so it picks up the skills.

Run each prompt as a fresh chat. The expected behaviour is the skill auto-loads,
the host LLM follows its checklist, and the output cites principles/techniques
from the loaded catalogue (not invented).

| # | Prompt | Skill that should auto-load | Pass criteria |
|---|---|---|---|
| 1 | "what QA approach should I take for refactoring the pricing pipeline?" | qa-deciding-approach | Routes to `coverage-first-then-refactor`; cites ISTQB principle 4 (defects cluster) |
| 2 | "create a test plan for the new tax-calculation feature" | qa-creating-test-plan | Output has explicit entry/exit criteria; ≥3 named risks; techniques from catalogue |
| 3 | "review my changes" (in a repo with uncommitted edits) | qa-reviewing-before-merge | Runs tests; surfaces verdict with fresh evidence; doesn't claim safe-to-merge without it |
| 4 | "Pitest shows 5 surviving mutants — kill them" | qa-strengthening-tests | Reads prod READ-ONLY; suggests strengthening tests OR config suppression per mutant |
| 5 | "design our QA strategy" | sumo-qa-strategising | Walks the repo with file tools; risk-prioritised; phased rollout |

### IntelliJ AI Assistant

Same prompts as above, but invoke each skill by MCP prompt name (e.g. `qa_creating_test_plan`).

| # | Prompt name | Expected behaviour |
|---|---|---|
| 1 | qa_deciding_approach | Returns the skill body; AI Assistant follows the checklist |
| 2 | qa_creating_test_plan | The original failing scenario — must NOT produce ContinuousSSEException |
| 3 | qa_reviewing_before_merge | Verdict with evidence |

The `qa_creating_test_plan` invocation is the primary regression check — this is the prompt that triggered the original IntelliJ SSE failure that started this restructure. If it returns cleanly (no SSE crash), the architectural change has solved the trigger problem.

### VS Code + GitHub Copilot

Same prompts. Copilot reads `.github/copilot-instructions.md` and surfaces MCP prompts.

| # | Prompt | Pass criteria |
|---|---|---|
| 1 | "review my changes" | Copilot invokes qa_reviewing_before_merge prompt; runs tests; surfaces verdict |
| 2 | "create a test plan for X" | qa_creating_test_plan prompt fetched; no SSE / streaming issues |
| 3 | "what test data do I need for X" | qa_finding_test_data prompt routes correctly |

## Senior-istqb-grade rubric (per scenario)

Each manual smoke-test scores against the 10-dimension rubric. PASS if all 10 are met:

1. **principle_citation** — Names an ISTQB principle by number/name (from `principles.md`).
2. **smallest_useful_test_set** — Proposes 3-7 tests, each tied to a named risk.
3. **named_techniques** — Uses techniques from `techniques.md` (not invented).
4. **risk_based_focus** — Effort concentrated on named risks, not blanket coverage.
5. **facts_vs_assumptions** — Distinguishes "I know X because path/word Y" from "I'm assuming Z".
6. **no_waived_evidence** — Doesn't bless safe-to-merge without fresh test runs.
7. **decisive_routing** — Picks ONE canonical approach and commits.
8. **specialty_awareness** — Names a tool from `specialty_tools.md` when relevant; empty list when not.
9. **domain_specificity** — Cites actual file paths / domain terms; no "the service" / "the system" generics.
10. **no_generic_advice** — No "add edge case tests" / "consider security" without naming the case or the tool.

## Result recording template

After running the manual smoke-tests, record results here:

### Claude Code results

| # | Prompt | Pass / Fail | Senior-grade rubric (10/10) | Notes |
|---|---|---|---|---|
| 1 | what QA approach... | ___ | ___/10 | ___ |
| 2 | create a test plan... | ___ | ___/10 | ___ |
| 3 | review my changes | ___ | ___/10 | ___ |
| 4 | Pitest survivors | ___ | ___/10 | ___ |
| 5 | design our QA strategy | ___ | ___/10 | ___ |

### IntelliJ AI Assistant results

| # | Prompt | Pass / Fail | SSE clean? | Notes |
|---|---|---|---|---|
| 1 | qa_deciding_approach | ___ | ___ | ___ |
| 2 | qa_creating_test_plan | ___ | **must be yes** | ___ |
| 3 | qa_reviewing_before_merge | ___ | ___ | ___ |

### VS Code + Copilot results

| # | Prompt | Pass / Fail | Notes |
|---|---|---|---|
| 1 | review my changes | ___ | ___ |
| 2 | create a test plan for X | ___ | ___ |
| 3 | what test data... | ___ | ___ |

## Phase 4 gate

Phase 4 (delete the 6 heavy MCP tools + supporting Python) is gated on:
- All Phase 3 automated tests green (✅ achieved in-session)
- 5/5 Claude Code manual smoke-tests senior-grade (user runs)
- 3/3 IntelliJ smoke-tests pass, especially `qa_creating_test_plan` without SSE crash (user runs)
- 3/3 VS Code Copilot smoke-tests pass (user runs)

If any host falls short, the gap blocks Phase 4 until addressed. Possible
follow-ups: tighten skill content, expand the catalogue, fix host-specific
issues.

## Open: Task 12 from Phase 2 (standards pack annotation)

Independent of Phase 3 verification. Still deferred — schema relaxation + pack
splitting needed. Doesn't block Phase 4 because the heavy-tool deletion is
orthogonal to whether the standards filter returns data.
