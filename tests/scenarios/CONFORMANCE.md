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
| `expected_entry_skill` | the skill tool the host must route to first (`null` for a pure tool-selection scenario) |
| `required_tool_calls` | tools that MUST appear in the transcript (checked as a set: presence, not order or multiplicity, a documented first-slice limit) |
| `forbidden_tool_calls` | tools that MUST NOT appear |
| `required_output_markers` | substrings that MUST appear in the final assistant output (case-insensitive) |
| `forbidden_output_markers` | substrings that MUST NOT appear (anti-pattern claims, leaked internal labels; case-insensitive, so pin distinctive phrases: `INV-12345` also matches inside `INV-123456`) |

A deterministic scenario must declare at least one enforceable clause
(`expected_entry_skill`, a tool-call list, or an output marker); the loader
rejects a clause-free row rather than letting it pass every transcript
vacuously. Mis-route detection compares prior calls against the REGISTERED
skill-tool surface (every `skills/*/SKILL.md` directory), not just the skills
this fixture happens to name, and the router chain is order-aware:
`using_sumo_qa` must precede `sumo_qa_deciding_approach` when both fire.

## The transcript

A transcript is provider-agnostic: an ordered list of `(tool, args)` calls plus
the final assistant `output_text`. The validator
([`../../src/sumo_qa/conformance.py`](../../src/sumo_qa/conformance.py)) scores
it against a scenario and reports one violation per broken clause:
`wrong_skill_routing`, `missing_required_tool`, `forbidden_tool_called`,
`missing_output_marker`, `forbidden_output_marker`.

`transcript_from_debug_dir` reconstructs a transcript from a
`SUMO_QA_DEBUG_DIR` capture (see
[`../../src/sumo_qa/debug_capture.py`](../../src/sumo_qa/debug_capture.py)),
which records the tool exchanges of a live run. The capture holds tool calls
only, so the final assistant text is supplied by the reviewer running the
manual check.

## Running it

The deterministic checks run in the ordinary suite (no key, no network):

```bash
uv run pytest tests/test_conformance_transcript_validator.py
```

Those tests prove the fixture is well-formed (>= 8 deterministic scenarios,
the required families present, every tool name registered, every source
heading resolving), that a compliant transcript passes each scenario, and that
a synthetic bad transcript FAILS on each contract axis.

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
