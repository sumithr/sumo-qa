# Cross-model conformance layer

Deterministic, no-LLM conformance checks for QA routing and outputs (issue
#214). This layer turns the human-readable expectations in
[`SCENARIOS.md`](SCENARIOS.md) and [`TOOL-SELECTION.md`](TOOL-SELECTION.md)
into machine-readable contracts and scores a captured host/tool-call transcript
against them, so "does a host/model actually follow the skill chain?" becomes a
measured question with concrete artifacts, not a prose claim.

It sits between the two existing layers:

| Layer | Runs in PR CI? | Needs a model? | What it measures |
|---|---|---|---|
| Trigger-routing harness ([`test_skill_triggering.py`](../test_skill_triggering.py) + [`fixtures/skill_triggers.yaml`](../fixtures/skill_triggers.yaml)) | yes | no | a skill's MCP description still carries the natural-language phrase the host routes on |
| **Conformance validator (this layer)** | yes | no | a captured transcript routed to the right skill, called the required tools, avoided the forbidden ones, kept forbidden claims out of the output |
| Promptfoo evals ([`../evals/promptfoo/`](../evals/promptfoo/README.md)) | no (manual) | yes | response *quality*: grounding, verbosity, residual risks, anti-patterns |

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
| `taxonomy_label` | a bare label line: `Classification:` / `Approach:` (after a list, blockquote or heading prefix and a space; bold, code or quoted) whose value is exactly a catalogue entry name (read from the live catalogues) or `n/a`, with nothing else on the line but a clause end or a second label pair with its own catalogue value after `.`, `,`, `;`, a space, or glued straight on; or a qualified label (`Approach restated:`, `Chosen approach:`, `Classification identified:`, likewise `re-stated`, `selected`, `picked`) whose value opens with a whole catalogue name in any case, whatever prose follows (`**Approach restated:** Regression-first for the payments change`) | `Approach: pin today's behaviour first`, "a regression-first approach", a label inside a sentence ("so approach: recommend-removal"), a bare label followed by a reason, a qualifier not next to the colon ("Approach chosen with the team: ...") |
| `route_announcement` | "Picking the QA approach...", "Routing this QA intent.", "Routing to" or "Routed to" a `sumo-qa-...` skill name with an optional "this", "you" or "it", "the" or a colon ("Routing you to the `sumo-qa-strategising` skill"), a first-person "I'm routing you to...", "I'll route this to sumo-qa-..." or "I'm handing this to sumo-qa-..." | "routing to the pricing service", "I'm routing traffic through the load balancer", "I'm routing this traffic through the proxy", a downstream skill's handoff offer ("I'd recommend handing off to `sumo-qa-reviewing-before-merge`"), data sent to a tool ("the survivors are routed to sumo_qa_record_mutation") |
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
`skill-deciding-approach-user-facing.yaml`, which loads both routing hops, and
in the evals of the skills they route to (`skill-closing-qa-gaps.yaml`,
`skill-implementing-with-tdd.yaml`, `skill-security-testing.yaml`,
`skill-triaging-test-failures.yaml`), whose onward hand-off is invoking the next
skill, never naming it to the user; a contract test runs both over the
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
