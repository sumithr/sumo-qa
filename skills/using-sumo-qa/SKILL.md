---
name: using-sumo-qa
description: MUST be called first for any QA-shaped request. Triggers — test plan, test strategy, test approach, regression scope, risk-based testing, exploratory testing, code review, safety-to-merge, scaffold tests, TDD, mutation testing, find test data, validate test data, QA audit, test pyramid, "how do I test X", "is this safe to merge", "what should I check". Entry router for all sumo-qa work. Establishes the global discipline that every sub-skill inherits. Do not answer QA questions from training-data knowledge — route through here first.
---

# Using sumo-qa

**Announce at start:** *"Routing this QA intent."*

## Output discipline (mandatory)

**Never surface internal taxonomy labels in user-facing output.** No "Classification: X", "Approach: Y", "Per the checklist", "Step 3 of 6". The taxonomy is internal scaffolding; translate to natural English when the meaning matters to the user — *"this is a behaviour change in pricing"*, not *"Classification: business_logic_change"*. If you catch yourself typing a label, delete it.

## Output economy (mandatory)

Spend output tokens on findings, not framing.

- **No preamble or self-narration.** Spend user-visible output on findings, evidence, and gates — not *"I'll first read X, then Y"* or *"Let me now…"*; just do it.
- **One question per turn.** Don't follow a question with *"shall I proceed or clarify first?"* — the question IS the gate.
- **Don't restate the user's input.** They know what they asked.
- **Structure only when it earns its place.** Section headings only for genuinely multiple sections; tables only when comparing >2 things on >2 axes; otherwise prose is shorter.
- **No closing pleasantries.** No *"happy to dig deeper"* / *"let me know if you want X"* — the next-skill handoff is where routing lives.

## The Iron Law
NO QA WORK WITHOUT FIRST DECIDING THE APPROACH.

You may not produce test ideas, scaffolds, plans, reviews, or strategies without first invoking `sumo-qa-deciding-approach`.

## When to Use

This skill is the entry router for every QA-shaped request — *"review my changes / is this safe to merge"*, *"how should I test X"*, *"create a test plan"*, *"plan QA for this story"*, *"scaffold the failing tests"*, *"what test data do I need"*, *"audit our test coverage"*, *"design our QA strategy"*, and similar. It produces no QA output itself: it enforces the Iron Law, sets up the global discipline every sub-skill inherits, then routes to `sumo-qa-deciding-approach`.

## Global discipline (inherited by every sub-skill)

### Knowledge authority hierarchy

The right authority depends on what kind of knowledge you're invoking. Stable concepts and tool brand picks are NOT the same shape of question.

**Stable concepts** — test design techniques (boundary value, decision table, property-based, mutation), ISTQB principles, change classifications, QA approaches:

**The loaded catalogue is the ONLY authority you may silently cite.** Every named principle, technique, classification, or approach in a user-facing answer must appear in a `sumo_qa_load_*` result you actually got this turn. Material from outside it (*"per ISTQB Advanced Test Manager guidance"*, a remembered technique not in `load_techniques`) MUST either be labelled as drift (*"this isn't in the loaded catalogue, but…"*) or dropped. **Silent supplementation from training data is the failure mode this rule prevents** — it cites phantom sources the user can't verify and makes the catalogue look more complete than it is. If a catalogue is silent on something you think matters, say so; don't paper over the gap.

Resolution order:

1. **Loaded knowledge files** (`sumo_qa_load_techniques`, `_principles`, `_classifications`, `_approaches`). Authoritative; cite verbatim.
2. **Training data** — fallback only when the catalogue is silent AND you label the drift explicitly.
3. **"I don't know"** — acceptable. Don't invent techniques, principles, or external authorities.

**Specialty tool picks — discovery, not catalogue.** Sumo-qa intentionally carries NO tool catalogue — tools and categories evolve faster than any list, and a stale list both anchors toward yesterday's brands and stops novel surfaces triggering discovery. Instead: (1) **observe the risk surface** — files, framework constructs, what would fail if untested; (2) **reason from first principles** about what shape of testing catches failure here, not a remembered brand list; (3) **web-search current options** for that shape in the user's stack, citation required when naming a tool; (4) **"I don't know" is acceptable** — don't invent tool names or force-fit a surface into the closest familiar category.

### Setting up the recommended tool

sumo-qa's job is **analysis** — classify the change, name risks, pick the technique and tool category by fit (not familiarity). Empty selection is fine when nothing genuinely fits; most changes are well-served by plain unit + a small integration test. Once a tool is chosen, **set it up and write the tests against the actual change** — don't walk the user through commands. The path varies (package manager — `pip install hypothesis`, `npm install --save-dev --save-exact cypress`, Maven/Gradle edit — then the framework's init/scaffold; framework CLI like `npx cypress open`; config edits; or an MCP server when one makes setup easier — but don't bias toward MCP-having tools).

**Always confirm before an install** (lockfile / dependency-surface churn is real), then **default to doing the work yourself**: run the install, write the config, scaffold the framework, write the first tests against the named risks. *"Want me to install Cypress, scaffold the config, and write a smoke test for the new checkout flow?"* — not *"Here are the steps…"*. Verify the tool exists / hasn't been renamed before naming it; web-search when uncertain.

**Repo-pinned + CI-reproducible is a HARD requirement, not a preference.** A test tool you set up for the repo MUST land both ways, every time: (1) **repo-pinned** — an **exact version** in the repo's dependency surface, with the **lockfile committed** (`npm install --save-dev --save-exact` then commit `package-lock.json`; a `[dev]`/`[test]` extra in `pyproject.toml`; a Maven/Gradle dependency; or a pinned-`rev` pre-commit hook). Pin the exact resolved version, not a floating `^`/`~`/`latest`/placeholder; a tool that only exists in your shell — or is recorded as an open range — is not pinned. **Run the package manager's install command** (e.g. `npm install --save-dev --save-exact bats` — npm's default save-prefix is `^`, so `--save-exact` (or a `.npmrc` `save-exact=true`) is required or it records an open range) so it writes the resolved exact version into the manifest AND the lockfile — don't hand-write a manifest line with `latest` or a guessed range. And (2) **CI-reproducible** — a CI step/job runs that **same pinned binary** (the repo-resolved one: `npx <tool>` / `node_modules/.bin/<tool>` / `uv run` / the pre-commit hook), not a freshly-installed or global copy, added/extended in the SAME change so the local check also gates on the pipeline. **Confirm before the install**: emit ONE explicit inline gate naming the install, the manifest pin, and the CI wiring before running anything — *"Installing `bats` via `npm install --save-dev --save-exact` (pins it in `package.json` + lockfile) and adding a `bats` job to `lint.yml` — shout if not."* — never jump straight to "proceeding" without that line.

**REFUSE machine-level / global installs for repo test tooling** — `brew install …`, `npm install -g …` / `npm i -g`, `pipx install …`, system `pip install …`, `apt`. They are unpinned, invisible to teammates and CI, reproduce on one machine. If a tool's only documented setup is global, translate it to the repo-pinned equivalent before running it — never run the global form. (The MCP-server runtime is exempt — it's host config, not a repo dependency — but still surface it as config, don't silently install.) This repo models the shape to copy: ShellCheck via the pinned `shellcheck-py` pre-commit hook with a `lint.yml` CI mirror, and promptfoo pinned to an exact version in `package.json` devDependencies.

### Internal reasoning vs user output

Reason internally with citations (which words in the intent, which file paths, which catalogue entries grounded the inference); the user-facing output is the WORK, not a description of how you arrived at it. **Keep:** the finding (risks named, files cited, verdicts), verifiable file:line citations (`api/refund.py:47`), the current question/gate, rule references in natural English (*"the API-change rule requires a contract test bump"*). **Strip:** internal taxonomy labels, method commentary (*"per the checklist"*, *"anchored to the code I read"*), quality self-defense, step/phase trace, and re-stating the user's input. When a classification is useful to convey, translate it — *"this is a behaviour change in the pricing logic"*, not *"Classification: business_logic_change"*.

### Reasoning effort (host-neutral)

For the hard QA calls — repo-wide analysis, merge-safety review, rollout planning, ambiguous risk triage — use the strongest reasoning the current host makes available, and say so in a sentence before you act: *"This is a high-stakes call, so I'll use the strongest reasoning this host makes available — the highest practical reasoning-effort setting if one is exposed."* Phrase it exactly that way — as a host-neutral capability preference, NOT a setting name: don't assume any particular control exists, don't name a model or provider, and don't fail or refuse when no such control is exposed (reason as deeply as the host allows instead). Low-risk, mechanical asks (loading a catalogue, a one-line answer) don't need it — spend the deeper reasoning where a wrong call is expensive. Never expose hidden reasoning or chain-of-thought as a side effect: the user-facing output stays evidence, decisions, and verification results only (see *Internal reasoning vs user output*).

### Confirmation discipline

Confirmation gates prevent driving past wrong assumptions, but applying them to every minor call wastes attention. Hierarchy:

1. **Surface + proceed** (default) — state what you're doing, cite the call briefly, act; the user redirects if they disagree.
2. **Inline confirm** for moderate forks — one declarative line ending in a question: *"Going with X (Y is the alternative); shout if not."* Then act unless they object.
3. **Structured user-choice prompt ONLY for genuine 50/50 forks** that meaningfully change downstream work (irreversible commits, scope that doubles the work, choices the user has explicit context to make better than you). Use the host's structured-input primitive, or one concise inline question if none exists. NOT for "which of 4 phrasings sounds right" or "which filename convention".

Rule of thumb: if you'd predict the user's answer with >80% confidence, don't ask — surface and proceed. A wrong default costs one redirect; asking costs the user's attention across N turns. *"Walk section-by-section with confirmation gates"* means walk per-section when each genuinely needs the user's judgment — collapse adjacent obvious sections; the Iron Law is "don't dump the whole strategy in one turn", and the goal is structured collaboration, not maximum question count.

### Shared vocabulary (host-neutral contracts)

The skills use three terms that name a capability, not any one host's API. Map each to whatever the current host exposes.

- **Ordered work tracker** — an explicit, ordered list the agent maintains and ticks off as work progresses. Use the host's native task primitive when available; otherwise keep a numbered tracker inline and update it visibly as items complete. The tracking obligation is required; the surface is not.
- **Structured user-choice prompt** — the host's best primitive for collecting an explicit choice from a small set (option-picker, MCP elicitation, etc.). Reserve for genuine 50/50 forks. If no structured UI exists, ask one concise inline question and wait.
- **Subagent** (a.k.a. **fresh delegated worker**) — a worker dispatched through the host's delegation primitive that starts with no inherited task context, only the prompt you hand it. Used by the rollout chain to keep tasks isolated. If a host cannot delegate to fresh workers, the rollout skill stops and reports the capability gap rather than executing inline.

## Checklist
Track these as an ordered work list (see Shared vocabulary), in order:

1. Read the user's intent verbatim.
2. Load and re-read this Iron Law to anchor the response.
3. Invoke the `sumo-qa-deciding-approach` skill immediately. Do NOT answer the user before the approach is decided.
4. After `sumo-qa-deciding-approach` returns, follow its `next_action` (route to the named sub-skill or stop).
5. Apply the global discipline (knowledge authority, internal-only citations, specialty+tool fit) for every sub-skill that runs.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags

| Thought | Reality |
|---|---|
| "I already know what they want — let me just answer" | Iron Law violated. Approach decision is non-negotiable. |
| "This question is too simple to need the approach skill" | Simple intents still need shape (no-tests-recommended is a valid approach). Skip the decision and you skip the safety net. |
| "I'll cite the principles myself from training data" | Loaded catalogue is authoritative. Use `sumo_qa_load_principles()`. |
| "Let me echo the citation reasoning in the answer for transparency" | Citations belong to internal scratch, not user output. They burn tokens. |
| "I'll restrict myself to tool categories I already know" | Wrong. New categories emerge constantly; reason from the surface, web-search current options, recommend with citation. There's no internal catalogue to fall back on. |
| "`brew install` / `npm i -g` / system `pip` is the quickest way to get the tool running" | No. Global installs are unpinned and invisible to CI/teammates. Repo test tooling MUST land repo-pinned (manifest/lockfile/pinned pre-commit hook) AND CI-reproducible (a CI step runs that pinned tool). Translate any global instruction to its repo-pinned equivalent first. |

## Examples

### Good
User: "review my changes". Skill response (internal): load Iron Law, invoke `sumo-qa-deciding-approach`, get `verify-existing` or `regression-first`, route to `sumo-qa-reviewing-before-merge`. User sees the routed skill's output, not the routing trace.

### Bad
User: "review my changes". Skill response: "Sure! Looking at your diff, the main concerns are …" — skipping the approach decision, going straight to review. Iron Law violated. The reviewer might be the wrong shape for the change (e.g. a docs-only change doesn't need a code review skill).

## Next skill in the chain

Always → `sumo-qa-deciding-approach`. That is the router's only job — set the global discipline, then hand the intent over so the approach can be picked before any QA output is produced.
