---
name: sumo-qa-measuring-coverage
description: Use when the user wants coverage or mutation numbers in the local QA report — "run coverage", "measure coverage", "run mutation testing", "record the survivors". Runs the repo's configured coverage/mutation tool, reads its output (any format), and persists a compact summary into the .sumo-qa artifacts the report loads.
---

# Measuring coverage & mutation

Turn a repo's coverage/mutation run into evidence the QA report can cite. The report reads `.sumo-qa/coverage.json` and `.sumo-qa/mutation.json`; this skill produces them. The host (you) runs the tool and reads its output; the MCP tools only validate + persist.

**Announce at start:** *"Measuring coverage/mutation and recording it for the report."*

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: never surface internal taxonomy labels; spend output on findings not framing; one question per turn; no preamble or closing pleasantries.

<HARD-GATE>
NEVER fabricate a number. A coverage percentage or survivor count goes into an artifact ONLY when it came from a real run (or a report the user pointed you at) in this session. No run / no report ⇒ record nothing, report "not available".
</HARD-GATE>

## The Iron Law

**MEASURED, REPORTED, NEVER GATED.** Coverage and mutation are evidence the report *shows* — they never become a pass/fail gate and never flip a readiness verdict. A 100% coverage signal does not make a risk "covered" or a blocked verdict "ready". If you catch yourself treating a percentage as a safety threshold, stop.

## When to Use

- *"run coverage and put it in the report"*, *"measure coverage"*, *"what's my coverage"* (when the report should carry it)
- *"run mutation testing"*, *"record the survivors"*, *"get mutation into the scorecard"*
- As a follow-on to a QA rollout, before `sumo_qa_generate_qa_report`, when you want the Coverage/Mutation rows populated instead of "not available".

NOT for: live PostToolUse mutation-survivor routing (that is #127's router — a different concern; see `sumo-qa-strengthening-tests`). Reading a saved report ≠ running the router.

## Checklist

1. **Detect (configured tooling only).** Inspect for tooling the project already pins — coverage: `pyproject [tool.coverage]` / `--cov` in pytest addopts / `.coveragerc`, `package.json` jest `--coverage` / `nyc` / `c8`, `go test -cover`, a committed `coverage.xml` (Cobertura) / `coverage.json` (coverage.py) / `lcov.info`; mutation: `[tool.mutmut]` / `mutmut`, Stryker (`stryker.conf.*`, `mutation.json`), PIT (`mutations.xml`). **Never `pip install` / `npm i` a tool.** Nothing configured → stop, report "not available" (step 5). Configured but unrun → offer a scoped run; if declined, fall back.
2. **Run the detected command, scoped.** Run the project's own command, preferring a machine-readable report and scoping to changed code when a diff is in play (e.g. `pytest --cov=<pkg> --cov-report=json`; `mutmut run` + its results summary). A run that errors (missing dep, misconfig) → report it plainly and fall back; never mask it.
3. **Collect (LLM reads any format).** Read the output — JSON, XML, lcov, or console text — and extract: coverage → `line_percent` + a compact `detail` naming uncovered/weak **changed** files/functions (tie gaps to `.sumo-qa/diff-impact.json` when present — changed code, not global vanity totals); mutation → `survivors` + `killed` + a `detail` on where notable survivors live. Set `freshness="fresh"` (you just ran it), `source_tool` = what you ran, `generated_at` = an ISO-8601 timestamp.
4. **Persist.** Coverage → `sumo_qa_record_coverage(root, coverage={...})`; mutation → `sumo_qa_record_mutation(root, mutation={...})`. Each validates and writes the artifact, or returns an error envelope (fix the payload, don't hand-write the file). Then tell the user to (re)run `sumo_qa_generate_qa_report` to see the Coverage/Mutation rows populate.
5. **Fallback (no tool / no run).** Report concisely: *"Coverage/mutation not available — no coverage tool is configured in this repo."* Record nothing. A first-class outcome, never a workflow failure, never a reason to invent a number.

## Process Flow

See the Checklist above — that's the flow.

## Red Flags — STOP

| Thought | Reality |
|---|---|
| "Coverage is 100%, so this risk is covered / it's safe to merge" | Iron Law. Coverage is reported, never a gate. It cannot discharge a risk or flip a verdict. |
| "No coverage tool here, I'll just `pip install` one" | Never. Configured tooling only; absent tool ⇒ "not available". Adoption is a separate decision (`sumo-qa-strategising`), repo-pinned, never ad-hoc. |
| "I'll estimate the percentage from reading the code" | Fabrication. A number comes from a real run or a real report, or it doesn't get recorded. |
| "I'll re-run the suite to generate a mutation report for the live router" | Wrong skill. Reading a SAVED report here ≠ #127's PostToolUse router. Don't conflate them. |
| "I'll hand-edit `.sumo-qa/coverage.json`" | Use `sumo_qa_record_coverage` — it validates the shape. A bad payload is an error to fix, not a file to forge. |
| "The run errored, I'll record the last known number" | Stale/fabricated. Report the failure, fall back to "not available". |

## Example

Repo pins `pytest --cov` in addopts. User: *"get coverage into the QA report."*
1. Detect: `[tool.pytest]` addopts carry `--cov=src/pkg`. ✓
2. Run: `pytest --cov=src/pkg --cov-report=json` → `coverage.json`, 96.4% lines.
3. Collect: `line_percent=96.4`, `detail="changed-file gaps: pkg/api.py L40-44 (error branch uncovered)"`, `freshness="fresh"`, `source_tool="pytest-cov (coverage.py json)"`.
4. Persist: `sumo_qa_record_coverage(root=".", coverage={...})` → `.sumo-qa/coverage.json`. Tell the user to regenerate the report.
