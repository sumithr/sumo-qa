# Cross-host validation — final state

Live validation of the post-restructure architecture across four host configurations. Captures the host-specific quirks each one surfaced so future-us doesn't re-walk these paths.

## Validated hosts

| Host | Model | Result | Setup |
|---|---|---|---|
| Claude Code | Claude (default) | Senior-grade, interactive | `install.py --claude-code` — per-skill symlinks at top level of `~/.claude/skills/` |
| IntelliJ AI Assistant | GPT-5.5 | Senior-grade content, single-shot (no multi-turn walkthrough) | One-time Settings UI add — external XML write doesn't register the runtime coroutine reliably on IDEA 2026.1 |
| IntelliJ + Junie | Claude Opus 4.7 | Textbook senior-istqb-grade, full Test 1 rubric hit | `~/.junie/mcp/sumo-qa.json` with `mcpServers` schema |
| VS Code + Copilot Chat (Agent mode) | Claude Sonnet 4.5 | Senior-grade, calls MCP tools by description | `<repo>/.vscode/mcp.json` with `servers` schema (VS Code-native) |

## Host-specific findings — added to install.py and docs

### Claude Code

- Native skill loader reads `~/.claude/skills/<name>/SKILL.md` at top level. **Does NOT recurse** into wrapper directories. Earlier installs used `~/.claude/skills/sumo-qa/qa-*/SKILL.md` (wrapper) — invisible to Claude Code; only 7 stale top-level copies surfaced (residue from before the wrapper).
- Fix: per-skill symlinks at top level. install.py also cleans up the legacy wrapper and any stale top-level copies whose content matches our repo skills (so user-customised skills are preserved).
- MCP tools are NOT slash-invocable in Claude Code's UI. Atomic tools (`sumo_qa_load_*`, `sumo_qa_*_test_data`) must be called via natural language. The 10 skills appear as `/qa-*` (hyphens) from the native skill files.

### JetBrains AI Assistant

- The MCP plugin's config (`~/Library/Application Support/JetBrains/<ide>/options/llm.mcpServers.xml`) is technically writable externally — but on IDEA 2026.1 it doesn't reliably register the runtime registration coroutine. External writes show as disabled entries with `LazyStandaloneCoroutine was cancelled` errors. 3 attempts at making auto-write work all failed.
- Architectural pivot (per systematic-debugging Phase 4.5): stop auto-writing the XML. install.py prints the exact Settings UI fields with the absolute binary path. User clicks Apply once; entry persists across restarts.
- Slash menu surfaces ALL MCP entries (10 skill tools + 11 atomic = 21 slash commands).

### JetBrains Junie

- Junie reads MCP configs from JSON files in `~/.junie/mcp/` (global) or `<repo>/.junie/mcp/` (per-project).
- Schema is the standard Claude Desktop / Code one: `{ "mcpServers": { "sumo-qa": { "command": "<abs path>" } } }`.
- More agentic than IntelliJ AI Assistant. Picks tools by description in natural-language chat; doesn't auto-chain `next_action.skill` (waits for user to confirm before proceeding to the next skill).
- Best fidelity in Test 1 — full senior-istqb-grade output with all 10 rubric dimensions hit.

### VS Code + GitHub Copilot

- Schema is DIFFERENT from Claude Desktop / Junie. VS Code reads `.vscode/mcp.json` with the `"servers"` key (NOT `"mcpServers"`), and each server needs `"type": "stdio"`:
  ```json
  { "servers": { "sumo-qa": { "type": "stdio", "command": "...", "args": [] } } }
  ```
- Earlier install.py wrote the wrong schema. VS Code parsed the file, registered zero servers, model said "I don't have access to those tools".
- Requires **Agent mode** in Copilot Chat (not Ask, not Edit). Tools require Agent mode.
- Requires a **capable model** — Claude Sonnet 4.5 or GPT-5 full. Mini variants don't reliably call MCP tools (they read the skill files via filesystem and meta-answer instead of invoking the tool).
- Needs **Developer: Reload Window** after writing `.vscode/mcp.json` — VS Code caches the MCP server list at startup.

## install.py — final shape

```bash
python3 install.py                                    # all detected hosts
python3 install.py --claude-code                      # one host at a time
python3 install.py --vscode --workspace /path/to/repo
python3 install.py --jetbrains                        # prints Settings UI steps
python3 install.py --vscode --skip-mcp-install        # skip uv reinstall on re-run
```

- Refuses to write `$HOME/.vscode/mcp.json` (not a workspace; VS Code ignores it).
- Cleans up the legacy `~/.claude/skills/sumo-qa/` wrapper and stale top-level copies.
- Writes VS Code-native schema for `.vscode/mcp.json`; strips any legacy `mcpServers` key.
- Prints (doesn't try to write) JetBrains XML — JetBrains needs UI registration.
- Verifies MCP responds to JSON-RPC `initialize` at the end.

## Spec coverage

The Phase 3 verification protocol in [`round-10-phase-3-verification.md`](round-10-phase-3-verification.md) is satisfied:

- Claude Code automated 11/11 scenarios: still green (eval suite, conformance tests)
- IntelliJ smoke-test: ✅ (Junie / Test 1 produced textbook senior-grade output; AI Assistant produced senior-grade content with less interactivity)
- VS Code smoke-test: ✅ (Copilot Chat Agent mode + Claude Sonnet 4.5 returned correct classifications)
- Original IntelliJ `create_test_plan` SSE failure: cannot reproduce — no heavy single-shot tool remains in the new architecture for it to fire against

## What's settled

The architecture is host-agnostic at the protocol level. Surface differences (slash menu naming, schema specifics, auto-chaining vs single-shot, MCP-tools-as-slash vs natural-language-only) are baked into each host and can't be hidden without writing host-specific plugins. install.py and the per-host docs name those differences clearly.

The five-phase superpowers restructure is complete and validated. The branch `feat/superpowers-restructure` is ready for merge review.
