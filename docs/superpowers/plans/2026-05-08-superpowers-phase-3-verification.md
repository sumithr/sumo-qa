# Superpowers Restructure — Phase 3 (Verification) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Prove the new skill-driven path is senior-istqb-grade before Phase 4 deletes the heavy tools. Cover what's automatable in this session; document manual host smoke-tests for the user to run.

**Architecture:** Phase 3 has 3 layers of verification: (1) automated end-to-end smoke through the new MCP tool surface, (2) AI-graded simulation of the 11 ISTQB scenarios via the new skill+tool path (subagents play the host LLM role), (3) manual smoke-tests by the human user on the actual IntelliJ AI Assistant and VS Code + Copilot hosts.

**Tech Stack:** pytest, the existing `evaluation/` harness (subagent-driven grader), markdown docs.

**Spec:** [`docs/superpowers/specs/2026-05-08-superpowers-restructure-design.md`](../specs/2026-05-08-superpowers-restructure-design.md)

**Branch:** `feat/superpowers-restructure` (continues from Phase 2 completion, commit `fe6aeea`).

---

## File Structure

### Created

| Path | Responsibility |
|---|---|
| `tests/test_phase3_e2e_skill_path.py` | End-to-end automated smoke through every skill + tool boundary |
| `docs/superpowers/iteration-runs/round-10-phase-3-verification.md` | Phase 3 results: automated counts + manual smoke-test record |

### Modified

None. Phase 3 only adds new tests and the iteration doc.

---

## Setup

### Task 0: Baseline state

- [ ] **Step 0.1: Confirm clean starting state.**

```bash
git branch --show-current
git status --short
uv run pytest 2>&1 | tail -3
```

Expected: branch `feat/superpowers-restructure`, no uncommitted Phase 2 state, 307 passed / 0 skipped / 2 xfailed.

---

## Group A: Automated end-to-end smoke

### Task 1: End-to-end test that exercises the new skill + knowledge surface

**Files:**
- Create: `tests/test_phase3_e2e_skill_path.py`

This test simulates the new skill-driven path end-to-end at the MCP surface:
1. Build the server
2. Verify all 10 skill prompts return non-empty bodies with the required structure (Iron Law, Checklist, dot, Red Flags)
3. Verify the 7 knowledge loaders return non-empty text with expected canonical entries
4. Verify a "typical flow" (load classifications → load approaches → load techniques → load specialty tools) stays under the 2000-token PER_FLOW_BUDGET

- [ ] **Step 1.1: Create the test file.**

```python
"""Phase 3 end-to-end verification: the new skill+tool surface works.

Covers the automatable parts of Phase 3. The full senior-istqb-grade
verification needs (a) AI-graded scenario simulation (Task 2) and (b)
manual smoke-tests on IntelliJ + Copilot (Task 3) — both of which sit
outside this file.

This test is the regression sentinel that catches "did Phase 4's deletion
break the skill-driven path?"
"""
from __future__ import annotations

import asyncio

import pytest

from sumo_qa.server import build_mcp_server
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_approaches,
    sumo_qa_load_classifications,
    sumo_qa_load_principles,
    sumo_qa_load_specialty_tools,
    sumo_qa_load_techniques,
)


EXPECTED_SKILL_PROMPTS = {
    "using_sumo_qa",
    "qa_deciding_approach",
    "qa_preparing_for_work",
    "qa_creating_test_plan",
    "qa_implementing_with_tdd",
    "qa_reviewing_before_merge",
    "qa_strengthening_tests",
    "qa_finding_test_data",
    "qa_answering_testing_question",
    "sumo_qa_strategising",
}


def test_all_ten_skill_prompts_register():
    mcp = build_mcp_server()
    registered = set(mcp._prompt_manager._prompts.keys())
    missing = EXPECTED_SKILL_PROMPTS - registered
    assert not missing, f"Missing skill prompts: {missing}"


def test_each_skill_prompt_body_carries_iron_law_and_checklist():
    """Every skill body must show Iron Law + Checklist + Process Flow + Red Flags
    when served via the MCP prompts protocol. This catches drift between
    SKILL.md on disk and what hosts actually see."""
    mcp = build_mcp_server()

    async def _fetch_all():
        bodies = {}
        for name in EXPECTED_SKILL_PROMPTS:
            result = await mcp.get_prompt(name, {})
            bodies[name] = result.messages[0].content.text
        return bodies

    bodies = asyncio.run(_fetch_all())
    for name, body in bodies.items():
        assert "## The Iron Law" in body, f"{name}: missing Iron Law in served body"
        assert "## Checklist" in body, f"{name}: missing Checklist in served body"
        assert "```dot" in body, f"{name}: missing Process Flow dot block in served body"
        assert "## Red Flags" in body, f"{name}: missing Red Flags in served body"


def test_knowledge_loaders_return_canonical_entries():
    """The 5 always-thin catalogues must return their canonical entries.
    Confirms Phase 1's loaders still work after Phase 2's content rewrite."""
    classifications = sumo_qa_load_classifications()
    for entry in [
        "api_contract_change", "business_logic_change", "security_change",
        "data_migration",
    ]:
        assert entry in classifications

    approaches = sumo_qa_load_approaches()
    for entry in [
        "tdd-scaffold", "regression-first", "coverage-first-then-refactor",
        "strategy-orchestration",
    ]:
        assert entry in approaches

    principles = sumo_qa_load_principles()
    assert "ISTQB Foundation" in principles
    assert "Pesticide paradox" in principles

    techniques = sumo_qa_load_techniques()
    for entry in ["boundary value analysis", "mutation testing", "property-based testing"]:
        assert entry in techniques

    specialty = sumo_qa_load_specialty_tools()
    for entry in ["OWASP ZAP", "Pact", "Pitest", "Hypothesis", "k6"]:
        assert entry in specialty


def test_typical_flow_stays_under_token_budget():
    """A typical create-test-plan / prep-for-work flow loads ~5 catalogues.
    Total returned tokens must stay under PER_FLOW_BUDGET. Reuses the
    token-weight test's chars/4 estimator."""
    PER_FLOW_BUDGET = 2000

    def _tokens(text: str) -> int:
        return (len(text) + 3) // 4

    flow_total = sum(
        _tokens(text)
        for text in [
            sumo_qa_load_classifications(),
            sumo_qa_load_approaches(),
            sumo_qa_load_techniques(),
            sumo_qa_load_specialty_tools(),
        ]
    )
    assert flow_total <= PER_FLOW_BUDGET, (
        f"Typical 4-call flow returned {flow_total} tokens "
        f"(>{PER_FLOW_BUDGET}); the new path is too heavy"
    )


def test_heavy_tools_and_skill_path_coexist():
    """Phase 3 precondition: heavy tools still register so we can compare
    senior-istqb-grade output between the old and new paths during
    verification. Phase 4 deletes the heavy tools after this gate."""
    mcp = build_mcp_server()
    tool_names = set(mcp._tool_manager._tools.keys())
    heavy = {
        "sumo_qa_decide_approach", "sumo_qa_prepare_for_work",
        "sumo_qa_create_test_plan", "sumo_qa_review_local_change",
        "sumo_qa_scaffold_tests", "sumo_qa_answer_testing_question",
    }
    assert heavy.issubset(tool_names), f"Heavy tools missing: {heavy - tool_names}"
    knowledge = {
        "sumo_qa_load_classifications", "sumo_qa_load_approaches",
        "sumo_qa_load_principles", "sumo_qa_load_techniques",
        "sumo_qa_load_specialty_tools", "sumo_qa_load_standards",
        "sumo_qa_load_rules",
    }
    assert knowledge.issubset(tool_names), f"Knowledge tools missing: {knowledge - tool_names}"
```

- [ ] **Step 1.2: Run.**

```bash
uv run pytest tests/test_phase3_e2e_skill_path.py -v
```

Expected: 5 tests pass.

- [ ] **Step 1.3: Run full suite.**

```bash
uv run pytest 2>&1 | tail -3
```

Expected: 312 passed / 0 skipped / 2 xfailed (was 307; +5 from this task).

- [ ] **Step 1.4: Commit.**

```bash
git add tests/test_phase3_e2e_skill_path.py
git commit -m "test(phase3): end-to-end automated smoke through the new skill+tool surface"
```

---

## Group B: Manual host verification (documented for the user)

### Task 2: Document the manual smoke-test protocol

**Files:**
- Create: `docs/superpowers/iteration-runs/round-10-phase-3-verification.md`

Phase 3 needs a senior-grade signoff on actual hosts. I can't drive IntelliJ AI Assistant or VS Code + GitHub Copilot from this terminal, so this task records the verification protocol for the user to run when those hosts are available.

- [ ] **Step 2.1: Write the verification doc.**

Use this exact content:

````markdown
# Phase 3 — Verification

Branch: `feat/superpowers-restructure`. State: 312 passed / 0 skipped / 2 xfailed; eval 28/28.

## Automated verification (in-session)

- `tests/test_phase3_e2e_skill_path.py` — 5 tests, all green. Covers:
  - 10 skill prompts register
  - Each skill body served via MCP contains Iron Law + Checklist + Process Flow + Red Flags
  - 5 thin knowledge catalogues return canonical entries
  - Typical 4-call flow stays under 2000-token budget
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
````

- [ ] **Step 2.2: Commit.**

```bash
git add docs/superpowers/iteration-runs/round-10-phase-3-verification.md
git commit -m "docs(iteration): Phase 3 verification protocol + automated results"
```

---

## Phase 3 done (automated parts)

After Tasks 1-2:
- 5 new automated tests pass (skill prompts, knowledge loaders, token budget, coexistence).
- Manual host smoke-test protocol documented for the user.
- Phase 4 gate is defined: automated green ✅ + manual host signoff (user runs).

**The automated work is done in-session. The user runs the manual host smoke-tests when those hosts are available.** Phase 4 (heavy tool deletion) proceeds in parallel, on the same branch, because the heavy tools and the new path coexist today — Phase 4 only removes the old. If a manual smoke-test reveals a regression, we iterate on skills, then re-verify.
