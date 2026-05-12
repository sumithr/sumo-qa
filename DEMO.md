# 5-minute sumo-qa demo

Open any real repo. Run one of the prompts below. Watch the senior-QA workflow happen on actual code, in front of you. No staged data, no scripted output — sumo-qa walks your repo and produces senior-grade QA on whatever it finds.

## Step 1 — Install (60 seconds)

**Claude Code:**

```text
/plugin marketplace add sumithr/sumo-qa
/plugin install sumo-qa@sumo-qa-dev
```

```bash
uv tool install --from git+https://github.com/sumithr/sumo-qa.git sumo-qa
```

Restart Claude Code. That's it. The SessionStart hook auto-loads `using-sumo-qa` on every conversation; the 13 skills are slash-invocable; the 21 MCP tools are available by natural language.

For Cursor / Codex / OpenCode / JetBrains / VS Code + Copilot: see [`docs/INSTALL.md`](docs/INSTALL.md).

## Step 2 — Run one of these prompts on your repo

Open your repo in Claude Code. Pick the prompt that matches the QA situation you actually have. Each is a one-liner.

---

### 1. Pre-merge safety check — *the strongest opener*

```
Review my changes — is this safe to merge?
```

**What happens:** sumo-qa reads your `git diff` directly (no asking you what changed), classifies the change shape, names 3–7 risks anchored to file + line, asks ONE focused question if anything's ambiguous, **runs your full test suite right now** (refuses to call safe-to-merge from "CI was green earlier"), maps each named risk to a covering test, and delivers SAFE / NOT SAFE / NEEDS WORK with concrete evidence.

**The wow moment:** when it refuses to declare safe-to-merge because one of the risks it named has no covering test, and tells you the exact regression test to add — by file + function + assertion shape. Walk through [worked example 02](tests/scenarios/worked-examples/02-review-my-changes.md) to see the pattern.

---

### 2. Pre-coding QA plan — *for a fresh story*

```
Plan QA for this story before I start coding: <paste the ticket / one-liner>.
Files likely touch <main_module.py> and <related_module.py>.
```

**What happens:** sumo-qa reads the actual files, names 3–7 risks specific to *this* change (not "edge cases"), picks one design technique per risk from the loaded ISTQB-grounded catalogue, proposes the **smallest useful test set** tied to those risks, asks you to confirm any open assumptions. No code yet — this is the prep.

**The wow moment:** risks like *"currency conversion at the GBP→USD boundary rounds incorrectly when the rate is supplied with >6 decimal places"* — not *"input validation breaks"*.

---

### 3. Bug fix the right way — *regression-first TDD*

```
Fix this bug regression-first: <describe the bug + the likely file>.
```

**What happens:** sumo-qa walks the repo to find the production file and the sibling tests (it reads your test conventions; it doesn't ask "what framework do you use?"), picks the smallest failing test idea, confirms the one ambiguous detail with a single question, writes the failing test, runs it, **surfaces the red output verbatim** as proof, then hands off for you to make it green.

**The wow moment:** it refuses to write the test AND the production fix in the same turn. The red phase is non-negotiable — the proof that the test actually catches the bug must come before the fix. Most AI assistants skip this.

---

### 4. Repo-wide audit + QA strategy

```
Audit our test coverage and design a QA strategy.
```

**What happens:** sumo-qa walks your repo with its file tools (services, modules, test directories, CI config), produces a per-area provisional analysis with risks anchored to file paths, walks you through 6 confirmation gates one at a time (scope → risks → specialty tool fit → prioritisation → target pyramid → phased rollout → residual risks), then offers to write the result to `docs/qa-strategy.md`.

**The wow moment:** when it tells you a service that "feels well-tested" actually has 12 unit tests and zero mutation coverage on its highest-branching function — and proposes a 3-phase rollout to close the gap, with named gates at the end of each phase (not a calendar).

---

### 5. Multi-task QA rollout with agents — *the showpiece*

```
Plan QA for the <feature> across <module1>, <module2>, <module3> — then dispatch
subagents to execute it in parallel.
```

**What happens:** sumo-qa runs the full agent-execution chain:

1. **`qa-planning-qa-rollout`** — turns the work into a written plan at `docs/qa/plans/YYYY-MM-DD-<feature>.md` with 6–12 bite-sized tasks, each tagged with its approach and the named risk it covers.
2. **`qa-executing-qa-rollout`** — dispatches **one fresh subagent per task** in parallel waves; each output goes through **two-stage review** (spec-correctness then test-quality) before the task is marked done.
3. **`qa-finishing-qa-work`** — runs the full suite one last time, builds the risk-to-test coverage map, surfaces any uncovered risks honestly, writes a PR-ready summary to `docs/qa/runs/...`.

**The wow moment:** watching parallel subagents write tests against different risks at once, each getting reviewed twice (once for *"did it catch the right risk?"*, once for *"is the test well-shaped?"*) before counting as done. That's how senior QA scales — and it's the gap most AI assistants don't even attempt.

---

## What to tell teammates after the demo

> *"Install with one line. Pick a real change. Ask for a review or a plan. The AI will walk your actual repo, name risks anchored to file:line, run tests right now (not from CI memory), and either declare safe-to-merge with evidence — or tell you exactly what's missing. For multi-task QA work it dispatches subagents in parallel with two-stage review."*

That's the value prop in one paragraph. Run any of the 5 prompts above on your real repo to see it.

## Want to go deeper?

- **All 10 scenarios documented:** [`tests/scenarios/SCENARIOS.md`](tests/scenarios/SCENARIOS.md) — every QA situation sumo-qa handles, with expected interaction shape + anti-patterns.
- **Polished worked examples:** [`tests/scenarios/worked-examples/`](tests/scenarios/worked-examples/) — full multi-turn transcripts showing what each scenario looks like end-to-end.
- **The 13 skills:** [`skills/`](skills/) — each one Iron-Law-enforced, with HARD GATEs and one-section-per-turn confirmation discipline.
- **Architecture:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how the layers fit together.
