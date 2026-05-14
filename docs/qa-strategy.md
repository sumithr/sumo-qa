# sumo-qa QA Strategy

Risk-prioritised, repo-anchored QA strategy for the sumo-qa repository itself. Produced by walking the actual codebase via the `sumo-qa-strategising` workflow on 2026-05-14, then confirmed section-by-section with the maintainer.

The principle: a repo whose product is *helping other repos achieve quality* should set the bar for itself. Targets and gates here are deliberately strict.

## Scope

Everything under this checkout: production code (`src/sumo_qa/`), tests (`tests/`), skills (`skills/`), knowledge catalogues (`knowledge/`), CI/release pipeline (`.github/workflows/`), pre-commit hooks, documentation. Quality is interpreted broadly — not just test coverage, but also CI hygiene, security scanning, dead-code cleanup, and recipe-drift prevention.

## Inventory

Walked the repo on 2026-05-14:

- **Single Python package** at `src/sumo_qa/` — 16 modules, 3,081 LOC.
- **Tests:** 19 files, 232 collected tests, 2,716 LOC. Headline coverage **75% line** with one large outlier.
- **14 skill bundles** under `skills/sumo-qa-*/` — each is `SKILL.md` + frontmatter, driving host-LLM workflow.
- **5 knowledge catalogues** under `knowledge/` (`approaches`, `classifications`, `principles`, `specialty_tools`, `techniques`) + a `test_data/` subtree for known-good fixtures.
- **Standards** under `standards/packs/` + `standards/rules/`.
- **CI:** 3 GitHub Actions — `lint.yml` (ruff check + format), `test.yml` (5 Python × 2 OS matrix; **no Windows**), `release.yml` (uv build).
- **Pre-commit hooks:** ruff, basic file checks (yaml/json/toml/whitespace/EOL), pytest.

### Coverage shape per area

| Area | Module(s) | Coverage | Note |
|---|---|---|---|
| Installer / host config | `installer.py` | **14%** (276 stmts, 237 missed) | Largest module. The just-fixed Claude Code MCP-registry gap is the prototype bug this hides. |
| TDM (test-data mgmt) | `tdm_*.py` (5 files, 877 LOC) | 92–94% | Already well-covered. |
| MCP server + tools | `server.py`, `tools.py`, `knowledge_loaders.py` | 77 / 87 / 83% | Decent — gaps mostly error paths. |
| Pivot dead code | `qaskills.py`, `node_install.py` | 100 / 95% | **Slated for deletion** — earlier pivot to Bash-driven SKILL.md made these obsolete; commits never reached this branch. |

### Per-area named risks

1. **Installer / host config** — (a) VS Code + JetBrains setup paths likely have analogous unverified gaps to the Claude Code one just fixed; (b) idempotency on re-run not tested; (c) path detection across pip / pipx / uv / editable / Windows vs POSIX is mostly untested.
2. **MCP server + tool dispatch** — (a) tool name ↔ skill name ↔ knowledge-file path drift (skill says "call sumo_qa_load_X" but no such tool registered); (b) knowledge-loader frontmatter parsing if a new section type is added; (c) error-envelope shape — `is_error` envelope assertions exist only on TDM tools.
3. **Skills + knowledge content** — (a) skill body refs MCP tools that no longer exist; (b) skill description drifts from actual capability — wrong auto-trigger; (c) knowledge catalogue restructured but loader still parses old shape.
4. **Pivot dead code** — to be deleted in Phase 1 (~1,100 LOC of code + tests).
5. **CI / release pipeline** — (a) docs claim Windows-supported but CI never proves it; (b) no coverage-floor gate, so installer.py-style 14% modules can land; (c) no SAST / dep vuln / secret scan despite shipping a binary to PyPI.
6. **TDM** — already in good shape; minor: validators run no downstream calls, so a known-good entry pointing at a dead URL passes validation today.
7. **Repo-walk recipe (meta)** — inventory-gathering during strategy walk is currently judgment-based per-Claude-session; risk of drift in what "good inventory" means across runs.

## Specialty + tool fit

Stack-anchored to Python + uv + pytest + ruff + GitHub Actions + MCP server. Most "pyramid layers" don't apply (no UI, no web app, no service mesh).

| Area | Specialty surface | Tool / approach |
|---|---|---|
| Installer / host config | Plain CLI orchestration over subprocess + filesystem. **No specialty surface.** | Just pytest + `unittest.mock` + `tmp_path`. Extend the new `test_installer_claude_code_mcp.py` pattern. |
| MCP server + tool dispatch | File-IO + dispatch — no specialty surface for the dispatch layer. Parser invariants in `knowledge_loaders.py`. | Phase 1: structural pytest. Phase 2: Hypothesis on the parsers. |
| Skills + knowledge content | Markdown structural conventions + cross-references. | Static structural pytest assertions (extend `test_skill_conformance.py`). |
| Dead code | Pure deletion. | No tool — delete + verify suite + coverage climbs. |
| CI / release pipeline | Cross-platform support, coverage floor, security scanning, dep vuln scanning. | Add `windows-latest` to matrix, `--cov-fail-under=100` to pytest invocation, **CodeQL** (GitHub-native, free, Python-supported). |
| TDM | Already covered. Minor: known-good URL freshness. | Scheduled GHA running `requests.head` weekly. |
| Repo-walk recipe | Documentation / convention. | `knowledge/repo_walk.md` + structural test + reference from `sumo-qa-strategising/SKILL.md`. |

**Cross-cutting:** **mutation testing via `mutmut`** on `knowledge_loaders.py`, `rules.py`, `standards.py`, `tdm_validation.py` (where coverage is high but assertion-strength is unclear) — Phase 3.

**Deliberately NOT in the pyramid** (would be cargo-cult for this repo): Cypress/Playwright (no UI), Pact / contract testing (MCP IS the contract; no downstream consumer split), k6/Locust (no SLO articulated), axe/Pa11y (no UI surface), mobile harnesses.

## Prioritisation

Ranked by `risk × current-coverage-gap`. Can't test everything (ISTQB Principle 2) — the gaps that hurt most go first.

| Rank | Item | Why first / why later |
|---|---|---|
| 1 | Delete qaskills + node_install (modules + tests + doc refs) | Prerequisite to a clean base. Every other improvement is easier on top. |
| 2 | Installer test expansion (VS Code, JetBrains, idempotency, path detection) | Highest concrete risk × biggest gap. The Claude Code MCP-registry bug we just fixed is the prototype. |
| 3 | CI: add `windows-latest` + `--cov-fail-under=100` + CodeQL workflow | Locks the gains in, proves the Windows claim, gets SAST + supply-chain in one move. Cheap config edits. |
| 4 | Repo-walk recipe (`knowledge/repo_walk.md` + structural test + ref from `sumo-qa-strategising`) | Cheap, prevents future strategy-walk drift. |
| 5 | Skill ↔ MCP tool cross-reference test | Catches "skill body refs deleted/renamed tool" failure mode. Depends on dead-code cleanup. |
| 6 | Property-based tests via Hypothesis on knowledge / standards / rules / tdm_validation parsers | Targets parser invariants where unit tests cover happy paths only. |
| 7 | Mutation testing (`mutmut`) on `knowledge_loaders.py`, `rules.py`, `standards.py`, `tdm_validation.py` | Assertion-strength check after coverage floor is in. Adds CI time — earn it. |
| 8 | TDM known-good URL freshness as scheduled GHA | Lowest risk × lowest gap. Scheduled, not per-push. |

## Target pyramid

Scaled to what this repo actually is. Static layer is doing more work than usual by design — the product is largely structured markdown, and structural tests catch most drift cheaper than runtime tests would.

```
                       Scheduled (Phase 3)
                       — TDM URL freshness, dep-vuln alerts
                  ─────────────────────────────────────
                          End-to-end (1–2)
                  — spawn `sumo-qa` binary, send JSON-RPC
                          initialize, assert tools/list
              ─────────────────────────────────────────────
                       In-process integration (light)
                — phase3_e2e_skill_path style: real registry,
                       real loaders, no host subprocess
        ─────────────────────────────────────────────────────────
                              Unit (heavy)
            — dispatch, envelope, parsers, validation, installer
            branches with mocked subprocess + tmp_path filesystem
   ─────────────────────────────────────────────────────────────────
                         Static (broad, cheap)
       — ruff (have) + CodeQL (Phase 1) + structural conformance
       (Iron Law present, skill ↔ MCP-tool cross-ref) + coverage floor
```

| Layer | Tool | Status |
|---|---|---|
| Static — lint/format | `ruff check` + `ruff format --check` | Have. CI per push. |
| Static — SAST + supply chain | **CodeQL** (separate workflow) | **Phase 1.** GitHub-native, covers SARIF + Dependabot alerts. |
| Static — coverage floor | `pytest --cov-fail-under=100` | **Phase 1.** Documented `# pragma: no cover` policy in `docs/COVERAGE.md`. |
| Static — structural conformance | pytest (extend `test_skill_conformance.py`) | Have for shape; **Phase 2** for skill ↔ MCP-tool cross-ref. |
| Unit | pytest + `unittest.mock` + `tmp_path` | Have. **Phase 1 expansion** for `installer.py`. |
| Unit — parser robustness | **Hypothesis** | **Phase 2.** Targeted at parsers / validators. |
| Unit — assertion strength | **mutmut** | **Phase 3.** Once coverage floor is in. |
| In-process integration | pytest (existing `test_phase3_e2e_skill_path.py` shape) | Have. Maintain. |
| End-to-end | pytest spawning `sumo-qa` binary, JSON-RPC over stdio | **Phase 1 add.** Permanent counterpart to `installer._verify_mcp_responds`. |
| Scheduled | GitHub Actions `schedule:` triggers | **Phase 3** for TDM freshness. |

## Coverage policy

Floor: **100%** statement coverage enforced via `pytest --cov-fail-under=100` in CI.

`# pragma: no cover` is allowed *only* for:
- Defensive `sys.exit(1)` after Python-version / type-of-environment guards that can't be reached under normal test conditions.
- Platform-conditional branches that can't run on the current OS (use one targeted pragma per branch, never wholesale).
- `if __name__ == "__main__":` guards.

Anything else needs a real test or an exclusion review captured in the PR description. The full policy lives in `docs/COVERAGE.md` (added in Phase 1).

100% statement coverage ≠ 100% behaviour coverage — that's exactly what mutation testing in Phase 3 is for. 100% is the floor for *statements*, not the ceiling for confidence.

## Phased rollout

Sequence with named gates, not a calendar.

### Phase 1 — Clean base + headline coverage + CI hardening + recipe

Deliverables:

1. **Delete dead code:** `qaskills.py`, `node_install.py`, `tests/test_qaskills_*.py` (3 files), `tests/test_node_install.py`; remove qaskills MCP tool registrations from `server.py`; clean doc references in `README.md`, `docs/INSTALL.md`, `docs/TOOLS.md`, `docs/ARCHITECTURE.md`; update tool-count claims everywhere.
2. **Expand installer tests:** extend the `test_installer_claude_code_mcp.py` pattern to VS Code + JetBrains setup paths, idempotency (re-run is no-op), path detection across pip / uv / editable. Target: lift `installer.py` from 14% to ≥ 95% (with the remaining gap covered by documented `# pragma: no cover` on platform-conditional branches).
3. **CI hardening:** add `windows-latest` to the `os:` matrix in `.github/workflows/test.yml`; add `--cov-fail-under=100` to the pytest invocation; add new `.github/workflows/codeql.yml` (Python language, push + PR + weekly schedule).
4. **Repo-walk recipe:** write `knowledge/repo_walk.md` (the fixed inventory commands + the data shape to capture); add `tests/test_repo_walk_recipe.py` (structural assertions); extend step 1 of `skills/sumo-qa-strategising/SKILL.md` to reference it.
5. **One end-to-end smoke:** `tests/test_e2e_mcp_initialize.py` — spawn the actual `sumo-qa` binary, send JSON-RPC `initialize`, assert the registered tool count matches the static list. Permanent counterpart to `installer._verify_mcp_responds`.
6. **Coverage policy doc:** `docs/COVERAGE.md` defining the `# pragma: no cover` allow-list.

**Minimum viable Phase 1 = green:** dead code gone, `installer.py` ≥ 95% covered (or 100% with documented pragmas), Windows in CI matrix, coverage gate active at 100%, CodeQL has run with zero "high" findings, e2e initialize test passes, repo-walk recipe exists and is referenced from the strategising skill.

**Gate before Phase 2:** all CI checks green on **3 OS × 5 Python versions**; PR merged to main; a fresh `pip install --upgrade sumo-qa && sumo-qa-install --claude-code` followed by `claude mcp list` shows sumo-qa connected.

### Phase 2 — Structural drift guards + parser robustness

Deliverables:

1. **Skill ↔ MCP-tool cross-reference test:** scan every `skills/*/SKILL.md` for `sumo_qa_*` references, assert each is a registered tool name. And the converse: every registered tool is referenced by at least one SKILL.md (catches dead tools).
2. **Hypothesis tests** on `knowledge_loaders.py` for adversarial frontmatter / body shapes; targeted property tests on `rules.py`, `standards.py`, `tdm_validation.py` invariants (round-trip serialisation, idempotent validation).

**Minimum viable Phase 2 = green:** cross-ref test catches a deliberate "rename a tool, don't update the SKILL.md" injection in CI; Hypothesis suite runs deterministically in CI (no flake on re-run).

**Gate before Phase 3:** cross-ref test green; Hypothesis suite runs ≤ 30s; one previously-uncaught edge case found *or* explicitly recorded as "parser is robust to the shrunk inputs we tried".

### Phase 3 — Assertion strength + freshness

Deliverables:

1. **`mutmut`** configured against `knowledge_loaders.py`, `rules.py`, `standards.py`, `tdm_validation.py`; baseline mutation score per module captured; survivors triaged (legit → strengthen test; equivalent → suppress in config); CI runs nightly (not per-push — keeps push-time CI fast).
2. **`.github/workflows/tdm-freshness.yml`** — scheduled weekly: fetches each known-good test-data entry's URL with `requests.head`, opens a GitHub issue tagged `tdm-freshness` if any non-2xx response.

**Minimum viable Phase 3 = green:** mutation score ≥ 75% per targeted module (or surviving mutants documented as equivalent); freshness workflow has run at least one full cycle without false alarm.

**Strategy closure gate:** all three phases land; this document is the source of truth for what was done and why.

## Residual risks accepted

What this strategy is honestly NOT addressing, and why:

1. **Performance / load testing** — no SLO articulated for catalogue load latency, MCP-tool dispatch RTT, or installer runtime. **Accepted cost.** ISO 25010's *performance efficiency* deliberately deselected. Generic perf tests without a budget would be theatre. Revisit if catalogue size or tool surface grows enough to matter.
2. **Real-host integration tests** — `installer.py` is tested with mocked subprocess + `tmp_path`. We do *not* actually install into a real Claude Code / VS Code / JetBrains, observe MCP-tool surfacing, and assert the workflow runs end-to-end. **Mitigated** by: the Phase 1 e2e initialize test, the Phase 1 gate requiring a manual `pip install` + `sumo-qa-install` + `claude mcp list` post-merge, and CodeQL catching some classes of misconfig. **Residual:** silent host-API drift (e.g. Claude Code changes the `claude mcp add` flag set) won't be caught until a user report.
3. **Skill *content* quality** — we test structural conformance (Iron Law present, frontmatter valid, every tool reference resolves). We don't test that the skill *prompts* actually elicit good QA behaviour from a host LLM. **Accepted cost / deferred.** Real judgment requires LLM-as-judge eval (Promptfoo / DeepEval / Ragas) — its own engineering investment. The `tests/scenarios/worked-examples/` markdowns are the current human-eval proxy. Lift out as a separate "Phase 4: skill behaviour eval" *only if* user-reported skill drift becomes recurring.
4. **Post-PyPI release smoke** — `release.yml` builds and publishes the wheel; we don't pull it back from PyPI in a clean container and run the full installer flow. **Deferred.** Could be added as a release-time GitHub Action with a real Linux runner + `claude` CLI installed. Effort > value until a botched release happens.

## Next steps

This strategy is signed off. Phase 1 is being turned into a bite-sized, dispatchable plan via `sumo-qa-planning-qa-rollout` (the next skill in the chain). The plan will live at `docs/qa/plans/2026-05-14-phase1-quality-baseline.md` and is the executable companion to this strategy document.
