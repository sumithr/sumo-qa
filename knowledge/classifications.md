# Canonical change classifications

Ten canonical classifications that shape testing strategy. The host LLM picks
which apply by reasoning over the user's intent and what each changed file does.
The catalogue is authoritative: never invent a classification outside it.

**The executable-behaviour rule:** a file is runtime when something executes,
imports, or follows it as instructions (an agent or operator, installer, CI job,
test runner helper), whatever its path or extension. The diff then decides: a
changed command, value, sentinel, branch or step hand-off is runtime; a
prose-only edit (typo, wording changing no step) keeps the lighter handling.

## api_contract_change
A change that adds, removes, or modifies a public API surface (HTTP endpoint,
gRPC method, public library function, event schema), including an MCP tool,
resource, or prompt (name, input schema, output schema, error envelope) and any
caller-visible serialization or versioned wire format, such as a new format
added to an existing tool or exporter. Risk: downstream consumers break on
signature drift. Refactoring an internal serializer with no observable output
change is `business_logic_change`, not this.

## business_logic_change
A change to domain rules, calculations, decision logic, or state machines.
Risk: incorrect outcomes for valid inputs.

## security_change
A change touching authentication, authorisation, secrets handling, encryption,
input sanitisation, rate limiting, audit logging. Risk: privilege escalation,
data leak, regression of a security control.

## performance_change
A change motivated by latency, throughput, memory, or resource consumption,
including caching, batching, query plan changes, and indexing.
Risk: regression in p99 or memory profile under load.

## frontend_change
A change to UI components, page layout, accessibility tree, client-side
interaction, or rendering. Risk: visual / interaction regressions, a11y
regressions.

## infrastructure_change
A change to deployment, IaC, runtime configuration, networking, or platform-
level concerns (Kubernetes manifests, Terraform, Docker, CI), and the tooling
they run: scripts, hooks, test runners, followed procedures. Risk:
environment-only failures invisible in unit tests.

## test_change
A change exclusively to test code or test fixtures, with no production code
movement. Includes mutation-testing follow-up, raise-coverage tasks,
strengthening weak assertions, and refactoring tests. Risk: false confidence
if tests become tautological. Executable test infrastructure (runner, matcher,
parser, grader, reporter, transform, fixture generator) is
`infrastructure_change` by the executable-behaviour rule; tests and fixtures
that only declare data or call the code under test stay here.

## docs_change
A change to documentation, comments, README, or any non-executable artefact.
Risk: minimal — typically no QA test work needed beyond build/lint. A changed
command, value or step in a procedure an agent or operator follows is runtime
by the executable-behaviour rule; a prose-only edit stays here.

## config_change
A change to configuration files (YAML, JSON, env files, feature flags) where
the configuration is consumed at runtime by existing code paths. Risk:
behaviour drift via the config without code review catching it.

## data_migration
A change that transforms persisted data (schema migration, backfill, ETL).
Risk: data loss, broken referential integrity, partial migrations.
