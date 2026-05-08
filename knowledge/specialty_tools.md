# Specialty + tool fit catalogue

When a particular testing tool would meaningfully improve quality for a risk,
pick the fit from this catalogue. Specialty + tool fit applies to any quality
improvement, not only non-functional surfaces. Empty selection is acceptable
when nothing genuinely applies. The catalogue below is authoritative — do
not invent tools not in this list. If a risk needs a tool not catalogued,
flag the gap rather than confabulating.

## Token TTL / signature / claim validation
- JJWT integration tests
- Auth0 java-jwt test fixtures
- jose4j conformance suite

## HTTP request / response handling, new endpoint, new auth filter
- OWASP ZAP (DAST)
- Burp Suite (DAST)

DAST scanners only fit when there is an HTTP surface to scan. Do NOT
recommend ZAP or Burp for in-process pure functions.

## Static code analysis for security pitfalls (alg=none, hard-coded secrets)
- Semgrep
- Snyk
- SonarQube

## REST contract drift (consumer / provider)
- Pact (consumer-driven)
- Spring Cloud Contract
- Schemathesis (OpenAPI fuzzing)

## Async / event-driven contract drift
- Schemathesis (JSON-schema-based fuzzing)
- AsyncAPI test runners

## Frontend visual / interaction
- Cypress
- Playwright

## Frontend accessibility (a11y)
- axe-core (often via Playwright)
- Pa11y

## Mobile UI
- Appium
- Maestro
- Detox
- XCUITest
- Espresso

## Performance / load
- k6 (HTTP + gRPC)
- Locust
- Gatling
- JMeter

## Mutation testing / kill weak assertions
- Pitest (JVM)
- Stryker (JS / TS / .NET / Scala)
- MutPy / mutmut (Python)

## Property-based testing
- Hypothesis (Python)
- jqwik (JVM)
- fast-check (JS / TS)
- ScalaCheck (Scala)

## AI / LLM behaviour
- Promptfoo
- DeepEval
- Ragas (RAG)
- TruLens
- Evidently (drift / monitoring)

## Tool fit discipline

Specialty + tool pairings outside this catalogue are valid only if the
risk genuinely justifies them. Flag the fit in narrative; do not silently
introduce un-catalogued tools.
