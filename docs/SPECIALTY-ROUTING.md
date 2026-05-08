# Specialty Routing

When sumo-qa pulls in extra capability beyond the host's default test toolchain — and which tool fits which risk. Two parts: (1) the static `SPECIALTY_REGISTRY` (extension/path/classification-based detection) and (2) the tool-fit guide from `SENIOR_QA_SYSTEM_PROMPT`.

Every relevant response (`sumo_qa_review_local_change`, `sumo_qa_prepare_for_work`, `sumo_qa_answer_testing_question`, `sumo_qa_create_test_plan`, `sumo_qa_decide_approach`) carries `specialty_needs`. The rendered output shows it as a `Pull in:` block.

## Static registry

Source: [`src/sumo_qa/specialty_routing.py`](../src/sumo_qa/specialty_routing.py). The registry is the AI's grounding; the deterministic detector matches structural signals only (file extensions, path substrings, classifications) — never free-text phrases.

| Specialty | Approach | Well-known tools | When to use |
|---|---|---|---|
| `frontend_e2e` | Browser-driven E2E and component testing | Playwright, Cypress, Selenium, React Testing Library | UI behaviour, navigation, forms, component rendering. Triggers on `ui_only_change` or `.tsx` / `.jsx` / `.vue` / `.svelte` / `.html`. |
| `contract_testing` | Consumer-driven contract testing or schema validation | Pact, Schemathesis, Dredd, Spectral | API contracts, payload shapes, schema definitions, cross-service boundaries. Triggers on `api_contract_change` / `data_mapping_change`. |
| `performance_testing` | Load testing, latency profiling, throughput measurement | k6, Locust, JMeter, Gatling | Latency / throughput / concurrency in the acceptance bar. Triggers on `caching_change` / `async_flow_change`. |
| `security_testing` | SAST + DAST | OWASP ZAP, Burp Suite, Semgrep, Snyk, Bandit | Authentication, authorization, sensitive data, input parsing, anything user-supplied across a trust boundary. Triggers on `auth` / `security` / `credentials` path substrings. |
| `mobile_testing` | Mobile UI automation and on-device testing | Appium, Maestro, Detox, XCUITest, Espresso | iOS, Android, cross-platform mobile. Triggers on `.swift` / `.kt` / `.m` / `.mm` extensions or `/ios/` / `/android/` / `/mobile/` / `react-native` paths. |
| `ai_ml_testing` | LLM and ML evaluation, prompt regression, embedding sanity | Promptfoo, DeepEval, Evidently, Trulens, Ragas | LLM calls, prompts, embeddings, RAG retrieval, non-deterministic model behaviour. Triggers on `/ml/` / `/ai/` / `/llm/` / `/models/` / `/prompts` paths. |
| `accessibility_testing` | Automated + manual a11y validation against WCAG | axe-core, Pa11y, Lighthouse, NVDA, VoiceOver | Rendered UI, especially forms, navigation, modals, keyboard- or screen-reader-driven flows. Triggers on `ui_only_change`. |

Keyword matching uses word boundaries (so `aria` doesn't match inside `variants`, `auth` doesn't match inside `authentic`).

## Tool-fit guide

From `SENIOR_QA_SYSTEM_PROMPT` ([`src/sumo_qa/prompts.py`](../src/sumo_qa/prompts.py)). The principle: **the tool you name must FIT THE RISK**. Classification flags alone don't justify a specialty — the change has to genuinely cross a service boundary, exercise a non-functional concern (perf, security, a11y), or imply a specialty test discipline (mutation, property-based).

Positive examples per risk shape:

- **Token TTL / signature / claim validation:** JJWT integration tests, Auth0 java-jwt test fixtures, jose4j conformance suite. (Not OWASP ZAP — there's no HTTP surface to scan for a TTL bump.)
- **HTTP request/response handling, new endpoint, new auth filter:** OWASP ZAP, Burp Suite. DAST scanners only fit when there is an HTTP surface.
- **Static security analysis (alg=none, hard-coded secrets):** Semgrep, Snyk, SonarQube.
- **REST contract drift (consumer ↔ provider):** Pact (consumer-driven), Spring Cloud Contract, Schemathesis.
- **Async / event-driven contract drift:** Schemathesis (JSON-schema fuzzing), AsyncAPI test runners.
- **Frontend visual / interaction:** Cypress, Playwright. Forms / a11y rendering: axe-core (often via Playwright), Pa11y.
- **Mobile UI:** Appium, Maestro, Detox, XCUITest, Espresso.
- **Performance / load:** k6 (HTTP + gRPC), Locust, Gatling, JMeter.
- **Mutation testing / kill weak assertions:** Pitest (JVM), Stryker (JS / TS / .NET / Scala), MutPy / mutmut (Python).
- **AI / LLM behaviour:** Promptfoo, DeepEval, Ragas (RAG), Trulens, Evidently (drift / monitoring).

Specialty + tool pairings outside this guide are valid only if the risk justifies them — the rationale must explain the fit, not just the pairing.

When the target is purely in-process (a domain validator, pure function, internal helper, or any code with no HTTP / queue / UI / persistence / external integration boundary), `specialty_needs` MAY be `[]` and the reason placed under `assumptions`.
