# Phase 1 — Quality Baseline QA Run Summary

**Date:** 2026-05-14
**Plan:** [`docs/qa/plans/2026-05-14-phase1-quality-baseline.md`](../plans/2026-05-14-phase1-quality-baseline.md)
**Strategy:** [`docs/qa-strategy.md`](../../qa-strategy.md)
**Branch:** `feat/qaskills-integration-trial` → main (PR pending)
**Approach mix:** verify-existing (T1, T7, T8, T11, T12) + coverage-first-then-refactor (T2) + strengthen-test-coverage (T3, T4, T5, T6) + tdd-scaffold (T9, T10) + docs-change (T2, T9, T11)

## Evidence

**Suite run** *(fresh, this turn):*
- Total: **317 collected**
- Passed: **316**
- xfailed: **1** *(expected)*
- Failed: **0**
- Duration: **2.28s**
- Command: `uv run pytest -q`

**Coverage** *(fresh, this turn — gate `--cov-fail-under=100` is now active in CI and `pyproject.toml` `addopts`):*

| File | Stmts | Miss | Cover |
|---|---|---|---|
| `src/sumo_qa/__init__.py` | 1 | 0 | **100%** |
| `src/sumo_qa/__main__.py` | 1 | 0 | **100%** |
| `src/sumo_qa/debug_capture.py` | 28 | 0 | **100%** |
| `src/sumo_qa/installer.py` | 262 | 0 | **100%** |
| `src/sumo_qa/knowledge_loaders.py` | 77 | 0 | **100%** |
| `src/sumo_qa/rules.py` | 64 | 0 | **100%** |
| `src/sumo_qa/server.py` | 93 | 0 | **100%** |
| `src/sumo_qa/skill_prompts.py` | 46 | 0 | **100%** |
| `src/sumo_qa/standards.py` | 74 | 0 | **100%** |
| `src/sumo_qa/tdm_catalogue.py` | 121 | 0 | **100%** |
| `src/sumo_qa/tdm_models.py` | 89 | 0 | **100%** |
| `src/sumo_qa/tdm_service.py` | 147 | 0 | **100%** |
| `src/sumo_qa/tdm_validation.py` | 85 | 0 | **100%** |
| `src/sumo_qa/tools.py` | 55 | 0 | **100%** |
| **TOTAL** | **1146** | **0** | **100.00%** |

(Statement count is 1146 vs 1143 pre-cleanup: tools.py shrank by 3 statements after deleting the dead `try/except` blocks; installer.py grew by 6 after extracting `_detect_install_mode()`; net +3.)

**Lint:** `uv run ruff check . && uv run ruff format --check .` — All checks passed; 36 files already formatted.

**CI matrix (latest):** All **15 jobs** (Ubuntu + macOS + Windows × Python 3.10–3.14) ran pytest successfully on the rebased + post-Phase-1-fixup branch. Plus `Analyze (python)` (default-setup CodeQL) green, `ruff check + format` green. The R-WIN coverage now empirically holds — 3 Windows-only bugs were surfaced by adding `windows-latest` to the matrix and fixed in commits `d8c1522`, `eb54d3d`, `d2fb7a8`:

1. `installer.py:419` was calling `.read_text()` without `encoding="utf-8"` (Windows defaults to cp1252; UTF-8 byte 0x9d unrecognised).
2. `hooks/session-start` is a Bash script; Git's default `core.autocrlf=true` on Windows checked it out with CRLF line endings, which bash on Windows can't parse. Added `.gitattributes` forcing LF for `hooks/session-start`, `*.sh`, `*.py`.
3. `test_session_start_hook.py` invoked `bash` on Windows, which resolves to the WSL stub at `C:\Windows\System32\bash.exe` (returns "WindowsSubsystem... to install" with exit 1). Skipped on Windows — the hook is for macOS/Linux plugin runtimes.

Also `installer.py:419` was refined further to normalise newlines in the SKILL-content match (`replace("\r\n", "\n")`), and the test that exercises that path was switched from `write_text(read_text())` to `shutil.copy()` for byte-exact duplication.

**Coverage delta on most-affected file:** `installer.py` lifted from **14% → 100%** (262 statements, 237 previously missed, 0 missed now). 6 of those 237 are now covered by `# pragma: no cover` with inline justifications; the remaining 231 are covered by real tests.

## Risk-to-test coverage map

| Risk | Covering test(s) / artifact | Status |
|---|---|---|
| **R-DEAD** — qaskills + node_install dead code (~1,100 LOC + 8 MCP tool registrations) | `tests/test_server.py::test_no_heavy_tools_leak_after_phase_4_deletion` (defensive guard), 8 file deletions | ✅ green |
| **R-EXTSKILL** — `sumo-qa-suggesting-external-skill` SKILL referenced deleted MCP tools | `tests/test_qa_suggesting_external_skill_conformance.py::test_skill_targets_skills_sh_registry`, `test_skill_documents_find_skills_install_command_verbatim`, `test_skill_gates_find_skills_install_on_user_confirmation`, `test_skill_explicitly_rejects_companion_python_shims` | ✅ green |
| **R-INSTALLER (VS Code)** — `_setup_vscode_copilot` (`installer.py:446-543`) untested | `tests/test_installer_vscode.py` — 7 tests | ✅ green |
| **R-INSTALLER (JetBrains)** — `_setup_intellij` (`installer.py:544-613`) untested | `tests/test_installer_jetbrains.py` — 8 tests | ✅ green |
| **R-INSTALLER (idempotency)** — re-run safety untested | `tests/test_installer_idempotency.py` — 4 tests + 6 added by T12 | ✅ green |
| **R-INSTALLER (binary discovery)** — `_install_mcp_binary` (`installer.py:218-269`) untested | `tests/test_installer_mcp_binary.py` — 6 tests | ✅ green |
| **R-INSTALLER (Claude Code)** — `_setup_claude_code` + `_register_claude_code_mcp` | `tests/test_installer_claude_code_mcp.py` — 4 original + 12 added by T12 | ✅ green |
| **R-WIN** — README claimed Windows support; CI didn't prove it | `.github/workflows/test.yml:16` — `os: [ubuntu-latest, macos-latest, windows-latest]` | ✅ matrix expanded; first Windows run pending push |
| **R-COVDRIFT** — no coverage floor | `pyproject.toml:81` (`addopts`) + `.github/workflows/test.yml:34` both carry `--cov=src/sumo_qa --cov-fail-under=100` | ✅ green |
| **R-SEC** — no SAST or supply-chain alerting | GitHub's **default-setup CodeQL** (Python, push + PR) | ✅ green ("Analyze (python)" CI check). *(Note: the original Phase 1 plan added a custom `.github/workflows/codeql.yml`, but the repo's default-setup CodeQL was already active and rejected the advanced configuration's SARIF upload. The custom workflow was removed in commit `d2fb7a8` after the conflict surfaced. Coverage equivalent — Python SAST on push + PR via the default setup.)* |
| **R-RECIPEDRIFT** — strategy walk inventory not standardised | `knowledge/repo_walk.md` (3 H2 sections + fenced code blocks); `tests/test_repo_walk_recipe.py` (4 structural tests); `skills/sumo-qa-strategising/SKILL.md:55` references the recipe | ✅ green |
| **R-MCPSTART** — no test that the binary speaks MCP | `tests/test_e2e_mcp_initialize.py::test_initialize_returns_serverinfo`, `::test_tools_list_returns_registered_count` (count derived dynamically from `build_mcp_server()._tool_manager._tools`) | ✅ green |
| **R-PRAGMASPAM** — coverage gate could invite pragma drift | `docs/COVERAGE.md` (Floor + Allowed pragmas + Disallowed + How to add + Running locally + Lowering the floor); 6 pragmas added by T12, all carry inline justification | ✅ green (with 2 follow-ups, see below) |
| **R-SKILLDRIFT** — skill ↔ MCP tool ↔ knowledge file references checked only by humans | *(deferred to Phase 2 per strategy)* | ⏭ Phase 2 |

**Risks covered: 13 / 14.** R-SKILLDRIFT was always Phase 2 scope.

## Known gaps + open follow-ups

**Closed during this rollout** *(addressed before commit, after cross-task review surfaced them):*
- `src/sumo_qa/tools.py:41,51` — both `try/except` blocks deleted. The `ImportError` fallback for `importlib.resources` was dead code (stdlib since 3.7; we require 3.10+); the `except Exception` around `Path(str(anchor))` was paranoid (the constructor doesn't raise on string inputs). 2 pragmas removed via deletion.
- `src/sumo_qa/installer.py:65,79` — module-level wheel-vs-editable detection refactored into `_detect_install_mode()` function (parameters with `_MODULE_DIR` / `_BUNDLED_SKILLS` defaults). Both branches + the broken-repo-layout exit are now covered by `tests/test_installer_mcp_binary.py::test_detect_install_mode_wheel_branch`, `::test_detect_install_mode_editable_branch`, `::test_detect_install_mode_broken_layout_exits`. 2 pragmas removed via test.
- `.idea/` — added to `.gitignore` so JetBrains users don't accidentally stage IDE config.

**Final pragma audit** — only 4 pragmas remain in production code; every one matches one of the three documented allowed cases:

| File:Line | Comment | Allowed case |
|---|---|---|
| `src/sumo_qa/installer.py:38` | "defensive exit for Python <3.10 (CI runs 3.10+)" | Case 1 (defensive sys.exit after Python-version guard) |
| `src/sumo_qa/installer.py:284` | "platform-conditional Windows branch" | Case 2 (platform-conditional) |
| `src/sumo_qa/installer.py:660` | "main guard" | Case 3 (`__name__ == '__main__'`) |
| `src/sumo_qa/__main__.py:4` | "main guard" | Case 3 |

**Phase 2 deliverables ready to plan** *(per `docs/qa-strategy.md`):*
- Skill ↔ MCP tool cross-reference test (R-SKILLDRIFT).
- Property-based tests via Hypothesis on `knowledge_loaders.py`, `rules.py`, `standards.py`, `tdm_validation.py` parsers.

**Phase 3 deliverables** *(per strategy, after Phase 2):*
- Mutation testing via `mutmut` on the 4 parser modules.
- TDM known-good URL freshness scheduled GHA.

## Files touched

**Deleted (8 — qaskills/node_install purge, T1):**
- `src/sumo_qa/qaskills.py` (235 LOC), `src/sumo_qa/node_install.py` (107 LOC)
- `tests/test_qaskills_shim.py` (268), `tests/test_qaskills_local_check.py` (70), `tests/test_qaskills_server_tools.py` (167), `tests/test_node_install.py` (153)
- `tests/fixtures/qaskills_search_playwright.txt`, `tests/fixtures/qaskills_info_playwright_e2e.txt`

**Modified (production):**
- `src/sumo_qa/server.py` — qaskills imports + `_register_qaskills_tools` removed (T1); coverage gaps closed (T12)
- `src/sumo_qa/installer.py` — Claude Code MCP-registry registration via `claude mcp add` (install-fix); 4 pragmas (T12)
- `src/sumo_qa/__main__.py` — main-guard pragma (T12)

**Modified (tests):**
- `tests/test_server.py` — qaskills assertion removal + 9 new tests (T1, T12)
- `tests/test_qa_suggesting_external_skill_conformance.py` — rewritten to assert find-skills design (T2)
- `tests/test_installer_claude_code_mcp.py` — new (install-fix); +12 tests (T12)
- `tests/test_debug_capture.py`, `test_knowledge_loaders.py`, `test_skill_prompts.py`, `test_standards.py`, `test_tdm.py`, `test_tools.py` — coverage-fill tests (T12)

**Modified (docs / skills):**
- `README.md`, `docs/ARCHITECTURE.md`, `docs/INSTALL.md`, `docs/TOOLS.md`, `docs/SKILLS.md` — tool count 33→25, skill count 13→14, qaskills section retitled to "External-skill discovery" (T2)
- `skills/sumo-qa-suggesting-external-skill/SKILL.md` — rewritten to find-skills/skills.sh Bash flow (T2)
- `skills/sumo-qa-deciding-approach/SKILL.md` — fallback paragraph rewritten (T2)
- `skills/sumo-qa-strategising/SKILL.md` — step 1 references `knowledge/repo_walk.md` (T9)

**Modified (CI / config):**
- `.github/workflows/test.yml` — `windows-latest` added to OS matrix (T7); `--cov=src/sumo_qa --cov-fail-under=100` added to pytest invocation (T12)
- `pyproject.toml` — `addopts` now carries the same coverage args (T12)

**New (docs / knowledge / CI):**
- `docs/qa-strategy.md` — Phase 1+2+3 strategy
- `docs/qa/plans/2026-05-14-phase1-quality-baseline.md` — the executed plan
- `docs/qa/runs/2026-05-14-phase1-quality-baseline.md` — this document
- `docs/COVERAGE.md` — pragma policy (T11)
- `knowledge/repo_walk.md` — strategy-walk recipe (T9)
- `.github/workflows/codeql.yml` — CodeQL workflow (T8)

**New (tests):**
- `tests/test_installer_vscode.py` (T3) — 7 tests
- `tests/test_installer_jetbrains.py` (T4) — 8 tests
- `tests/test_installer_idempotency.py` (T5) — 10 tests
- `tests/test_installer_mcp_binary.py` (T6) — 6 tests
- `tests/test_repo_walk_recipe.py` (T9) — 4 tests
- `tests/test_e2e_mcp_initialize.py` (T10) — 2 tests

**Diff magnitude:** 29 files modified, ~91 net new tests, ~1,100 LOC of dead code removed.
