# Cross-model conformance layer

Deterministic, no-LLM conformance checks for QA routing and outputs (issue
#214). This layer turns the human-readable expectations in
[`SCENARIOS.md`](SCENARIOS.md) and [`TOOL-SELECTION.md`](TOOL-SELECTION.md)
into machine-readable contracts and scores a captured host/tool-call transcript
against them, so "does a host/model actually follow the skill chain?" becomes a
measured question with concrete artifacts, not a prose claim.

It sits among the other layers like this:

| Layer | Runs in PR CI? | Needs a model? | What it measures |
|---|---|---|---|
| Trigger-routing harness ([`test_skill_triggering.py`](../test_skill_triggering.py) + [`fixtures/skill_triggers.yaml`](../fixtures/skill_triggers.yaml)) | yes | no | a skill's MCP description still carries the natural-language phrase the host routes on |
| **Conformance validator (this layer)** | yes | no | a captured transcript routed to the right skill, called the required tools, avoided the forbidden ones, kept forbidden claims out of the output |
| Promptfoo evals ([`../evals/promptfoo/`](../evals/promptfoo/README.md)) | no (manual) | yes | response *quality*: grounding, verbosity, residual risks, anti-patterns |
| Live-host first hop ([`../../scripts/live_first_hop.py`](../../scripts/live_first_hop.py)) | no (manual) | yes | a real host, given only the sumo-qa tool list, takes the first hop; scored by this layer's validator |

The conformance validator does not replace the promptfoo evals; it pins the
deterministic contract (routing + tool calls + output markers) that does not
need an LLM to judge, and defers everything behavioural to the provider-backed
layer.

## The fixture format

The fixtures live in [`conformance/scenarios.yaml`](conformance/scenarios.yaml).
Each scenario is seeded from a heading in `SCENARIOS.md` or `TOOL-SELECTION.md`
(the `source_doc` + `source_heading` fields), so this is not a second source of
truth: a guard test re-resolves each heading, and every tool name is checked
against the registered MCP tool surface.

```yaml
- id: S02-review-before-merge
  source_doc: SCENARIOS.md
  source_heading: "Review uncommitted changes before merging"
  user_prompt: "Review my changes - is this safe to merge?"
  mode: deterministic            # or provider-backed (deferred to promptfoo)
  expected_entry_skill: sumo_qa_reviewing_before_merge
  required_tool_calls:
    - sumo_qa_load_classifications
    - sumo_qa_load_rules
  forbidden_output_markers:
    - "Classification: business_logic_change"   # internal taxonomy leak
```

Field reference:

| Field | Meaning |
|---|---|
| `mode` | `deterministic` (scored here) or `provider-backed` (the validator skips it; promptfoo judges it) |
| `expected_entry_skill` | the skill tool the router chain must reach (`null` for a pure tool-selection scenario or a non-QA development control); see *The first hop* below |
| `required_tool_calls` | tools that MUST appear in the transcript (checked as a set: presence, not order or multiplicity, a documented first-slice limit) |
| `forbidden_tool_calls` | tools that MUST NOT appear |
| `required_output_markers` | substrings that MUST appear in the final assistant output (case-insensitive) |
| `forbidden_output_markers` | substrings that MUST NOT appear (anti-pattern claims, leaked internal labels; case-insensitive, so pin distinctive phrases: `INV-12345` also matches inside `INV-123456`) |
| `forbid_sumo_qa_calls` | `true`: the transcript must contain no sumo-qa call at all (`using_sumo_qa` or any `sumo_qa_*` tool); for requests that must not enter sumo-qa |

A deterministic scenario must declare at least one enforceable clause
(`expected_entry_skill`, a tool-call list, an output marker, or
`forbid_sumo_qa_calls`); the loader
rejects a clause-free row rather than letting it pass every transcript
vacuously. Mis-route detection compares prior calls against the REGISTERED
skill-tool surface (every `skills/*/SKILL.md` directory), not just the skills
this fixture happens to name.

## The first hop

The canonical rule lives in
[`../../src/sumo_qa/first_hop.py`](../../src/sumo_qa/first_hop.py) and is
carried verbatim by the MCP server instructions,
`.github/copilot-instructions.md`, the `using-sumo-qa` skill, the trigger
fixture, and this layer's fixture (a guard test,
[`../test_first_hop.py`](../test_first_hop.py), fails when any
of them drifts):

> First hop: every QA-shaped request, including a development-framed one such
> as "I'm adding X, how should I test it?", "what tests do I need?" or "write
> the failing tests first", calls `using_sumo_qa` before any other sumo-qa tool
> and before any QA advice, then `sumo_qa_deciding_approach`, then the one skill
> it routes to. No specialist skill is entered directly.

The pre-routing surfaces (the server and Copilot instructions, which a host
reads before any skill body) also carry `CLARIFY_AFTER_ROUTING` from the same
module: an underspecified QA request still takes the first hop before the host
asks the user anything, and `sumo_qa_deciding_approach` (or the skill it
routes to) asks the clarifying question.
Without it, the weakest candidate answered "write the failing tests first"
with a clarifying question and never reached the router.

For every scenario with an `expected_entry_skill`, the validator enforces it:
the first sumo-qa call (`using_sumo_qa` or any `sumo_qa_*` tool) must be
`using_sumo_qa`, and the FIRST calls of `using_sumo_qa`,
`sumo_qa_deciding_approach`, and the expected skill must occur in that order,
with no other sumo-qa call (a specialist or a catalogue loader) between the
router and the decider.
Host tools (file reads, shell) may come anywhere. A transcript that answers
with no sumo-qa call, loads a catalogue before the router or before the
decider, enters a specialist directly, or skips the decider fails with
`first_hop_violation`.
The transcript does not interleave output with calls, so "before any QA advice"
is checked as "the first hop exists and comes first among sumo-qa calls".

The `D0x` scenarios pin the four development-framed prompts from issue #247.
The `DC0x` scenarios are their controls: the same framing with no testing ask
(backoff, logging, naming, formatting) sets `forbid_sumo_qa_calls`, so neither
the router nor a directly entered specialist may appear.

## The transcript

A transcript is provider-agnostic: an ordered list of `(tool, args)` calls plus
the final assistant `output_text`. The validator
([`../../src/sumo_qa/conformance.py`](../../src/sumo_qa/conformance.py)) scores
it against a scenario and reports one violation per broken clause:
`wrong_skill_routing`, `first_hop_violation`, `missing_required_tool`,
`forbidden_tool_called`, `missing_output_marker`, `forbidden_output_marker`,
`routing_state_leak`.

## Routing-state leaks

The two routing hops, the entry router (`using-sumo-qa`) and the approach
router (`sumo-qa-deciding-approach`), are internal: their routing payload,
taxonomy labels, route announcement and checklist bookkeeping must never reach
the user. Every deterministic scenario's output is scored for
five leak families by `find_routing_leaks`, with no per-scenario opt-in:

| Family | Caught | Not caught (ordinary prose) |
|---|---|---|
| `payload_json` | one outermost brace-balanced span (braces inside strings ignored; an opening brace that never closes is skipped; a single quote between two ASCII letters, digits or underscores is an apostrophe; `“` opens a string that `”` closes, and inside a `"..."` string both are text) naming `classification`, `approach` and a `next_action` object that itself holds a `skill` handoff (compact, pretty-printed, or unquoted keys) | a config snippet, even one with `classification`/`approach`/`next_action` keys and a `skill:` elsewhere; `next_action:{` written inside a quoted key |
| `taxonomy_label` | a bare label line: `Classification:` / `Approach:` (after a list, blockquote or heading prefix and a space; bold, code or quoted) whose value is exactly a catalogue entry name (read from the live catalogues) or `n/a`, with nothing else on the line but a clause end or a second label pair with its own catalogue value after `.`, `,`, `;`, a space, or glued straight on | `Approach: pin today's behaviour first`, "a regression-first approach", a label inside a sentence ("so approach: recommend-removal"), a label followed by a reason |
| `route_announcement` | "Picking the QA approach...", "Routing this QA intent.", "Routing to" or "Routed to" a `sumo-qa-...` skill name with an optional "this", "you" or "it", "the" or a colon ("Routing you to the `sumo-qa-strategising` skill"), a first-person "I'm routing you to..." or "I'll route this to sumo-qa-..." | "routing to the pricing service", "I'm routing traffic through the load balancer", "I'm routing this traffic through the proxy", a downstream skill's handoff offer ("I'd recommend handing off to `sumo-qa-reviewing-before-merge`"), data sent to a tool ("the survivors are routed to sumo_qa_record_mutation") |
| `checklist_status` | `[DONE]`, `[IN PROGRESS]`, `[PENDING]`, `[COMPLETED]` on a line naming a router step | markdown `[x]` / `[ ]` checkboxes; a downstream plan's `[DONE] Run the suite` |
| `router_checklist` | two or more numbered lines naming router steps (load classifications/approaches, removability gate, pick the approach, routing payload, ...) | a numbered test plan, even one line mentioning the removability gate |

The families match high-confidence router voice only. A label inside prose and
a paraphrased handoff ("handing this over to...", "the next step will...") read
the same as text a downstream skill may legitimately write, so the
user-facing eval's judge grades them instead, and a test pins that boundary.
Two overlaps remain, each flagged if it reaches scored output: a downstream
field line with a catalogue value, such as the planning-qa-rollout task
template's `**Approach:** regression-first` or the rollout reviewer prompts'
`- Approach: tdd-scaffold`; and a downstream skill narrating its own onward
route in router wording, such as "Routing to `sumo-qa-preparing-for-work`
first". Third-person handoff targets are hyphenated skill names (`sumo-qa-...`,
`using-sumo-qa`, `using_sumo_qa`); `sumo_qa_*` tool names such as
`sumo_qa_record_coverage` are not. The silent-hop instruction in
both routing skills is the primary control.

[`conformance/leak_transcripts.yaml`](conformance/leak_transcripts.yaml) holds
a leaking and a clean near-miss output for every family, scored against the
routed scenario (S11) and both STOP scenarios (S10 `no-tests-recommended`,
S20 `recommend-removal`). The promptfoo assert
[`../evals/promptfoo/asserts/no-routing-leak.js`](../evals/promptfoo/asserts/no-routing-leak.js)
applies the same families to live candidate replies in
`skill-deciding-approach-user-facing.yaml`; a contract test runs both over the
fixture so they stay in step. One deliberate difference: the assert reads
catalogue names from `QA_KNOWLEDGE_PATH` or the repo's `knowledge/` (what the
eval loads), while the validator resolves ingested project/global packs too.

`transcript_from_debug_dir` reconstructs a transcript from a
`SUMO_QA_DEBUG_DIR` capture (see
[`../../src/sumo_qa/debug_capture.py`](../../src/sumo_qa/debug_capture.py)),
which records the tool exchanges of a live run. The capture holds tool calls
only, so the final assistant text is supplied by the reviewer running the
manual check. It records MCP tool calls only: a host that loads the router through
a native skill (Claude Code's Skill tool, or the SessionStart hook injecting the
router body) leaves no `using_sumo_qa` call in the capture, so score such a run
from the host's own transcript instead.

## Running it

The deterministic checks run in the ordinary suite (no key, no network):

```bash
uv run pytest tests/test_conformance_transcript_validator.py tests/test_conformance.py
```

Those tests prove the fixture is well-formed (>= 8 deterministic scenarios,
the required families present, every tool name registered, every source
heading resolving), that a compliant transcript passes each scenario, that
a synthetic bad transcript FAILS on each contract axis, and that every
routing-leak fixture scores as labelled.

To score your own captured run against a scenario:

```python
from sumo_qa.conformance import (
    load_scenarios,
    validate_all,
    format_report,
    transcript_from_debug_dir,
)

scenarios = load_scenarios("tests/scenarios/conformance/scenarios.yaml")
transcript = transcript_from_debug_dir(
    "/path/to/SUMO_QA_DEBUG_DIR",
    scenario_id="TS15-capabilities",
    output_text="...the final assistant message...",
)
print(format_report(validate_all(scenarios, [transcript])))
```

`format_report` emits a compact per-scenario PASS / FAIL / SKIP line with the
violated contract inline. It identifies the failing scenario and the broken
clause without reading raw provider logs.

### Live host first hop

The fixtures above score a transcript; they cannot see whether a real host
picks `using_sumo_qa` from its tool list. The in-prompt evals preload the
router skill, so they cannot either.
[`../../scripts/live_first_hop.py`](../../scripts/live_first_hop.py) runs each
deterministic scenario's `user_prompt` through `claude -p` with only the
sumo-qa MCP server of a named build attached, and scores the host's own tool
calls with `validate_all`:

```bash
# one build: a git ref (archived, built to a wheel) or a .whl path
uv run --no-sync python scripts/live_first_hop.py origin/main
# before/after on the same prompts, limited to the D0x/DC0x set
uv run --no-sync python scripts/live_first_hop.py origin/main path/to/branch.whl --only 'DC?0'
```

It is manual and never in PR CI: every prompt is a billed host run on the
subscription, so follow the promptfoo cost guardrails and narrow the set with
`--only` (a regex on scenario ids). The default model is `haiku`, the weakest
candidate: stronger models routed every development-framed prompt on both
builds and so could not tell them apart. Pass `--model` for an extra data point.

Every build is clean-installed into its own venv under the run dir before any
host runs, so a bad second build fails before anything is billed. The child
host runs in a throwaway cwd with `--strict-mcp-config`, no settings sources (no
user hooks or plugins), no skills, no CLAUDE.md or auto-memory, and an allowlist
of host tools: `--tools ToolSearch,Agent,Read,Glob,Grep`, with `--disallowedTools
Bash Write Edit NotebookEdit` on top. A subagent inherits the main session's
tool pool, narrowed and never widened, so `Agent` adds no tool.

Which sumo-qa tools are pre-approved is derived per build, from that build's
own server: the harness runs the installed binary once (`initialize` then
`tools/list`) and reads each tool's annotations. A tool that declares
annotations is pre-approved only with `readOnlyHint` true and `openWorldHint`
false (a missing `openWorldHint` means open-world, the MCP default). A tool
with no annotations is pre-approved only if it is the router (`using_sumo_qa`)
or one of that build's skill tools, which only return guidance text: refusing
them would refuse the first hop being measured. The skill tools are read from
the skills the build's installed wheel bundles (`sumo_qa/_data/skills/<dir>/`,
tool name = directory name with `-` as `_`). Any other unannotated tool is
refused, so a build that predates tool annotations cannot have its writers
approved. On top of that, `sumo_qa_install_external_skill` and
`sumo_qa_execute_external_skill` are refused by name whatever their
annotations say: installing or executing an external skill is never safe to
auto-approve in an unattended run. Every other tool, such as the npm-backed
`sumo_qa_search_external_skills`, stays in the tool list, so a scenario that
forbids one still sees the host reach for it, but a call to one is refused. The guard section of the report lists the refused tools per build.

The child's environment takes from the parent only `PATH`, `HOME`, `USER`,
`LANG`, `TMPDIR`, the login (`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`,
`CLAUDE_CONFIG_DIR`), the proxy and CA variables (`HTTPS_PROXY`, `HTTP_PROXY`,
`NO_PROXY` and their lowercase forms, `NODE_EXTRA_CA_CERTS`, `SSL_CERT_FILE`,
`REQUESTS_CA_BUNDLE`), a gateway (`ANTHROPIC_BASE_URL`,
`ANTHROPIC_AUTH_TOKEN`), and the Bedrock and Vertex switches with their
credential, region and base-URL variables, each only when set (the full list is
`CHILD_ENV_PASSTHROUGH` in the script); nothing else from the parent. With
`CLAUDE_CODE_USE_BEDROCK` or `CLAUDE_CODE_USE_VERTEX` on (`1`, `true`, `yes` or
`on`, any case, as the CLI reads them; `0` or `false` is off), the backend's model
alias mapping (`ANTHROPIC_DEFAULT_HAIKU_MODEL`, `_SONNET_`, `_OPUS_`),
`VERTEX_REGION_CLAUDE_*` and `CLOUDSDK_CONFIG` pass too; the report records
the model the host actually ran from its init event. The harness adds its own
isolation switches. A parent's model override (`ANTHROPIC_MODEL`,
`CLAUDE_CODE_SUBAGENT_MODEL`, and `ANTHROPIC_DEFAULT_*_MODEL` without a
backend switch) or `SUMO_QA_DEBUG_DIR` cannot reach the host or its MCP
server. The MCP
server's `HOME` points into the run dir.

Before any scenario runs, a write-guard control prompt per build asks the host
to create a plainly named file (`notes/todo.txt` in the build's run dir, outside
every host cwd) using any tool it has. The harness stops there if the file
appears (exit 3). It also stops (exit 4) unless all of these hold: that build's
MCP server connected; the model acted (the guard run ended in `success` or a
turn limit, `error_max_turns`; a usage limit, an API error, an execution error,
no result, a cut-off stream or a timeout proves nothing); and the guard run's
host tool pool, the `tools` list of its `system/init` event, holds nothing but
the allowlisted host tools (as the CLI names them: it lists `Agent` as `Task`)
and that build's own `mcp__sumo-qa__*` tools. Any other tool in the pool fails
the guard with `sandbox not proven: <tool> in the host tool pool`, and the
report marks it `NOT PROVEN`. The proof is the pool, not the model's behaviour:
the guard's tool calls are listed in the report for information and never
decide the verdict. The guard section also lists the pool's host tools and the
number of sumo-qa tools in it.

A run is valid only when its MCP server connected and it ended in a clean
`success` with exit code 0. A usage-limit stop (`Claude AI usage limit
reached|<epoch>`, detected with the promptfoo provider's own pattern), a turn
limit, an execution error, a timeout or a cut-off stream (a final line that is
not JSON) is invalid: it is not scored (its scenario reads SKIP), and the report
lists it under `not scored`. A stream with several `result` events (a background
agent finishing after the main turn) is a success only if every one is, and its
output is every result's text in order. A non-JSON line mid-stream is skipped
and counted in the report.

The report records the host and its version, the model, and per prompt the MCP
connection status, the outcome, the CLI exit code and the ordered tool calls
(host-namespaced `mcp__sumo-qa__<tool>` names are normalised to the bare names
the validator expects; a call a subagent made is shown as `sub:<tool>` but
scored like any other), then the `format_report` table per build and a before
-> after line per scenario. The raw stream-json and stderr of every run stay in
the run dir (`--out`, a new or empty dir, default a temp dir).

| Exit code | Meaning |
|---|---|
| 0 | every run was valid |
| 1 | the harness itself failed (a build, install or other error; the traceback says which) |
| 2 | bad arguments, including an `--only` that matches no scenario or an `--out` that is a file or a non-empty dir |
| 3 | the write guard was breached |
| 4 | a billed run was not valid (a scenario run, or a guard run that proves nothing, including a host tool pool that holds a tool outside the sandbox), so the scores are not valid |

## The provider-backed half

Model-variance and response-quality signal stays with the promptfoo evals.
They are manually run and documented with cadence and cost in
[`../evals/promptfoo/README.md`](../evals/promptfoo/README.md) (its "NOT in CI",
"When to run", and "Cost guardrails" sections). Their scenario-level variance /
stability report is [`../evals/promptfoo/aggregate.py`](../evals/promptfoo/aggregate.py),
which reports the per-scenario verdict-flip rate across repeated runs. This
conformance layer is the deterministic counterpart to that report; together
they answer "where does a model or host fail?" with concrete test and eval
artifacts.
