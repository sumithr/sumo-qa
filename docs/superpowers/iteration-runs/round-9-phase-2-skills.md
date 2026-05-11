# Phase 2 — Skills (complete, with one task deferred)

Branch: `feat/superpowers-restructure`. 12 new commits since Phase 1 completion (`1a62012`).

## What landed

- **10 SKILL.md files rewritten** with full superpowers-style content (frontmatter + Iron Law + When-to-Use + Checklist + Process Flow graphviz + Red Flags table + Good/Bad examples):
  - 7 rewrites: `using-sumo-qa`, `qa-deciding-approach`, `qa-implementing-with-tdd`, `qa-reviewing-before-merge`, `qa-strengthening-tests`, `qa-finding-test-data`, `sumo-qa-strategising`.
  - 3 stubs filled in: `qa-preparing-for-work`, `qa-creating-test-plan`, `qa-answering-testing-question`.
- **4 conformance structure checks un-skipped** — all 10 skills pass all 4 (Iron Law present, Checklist ≥ 4 items, Process Flow dot block present, Red Flags table present).
- **Obsolete `tests/test_skills.py` deleted** — its assertions tested the old architecture (skills referencing specific heavy tool names, entry skill cross-referencing every sub-skill, `docs/QA_WORKFLOW.md` requirement). All structural concerns are now covered by `tests/test_skill_conformance.py`. Deletion was scheduled for Phase 4 per the spec; landed early because Phase 2 skill rewrites broke its legacy assertions.

## Test gate

- `uv run pytest`: **307 passed, 0 skipped, 2 xfailed** in 5.65s.
- `uv run sumo-qa-eval`: **28/28** — no eval regression.

## Iron Laws (one per skill)

| Skill | Iron Law |
|---|---|
| `using-sumo-qa` | NO QA WORK WITHOUT FIRST DECIDING THE APPROACH. |
| `qa-deciding-approach` | SHAPE FIRST. |
| `qa-preparing-for-work` | NO TEST IDEA WITHOUT A NAMED RISK. |
| `qa-creating-test-plan` | NO PLAN WITHOUT EXPLICIT ENTRY AND EXIT CRITERIA. |
| `qa-implementing-with-tdd` | RED PHASE FIRST. NO PRODUCTION CODE BEFORE A FAILING TEST. |
| `qa-reviewing-before-merge` | NEVER CLAIM SAFE-TO-MERGE WITHOUT FRESH VERIFICATION EVIDENCE. |
| `qa-strengthening-tests` | PRODUCTION CODE STAYS UNCHANGED. |
| `qa-finding-test-data` | STALE IS A DEFECT. NEVER INVENT ENTRIES NOT IN THE CATALOGUE. |
| `qa-answering-testing-question` | NO ANSWER WITHOUT A CITED PRINCIPLE OR TECHNIQUE. |
| `sumo-qa-strategising` | WALK THE REPO FIRST. |

## Deferred from Phase 2 — Task 12 (standards pack annotation)

Phase 2 Task 12 (annotating `standards/packs/*.yml` with `applies_to_classifications` metadata so `sumo_qa_load_standards(classification=...)` returns useful results) was attempted and BLOCKED by two real architectural issues:

1. **Pydantic schema rejects unknown fields.** `_RawPack` in `src/sumo_qa/standards.py` uses `model_config = ConfigDict(extra="forbid")`. Adding `applies_to_classifications:` to either pack triggers `ValidationError`, cascading into ~60 unrelated tests via `QAShiftLeftService.from_standards_path`. Allowing the new field requires editing `_RawPack`.

2. **Filtered pack size exceeds per-call token budget.** Even with schema relaxation, `sumo_qa_load_standards(classification='business_logic_change')` would return ~9257 chars (~2315 tokens), exceeding the `PER_CALL_BUDGET=1500` enforced by `test_filtered_standards_and_rules_stay_under_per_call_budget`. Both packs are large general-purpose documents; per-classification filtering returns them whole.

These are real Phase 3 issues, not Phase 2 implementation defects. Resolution path (for a follow-up plan):

- Relax `_RawPack` schema to allow `applies_to_classifications: list[str] | None = None`.
- Either (a) split packs into per-classification subsets, (b) trim packs so the filtered output fits the budget, OR (c) change the filter semantic to return only the classification-relevant subset of each pack.
- Then land the metadata.

Today's working state: filter still returns empty string for any classification (Phase 1 behaviour preserved). The skills compensate by reading standards via the unfiltered path (whose unfiltered call is also xfail-budgeted in the token-weight test — Phase 4 deletes the heavy-path users of that anyway).

## Commit chain

```
8099ce9 test(skills): un-skip conformance structure checks now that Phase 2 skills land
d772e05 skills(sumo-qa-strategising): full superpowers-style content
7628438 skills(qa-answering-testing-question): full superpowers-style content
61a14a9 skills(qa-finding-test-data): full superpowers-style content
b92409a skills(qa-strengthening-tests): full superpowers-style content
4807743 skills(qa-reviewing-before-merge): full superpowers-style content
dbac63c skills(qa-implementing-with-tdd): full superpowers-style content
0fa7326 skills(qa-creating-test-plan): full superpowers-style content
1e535e4 test: delete obsolete test_skills.py (superseded by test_skill_conformance.py)
cb5c72b skills(qa-preparing-for-work): full superpowers-style content
d8c1d15 skills(qa-deciding-approach): full superpowers-style content
f140b71 skills(using-sumo-qa): full superpowers-style content
920fee2 docs(plan): superpowers restructure phase 2 — skills implementation plan
```

## Ready for Phase 3

Plan 3 (Phase 3 — cross-host verification) is written after Phase 2 is reviewed:

- Run the 11 ISTQB scenarios via the new skill-driven path in Claude Code (automated, AI-graded).
- Manual smoke-test on IntelliJ AI Assistant and VS Code Copilot (2-3 prompts each, including the original `create_test_plan` that broke).
- Confirm 11/11 senior-istqb-grade preserved through the new path.
- Document results.

Phase 4 (delete heavy tools + supporting Python) happens after Phase 3 verifies the new path is senior-grade. Phase 5 (docs + cross-platform install polish) follows. The Task 12 follow-up (standards pack annotation + schema relaxation + pack splitting) can land between Phase 3 and Phase 4, or alongside Phase 5 — it's independent of the heavy-tool deletion.
