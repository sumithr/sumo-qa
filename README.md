# sumo-qa MCP

Turns the host LLM into a senior ISTQB-certified QA engineer. Works with any MCP-compliant host (Claude Code, Cursor, Copilot, Windsurf, IntelliJ AI Assistant). No external services, no Jira / Confluence / vector DB / KB dependency.

The output is structured and senior-QA-shaped: top risks tied to evidence paths, smallest useful test set, named ISTQB techniques, what NOT to test, explicit assumptions, decisive routing.

## Install

```bash
./install.sh
```

The script installs `uv`, isolates the MCP into its own environment, puts `sumo-qa-mcp` on your PATH, and prints the JSON to paste.

```json
{
  "mcpServers": {
    "sumo-qa": {
      "command": "sumo-qa-mcp"
    }
  }
}
```

| Host | Where to paste |
|---|---|
| Claude Code | `~/.config/claude/claude_desktop_config.json` (`mcpServers`) or `claude mcp add` |
| Cursor | Settings → Tools & Integrations → MCP → Add server |
| Windsurf | Settings → MCP Servers |
| IntelliJ AI Assistant | Settings → Tools → AI Assistant → Model Context Protocol |
| GitHub Copilot (VS Code) | Settings → Copilot → MCP Servers |

Manual `uv` / `pipx` / Docker paths: see [docs/INSTALL.md](docs/INSTALL.md).

## Use it

Type your question in chat. The host model picks the right tool from the registry.

| What you say | Tool the model picks |
|---|---|
| "What QA approach should I take for X" / "do I even need tests" | `sumo_qa_decide_approach` |
| "Review my changes" / "is this safe to merge?" | `sumo_qa_review_local_change` |
| "Plan QA for this story" / "what should I test for X?" | `sumo_qa_prepare_for_work` |
| "Create a test plan for X" / "give me entry/exit criteria for X" | `sumo_qa_create_test_plan` |
| "Scaffold the failing tests for X" | `sumo_qa_scaffold_tests` |
| "How do I test this?" | `sumo_qa_answer_testing_question` |
| "What test data do I need for X?" | `sumo_qa_explain_test_data_requirements` |
| "Find me a known-good SKU for X" | `sumo_qa_find_test_data` |
| "Is this test data still valid?" | `sumo_qa_validate_test_data` |
| "Save this as known-good test data" | `sumo_qa_register_known_good_test_data` |

`sumo_qa_decide_approach` is the entry point on any QA intent — it picks the shape of the work (TDD scaffold, regression-first, refactor-with-coverage, strengthen-tests, verify-existing, no-tests, spike, repo-wide strategy) before any deeper tool is called. See [docs/APPROACHES.md](docs/APPROACHES.md).

## Custom team standards

Override only if you want your team's own:

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

Full list of env vars (including `QA_DISABLE_HOST_SAMPLING`, `SUMO_QA_DEBUG_DIR`, `SUMO_QA_TARGET_REPO`): see [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Docs

- [docs/TOOLS.md](docs/TOOLS.md) — full reference for the 10 MCP tools and 9 prompts.
- [docs/SKILLS.md](docs/SKILLS.md) — the 7 Claude Code skills installed by `./install.sh`.
- [docs/APPROACHES.md](docs/APPROACHES.md) — the 8 canonical QA approaches and how they're picked.
- [docs/WORKFLOW-LOOP.md](docs/WORKFLOW-LOOP.md) — plan → scaffold → red → green → review per approach.
- [docs/ISTQB-GROUNDING.md](docs/ISTQB-GROUNDING.md) — the senior-QA persona, ISTQB principles, ISO 25010, technique mapping.
- [docs/SPECIALTY-ROUTING.md](docs/SPECIALTY-ROUTING.md) — when to pull in Cypress / k6 / ZAP / Pact / Appium / axe-core / Promptfoo, and how to pick the tool that fits the risk.
- [docs/TEST-DATA.md](docs/TEST-DATA.md) — the local known-good test-data catalogue, its shape, validation, and registration.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — file map and the two-layer (deterministic + host-LLM) design.
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — env vars.
- [docs/INSTALL.md](docs/INSTALL.md) — manual install paths (uv / pipx / Docker).
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — local dev, render preview, evaluation suite.
- [docs/QA_WORKFLOW.md](docs/QA_WORKFLOW.md) — host-agnostic discipline doc, drop-in for `.cursorrules` / `.windsurfrules` / `AGENTS.md`.
