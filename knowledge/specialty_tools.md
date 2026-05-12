# Specialty + tool fit — category primer

Category-fit primer, **NOT** a brand whitelist. Each section says WHEN that
specialty category applies. Brand names are illustrative — pick the best fit
from your knowledge of the user's stack, verify currency via web search when
uncertain. Once chosen, **install and set the tool up** (package manager,
framework CLI, config edit, or MCP server — whichever path is shortest) and
write the first tests against the named risks. Empty selection is acceptable.

---

**Token TTL / signature / claim validation** — JWT/JOSE/OAuth, signature
verify, claims, expiry. Examples: JJWT, Auth0 java-jwt, jose4j.

**HTTP DAST — new endpoint / auth filter** — header/CORS/auth bypasses on a
real HTTP surface (not in-process pure functions). Examples: OWASP ZAP, Burp Suite.

**Static security analysis** — hard-coded secrets, `alg=none`, SQLi, unsafe
deserialisation. Examples: Semgrep, Snyk, SonarQube.

**REST contract drift** — HTTP service with external consumers. Examples:
Pact (consumer-driven), Spring Cloud Contract, Schemathesis (OpenAPI fuzzing).

**Async / event contract drift** — handlers consuming events whose schemas
may drift. Examples: Schemathesis, AsyncAPI test runners.

**Frontend visual / interaction** — UI needing end-to-end browser coverage.
Examples: Cypress, Playwright. (MCP servers exist for some; package-manager
install is usually shorter.)

**Frontend a11y** — keyboard nav, screen readers, ARIA, contrast. Examples:
axe-core (often via Playwright), Pa11y.

**Mobile UI** — mobile app surface. Examples: Appium, Maestro, Detox, XCUITest, Espresso.

**Performance / load** — hot path with articulated SLO (p95, RPS). Without a
budget it's theatre. Examples: k6, Locust, Gatling, JMeter.

**Mutation testing** — coverage looks good but assertion strength suspect.
Examples: Pitest (JVM), Stryker (JS/TS/.NET/Scala), MutPy / mutmut (Python).

**Property-based** — invariant across many inputs (commutativity, idempotency,
round-trip, monotonicity). Examples: Hypothesis (Python), jqwik (JVM),
fast-check (JS/TS), ScalaCheck.

**AI / LLM behaviour** — probabilistic surfaces: prompts, RAG, agents.
Examples: Promptfoo, DeepEval, Ragas, TruLens, Evidently.

---

Discipline: pick by fit, not familiarity. Verify currency before naming.
Once chosen, set the tool up yourself (install, config, scaffold the first
tests) — don't hand the user a list of commands. Confirm before installing
dependencies. Empty selection is honest; most changes don't need this.
