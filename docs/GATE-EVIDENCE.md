# Evidence-backed gate reporting

An LLM cannot be relied on to follow a procedure or report execution truthfully
by instruction alone. It will call a change "safe to merge" off CI that ran an
hour ago, say "tests passed" without running anything, and declare a gate green
because the prose sounds green. sumo-qa cannot make a probabilistic model
deterministic. What it can do is require **evidence** for a safety claim, and
give that evidence a shape a validator can check.

That is the honesty boundary this control draws (issue #213): the model stays
probabilistic, but a gate claim that asserts an execution outcome must cite the
observed evidence behind it, or mark itself `unverified`.

## The schema

The schema is a lightweight, standalone record in
[`src/sumo_qa/gate_evidence_models.py`](../src/sumo_qa/gate_evidence_models.py).
It is deliberately **not** wired into the MCP tool-output surface, so the
existing `isError` envelope behaviour in
[`src/sumo_qa/server.py`](../src/sumo_qa/server.py) and
[`src/sumo_qa/server_schemas.py`](../src/sumo_qa/server_schemas.py) is untouched.

A `GateReport` carries a list of `GateClaim`s. Each claim has a `gate` name, a
`status`, a plain-English `statement`, and a list of `EvidenceItem`s.

### Gate statuses

| Status | Meaning |
|---|---|
| `passed` | The gate ran and its check succeeded. |
| `failed` | The gate ran and its check failed. |
| `skipped` | The gate was deliberately not run (not applicable this turn). |
| `blocked` | The gate could not run because a precondition or dependency failed. |
| `unverified` | No evidence was observed. The honest "cannot claim" state. |

### Evidence source types

Each `EvidenceItem` names where an observation came from:

| Source | Meaning |
|---|---|
| `command` | A shell command the host ran; its output is the proof. |
| `tool_call` | A tool or function invocation and its returned result. |
| `file_read` | Reading a file's contents (a coverage report, a lockfile). |
| `user_fact` | A fact the user asserted (product context the diff cannot show). |
| `external_ci` | An external CI or pipeline result. |
| `manual_observation` | A human or agent observation not captured by the above. |

### The evidence rule

Enforced at construction, mirroring the ledger schema's validators:

- An **evidence-backed** status (`passed`, `failed`, `blocked`) must cite at
  least one `EvidenceItem`. A `passed` claim with no cited evidence is exactly
  the unsupported "tests passed" this control exists to reject.
- `unverified` must cite **no** evidence. Attaching evidence contradicts the
  label; the claim should then be `passed`, `failed`, or `blocked`.
- `skipped` may cite no evidence (it was deliberately not run).

## The validators

Two entry points live in
[`src/sumo_qa/gate_evidence_validation.py`](../src/sumo_qa/gate_evidence_validation.py),
matching "transcript snippets or structured evidence blocks":

- **Structured path.** `load_gate_report(dict)` validates a parsed report. An
  unsupported `passed` / `failed` / `blocked` claim raises
  `GateEvidenceValidationError` with `kind="value_error"`, the deterministic
  rejection the acceptance criteria require. Every failure mode carries a stable
  `kind` (`schema_version_mismatch`, `missing_field`, `unknown_field`,
  `vocab_error`, `value_error`, `type_error`) so callers branch on the category
  rather than parsing free-form messages.
- **Transcript path.** `find_unsupported_claims(transcript)` and its raising
  counterpart `assert_transcript_supported(transcript)` are a lint-grade guard
  over free text. They flag a pass or safe phrase ("tests passed", "safe to
  merge") that appears with no evidence signal anywhere in the snippet and no
  `unverified` hedge on its own line. This path is deliberately coarse, a lint
  rather than a proof, because a probabilistic transcript cannot be parsed to a
  proof. The structured path above is the rigorous one.

## Where it is used

The gate-status and evidence-source vocabulary is the reporting discipline the
QA workflow skills now carry. Each of these skills gained an "Evidence-backed
gate reporting" section requiring every gate claim that asserts an execution
outcome (`passed`, `failed`, `blocked`) to cite one evidence source, unless the
claim is `skipped` or `unverified`, which carry none:

- [`skills/sumo-qa-reviewing-before-merge/SKILL.md`](../skills/sumo-qa-reviewing-before-merge/SKILL.md):
  the suite verdict, each risk's coverage, and the safe-to-merge call are gate
  claims. `SAFE TO MERGE` is a `passed` safe-to-merge gate, unreachable while
  any gate is `failed`, `blocked`, or `unverified`.
- [`skills/sumo-qa-finishing-qa-work/SKILL.md`](../skills/sumo-qa-finishing-qa-work/SKILL.md):
  each summary claim ("suite green", a risk covered, a known gap) is a gate
  claim; a known gap is `unverified` or `failed`, never a silent `passed`.
- [`skills/sumo-qa-executing-qa-rollout/SKILL.md`](../skills/sumo-qa-executing-qa-rollout/SKILL.md):
  marking a task done or a review passed is a gate claim citing the worker's
  returned result or the fresh run.
- [`skills/sumo-qa-creating-test-plan/SKILL.md`](../skills/sumo-qa-creating-test-plan/SKILL.md):
  each entry or exit criterion is a gate whose eventual claim names the evidence
  source that would settle it; at plan time every criterion is `unverified`.

## What it is not

- Not a claim that evidence capture can observe every host-side action in every
  host. The transcript lint is coarse by design.
- No required telemetry upload or external service.
- No weakening of the existing human-readable workflow output; evidence renders
  as a short status word plus a source cite, not a second narrative.
- No new reasoning tool that replaces the skills. The schema locks a shape; the
  host LLM still does the QA reasoning.
