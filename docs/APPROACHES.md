# Approaches

The 8 canonical QA approaches `sumo_qa_decide_approach` picks from. Source: [`src/sumo_qa/approach_decision.py`](../src/sumo_qa/approach_decision.py). Canonical list verified in [`docs/superpowers/iteration-runs/MCP-STATE-AND-CAPABILITIES.md`](superpowers/iteration-runs/MCP-STATE-AND-CAPABILITIES.md).

The AI may invent a new approach when none of these fits, but every relevant tool response leads with a recommended approach so the host knows what to do next.

| Approach | When it fires | `next_action` | Response also includes |
|---|---|---|---|
| `tdd-scaffold` | Greenfield-ish change adding behaviour. Default when in doubt. | `tool: sumo_qa_scaffold_tests` | standard senior-QA fields |
| `regression-first` | Bug fix on existing code. Reproduce as one failing test, then fix. | `tool: sumo_qa_scaffold_tests` (single reproducer first) | standard fields |
| `coverage-first-then-refactor` | Behaviour-preserving refactor. Audit existing coverage before touching code. | `tool: sumo_qa_review_local_change` (to find coverage gaps) | `characterization_tests` |
| `strengthen-test-coverage` | Mutation-testing follow-up. Production code unchanged; only tests get stronger. | `tool: sumo_qa_scaffold_tests` (against existing tests) | standard fields |
| `verify-existing` | Trivial / config / version-bump tweak. | `tool: null` (run existing suite + smoke) | standard fields |
| `no-tests-recommended` | Pure docs / typos / comments. | `tool: null, skill: null, deliverable: "static_review_completed"` | standard fields |
| `spike-first-then-tests` | Exploratory throwaway prototype. Defer test discipline until design settles. | `tool: null, skill: null, deliverable: "captured_conditions_and_fit_record"` | `next_action.deliverable` |
| `strategy-orchestration` | Repo-wide / policy / pyramid / rollout ask, not a single change. | `skill: "sumo-qa-strategising"` | `pyramid_shape`, `gate_calibration`, `ci_feedback_time`, `rollout_plan` |

Critical-path detection (auth, JWT, payment, billing, encryption, security boundary, rate limit) bumps the rationale to mention "high-risk" and recommends wider regression scope.

Each decision also lists alternatives + the conditions that would justify them, so the user can override via `signals` or by calling a different tool directly.

## How the AI picks

The AI-sampling path is the primary decider — the host LLM is grounded as a senior QA via `SENIOR_QA_SYSTEM_PROMPT` (see [docs/ISTQB-GROUNDING.md](ISTQB-GROUNDING.md)) and reasons over the change shape, the loaded team rules, and the team standards.

The deterministic fallback (used only when the host doesn't support MCP sampling, or when `QA_DISABLE_HOST_SAMPLING=1`) does NOT pattern-match free text. It only honours caller-supplied `signals`:

- `is_strategic_planning` → `strategy-orchestration`
- `is_test_only` → `strengthen-test-coverage`
- `is_bug` → `regression-first`
- `is_refactor` → `coverage-first-then-refactor`
- `is_spike` → `spike-first-then-tests`
- `is_docs_only` → `no-tests-recommended`
- `is_config_only` → `verify-existing`
- `has_acceptance_criteria` → bumps fallback confidence from `low` to `medium`

Without signals + without AI, the fallback returns `tdd-scaffold` with a `reasoning_note` flagging that AI sampling is the right path for accurate routing.
