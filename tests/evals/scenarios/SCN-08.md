---
id: SCN-08
scenario_type: skill
expected_skill: sumo-qa-strategising
anti_patterns:
  - 'Single-shot dump: "Phase 1 unit tests, Phase 2 integration, Phase 3 e2e, aim for 80% coverage."'
  - 'Generic recommendation: *"introduce a QA Center of Excellence"*.'
  - Asks the user what services exist (read the repo).
  - No residual risks listed (every strategy has them).
---

## User prompt

Audit our test coverage across the customer-platform monorepo and design a QA strategy. We've got 4 services and a shared lib.

## Expected interaction shape

1. Walks the repo *with the host's file tools first*. Inventory: services, top-level modules, test dirs, CI config, coverage reports. Does NOT ask the user to enumerate the repo.
2. Per-area provisional analysis: classification per area, existing coverage shape (unit-heavy / integration-heavy / e2e-heavy), 2–3 named risks per area citing file paths.
3. **Confirms scope + inventory** in one paragraph, asks ONE focused question (e.g. *"are all 4 services in scope, or just the ones you own?"*).
4. Walks subsequent sections one at a time with confirmation gates: per-area risks → specialty fit + tool setup offer → prioritisation → target pyramid → phased rollout → residual risks.
5. Final deliverable: a coherent strategy document; offers to write it to `docs/qa-strategy.md` only after the user confirms.

## Anti-patterns

- Single-shot dump: "Phase 1 unit tests, Phase 2 integration, Phase 3 e2e, aim for 80% coverage."
- Generic recommendation: *"introduce a QA Center of Excellence"*.
- Asks the user what services exist (read the repo).
- No residual risks listed (every strategy has them).
