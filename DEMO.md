# 5-minute sumo-qa demo

Open any real repo. Run one of the prompts below. Watch the senior-QA workflow happen on actual code. No staged data, no scripted output — sumo-qa walks your repo and produces senior-grade QA on whatever it finds.

> [!IMPORTANT]
> **sumo-qa is an advisor, not an oracle.** Like all AI tools, it can be wrong — do not rely on its output 100%. Use your own judgment and your team's standards as the final word.

## Prerequisites

- **Python 3.10 or newer.** Check with `python --version` (or `py --version` on Windows).
- **An MCP-capable host:** Claude Code, Cursor, Codex, OpenCode, JetBrains AI Assistant or Junie, or VS Code + GitHub Copilot (Agent mode, with Claude Sonnet 4.5 or GPT-5 full).

## Step 1 — Install and wire it up (one line)

Pick the flag for your host and run a single command:

```bash
# Claude Code
pip install sumo-qa && sumo-qa-install --claude-code

# VS Code + GitHub Copilot
pip install sumo-qa && sumo-qa-install --vscode --workspace <path-to-your-repo>

# JetBrains AI Assistant
pip install sumo-qa && sumo-qa-install --jetbrains

# Every host detected on this machine
pip install sumo-qa && sumo-qa-install
```

`pip install sumo-qa` puts both binaries on PATH (`sumo-qa` the MCP server + `sumo-qa-install` the configurator). `sumo-qa-install` then does the host wiring: symlinks skills into `~/.claude/skills/`, writes `claude_desktop_config.json` or `.vscode/mcp.json` or prints JetBrains UI steps, depending on the flag. Works identically on Windows, macOS, and Linux — pip generates `.exe` wrappers on Windows so no `python3` invocation is involved.

Restart your host (or open a fresh chat) once it's done.

**Cursor, Codex, OpenCode**: the repo ships plugin manifests at `.cursor-plugin/plugin.json` and `.codex-plugin/plugin.json` for those host plugin systems. We haven't documented those install paths end-to-end yet — for now, follow that host's own plugin/MCP-server setup docs and point at either the plugin manifest or the absolute path to the `sumo-qa` binary printed by `sumo-qa-install --help`.

### Updating later

```bash
pip install --upgrade sumo-qa && sumo-qa-install
```

Then open a fresh chat. The host re-reads `~/.claude/skills/` (Claude Code) and the MCP tool list on the next session, picking up the upgraded skills and knowledge. If you installed sumo-qa as a Claude Code or Cursor plugin instead, the bundled SessionStart hook re-fires automatically.

---

## Step 2 — Run one of these prompts on your repo

Open your repo in the host you configured. Pick the prompt that matches the QA situation you actually have. Each is a one-liner.

---

### 1. Pre-merge safety check

```
Review my changes — is this safe to merge?
```

**What happens:** sumo-qa reads your `git diff` directly (no asking you what changed), classifies the change shape, names 3–7 risks anchored to file + line, asks ONE focused question if anything's ambiguous, **runs your full test suite right now** (refuses to call safe-to-merge from "CI was green earlier"), maps each named risk to a covering test, and delivers SAFE / NOT SAFE / NEEDS WORK with concrete evidence.

**Why it matters:** when it refuses to declare safe-to-merge because one of the risks it named has no covering test, and tells you the exact regression test to add — by file + function + assertion shape. Walk through [worked example 02](tests/scenarios/worked-examples/02-review-my-changes.md) to see the pattern.

---

### 2. Pre-coding QA plan — *for a fresh story*

```
Plan QA for this story before I start coding: <paste the ticket / one-liner>.
Files likely touch <main_module.py> and <related_module.py>.
```

**What happens:** sumo-qa reads the actual files, names 3–7 risks specific to *this* change (not "edge cases"), picks one design technique per risk from the loaded ISTQB-grounded catalogue, proposes the **smallest useful test set** tied to those risks, asks you to confirm any open assumptions. No code yet — this is the prep.

**Why it matters:** risks like *"currency conversion at the GBP→USD boundary rounds incorrectly when the rate is supplied with >6 decimal places"* — not *"input validation breaks"*.

---

### 3. Bug fix the right way — *regression-first TDD*

```
Fix this bug regression-first: <describe the bug + the likely file>.
```

**What happens:** sumo-qa walks the repo to find the production file and the sibling tests (it reads your test conventions; it doesn't ask "what framework do you use?"), picks the smallest failing test idea, confirms the one ambiguous detail with a single question, writes the failing test, runs it, **surfaces the red output verbatim** as proof, then hands off for you to make it green.

**Why it matters:** it refuses to write the test AND the production fix in the same turn. The red phase is non-negotiable — the proof that the test actually catches the bug must come before the fix. Most AI assistants skip this.

---

### 4. Repo-wide audit + QA strategy

```
Audit our test coverage and design a QA strategy.
```

**What happens:** sumo-qa walks your repo with its file tools (services, modules, test directories, CI config), produces a per-area provisional analysis with risks anchored to file paths, walks you through 6 confirmation gates one at a time (scope → risks → specialty tool fit → prioritisation → target pyramid → phased rollout → residual risks), then offers to write the result to `docs/qa-strategy.md`.

**Why it matters:** when it tells you a service that "feels well-tested" actually has 12 unit tests and zero mutation coverage on its highest-branching function — and proposes a 3-phase rollout to close the gap, with named gates at the end of each phase (not a calendar).

---

### 5. Multi-task QA rollout with agents

```
Plan QA for the <feature> across <module1>, <module2>, <module3> — then dispatch
subagents to execute it in parallel.
```

**What happens:** sumo-qa runs the full agent-execution chain:

1. **`sumo-qa-planning-qa-rollout`** — turns the work into a written plan at `docs/qa/plans/YYYY-MM-DD-<feature>.md` with 6–12 bite-sized tasks, each tagged with its approach and the named risk it covers.
2. **`sumo-qa-executing-qa-rollout`** — dispatches **one fresh subagent per task** in parallel waves; each output goes through **two-stage review** (spec-correctness then test-quality) before the task is marked done.
3. **`sumo-qa-finishing-qa-work`** — runs the full suite one last time, builds the risk-to-test coverage map, surfaces any uncovered risks honestly, writes a PR-ready summary to `docs/qa/runs/...`.

**Why it matters:** watching parallel subagents write tests against different risks at once, each getting reviewed twice (once for *"did it catch the right risk?"*, once for *"is the test well-shaped?"*) before counting as done. That's how senior QA scales — and it's the gap most AI assistants don't even attempt.

---

## Want to go deeper?

- **All 10 scenarios documented:** [`tests/scenarios/SCENARIOS.md`](tests/scenarios/SCENARIOS.md) — every QA situation sumo-qa handles, with expected interaction shape + anti-patterns.
- **Polished worked examples:** [`tests/scenarios/worked-examples/`](tests/scenarios/worked-examples/) — full multi-turn transcripts showing what each scenario looks like end-to-end.
- **The 13 skills:** [`skills/`](skills/) — each one Iron-Law-enforced, with HARD GATEs and one-section-per-turn confirmation discipline.
- **Architecture:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how the layers fit together.
