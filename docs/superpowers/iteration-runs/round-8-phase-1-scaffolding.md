# Phase 1 — Scaffolding (complete)

Branch: `feat/superpowers-restructure`. 22 commits since spec commit `c7b1f38`.

## What landed

- 5 knowledge catalogues at `knowledge/`: classifications.md, approaches.md,
  principles.md, techniques.md, specialty_tools.md.
- 7 `sumo_qa_load_*` loader functions in `src/sumo_qa/knowledge_loaders.py`,
  TDD'd one commit at a time, with metadata-based filtering on
  `load_standards` and `load_rules`.
- 7 new MCP tools registered in `src/sumo_qa/server.py` alongside the
  existing 10 heavy tools (additive).
- 3 new skill stubs (frontmatter-only): qa-preparing-for-work,
  qa-creating-test-plan, qa-answering-testing-question.
- MCP prompt registration: every `skills/*/SKILL.md` now exposes as an MCP
  prompt at server startup. 10 skill prompts (legacy hardcoded prompts
  retained for Phase 4 deletion).
- Skill conformance test scaffolding (active checks: frontmatter, name match,
  description length, description uniqueness; structure checks skipped until
  Phase 2 lands full skill content).
- Token-weight regression test (3 active assertions + 2 xfails for
  acknowledged-heavy paths).
- `AGENTS.md`, `install.py`, `.github/copilot-instructions.md` for self-
  bootstrap and cross-platform install.

## Test gate

- `uv run pytest`: **304 passed, 40 skipped, 2 xfailed** in 5.58s.
  - 257 baseline + 47 new (10 loader tests + 1 server-tools test + 3 skill-prompt tests + 31 skill-conformance tests + 2 token-weight tests).
- `uv run sumo-qa-eval`: **28/28** — no eval regression.

## Backwards compatibility check

- The 10 heavy tools remain registered: `sumo_qa_decide_approach`,
  `sumo_qa_prepare_for_work`, `sumo_qa_create_test_plan`,
  `sumo_qa_review_local_change`, `sumo_qa_scaffold_tests`,
  `sumo_qa_answer_testing_question`, plus the 4 test-data tools.
- 9 legacy hardcoded `@mcp.prompt` decorators retained.
- `build_service()` still returns a working `QAShiftLeftService`; calling
  `qa_decide_approach('refactor the pricing pipeline', target_paths=[])`
  returns the expected structured response.
- The new path coexists with the old: 7 new tools, 17 total. 10 new
  prompts, 19 total.

## Phase 1 vs Phase 2/4 markers

- Skill conformance: 4 structure checks skipped until Phase 2 full skill
  content lands.
- Token-weight: unfiltered standards/rules are xfail (Phase 2 metadata
  gap); flow total is xfail (Phase 4 heavy-tool deletion).
- 3 new skills are frontmatter-only stubs; Phase 2 fills in Iron Law +
  Checklist + Process Flow + Red Flags + Examples.

## Known concerns flagged for Phase 2+

- Standards packs (`standards/packs/*.yml`) carry no
  `applies_to_classifications` metadata yet, so `load_standards` filtered
  by classification returns the empty string. Phase 2 should annotate
  packs OR change the filter semantic to "include unlabelled packs by
  default, exclude only those that explicitly declare other classifications".
- Existing 7 skills still point at the heavy tools; Phase 2 rewrites them
  to be self-contained checklists that lean on knowledge loaders + host
  file tools.

## Commit chain

```
3097ce1 feat(install): add cross-platform Python installer
58c17b3 docs: add Copilot instructions pointing at sumo-qa MCP prompts
ce1aa87 docs: add AGENTS.md self-bootstrap entry for AI agents
cadb98e test(token-weight): add regression test (Phase 4 un-xfails flow assertion)
5369d31 test(skills): add conformance test scaffolding (Phase 2 unskips structure checks)
ee01b48 feat(server): register skills/*/SKILL.md as MCP prompts at startup
c10418d skills: add qa-answering-testing-question stub (frontmatter only)
aa82af2 skills: add qa-creating-test-plan stub (frontmatter only)
41234fc skills: add qa-preparing-for-work stub (frontmatter only)
2529176 feat(server): register the 7 sumo_qa_load_* knowledge tools
151f612 feat(knowledge): add sumo_qa_load_rules loader
8e2a9f1 feat(knowledge): add sumo_qa_load_standards loader
9213cca feat(knowledge): add sumo_qa_load_specialty_tools loader
c356e76 feat(knowledge): add sumo_qa_load_techniques loader
5cb93c4 feat(knowledge): add sumo_qa_load_principles loader
36cd4b6 feat(knowledge): add sumo_qa_load_approaches loader
5c1c588 feat(knowledge): add sumo_qa_load_classifications loader
3e154e7 knowledge: add specialty_tools.md fit catalogue
613a44e knowledge: add techniques.md catalogue
823b82d knowledge: add principles.md with ISTQB + ISO 25010 grounding
a4800aa knowledge: add approaches.md with the 8 canonical QA approaches
eded095 knowledge: add classifications.md with the 10 canonical classifications
```

## Ready for Phase 2

Plan 2 (Phase 2 — Write the 10 skills) will be written after the user
reviews the Phase 1 result. The next-phase content:

- Rewrite the 7 existing skills into superpowers-style (Iron Law, checklist,
  flowchart, Red Flags, examples) drawing on knowledge from `sumo_qa_load_*`
  and host file tools.
- Fill in the 3 new skill stubs with full content.
- Un-skip the 4 conformance structure checks once skills satisfy them.
- Add classification metadata to standards packs so the `load_standards`
  filter returns useful results.
