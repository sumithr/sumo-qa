# Claude Code skills

`./install.sh` symlinks seven skill files into `~/.claude/skills/` so Claude
Code loads them automatically on QA-shaped intents. They follow the
[superpowers](https://github.com/anthropics/superpowers) conventions
exactly: YAML frontmatter (`name`, `description`), an Iron Law block, a
checklist, a Red Flags table, examples. The MCP tools in this server
are the *concrete actions* the skills prescribe.

| Skill | When Claude loads it | What it enforces |
|---|---|---|
| `using-sumo-qa` | Any QA-shaped intent (entry point) | Iron Law: NO QA WORK WITHOUT FIRST DECIDING THE APPROACH. Routes to a sub-skill. |
| `qa-deciding-approach` | First step on any QA intent | Calls `sumo_qa_decide_approach`, surfaces the approach, routes or stops. |
| `qa-implementing-with-tdd` | After decision is `tdd-scaffold` / `regression-first` / `coverage-first-then-refactor` | Plan → scaffold → red → user implements → green → review, with verify between every step. |
| `qa-reviewing-before-merge` | "review my changes" / "is this safe to merge" | Surfaces the verdict literally; refuses to claim safe-to-merge unless the tool says so. |
| `qa-strengthening-tests` | After decision is `strengthen-test-coverage` | Mutation-testing follow-up. Production code stays unchanged; one strengthening test per real mutant; equivalent mutants suppressed in tool config. |
| `qa-finding-test-data` | Test data discovery / validation / registration | Stale = defect; high confidence requires validation; never invent entries not in the catalogue. |
| `sumo-qa-strategising` | Repo-wide strategy / audit / pyramid / rollout asks | Walks the repo with the host's file tools first, then chains the MCP tools per priority area. |

The skills are Claude-Code-specific. For other MCP-compliant hosts
(IntelliJ AI Assistant, Cursor, Copilot, Windsurf), the same discipline
lives in the MCP **prompts** the server registers — see
[TOOLS.md](TOOLS.md) for the prompt list. Same flow, host-appropriate
delivery.

If you want the discipline enforced in any host that doesn't surface
MCP prompts (raw natural-language usage), drop
[QA_WORKFLOW.md](QA_WORKFLOW.md) into a project-level agent-rules file
(`.cursorrules`, `.windsurfrules`, `.github/copilot-instructions.md`,
`AGENTS.md`).
