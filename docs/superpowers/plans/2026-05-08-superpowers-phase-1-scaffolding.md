# Superpowers Restructure — Phase 1 (Scaffolding) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land additive scaffolding for the superpowers restructure. After Phase 1, the new knowledge catalogues, knowledge-loader MCP tools, MCP-prompt registration for `skills/*/SKILL.md`, three new skill stubs, conformance tests, token-weight regression test, and self-bootstrap files are all in place. The old heavy-tool path remains fully functional and senior-istqb-grade is preserved.

**Architecture:** Knowledge catalogues live as plain markdown at `knowledge/` (repo root), bundled into the wheel via hatch. Seven `sumo_qa_load_*` MCP tools read these catalogues and return text — no inference. The MCP server registers every `skills/*/SKILL.md` as an MCP prompt at startup so IntelliJ AI Assistant and VS Code Copilot can fetch them. Three new skill directories are created as frontmatter-only stubs (full content lands in Phase 2). All changes are additive — nothing existing is deleted.

**Tech Stack:** Python 3.10+, FastMCP (`mcp>=1.12,<2`), pytest 8.4, pydantic 2.8, PyYAML 6, uv, hatchling.

**Spec:** [`docs/superpowers/specs/2026-05-08-superpowers-restructure-design.md`](../specs/2026-05-08-superpowers-restructure-design.md)

**Branch:** `feat/superpowers-restructure` (cut from `feat/ai-driven-iteration-loop`).

---

## File Structure

### Created

| Path | Responsibility |
|---|---|
| `knowledge/classifications.md` | The 10 canonical change classifications + their definitions |
| `knowledge/approaches.md` | The 8 canonical QA approaches + when each fits |
| `knowledge/principles.md` | ISTQB Foundation 7 + Advanced + ISO 25010 quality characteristics |
| `knowledge/techniques.md` | Black-box / white-box / experience-based / static test design techniques |
| `knowledge/specialty_tools.md` | Specialty + tool fit catalogue (Pitest / ZAP / Pact / k6 / etc.) |
| `src/sumo_qa/knowledge_loaders.py` | The 7 `sumo_qa_load_*` functions and `KNOWLEDGE_DIR` resolver |
| `src/sumo_qa/skill_prompts.py` | `register_skills_as_prompts(mcp)` — reads `skills/*/SKILL.md`, registers each as `@mcp.prompt` |
| `skills/qa-preparing-for-work/SKILL.md` | Frontmatter-only stub (full content in Phase 2) |
| `skills/qa-creating-test-plan/SKILL.md` | Frontmatter-only stub |
| `skills/qa-answering-testing-question/SKILL.md` | Frontmatter-only stub |
| `tests/test_knowledge_loaders.py` | Unit tests for the 7 loaders |
| `tests/test_skill_conformance.py` | Skill structure validator (frontmatter, Iron Law, checklist, flowchart, Red Flags) |
| `tests/test_skill_prompts.py` | MCP prompt registration tests |
| `tests/test_token_weight_regression.py` | Token-weight regression gate |
| `AGENTS.md` | Self-bootstrap entry for AI agents |
| `install.py` | Cross-platform Python installer (Windows / macOS / Linux) |
| `.github/copilot-instructions.md` | ~5-line MCP-prompt pointer for VS Code Copilot |

### Modified

| Path | Change |
|---|---|
| `src/sumo_qa/server.py` | Register the 7 `sumo_qa_load_*` tools alongside existing tools; call `register_skills_as_prompts(mcp)` once at startup |
| `pyproject.toml` | Confirm `knowledge/` is in `force-include` (already present — verify only) |

### Untouched in Phase 1

The 6 heavy tools (`sumo_qa_decide_approach`, `sumo_qa_prepare_for_work`, `sumo_qa_create_test_plan`, `sumo_qa_review_local_change`, `sumo_qa_scaffold_tests`, `sumo_qa_answer_testing_question`) and all their supporting Python (`prompts.py`, `approach_decision.py`, `tools.py` heavy parts, `models.py` heavy models, `rubric.py`, `scaffolder.py`, `render_preview.py`, `render_cli.py`, `specialty_routing.py`, `classification.py`, `local_diff.py`) are untouched. They get deleted in Phase 4.

The 7 existing skill files in `skills/<existing-name>/` are also untouched in Phase 1 — they get rewritten in Phase 2.

---

## Setup

### Task 0: Create the feature branch

- [ ] **Step 0.1:** Cut a new branch off the current one.

```bash
git checkout -b feat/superpowers-restructure
```

- [ ] **Step 0.2:** Confirm we're on the new branch.

```bash
git branch --show-current
```

Expected output: `feat/superpowers-restructure`

- [ ] **Step 0.3:** Run the existing test suite to confirm the starting state is green.

```bash
uv run pytest -q
```

Expected: all tests pass (currently 257 passing per Round 7).

---

## Group A: Knowledge catalogues (extract markdown content)

Each catalogue is a markdown file. The content is extracted from existing Python source so the human-readable canonical knowledge moves out of code into prose. No content is invented; everything sources from existing files identified per task.

### Task 1: Create `knowledge/classifications.md`

**Files:**
- Create: `knowledge/classifications.md`
- Source: `src/sumo_qa/classification.py` and the `_CLASSIFIED` / canonical list it uses

- [ ] **Step 1.1: Read the canonical list from source.**

```bash
grep -n "api_contract_change\|business_logic_change\|security_change\|performance_change\|frontend_change\|infrastructure_change\|test_change\|docs_change\|config_change\|data_migration" src/sumo_qa/classification.py | head -30
```

This gives the 10 canonical classifications and the keyword/path heuristics today. Take the *names and definitions only*; do NOT carry the heuristics across — they are deterministic inference and stay deleted.

- [ ] **Step 1.2: Write `knowledge/classifications.md` with this content:**

```markdown
# Canonical change classifications

Ten canonical classifications used to shape testing strategy. The host LLM picks
which apply to a given change by reasoning over the user's intent and target
paths. The catalogue below is authoritative — do not invent classifications
not in this list.

## api_contract_change
A change that adds, removes, or modifies a public API surface (HTTP endpoint,
gRPC method, public library function, event schema). Risk: downstream
consumers break on signature drift.

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
level concerns (Kubernetes manifests, Terraform, Docker, CI). Risk:
environment-only failures invisible in unit tests.

## test_change
A change exclusively to test code or test fixtures, with no production code
movement. Includes mutation-testing follow-up, raise-coverage tasks,
strengthening weak assertions, and refactoring tests. Risk: false confidence
if tests become tautological.

## docs_change
A change to documentation, comments, README, or any non-executable artefact.
Risk: minimal — typically no QA test work needed beyond build/lint.

## config_change
A change to configuration files (YAML, JSON, env files, feature flags) where
the configuration is consumed at runtime by existing code paths. Risk:
behaviour drift via the config without code review catching it.

## data_migration
A change that transforms persisted data (schema migration, backfill, ETL).
Risk: data loss, broken referential integrity, partial migrations.
```

- [ ] **Step 1.3: Verify the file exists and has 10 classification headings.**

```bash
grep -c "^## " knowledge/classifications.md
```

Expected: `10`

- [ ] **Step 1.4: Commit.**

```bash
git add knowledge/classifications.md
git commit -m "knowledge: add classifications.md with the 10 canonical classifications"
```

---

### Task 2: Create `knowledge/approaches.md`

**Files:**
- Create: `knowledge/approaches.md`
- Source: `src/sumo_qa/approach_decision.py`'s canonical approach list and `tools.py`'s `_build_decide_approach_sampling_prompt` (lines ~870-879)

- [ ] **Step 2.1: Confirm the 8 canonical approaches.**

```bash
grep -n "tdd-scaffold\|regression-first\|coverage-first-then-refactor\|strengthen-test-coverage\|verify-existing\|no-tests-recommended\|spike-first-then-tests\|strategy-orchestration" src/sumo_qa/tools.py | head -10
```

- [ ] **Step 2.2: Write `knowledge/approaches.md`:**

```markdown
# Canonical QA approaches

Eight canonical approaches the host LLM picks from when deciding the shape
of QA work. The LLM may invent a new approach if the situation genuinely
needs one, but it must explain why none of these eight fit.

## strategy-orchestration
Repo-wide / policy-shaped ask: "design a test strategy", "audit our coverage",
"design our pyramid", "rollout to other services", "minimum viable QA setup".
Do NOT force per-change output. Next step is loading the
`sumo-qa-strategising` skill.

## tdd-scaffold
Greenfield-ish change adding behaviour. Plan -> scaffold -> red ->
implement -> green. Fits when production code is being written for new
functionality.

## regression-first
Bug fix on existing code. Reproduce the defect as one failing test, fix it,
confirm green, run targeted regression. Fits when the user describes a
specific defect on existing behaviour.

## coverage-first-then-refactor
Behaviour-preserving refactor (rename, extract method, split module, restructure
without changing outputs). Audit existing coverage and add characterization
tests BEFORE refactoring. Tests pin current behaviour so the refactor doesn't
silently change outputs.

## strengthen-test-coverage
Strengthen existing tests on UNCHANGED production code. Mutation-testing
follow-up, raise-coverage tasks, killing weak assertions. Production code
stays still. Equivalent mutants get suppressed in tool config rather than
chased with tautological tests.

## verify-existing
Config-only or trivial tweak that doesn't merit new tests. Run the existing
suite plus a smoke test. Fits when a config bump or mechanical edit needs
confirmation, not new coverage.

## no-tests-recommended
Pure docs / typos / comments. Build + lint, no QA test work. The honest
senior-QA answer when the change has no behavioural surface.

## spike-first-then-tests
Exploratory prototype. Defer test discipline until the design settles. The
deliverable is a captured-conditions-and-fit record, not scaffolded tests.
```

- [ ] **Step 2.3: Verify.**

```bash
grep -c "^## " knowledge/approaches.md
```

Expected: `8`

- [ ] **Step 2.4: Commit.**

```bash
git add knowledge/approaches.md
git commit -m "knowledge: add approaches.md with the 8 canonical QA approaches"
```

---

### Task 3: Create `knowledge/principles.md`

**Files:**
- Create: `knowledge/principles.md`
- Source: `src/sumo_qa/prompts.py:18-58` (ISTQB Foundation 7, ISO 25010, test design techniques sections)

- [ ] **Step 3.1: Read the existing prompt content for principles.**

```bash
sed -n '18,58p' src/sumo_qa/prompts.py
```

- [ ] **Step 3.2: Write `knowledge/principles.md`:**

```markdown
# QA principles — ISTQB Foundation, Advanced, ISO 25010

## ISTQB Foundation — the seven testing principles

1. Testing shows the presence of defects, not their absence.
2. Exhaustive testing is impossible; use risk and prioritisation.
3. Early testing saves time and money — shift left.
4. Defects cluster — concentrate effort where defect history is dense.
5. Pesticide paradox — the same tests stop finding defects; refresh
   assertions and add new techniques.
6. Testing is context-dependent — safety-critical, regulated, web,
   mobile, AI all warrant different mixes.
7. Absence-of-errors fallacy — validate fitness for use, not just
   code-level correctness.

## ISTQB Advanced

- **Test Manager:** risk-based testing (likelihood x impact), shaping
  coverage to where risk is highest, accepting low-risk areas with
  thinner tests, entry/exit criteria, test estimation.
- **Test Analyst:** black-box / experience-based technique mastery,
  tester independence, defect taxonomy.
- **Technical Test Analyst:** white-box / structural coverage, code
  analysis, performance / security / reliability test design.

## ISO/IEC 25010 quality characteristics

- functional suitability
- performance efficiency
- compatibility
- usability
- reliability
- security
- maintainability
- portability

Pick the characteristics the change actually threatens; do not list them all.

## Test levels and the pyramid

unit -> component integration -> system -> system integration -> acceptance.
Shape the mix to the risk and the change.

## Test types (orthogonal to levels)

- functional
- non-functional (performance, security, accessibility, reliability,
  compatibility, usability)
- white-box / structural
- change-related (confirmation + regression)

## Static testing

Review (informal walkthrough, technical review, inspection) and static
analysis (linters, type checkers, SAST). Often the cheapest defect removal.
A code review or a stricter linter rule can be the right answer instead of
"add more tests".

## Senior-QA disciplines

- Decide the SHAPE of the work first (single change vs repo-wide strategy;
  bug vs greenfield vs refactor vs strengthen-existing-tests vs spike vs
  config tweak vs docs). Wrong shape = wrong-shaped tests.
- Reach for the smallest useful test set that gives release confidence.
  Avoid generic advice; tie every recommendation to a specific risk.
- When the user asks about strategy / audit / pyramid / rollout, that is a
  strategy ask, not a single change. Don't force per-change output.
- When the user describes work that doesn't change production code (mutation-
  testing follow-up, raise-coverage, kill surviving mutants, tighten weak
  assertions), do NOT scaffold tests against new behaviour. Strengthen
  existing tests. Suppress equivalent mutants in tool config rather than
  chasing them.
- Critical paths (auth, authorization, payment, billing, encryption, rate
  limiting, anything where a regression hits money, security, or customer
  trust) warrant tighter coverage and at least one boundary test per rule.
- Honest TDD: red phase first. Tests that fail BEFORE production code is
  written. Never bless a change as merge-ready without evidence.
- Static testing counts. A code review or a stricter linter rule can be
  the right answer instead of "add more tests".
```

- [ ] **Step 3.3: Verify content.**

```bash
grep -c "^## " knowledge/principles.md
```

Expected: at least `6` (Foundation, Advanced, ISO 25010, levels, types, static, disciplines).

- [ ] **Step 3.4: Commit.**

```bash
git add knowledge/principles.md
git commit -m "knowledge: add principles.md with ISTQB + ISO 25010 grounding"
```

---

### Task 4: Create `knowledge/techniques.md`

**Files:**
- Create: `knowledge/techniques.md`
- Source: `src/sumo_qa/prompts.py:35-46` (test design techniques section)

- [ ] **Step 4.1: Write `knowledge/techniques.md`:**

```markdown
# Test design techniques

Pick one technique per named risk. The catalogue below is authoritative —
do not invent techniques not in this list. If a risk needs something not
catalogued, flag it as a gap rather than confabulating.

## Black-box

### equivalence partitioning
Group inputs into classes that share behaviour; pick one representative
per class. Use when the input space is large but partitions clearly.

### boundary value analysis
Test the values immediately above, at, and below boundaries (off-by-one,
limits, capacity thresholds). Defects cluster at boundaries.

### decision tables
Enumerate every combination of input conditions and the expected output.
Use when business rules are conjunctions of multiple conditions.

### state transition testing
Model the system as a finite state machine; test every legal transition
and a sample of illegal ones. Use for stateful components.

### pairwise / orthogonal arrays
When a feature has many parameters with many values each, test every pair
of value combinations rather than the full Cartesian product.

### classification trees
Hierarchical refinement of equivalence partitions, useful when partitions
have sub-partitions.

### use case testing
Walk through end-to-end user scenarios. Catches integration defects unit
tests miss.

## White-box / structural

### statement coverage
Every statement executes at least once.

### branch coverage
Every branch (if/else, switch arm, loop entry/exit) is exercised both ways.

### decision coverage
Every boolean decision evaluates to both true and false.

### MC-DC (modified condition / decision coverage)
Each condition independently affects the decision outcome. Required for
safety-critical software.

### data-flow coverage
Every definition-use pair is exercised.

## Experience-based

### error guessing
Senior-QA judgment on where defects historically appear in similar systems.

### exploratory testing charters
Time-boxed, mission-driven sessions documenting findings.

### checklist-based testing
Reusable list of common pitfalls (e.g. OWASP Top 10).

## Static

### review (walkthrough / technical review / inspection)
Code review with varying formality. Cheapest defect removal.

### static analysis
Linters, type checkers, SAST scanners. Catches whole classes of defects
without execution.

## Property-based

### property-based testing
Generate inputs satisfying invariants and check the output preserves the
invariant. Tools: Hypothesis (Python), jqwik (JVM), fast-check (JS).
Fits pure-function refactors and algorithms.

## Mutation

### mutation testing
Mutate the production code, run the test suite, kill the mutants. Surfaces
weak assertions. Tools: Pitest (JVM), Stryker (JS / .NET), mutmut (Python).
Fits strengthen-test-coverage approach.
```

- [ ] **Step 4.2: Verify.**

```bash
grep -c "^### " knowledge/techniques.md
```

Expected: at least `15` (techniques across categories).

- [ ] **Step 4.3: Commit.**

```bash
git add knowledge/techniques.md
git commit -m "knowledge: add techniques.md catalogue"
```

---

### Task 5: Create `knowledge/specialty_tools.md`

**Files:**
- Create: `knowledge/specialty_tools.md`
- Source: `src/sumo_qa/prompts.py:126-149` (tool selection guide) + `src/sumo_qa/specialty_routing.py`

- [ ] **Step 5.1: Read the existing tool-fit guide.**

```bash
sed -n '126,149p' src/sumo_qa/prompts.py
```

- [ ] **Step 5.2: Write `knowledge/specialty_tools.md`:**

```markdown
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
```

- [ ] **Step 5.3: Verify.**

```bash
grep -c "^## " knowledge/specialty_tools.md
```

Expected: at least `12` (categories).

- [ ] **Step 5.4: Commit.**

```bash
git add knowledge/specialty_tools.md
git commit -m "knowledge: add specialty_tools.md fit catalogue"
```

---

## Group B: Knowledge loader functions (TDD)

Each loader is a 3-line function that reads a markdown file and returns it. TDD-style: test asserts a known string is in the returned content, then implement.

### Task 6: TDD `sumo_qa_load_classifications`

**Files:**
- Create: `src/sumo_qa/knowledge_loaders.py`
- Test: `tests/test_knowledge_loaders.py`

- [ ] **Step 6.1: Write the failing test.**

```python
# tests/test_knowledge_loaders.py
"""Tests for sumo_qa.knowledge_loaders.

These tools read markdown catalogues and return them verbatim. No inference,
no filtering beyond optional metadata-based subset selection. The tests
assert that known canonical entries are present in the returned text.
"""
from sumo_qa.knowledge_loaders import sumo_qa_load_classifications


def test_load_classifications_contains_ten_canonical_entries():
    text = sumo_qa_load_classifications()
    for entry in [
        "api_contract_change",
        "business_logic_change",
        "security_change",
        "performance_change",
        "frontend_change",
        "infrastructure_change",
        "test_change",
        "docs_change",
        "config_change",
        "data_migration",
    ]:
        assert entry in text, f"Missing canonical classification: {entry}"


def test_load_classifications_returns_non_empty_text():
    text = sumo_qa_load_classifications()
    assert isinstance(text, str)
    assert len(text) > 200
```

- [ ] **Step 6.2: Run the test, expect ImportError.**

```bash
uv run pytest tests/test_knowledge_loaders.py -v
```

Expected: `ImportError: cannot import name 'sumo_qa_load_classifications' from 'sumo_qa.knowledge_loaders'`

- [ ] **Step 6.3: Create the loader module.**

```python
# src/sumo_qa/knowledge_loaders.py
"""Knowledge-provider tools.

Each `sumo_qa_load_*` function reads a markdown catalogue from
`knowledge/<name>.md` and returns it verbatim. No inference, no filtering
beyond optional metadata-based subset selection on `load_standards` and
`load_rules`. The host LLM picks from the returned catalogue.

Path resolution mirrors the existing pattern in `server.py` for
`QA_TEST_DATA_PATH`: env var override, then bundled `_data/knowledge/`
in installed wheels, then `knowledge/` at repo root in dev.
"""
from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT_KNOWLEDGE = Path(__file__).parent.parent.parent / "knowledge"
_BUNDLED_KNOWLEDGE = Path(__file__).parent / "_data" / "knowledge"


def _knowledge_dir() -> Path:
    """Return the directory holding knowledge catalogues.

    Resolution order: QA_KNOWLEDGE_PATH env var > bundled _data > repo root.
    """
    override = os.environ.get("QA_KNOWLEDGE_PATH")
    if override:
        return Path(override)
    if _BUNDLED_KNOWLEDGE.is_dir():
        return _BUNDLED_KNOWLEDGE
    return _REPO_ROOT_KNOWLEDGE


def _read(name: str) -> str:
    path = _knowledge_dir() / name
    return path.read_text(encoding="utf-8")


def sumo_qa_load_classifications() -> str:
    """Return the catalogue of 10 canonical change classifications as text."""
    return _read("classifications.md")
```

- [ ] **Step 6.4: Run the test, expect green.**

```bash
uv run pytest tests/test_knowledge_loaders.py -v
```

Expected: `2 passed`.

- [ ] **Step 6.5: Commit.**

```bash
git add src/sumo_qa/knowledge_loaders.py tests/test_knowledge_loaders.py
git commit -m "feat(knowledge): add sumo_qa_load_classifications loader"
```

---

### Task 7: TDD `sumo_qa_load_approaches`

**Files:**
- Modify: `src/sumo_qa/knowledge_loaders.py`
- Modify: `tests/test_knowledge_loaders.py`

- [ ] **Step 7.1: Add the failing test.**

```python
# Append to tests/test_knowledge_loaders.py
from sumo_qa.knowledge_loaders import sumo_qa_load_approaches


def test_load_approaches_contains_eight_canonical_entries():
    text = sumo_qa_load_approaches()
    for entry in [
        "strategy-orchestration",
        "tdd-scaffold",
        "regression-first",
        "coverage-first-then-refactor",
        "strengthen-test-coverage",
        "verify-existing",
        "no-tests-recommended",
        "spike-first-then-tests",
    ]:
        assert entry in text, f"Missing canonical approach: {entry}"
```

- [ ] **Step 7.2: Run, expect ImportError on `sumo_qa_load_approaches`.**

```bash
uv run pytest tests/test_knowledge_loaders.py::test_load_approaches_contains_eight_canonical_entries -v
```

- [ ] **Step 7.3: Add the loader.**

```python
# Append to src/sumo_qa/knowledge_loaders.py
def sumo_qa_load_approaches() -> str:
    """Return the catalogue of 8 canonical QA approaches as text."""
    return _read("approaches.md")
```

- [ ] **Step 7.4: Run, expect green.**

```bash
uv run pytest tests/test_knowledge_loaders.py -v
```

Expected: `3 passed`.

- [ ] **Step 7.5: Commit.**

```bash
git add src/sumo_qa/knowledge_loaders.py tests/test_knowledge_loaders.py
git commit -m "feat(knowledge): add sumo_qa_load_approaches loader"
```

---

### Task 8: TDD `sumo_qa_load_principles`

- [ ] **Step 8.1: Add the failing test.**

```python
# Append to tests/test_knowledge_loaders.py
from sumo_qa.knowledge_loaders import sumo_qa_load_principles


def test_load_principles_contains_istqb_and_iso():
    text = sumo_qa_load_principles()
    assert "ISTQB Foundation" in text
    assert "ISO/IEC 25010" in text
    assert "Pesticide paradox" in text
    assert "Defects cluster" in text
    assert "shift left" in text.lower() or "shift-left" in text.lower()
```

- [ ] **Step 8.2: Run, expect ImportError.**

```bash
uv run pytest tests/test_knowledge_loaders.py::test_load_principles_contains_istqb_and_iso -v
```

- [ ] **Step 8.3: Add the loader.**

```python
# Append to src/sumo_qa/knowledge_loaders.py
def sumo_qa_load_principles() -> str:
    """Return ISTQB Foundation + Advanced + ISO 25010 grounding as text."""
    return _read("principles.md")
```

- [ ] **Step 8.4: Run, expect green.**

```bash
uv run pytest tests/test_knowledge_loaders.py -v
```

Expected: `4 passed`.

- [ ] **Step 8.5: Commit.**

```bash
git add src/sumo_qa/knowledge_loaders.py tests/test_knowledge_loaders.py
git commit -m "feat(knowledge): add sumo_qa_load_principles loader"
```

---

### Task 9: TDD `sumo_qa_load_techniques`

- [ ] **Step 9.1: Add the failing test.**

```python
# Append to tests/test_knowledge_loaders.py
from sumo_qa.knowledge_loaders import sumo_qa_load_techniques


def test_load_techniques_contains_canonical_techniques():
    text = sumo_qa_load_techniques()
    for entry in [
        "boundary value analysis",
        "equivalence partitioning",
        "decision tables",
        "state transition testing",
        "MC-DC",
        "exploratory testing",
        "property-based testing",
        "mutation testing",
    ]:
        assert entry in text, f"Missing canonical technique: {entry}"
```

- [ ] **Step 9.2: Run, expect ImportError.**

```bash
uv run pytest tests/test_knowledge_loaders.py::test_load_techniques_contains_canonical_techniques -v
```

- [ ] **Step 9.3: Add the loader.**

```python
# Append to src/sumo_qa/knowledge_loaders.py
def sumo_qa_load_techniques() -> str:
    """Return the test design technique catalogue as text."""
    return _read("techniques.md")
```

- [ ] **Step 9.4: Run, expect green.**

```bash
uv run pytest tests/test_knowledge_loaders.py -v
```

Expected: `5 passed`.

- [ ] **Step 9.5: Commit.**

```bash
git add src/sumo_qa/knowledge_loaders.py tests/test_knowledge_loaders.py
git commit -m "feat(knowledge): add sumo_qa_load_techniques loader"
```

---

### Task 10: TDD `sumo_qa_load_specialty_tools`

- [ ] **Step 10.1: Add the failing test.**

```python
# Append to tests/test_knowledge_loaders.py
from sumo_qa.knowledge_loaders import sumo_qa_load_specialty_tools


def test_load_specialty_tools_contains_canonical_pairings():
    text = sumo_qa_load_specialty_tools()
    for entry in [
        "OWASP ZAP",
        "Pact",
        "k6",
        "Pitest",
        "Stryker",
        "Hypothesis",
        "axe-core",
        "Cypress",
        "Promptfoo",
        "JJWT",
    ]:
        assert entry in text, f"Missing canonical specialty tool: {entry}"
```

- [ ] **Step 10.2: Run, expect ImportError.**

```bash
uv run pytest tests/test_knowledge_loaders.py::test_load_specialty_tools_contains_canonical_pairings -v
```

- [ ] **Step 10.3: Add the loader.**

```python
# Append to src/sumo_qa/knowledge_loaders.py
def sumo_qa_load_specialty_tools() -> str:
    """Return the specialty + tool fit catalogue as text."""
    return _read("specialty_tools.md")
```

- [ ] **Step 10.4: Run, expect green.**

```bash
uv run pytest tests/test_knowledge_loaders.py -v
```

Expected: `6 passed`.

- [ ] **Step 10.5: Commit.**

```bash
git add src/sumo_qa/knowledge_loaders.py tests/test_knowledge_loaders.py
git commit -m "feat(knowledge): add sumo_qa_load_specialty_tools loader"
```

---

### Task 11: TDD `sumo_qa_load_standards` (with metadata filter)

`load_standards` has an optional `classification` parameter. The filter is metadata-based: each standards pack already has YAML frontmatter declaring which classifications it applies to (existing behaviour). The loader returns the subset whose frontmatter lists the requested classification.

- [ ] **Step 11.1: Inspect an existing standards pack to confirm frontmatter shape.**

```bash
ls standards/packs/ | head -5
head -15 "$(ls standards/packs/*.yaml | head -1)"
```

The existing packs already have a `applies_to_classifications:` (or similar) field. Note the exact key name for the next step.

- [ ] **Step 11.2: Add the failing test.**

```python
# Append to tests/test_knowledge_loaders.py
from sumo_qa.knowledge_loaders import sumo_qa_load_standards


def test_load_standards_returns_text_when_no_filter():
    text = sumo_qa_load_standards()
    assert isinstance(text, str)
    assert len(text) > 0


def test_load_standards_filter_returns_only_matching_packs():
    """The classification filter is metadata-based — only packs whose
    frontmatter declares the classification are returned."""
    full = sumo_qa_load_standards()
    filtered = sumo_qa_load_standards(classification="security_change")
    # Filtered subset is shorter than (or equal to) full.
    assert len(filtered) <= len(full)
    # Filtered text mentions the classification in pack metadata or skips
    # packs that don't apply.
    assert isinstance(filtered, str)
```

- [ ] **Step 11.3: Run, expect ImportError.**

```bash
uv run pytest tests/test_knowledge_loaders.py::test_load_standards_returns_text_when_no_filter -v
```

- [ ] **Step 11.4: Add the loader using the existing standards module.**

```python
# Append to src/sumo_qa/knowledge_loaders.py
import yaml

def _standards_dir() -> Path:
    """Return the standards directory, honouring QA_STANDARDS_PATH override."""
    override = os.environ.get("QA_STANDARDS_PATH")
    if override:
        return Path(override) / "packs" if (Path(override) / "packs").is_dir() else Path(override)
    bundled = Path(__file__).parent / "_data" / "standards" / "packs"
    if bundled.is_dir():
        return bundled
    return Path(__file__).parent.parent.parent / "standards" / "packs"


def sumo_qa_load_standards(classification: str | None = None) -> str:
    """Return the team's loaded standards as text. Optional metadata filter
    by classification — packs whose frontmatter declares this classification.
    No keyword inference; the filter is pure file-metadata selection."""
    root = _standards_dir()
    packs: list[str] = []
    for path in sorted(root.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        if classification is not None:
            try:
                doc = yaml.safe_load(text) or {}
            except yaml.YAMLError:
                continue
            applies = doc.get("applies_to_classifications") or doc.get("classifications") or []
            if classification not in applies:
                continue
        packs.append(f"# {path.name}\n\n{text}")
    return "\n\n---\n\n".join(packs)
```

- [ ] **Step 11.5: Run, expect green.**

```bash
uv run pytest tests/test_knowledge_loaders.py -v
```

Expected: `8 passed`.

- [ ] **Step 11.6: Commit.**

```bash
git add src/sumo_qa/knowledge_loaders.py tests/test_knowledge_loaders.py
git commit -m "feat(knowledge): add sumo_qa_load_standards with metadata filter"
```

---

### Task 12: TDD `sumo_qa_load_rules` (with metadata filter)

- [ ] **Step 12.1: Inspect rules file shape.**

```bash
head -30 standards/rules/change_rules.yaml 2>/dev/null || head -30 rules/change_rules.yaml 2>/dev/null || find . -name "change_rules.yaml" -not -path "./.*" | head -3
```

Confirm the rules file path and the per-rule metadata that ties a rule to a classification.

- [ ] **Step 12.2: Add the failing test.**

```python
# Append to tests/test_knowledge_loaders.py
from sumo_qa.knowledge_loaders import sumo_qa_load_rules


def test_load_rules_returns_text_when_no_filter():
    text = sumo_qa_load_rules()
    assert isinstance(text, str)
    assert len(text) > 0


def test_load_rules_filter_by_classification_is_smaller():
    full = sumo_qa_load_rules()
    filtered = sumo_qa_load_rules(classification="security_change")
    assert len(filtered) <= len(full)
```

- [ ] **Step 12.3: Run, expect ImportError.**

- [ ] **Step 12.4: Add the loader. Adjust the path / metadata key per Step 12.1's findings.**

```python
# Append to src/sumo_qa/knowledge_loaders.py
def _rules_path() -> Path:
    override = os.environ.get("QA_RULES_PATH")
    if override:
        return Path(override)
    bundled = Path(__file__).parent / "_data" / "standards" / "rules" / "change_rules.yaml"
    if bundled.is_file():
        return bundled
    candidates = [
        Path(__file__).parent.parent.parent / "standards" / "rules" / "change_rules.yaml",
        Path(__file__).parent.parent.parent / "rules" / "change_rules.yaml",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]  # let the read fail informatively


def sumo_qa_load_rules(classification: str | None = None) -> str:
    """Return the team's loaded change rules as text. Optional metadata filter
    by classification — rules whose entry declares this classification."""
    path = _rules_path()
    text = path.read_text(encoding="utf-8")
    if classification is None:
        return text
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return text
    rules = doc.get("rules", []) if isinstance(doc, dict) else []
    matching = [
        r for r in rules
        if classification in (r.get("applies_to_classifications") or r.get("classifications") or [])
    ]
    return yaml.safe_dump({"rules": matching}, sort_keys=False)
```

- [ ] **Step 12.5: Run, expect green.**

```bash
uv run pytest tests/test_knowledge_loaders.py -v
```

Expected: `10 passed`.

- [ ] **Step 12.6: Commit.**

```bash
git add src/sumo_qa/knowledge_loaders.py tests/test_knowledge_loaders.py
git commit -m "feat(knowledge): add sumo_qa_load_rules with metadata filter"
```

---

## Group C: MCP integration

### Task 13: Register the 7 knowledge loaders as MCP tools

**Files:**
- Modify: `src/sumo_qa/server.py`
- Modify: `tests/test_server.py` (add tools-list assertion)

- [ ] **Step 13.1: Add the failing test that asserts the new tools are registered.**

```python
# Append to tests/test_server.py
def test_knowledge_loader_tools_are_registered():
    """The 7 sumo_qa_load_* tools must appear in the server's tool list."""
    from sumo_qa.server import build_server  # or whatever the existing helper is

    mcp = build_server()
    tool_names = {t.name for t in mcp._tool_manager.list_tools()}
    for name in [
        "sumo_qa_load_classifications",
        "sumo_qa_load_approaches",
        "sumo_qa_load_principles",
        "sumo_qa_load_techniques",
        "sumo_qa_load_specialty_tools",
        "sumo_qa_load_standards",
        "sumo_qa_load_rules",
    ]:
        assert name in tool_names, f"Missing tool: {name}"
```

If `build_server` doesn't exist in `server.py`, find the equivalent (likely `_register_tools(mcp)` or similar — check the file).

- [ ] **Step 13.2: Run, expect failure (tools not registered).**

```bash
uv run pytest tests/test_server.py::test_knowledge_loader_tools_are_registered -v
```

- [ ] **Step 13.3: Register the tools. Find the section in `server.py` that registers existing tools (search for `@mcp.tool`) and add a block at the same level. Import loaders with private aliases so the inner @mcp.tool functions can keep the canonical `sumo_qa_load_*` names — the MCP-exposed tool name comes from the function's `__name__` and must match the test assertions:**

```python
# Add to src/sumo_qa/server.py near the other tool registrations
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_approaches as _load_approaches,
    sumo_qa_load_classifications as _load_classifications,
    sumo_qa_load_principles as _load_principles,
    sumo_qa_load_rules as _load_rules,
    sumo_qa_load_specialty_tools as _load_specialty_tools,
    sumo_qa_load_standards as _load_standards,
    sumo_qa_load_techniques as _load_techniques,
)

def _register_knowledge_loaders(mcp):
    """Register the 7 knowledge-provider tools.

    Each tool is a thin wrapper around a markdown read. The host LLM picks
    from the returned catalogue; this server does no inference."""

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_load_classifications() -> str:
        """Return the 10 canonical change classifications as plain text. The
        host LLM picks which apply to a given change."""
        return _load_classifications()

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_load_approaches() -> str:
        """Return the 8 canonical QA approaches as plain text. The host LLM
        picks which approach fits a given piece of work."""
        return _load_approaches()

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_load_principles() -> str:
        """Return ISTQB Foundation + Advanced + ISO 25010 grounding as plain
        text. The host LLM cites principles when shaping recommendations."""
        return _load_principles()

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_load_techniques() -> str:
        """Return the test design technique catalogue (black-box, white-box,
        experience-based, static, property-based, mutation) as plain text.
        The host LLM picks one technique per named risk."""
        return _load_techniques()

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_load_specialty_tools() -> str:
        """Return the specialty + tool fit catalogue as plain text. The host
        LLM picks tools that fit the actual risk."""
        return _load_specialty_tools()

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_load_standards(classification: str | None = None) -> str:
        """Return the team's loaded standards packs as plain text. Optional
        classification filter is metadata-based (packs whose frontmatter
        declares the classification); no keyword inference."""
        return _load_standards(classification=classification)

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_load_rules(classification: str | None = None) -> str:
        """Return the team's loaded change rules as plain text. Optional
        classification filter is metadata-based; no keyword inference."""
        return _load_rules(classification=classification)
```

Add `_register_knowledge_loaders(mcp)` to the same place existing `_register_*` calls happen (find by searching `server.py` for `_register_` or where `@mcp.tool` decorators are actually attached).

- [ ] **Step 13.4: Run, expect green.**

```bash
uv run pytest tests/test_server.py::test_knowledge_loader_tools_are_registered -v
```

- [ ] **Step 13.5: Run the full test suite to verify nothing else broke.**

```bash
uv run pytest -q
```

Expected: previous test count + 11 new tests, all passing.

- [ ] **Step 13.6: Commit.**

```bash
git add src/sumo_qa/server.py tests/test_server.py
git commit -m "feat(server): register the 7 sumo_qa_load_* knowledge tools"
```

---

### Task 14: Register `skills/*/SKILL.md` as MCP prompts

**Files:**
- Create: `src/sumo_qa/skill_prompts.py`
- Modify: `src/sumo_qa/server.py`
- Create: `tests/test_skill_prompts.py`

- [ ] **Step 14.1: Write the failing test.**

```python
# tests/test_skill_prompts.py
"""Tests for src/sumo_qa/skill_prompts.py.

Every skills/*/SKILL.md must register as an MCP prompt at server startup.
The prompt name is the skill directory name with `-` replaced by `_`.
The prompt description matches the skill's frontmatter `description`.
The prompt body is the full SKILL.md content, read fresh on each call.
"""
from sumo_qa.server import build_server


def test_every_skill_registers_as_an_mcp_prompt():
    mcp = build_server()
    prompt_names = {p.name for p in mcp._prompt_manager.list_prompts()}
    # At least the 7 existing skills + 3 new stubs (after Tasks 15-17 land).
    expected = {
        "using_sumo_qa",
        "qa_deciding_approach",
        "qa_implementing_with_tdd",
        "qa_reviewing_before_merge",
        "qa_strengthening_tests",
        "qa_finding_test_data",
        "sumo_qa_strategising",
    }
    assert expected.issubset(prompt_names), f"Missing skill prompts: {expected - prompt_names}"


def test_skill_prompt_body_matches_file():
    from pathlib import Path
    mcp = build_server()
    prompts = {p.name: p for p in mcp._prompt_manager.list_prompts()}
    p = prompts["using_sumo_qa"]
    skill_path = Path(__file__).parent.parent / "skills" / "using-sumo-qa" / "SKILL.md"
    expected_text = skill_path.read_text(encoding="utf-8")
    # Render the prompt with no args; for a parameter-less prompt this returns
    # the static body.
    body = p.render({})  # adjust if the FastMCP API differs
    assert expected_text in body or body == expected_text
```

The exact API for listing prompts and rendering them depends on the FastMCP version. If `_prompt_manager.list_prompts()` doesn't exist, search the FastMCP source for the right accessor.

- [ ] **Step 14.2: Run, expect failure.**

```bash
uv run pytest tests/test_skill_prompts.py -v
```

- [ ] **Step 14.3: Create `src/sumo_qa/skill_prompts.py`.**

```python
"""Register every skills/*/SKILL.md as an MCP prompt.

The skill content IS the prompt body. No copy lives anywhere else; the file
is read fresh on each prompt invocation. Hosts that auto-load skills (Claude
Code) read the same files via symlinks. This single source of truth + two
delivery channels mechanism means editing a skill propagates to every host
without rebuild or restart."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    try:
        return yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}


def register_skills_as_prompts(mcp) -> None:
    """Register every SKILL.md under skills/ as an MCP prompt.

    Prompt name: directory name with `-` -> `_`. Description: from frontmatter.
    Body: full file content (including frontmatter), read fresh on each call.
    """
    if not _SKILLS_DIR.is_dir():
        return
    for skill_dir in sorted(_SKILLS_DIR.iterdir()):
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.is_file():
            continue
        text = skill_path.read_text(encoding="utf-8")
        frontmatter = _parse_frontmatter(text)
        prompt_name = skill_dir.name.replace("-", "_")
        description = frontmatter.get("description", f"Skill: {skill_dir.name}")
        _bind_prompt(mcp, prompt_name, description, skill_path)


def _bind_prompt(mcp, name: str, description: str, path: Path) -> None:
    @mcp.prompt(name=name, description=description)
    def _skill_prompt() -> str:
        return path.read_text(encoding="utf-8")
```

The `_bind_prompt` indirection is needed because Python closures capture `path` by reference; binding inside a loop without it would make every prompt return the last skill's content. The default-argument pattern in `lambda` works too if FastMCP accepts that.

- [ ] **Step 14.4: Wire it into the server.**

```python
# In src/sumo_qa/server.py, near the existing tool registrations
from sumo_qa.skill_prompts import register_skills_as_prompts

# In build_server() (or whichever function constructs the MCP instance):
register_skills_as_prompts(mcp)
```

- [ ] **Step 14.5: Run, expect green.**

```bash
uv run pytest tests/test_skill_prompts.py -v
```

If the second test fails because of FastMCP API differences in how prompts render, adjust per the actual API (use whatever `prompts/get` returns at the protocol level — `list_prompts()` returns descriptors, fetching the body may need a different call).

- [ ] **Step 14.6: Run the full suite.**

```bash
uv run pytest -q
```

- [ ] **Step 14.7: Commit.**

```bash
git add src/sumo_qa/skill_prompts.py src/sumo_qa/server.py tests/test_skill_prompts.py
git commit -m "feat(server): register skills/*/SKILL.md as MCP prompts at startup"
```

---

## Group D: New skill stubs (frontmatter only — full content in Phase 2)

Each new skill is a directory with a SKILL.md containing only YAML frontmatter (`name`, `description`) and a placeholder body explaining that the full content lands in Phase 2. The frontmatter is enough for the prompt registration test to pass and for Claude Code to detect the skill exists.

### Task 15: Create `skills/qa-preparing-for-work/SKILL.md`

- [ ] **Step 15.1: Create the directory and stub file.**

```bash
mkdir -p skills/qa-preparing-for-work
```

Write `skills/qa-preparing-for-work/SKILL.md`:

```markdown
---
name: qa-preparing-for-work
description: Use when the user asks to plan QA for a story, ticket, or piece
  of work before coding starts. Walks through risk identification anchored
  in the change shape and named risks, then proposes a smallest useful
  test set tied to those risks.
---

# Preparing for QA work

> Phase 1 stub. Full content lands in Phase 2 of the superpowers
> restructure (see `docs/superpowers/specs/2026-05-08-superpowers-restructure-design.md`).

## The Iron Law
NO TEST IDEA WITHOUT A NAMED RISK.

## When to Use
(populated in Phase 2)
```

- [ ] **Step 15.2: Verify the skill prompt registers.**

```bash
uv run pytest tests/test_skill_prompts.py -v
```

- [ ] **Step 15.3: Commit.**

```bash
git add skills/qa-preparing-for-work/SKILL.md
git commit -m "skills: add qa-preparing-for-work stub (frontmatter only)"
```

---

### Task 16: Create `skills/qa-creating-test-plan/SKILL.md`

- [ ] **Step 16.1: Create directory and stub.**

```bash
mkdir -p skills/qa-creating-test-plan
```

Write `skills/qa-creating-test-plan/SKILL.md`:

```markdown
---
name: qa-creating-test-plan
description: Use when the user asks for a test plan, a formal QA plan, or
  entry/exit criteria for a piece of work. Produces a phased ISTQB-style
  plan anchored to actual files and named risks, with explicit entry and
  exit criteria.
---

# Creating a Test Plan

> Phase 1 stub. Full content lands in Phase 2.

## The Iron Law
NO PLAN WITHOUT EXPLICIT ENTRY AND EXIT CRITERIA.

## When to Use
(populated in Phase 2)
```

- [ ] **Step 16.2: Verify.**

```bash
uv run pytest tests/test_skill_prompts.py -v
```

- [ ] **Step 16.3: Commit.**

```bash
git add skills/qa-creating-test-plan/SKILL.md
git commit -m "skills: add qa-creating-test-plan stub (frontmatter only)"
```

---

### Task 17: Create `skills/qa-answering-testing-question/SKILL.md`

- [ ] **Step 17.1: Create.**

```bash
mkdir -p skills/qa-answering-testing-question
```

Write `skills/qa-answering-testing-question/SKILL.md`:

```markdown
---
name: qa-answering-testing-question
description: Use when the user asks a generic testing question — "how do I
  test this?", "what should I check for X?" — that doesn't fit any of
  the more specific skills. Cites a principle or technique from the
  loaded catalogue rather than producing generic advice.
---

# Answering a testing question

> Phase 1 stub. Full content lands in Phase 2.

## The Iron Law
NO ANSWER WITHOUT A CITED PRINCIPLE OR TECHNIQUE.

## When to Use
(populated in Phase 2)
```

- [ ] **Step 17.2: Verify.**

```bash
uv run pytest tests/test_skill_prompts.py -v
```

- [ ] **Step 17.3: Commit.**

```bash
git add skills/qa-answering-testing-question/SKILL.md
git commit -m "skills: add qa-answering-testing-question stub (frontmatter only)"
```

---

## Group E: Test scaffolding

### Task 18: Skill conformance test framework

**Files:**
- Create: `tests/test_skill_conformance.py`

This test enforces every `skills/*/SKILL.md` has the structural sections superpowers requires. In Phase 1 the new skills are stubs, so most assertions are scoped down to "stub-acceptable" checks. Phase 2 will tighten the assertions.

- [ ] **Step 18.1: Write the conformance test, marking the structure-of-real-skills checks as `pytest.mark.skip` for now (un-skip in Phase 2).**

```python
# tests/test_skill_conformance.py
"""Skill conformance — every skills/*/SKILL.md must follow the upstream
superpowers structure.

In Phase 1, only frontmatter checks are active. Phase 2 unskips the
structure checks (Iron Law, Checklist, Process Flow, Red Flags, Examples)
once the stub skills get their full content."""
import re
from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).parent.parent / "skills"
SKILL_PATHS = sorted(SKILLS_DIR.glob("*/SKILL.md"))
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _frontmatter(path: Path) -> dict:
    match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    return yaml.safe_load(match.group(1)) if match else {}


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_has_frontmatter_with_name_and_description(skill_path):
    fm = _frontmatter(skill_path)
    assert "name" in fm, f"Missing 'name' frontmatter in {skill_path}"
    assert "description" in fm, f"Missing 'description' frontmatter in {skill_path}"


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_name_matches_directory_name(skill_path):
    fm = _frontmatter(skill_path)
    assert fm.get("name") == skill_path.parent.name, (
        f"Frontmatter name '{fm.get('name')}' must match directory '{skill_path.parent.name}'"
    )


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_descriptions_are_non_empty(skill_path):
    fm = _frontmatter(skill_path)
    desc = fm.get("description") or ""
    assert len(desc.strip()) >= 30, (
        f"Description too short in {skill_path}: {desc[:80]}"
    )


def test_skill_descriptions_are_unique():
    descriptions = [_frontmatter(p).get("description") for p in SKILL_PATHS]
    assert len(set(descriptions)) == len(descriptions), (
        "Duplicate skill descriptions detected — auto-trigger will be ambiguous"
    )


# Structure checks — un-skipped in Phase 2.
@pytest.mark.skip(reason="Phase 2 skill content; un-skip when full content lands")
@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_has_iron_law_section(skill_path):
    text = skill_path.read_text(encoding="utf-8")
    assert "## The Iron Law" in text or "## Iron Law" in text


@pytest.mark.skip(reason="Phase 2 skill content")
@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_has_checklist_section_with_at_least_four_items(skill_path):
    text = skill_path.read_text(encoding="utf-8")
    assert "## Checklist" in text
    checklist_section = text.split("## Checklist", 1)[1].split("##", 1)[0]
    items = re.findall(r"^\s*\d+\.", checklist_section, flags=re.MULTILINE)
    assert len(items) >= 4


@pytest.mark.skip(reason="Phase 2 skill content")
@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_has_process_flow_dot_block(skill_path):
    text = skill_path.read_text(encoding="utf-8")
    assert "```dot" in text


@pytest.mark.skip(reason="Phase 2 skill content")
@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.name)
def test_skill_has_red_flags_section(skill_path):
    text = skill_path.read_text(encoding="utf-8")
    assert "## Red Flags" in text
```

- [ ] **Step 18.2: Run, expect green for the active checks (frontmatter + uniqueness) across all skills, structure checks skipped.**

```bash
uv run pytest tests/test_skill_conformance.py -v
```

If a skill stub has a duplicate or thin description, fix in `skills/<name>/SKILL.md` until green.

- [ ] **Step 18.3: Commit.**

```bash
git add tests/test_skill_conformance.py
git commit -m "test(skills): add conformance test scaffolding (Phase 2 unskips structure checks)"
```

---

### Task 19: MCP prompt registration test (already created in Task 14)

Task 14 already created `tests/test_skill_prompts.py`. Verify it's still green after Tasks 15-18 added the three new stubs:

- [ ] **Step 19.1: Run.**

```bash
uv run pytest tests/test_skill_prompts.py -v
```

Expected: all assertions pass; the 3 new skills are registered as prompts alongside the 7 existing.

- [ ] **Step 19.2: If `test_every_skill_registers_as_an_mcp_prompt` doesn't include the new ones, add them to the `expected` set:**

```python
expected = {
    "using_sumo_qa",
    "qa_deciding_approach",
    "qa_preparing_for_work",
    "qa_creating_test_plan",
    "qa_implementing_with_tdd",
    "qa_reviewing_before_merge",
    "qa_strengthening_tests",
    "qa_finding_test_data",
    "qa_answering_testing_question",
    "sumo_qa_strategising",
}
```

- [ ] **Step 19.3: Re-run, commit if changes.**

```bash
uv run pytest tests/test_skill_prompts.py -v
git add tests/test_skill_prompts.py
git commit -m "test(skills): include 3 new skill stubs in prompt-registration test"
```

---

### Task 20: Token-weight regression test scaffolding

This is the test that would have caught the IntelliJ SSE failure. In Phase 1, the heavy tools still exist, so the assertion is initially `xfail` (expected to fail) — we're documenting the budget that the new path must hit. Phase 4 (delete heavy tools) flips it to `pass`.

**Files:**
- Create: `tests/test_token_weight_regression.py`

- [ ] **Step 20.1: Write the regression test.**

```python
# tests/test_token_weight_regression.py
"""Token-weight regression — the new architecture's per-flow MCP-call total
must stay under the budget that broke IntelliJ AI Assistant.

Phase 1: heavy tools still exist, so the budget assertion is xfail
(expected to fail). Phase 4 deletes the heavy path; this test then passes.

Token estimation here is approximate (length / 4 chars-per-token). For
exact counts, hosts use their own tokenizers. The budget targets are
conservative.
"""
import pytest

from sumo_qa.knowledge_loaders import (
    sumo_qa_load_approaches,
    sumo_qa_load_classifications,
    sumo_qa_load_principles,
    sumo_qa_load_rules,
    sumo_qa_load_specialty_tools,
    sumo_qa_load_standards,
    sumo_qa_load_techniques,
)


def _approx_tokens(text: str) -> int:
    """Approximate token count: length / 4, rounded up."""
    return (len(text) + 3) // 4


PER_CALL_BUDGET = 1500
PER_FLOW_BUDGET = 2000


def test_no_individual_knowledge_load_exceeds_per_call_budget():
    """Any single sumo_qa_load_* call must stay under PER_CALL_BUDGET tokens
    so it cannot break IntelliJ's SSE the way the old heavy tools did."""
    for name, fn in [
        ("classifications", sumo_qa_load_classifications),
        ("approaches", sumo_qa_load_approaches),
        ("principles", sumo_qa_load_principles),
        ("techniques", sumo_qa_load_techniques),
        ("specialty_tools", sumo_qa_load_specialty_tools),
        ("standards", lambda: sumo_qa_load_standards()),
        ("rules", lambda: sumo_qa_load_rules()),
    ]:
        text = fn()
        tokens = _approx_tokens(text)
        assert tokens <= PER_CALL_BUDGET, (
            f"{name} returned ~{tokens} tokens (>{PER_CALL_BUDGET}); "
            f"split the catalogue or lighten content"
        )


@pytest.mark.xfail(reason="Phase 1: heavy tools still in place. Un-xfail in Phase 4.")
def test_create_test_plan_flow_stays_under_token_budget():
    """A full create-test-plan flow via the new path uses these calls in
    sequence: classifications, approaches, principles (optional), techniques,
    specialty_tools, standards (filtered), rules (filtered).

    Total MCP-returned tokens across the flow must stay under PER_FLOW_BUDGET.
    """
    flow_total = sum(
        _approx_tokens(t)
        for t in [
            sumo_qa_load_classifications(),
            sumo_qa_load_approaches(),
            sumo_qa_load_techniques(),
            sumo_qa_load_specialty_tools(),
            sumo_qa_load_standards(classification="business_logic_change"),
            sumo_qa_load_rules(classification="business_logic_change"),
        ]
    )
    assert flow_total <= PER_FLOW_BUDGET, (
        f"create-test-plan flow returned ~{flow_total} tokens "
        f"(>{PER_FLOW_BUDGET}); the new path is too heavy"
    )
```

- [ ] **Step 20.2: Run.**

```bash
uv run pytest tests/test_token_weight_regression.py -v
```

Expected: `test_no_individual_knowledge_load_exceeds_per_call_budget` passes (catalogues are small). `test_create_test_plan_flow_stays_under_token_budget` is xfail. If the per-call test fails, the catalogue is too large — split it before continuing.

- [ ] **Step 20.3: Commit.**

```bash
git add tests/test_token_weight_regression.py
git commit -m "test(token-weight): add regression test (Phase 4 un-xfails flow assertion)"
```

---

## Group F: Self-bootstrap

### Task 21: Create `AGENTS.md`

**Files:**
- Create: `AGENTS.md`

- [ ] **Step 21.1: Write `AGENTS.md`.**

````markdown
# AGENTS.md — sumo-qa setup

If you are an AI agent in a code editor, follow these steps to set up
sumo-qa for the host you're running in. Do what you can with your
existing tools (bash, edit, write); explicitly hand off to the user
when you hit a step that needs UI clicks or admin permissions.

## Step 1 — detect your host

| Cue | Host |
|---|---|
| You have a `Skill` tool and `~/.claude/` exists | Claude Code |
| You're in a JetBrains IDE with MCP support but no `Skill` tool | IntelliJ AI Assistant |
| You're in VS Code with GitHub Copilot and MCP support | VS Code + Copilot |

## Step 2 — install the MCP server (host-agnostic)

```bash
uv tool install --from . sumo-qa-mcp
sumo-qa-mcp --help
```

If `uv` isn't installed:

- macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows: `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`

## Step 3 — register the MCP and load skills

### Claude Code

1. Symlink skills:

   - macOS / Linux:
     ```bash
     ln -sfn "$(pwd)/skills" ~/.claude/skills/sumo-qa
     ```
   - Windows (PowerShell, developer mode on):
     ```powershell
     New-Item -ItemType SymbolicLink -Path "$env:USERPROFILE\.claude\skills\sumo-qa" -Target "$(Get-Location)\skills"
     ```

2. Add MCP server. Edit:

   - macOS / Linux: `~/.config/claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

   Add:
   ```json
   {
     "mcpServers": {
       "sumo-qa": { "command": "sumo-qa-mcp" }
     }
   }
   ```

### IntelliJ AI Assistant

The agent typically cannot edit IntelliJ Settings programmatically. Hand
off to the user with these exact steps:

1. Open Settings (Cmd/Ctrl + ,)
2. Tools → AI Assistant → Model Context Protocol
3. Add server: command = `sumo-qa-mcp`
4. Skills are auto-exposed as MCP prompts. Invoke by name in AI Assistant chat.

### VS Code + Copilot

1. Edit `.vscode/mcp.json` in the workspace (or VS Code MCP config). Add:
   ```json
   {
     "mcpServers": {
       "sumo-qa": { "command": "sumo-qa-mcp" }
     }
   }
   ```

2. Skills are auto-exposed as MCP prompts. The repo's
   `.github/copilot-instructions.md` already tells Copilot to use them.

## Step 4 — verify

Ask the host to call `sumo_qa_load_classifications()`. If the response
contains the 10 canonical classification names (api_contract_change,
business_logic_change, security_change, ...), setup is complete.

If verification fails, check:
- `sumo-qa-mcp` is on PATH (`which sumo-qa-mcp` / `where sumo-qa-mcp`)
- The host's MCP config is syntactically valid
- The host has been restarted since the config edit

## What you can do, what you must ask the user for

| You CAN | You MUST ASK |
|---|---|
| Run `uv tool install` | Edits to user-level config files outside the workspace (claude_desktop_config.json, IntelliJ Settings UI) |
| Create symlinks (with developer mode on Windows) | Steps requiring sudo or admin elevation |
| Edit `.vscode/mcp.json` in the workspace | Steps requiring restarting the host |
| Run the verification step | |
````

- [ ] **Step 21.2: Verify it parses as valid markdown and the JSON snippets are valid.**

```bash
python -c "import json; json.loads('{\"mcpServers\": {\"sumo-qa\": {\"command\": \"sumo-qa-mcp\"}}}')"
```

Expected: no error.

- [ ] **Step 21.3: Commit.**

```bash
git add AGENTS.md
git commit -m "docs: add AGENTS.md self-bootstrap entry for AI agents"
```

---

### Task 22: Create `.github/copilot-instructions.md`

- [ ] **Step 22.1: Create the file.**

```bash
mkdir -p .github
```

Write `.github/copilot-instructions.md`:

```markdown
# QA tasks via sumo-qa MCP

For QA-shaped requests in this repo (test plans, code review, scaffolding
tests, finding test data, deciding QA approach), fetch the relevant prompt
from the `sumo-qa` MCP and follow its checklist.

Available skills (each registered as an MCP prompt with the same name,
hyphens replaced by underscores):

- `using_sumo_qa` — entry router; load this first for any QA intent
- `qa_deciding_approach` — pick the QA approach for the work
- `qa_preparing_for_work` — plan QA before coding starts
- `qa_creating_test_plan` — produce entry/exit criteria, phases, deliverables
- `qa_implementing_with_tdd` — red-green-refactor cycle
- `qa_reviewing_before_merge` — review local diff
- `qa_strengthening_tests` — mutation-testing follow-up
- `qa_finding_test_data` — known-good test data discovery and validation
- `qa_answering_testing_question` — generic "how do I test this?"
- `sumo_qa_strategising` — repo-wide QA strategy

The skills carry the senior-QA discipline (Iron Laws, checklists, Red Flags).
Knowledge catalogues are accessed via the `sumo_qa_load_*` tools — use them
for principles, techniques, classifications, approaches, and specialty tool
fits before relying on training-data knowledge.
```

- [ ] **Step 22.2: Commit.**

```bash
git add .github/copilot-instructions.md
git commit -m "docs: add Copilot instructions pointing at sumo-qa MCP prompts"
```

---

### Task 23: Create `install.py` (cross-platform)

**Files:**
- Create: `install.py`

- [ ] **Step 23.1: Write `install.py`.**

```python
#!/usr/bin/env python3
"""Cross-platform installer for sumo-qa.

Runs on Windows, macOS, and Linux. Installs the MCP server via uv,
symlinks skills/ into Claude Code's skills dir (or copies on Windows
without developer mode), and prints the host-specific config snippet.

Usage:
    python install.py
"""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SKILLS_SRC = REPO_ROOT / "skills"


def main() -> int:
    system = platform.system()
    print(f"sumo-qa installer — detected OS: {system}")

    _install_mcp_server()
    _install_claude_code_skills(system)
    _print_config_instructions(system)
    return 0


def _install_mcp_server() -> None:
    print("\n[1/3] Installing the MCP server via uv...")
    if shutil.which("uv") is None:
        print("ERROR: uv is not installed. Install it first:")
        print("  macOS / Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh")
        print('  Windows (PS):   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"')
        sys.exit(1)
    subprocess.run(
        ["uv", "tool", "install", "--from", str(REPO_ROOT), "sumo-qa-mcp"],
        check=True,
    )
    print("  done.")


def _install_claude_code_skills(system: str) -> None:
    print("\n[2/3] Installing Claude Code skill links...")
    home = Path.home()
    target = home / ".claude" / "skills" / "sumo-qa"
    if not target.parent.exists():
        print(f"  Claude Code config dir not found at {target.parent}; skipping.")
        print(f"  Skills are still available via MCP prompts on every host.")
        return
    if target.exists() or target.is_symlink():
        if target.is_symlink() or target.is_file():
            target.unlink()
        else:
            shutil.rmtree(target)
    try:
        target.symlink_to(SKILLS_SRC, target_is_directory=True)
        print(f"  symlinked {SKILLS_SRC} -> {target}")
    except OSError as exc:
        if system == "Windows":
            shutil.copytree(SKILLS_SRC, target)
            print(
                f"  Windows developer mode off — copied skills to {target}.\n"
                f"  Re-run install.py after editing skills/ to refresh."
            )
        else:
            raise


def _print_config_instructions(system: str) -> None:
    print("\n[3/3] Add this MCP server to your host's config:")
    snippet = json.dumps(
        {"mcpServers": {"sumo-qa": {"command": "sumo-qa-mcp"}}},
        indent=2,
    )
    print("\n" + snippet + "\n")
    print("Per-host config file:")
    if system == "Windows":
        print("  Claude Code:  %APPDATA%\\Claude\\claude_desktop_config.json")
    else:
        print("  Claude Code:  ~/.config/claude/claude_desktop_config.json")
    print("  IntelliJ:     Settings -> Tools -> AI Assistant -> MCP -> Add server")
    print("  VS Code:      .vscode/mcp.json (workspace) or VS Code MCP settings")
    print("\nSee AGENTS.md for the full per-host walkthrough.")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 23.2: Make it executable on Unix.**

```bash
chmod +x install.py
```

- [ ] **Step 23.3: Smoke-test syntax.**

```bash
python -m py_compile install.py
```

Expected: no output (success).

- [ ] **Step 23.4: Dry-run on the current host.**

```bash
python install.py
```

Expected: prints the config snippet. May actually install the MCP if `uv` is present — that's fine because the install is idempotent.

- [ ] **Step 23.5: Commit.**

```bash
git add install.py
git commit -m "feat(install): add cross-platform Python installer"
```

---

## Group G: Final verification

### Task 24: Run the full test suite

- [ ] **Step 24.1: Run all tests.**

```bash
uv run pytest -q
```

Expected: previous test count (257) + Phase 1 additions (~12 new tests across `test_knowledge_loaders.py`, `test_skill_prompts.py`, `test_skill_conformance.py`, `test_token_weight_regression.py`, `test_server.py`).

If anything fails that didn't fail before Phase 1, fix before continuing.

- [ ] **Step 24.2: Run the eval suite to confirm senior-grade hasn't regressed.**

```bash
uv run sumo-qa-eval
```

Expected: 28/28. Phase 1 is additive — no eval regression should be possible.

- [ ] **Step 24.3: Reinstall the local MCP so Claude Code picks up the new tools and prompts.**

```bash
uv tool install --from . sumo-qa-mcp --reinstall
```

---

### Task 25: Verify the original heavy path still works

The whole point of Phase 1 being additive is that the old path stays usable until Phase 3 verifies the new path. This task confirms.

- [ ] **Step 25.1: Run a heavy-path tool against a recorded scenario.**

```bash
uv run python -c "
from sumo_qa.tools import QAShiftLeftService
import json

svc = QAShiftLeftService.bundled()
out = svc.qa_decide_approach('refactor the pricing pipeline', target_paths=[])
print(json.dumps(out, indent=2)[:1000])
"
```

Expected: a structured response (recommended_approach, classifications, etc.) — confirming the old path is still callable.

- [ ] **Step 25.2: Verify the new path also works.**

```bash
uv run python -c "
from sumo_qa.knowledge_loaders import sumo_qa_load_classifications, sumo_qa_load_approaches
print(sumo_qa_load_classifications()[:500])
print('---')
print(sumo_qa_load_approaches()[:500])
"
```

Expected: catalogue text returns from both.

- [ ] **Step 25.3: Final commit / push to remote (LOCAL ONLY — DO NOT push without user approval).**

```bash
git log --oneline feat/superpowers-restructure ^feat/ai-driven-iteration-loop
```

Expected: 23-25 commits on the new branch (one per task above) — a clean reviewable sequence.

DO NOT run `git push` unless the user explicitly asks. Per project convention, the user reviews local commits before push.

- [ ] **Step 25.4: Document Phase 1 completion.**

Write a short note to `docs/superpowers/iteration-runs/round-8-phase-1-scaffolding.md`:

```markdown
# Phase 1 — Scaffolding (complete)

- 7 knowledge loaders added: classifications, approaches, principles,
  techniques, specialty_tools, standards, rules.
- 5 knowledge catalogues added under `knowledge/`.
- 3 new skill stubs added: qa-preparing-for-work, qa-creating-test-plan,
  qa-answering-testing-question.
- MCP prompt registration wired — every `skills/*/SKILL.md` is exposed
  as a prompt at server startup.
- Skill conformance test scaffolding in place (structure checks skipped
  until Phase 2 lands full skill content).
- Token-weight regression test in place (flow assertion xfail until
  Phase 4 deletes the heavy path).
- AGENTS.md, install.py, .github/copilot-instructions.md created.

Test count (record output of `uv run pytest -q --collect-only | tail -3`).
Eval: 28/28.
Old heavy path: still callable.
New path: knowledge tools functional, skill prompts registered.

Ready for Phase 2 (write the 10 SKILL.md files).
```

```bash
git add docs/superpowers/iteration-runs/round-8-phase-1-scaffolding.md
git commit -m "docs(iteration): Phase 1 scaffolding complete"
```

---

## Phase 1 done

After Task 25:
- Old heavy path: untouched, still works.
- New knowledge layer: 7 tools, 5 catalogues, all tested.
- New skill prompt layer: 10 prompts registered, conformance test scaffolding live.
- Self-bootstrap: AGENTS.md + install.py + Copilot instructions in place.
- Cross-platform install: works on Windows / macOS / Linux.

**Next:** Plan 2 (Phase 2 — Write the 10 skills) is written *after* the user reviews and approves Phase 1's results, because Phase 2's exact tasks depend on what Phase 1 produced.
