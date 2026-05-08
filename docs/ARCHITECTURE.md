# Architecture

How sumo-qa is laid out and the two-layer design that makes it work.

## Two-layer design

The QA reasoning is split across two layers, by design:

1. **Deterministic guardrails.** Classification, missing test levels, recommended test paths, plausibility checks, freshness scoring, rule-template attribution, signal-driven approach fallback. Always run, fully offline. This is the floor a senior QA never forgets.

2. **Host LLM brain (via [MCP sampling](https://modelcontextprotocol.io/specification/server/sampling)).** When the host advertises sampling, the server calls back through `ctx.session.create_message(...)`, supplying the senior-QA system prompt and a guardrailed user prompt that includes the deterministic findings as constraints. The host runs the completion using whatever model the user has configured — Claude Opus in Claude Code, the user's chosen Copilot model, Sonnet in Cursor, etc. The MCP never picks the model.

The user prompt explicitly states the deterministic guardrails as constraints the LLM must respect: classification + confidence, missing test levels, canonical test paths to add, deterministic findings, team standards, rule expectations. The LLM can reason about novel code and propose checks the rules can't see — but it cannot waive a missing test level or bless a change that lacks evidence. Guardrails are the floor, not the ceiling.

If the host doesn't support sampling, or the user opts out via `QA_DISABLE_HOST_SAMPLING=1`, the response degrades to the deterministic-only payload. The `llm_analysis.metadata.fallback_reason` field, when set, explains why the host narrative is missing for a given call.

## File map

Source under [`src/sumo_qa/`](../src/sumo_qa/):

- `server.py` — FastMCP wrapper. Registers the 10 tools and 9 prompts, attaches output schemas, wraps exceptions in the `isError` envelope.
- `tools.py` — `QAShiftLeftService`: sync + async (`aqa_*`) orchestration, deterministic response construction, sampling integration.
- `models.py` — strongly typed Pydantic response models for the QA tools.
- `tdm_models.py` — strongly typed test-data, validation, freshness, and requirement models.
- `prompts.py` — `SENIOR_QA_SYSTEM_PROMPT` and the per-tool guardrailed prompt builders.
- `approach_decision.py` — canonical approach list, `_NEXT_TOOL`, `_FOLLOW_UP`, `_ALTERNATIVES_BY_APPROACH`, signal-driven fallback decider.
- `classification.py` — heuristic change classification from paths, filenames, keywords, diff snippets.
- `rules.py` — standards rules engine for classification-specific QA expectations.
- `standards.py` — versioned YAML standards pack loader.
- `specialty_routing.py` — `SPECIALTY_REGISTRY` and registry-only structural detector.
- `scaffolder.py` — scaffold-task construction (file paths, frameworks, skeletons, verify commands).
- `local_diff.py` — lightweight `git diff` and nearby-test inspection.
- `knowledge.py` — pluggable `KnowledgeProvider` contract; default is `NullKnowledgeProvider`.
- `llm.py` — `HostSamplingClient` plus a deterministic `MockLLMClient` for tests.
- `tdm_catalogue.py` — local YAML-backed test-data catalogue.
- `tdm_validation.py` — pluggable validation abstraction with a heuristic `MockValidator`.
- `tdm_service.py` — TDM orchestration.
- `rubric.py` — ISTQB-grade rubric used by the evaluation harness to score scenario output.
- `debug_capture.py` — `SUMO_QA_DEBUG_DIR` capture (args + output + trace per invocation).
- `evaluation.py` — fixture-driven evaluation harness; runs from `evaluation/` YAMLs.
- `render_preview.py` / `render_cli.py` — local rendering preview without burning host LLM tokens.

## Standards and rules

Versioned QA standards live in [`standards/packs/`](../standards/packs/). Change-specific rules live in [`standards/rules/change_rules.yaml`](../standards/rules/change_rules.yaml) — each classification (`api_contract_change`, `business_logic_change`, `state_transition_change`, `ui_only_change`, `configuration_change`, `data_mapping_change`, `error_handling_change`, `async_flow_change`, `caching_change`, `security_change`) maps to `must_consider`, `suggested_test_types`, `test_design_techniques`, `quality_characteristics`, and `risk_templates`. The service applies these rules automatically before producing the response schema.
