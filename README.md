<p align="center">
  <img src="assets/logo.png" alt="sumo-qa — strong QA, crouching rikishi mark" width="520" />
</p>

# sumo-qa MCP

[![tests](https://github.com/sumithr/sumo-qa/actions/workflows/test.yml/badge.svg)](https://github.com/sumithr/sumo-qa/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/sumo-qa?cacheSeconds=300&v=0.46.0)](https://pypi.org/project/sumo-qa/) <!-- x-release-please-version -->
[![Python](https://img.shields.io/pypi/pyversions/sumo-qa?cacheSeconds=300&v=0.46.0)](https://pypi.org/project/sumo-qa/) <!-- x-release-please-version -->
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue)](LICENSE)

A QA-native MCP server and skills library: analyze a repo, map risks to tests and evidence, plan and scaffold tests, strengthen weak suites, and review diffs before merge with senior-QA discipline.

> [!IMPORTANT]
> sumo-qa is an advisor, not an oracle. Like any AI tool it can be wrong. Your judgment and your team's standards are the final word.

> ### 🚀 New here? **[5-minute demo →](DEMO.md)**
> One install line, then the QA loop on your own repo: map it, then review a change for a merge verdict or audit the whole repo for a strategy.

## Why it exists

Point your AI assistant at any repo and get QA it can defend: the repo understood well enough to test it, risks tied to specific files and lines, and a safe-to-merge answer backed by tests that ran this turn.

Ask a stock AI assistant to QA a change instead and you get the junior answer: "add unit tests, consider edge cases, maybe test performance." That's a checklist.

sumo-qa makes the agent work the way a senior QA does:

- Names 3–7 risks tied to specific files and lines, not categories
- Picks one design technique per risk from an ISTQB-grounded catalogue (boundary-value, decision-table, property-based, mutation)
- Runs your test suite fresh in the current turn before any "safe to merge" claim
- Holds TDD's red phase before any production code is written
- Keeps production code locked while strengthening tests against mutation survivors
- Won't ship a plan without measurable entry and exit criteria

The discipline lives in a library of [skill files](skills/), each followed literally — every one has an Iron Law and a HARD-GATE callout the LLM can't talk past. Skills route automatically from natural-language prompts; you don't need to remember to invoke them.

## Install

```bash
pip install sumo-qa && sumo-qa-install
```

Then restart your host or open a fresh chat. `sumo-qa-install` configures every MCP host it detects. Windows, single-host targeting, the one-command `install.sh` / `install.ps1` wrappers, plugin installs, and updating are all in **[docs/INSTALL.md](docs/INSTALL.md)**.

### Verify

```bash
sumo-qa-doctor
```

Green means you're wired — read-only diagnostics, and each failure prints the exact `Fix:` to run. Then ask any host *"load the QA classifications"*; the canonical names back confirm it end to end. ([Troubleshooting →](docs/INSTALL.md#diagnosing-setup-with-sumo-qa-doctor))

## Host support

Every host calls the same MCP server and reads the same SKILL.md files. What differs is how each host exposes them — that's a host-API difference, not a sumo-qa choice.

These hosts are verified end-to-end with `sumo-qa-install`:

| Host | Slash | Setup |
|---|---|---|
| **Claude Code** | `/sumo-qa-deciding-approach` (hyphens) | `sumo-qa-install --claude-code` |
| **VS Code + Copilot** (Agent mode, Claude Sonnet 4.5 or equivalent) | Natural language | `sumo-qa-install --vscode --workspace <repo>` writes `.vscode/mcp.json` |
| **JetBrains AI Assistant** | `/sumo_qa_deciding_approach` (underscores) | One-time UI setup; `sumo-qa-install --jetbrains` prints the fields to paste |
| **JetBrains Junie** | Natural language | Create `~/.junie/mcp/sumo-qa.json` (global) or `<repo>/.junie/mcp/` (per project) with the command path `sumo-qa-install --jetbrains` prints ([details](docs/INSTALL.md#jetbrains-ai-assistant--junie)) |

In Claude Code, type `/` then `sumo-qa-` to see the skills as hyphenated entries (symlinked into `~/.claude/skills/`). The same skills are also registered through MCP with underscores (`/sumo_qa_load_classifications`, `/sumo_qa_find_test_data`); both routes call the same SKILL.md.

Natural language works everywhere. *"Review my changes"*, *"plan QA for this story"*, *"load the QA classifications"* — the agent routes by tool description. Slash and natural-language paths produce the same result.

**Other MCP hosts** (Cursor, Codex, OpenCode, Gemini CLI, etc.): `pip install sumo-qa` ships a standard stdio MCP server, so it should work with anything that speaks MCP. Follow your host's MCP-server setup docs and point it at the absolute path of the `sumo-qa` script. These hosts are explicitly not yet verified end-to-end by us, so we don't ship per-host instructions for them.

### Host adapter folders

`sumo-qa` ships generated plugin manifest folders — `.claude-plugin/` (Claude Code) and `.codex-plugin/` (Codex, not yet verified end-to-end) — built from a single canonical source in `pyproject.toml` and drift-checked in CI on every PR. Architecture, per-host install status, and how to add a host: [docs/host-adapters.md](docs/host-adapters.md).

## See it in action

Transcripts showing the workflow on real code — diff reviews refusing to call safe-to-merge from stale CI, TDD cycles with the red output surfaced verbatim, mutation survivors walked one at a time, formal test plans gated on entry/exit criteria, and the case where the right answer is "no tests needed, stop here":

- [tests/scenarios/worked-examples/](tests/scenarios/worked-examples/) — start with [02 — review my changes](tests/scenarios/worked-examples/02-review-my-changes.md) for a representative end-to-end
- [tests/scenarios/SCENARIOS.md](tests/scenarios/SCENARIOS.md) — the scenario specs (prompt → expected shape → anti-patterns the skill prevents)

## What's included

Three layers: the host LLM follows skills, which cite knowledge and standards to produce the output. The [architecture doc](docs/ARCHITECTURE.md) has the diagram and the full data flow.

| Layer | What |
|---|---|
| **Skills** ([`skills/`](skills/)) | Iron-Law procedures across the QA lifecycle: deciding approach, preparing for work, TDD scaffolding, diff review, strengthening tests, finding test data, answering testing questions, repo strategy — plus the planning → parallel subagent execution → finishing chain. |
| **MCP entry points** | A thin tool surface — skill tools, knowledge loaders, a capabilities-discovery tool, repo-map tools, test-data tools, an ingestion tool, and external-skill lifecycle tools. Each is file IO or small deterministic logic; no inference. |
| **Progressive skill loading** | A read-only loader that fetches a skill in slices — routing manifest → section → module → full body — so a host pays the routing slice on each revisit, not the whole body. See [docs/TOOLS.md](docs/TOOLS.md#which-path-to-use--canonical-vs-compact) and [docs/SKILLS.md](docs/SKILLS.md#progressive-loading--manifest--section--module--full). |
| **Knowledge catalogues** ([`knowledge/`](knowledge/)) | Classifications, approaches, principles, techniques the agent picks from instead of recalling from training data. Editable as plain markdown. (Specialty-tool picks are deliberately not catalogued — observe the risk surface and web-search current options instead.) |

## Run it from the terminal

Beyond the host integration, sumo-qa ships terminal commands for the QA-native repo loop:

```bash
sumo-qa analyze            # map the current repo into .sumo-qa/repo-map.json
sumo-qa status             # is the map present and current against HEAD? what next?
sumo-qa report             # compose the .sumo-qa artifacts into qa-report.html
```

All take an optional `[path]` and `--json`; `report` renders honest not-available states for anything missing. (Bare `sumo-qa` launches the MCP server; `sumo-qa-doctor` runs diagnostics.)

## When sumo-qa doesn't fit

If your QA intent has no native fit (Playwright E2E, accessibility audits, k6 load testing, type checking), sumo-qa searches for an external skill through its MCP server, offers a `[y/N]` install gate, installs through the Skills CLI, then loads the installed `SKILL.md` back into the conversation.

The host never runs `npx` directly — four MCP tools own the lifecycle (search → `[y/N]` gate → install → load), and search returns the Skills CLI output verbatim, so there's no parser to drift. Node.js is required; if `npx` is missing the tool returns an actionable error rather than elevating. Any machine-level install the external skill suggests is translated to sumo-qa's repo-pinned, CI-reproducible standard, and sumo-qa keeps its confirmation gates, test evidence, and risk-to-test mapping.

## Support

Filing a clear issue gets it fixed faster. Pick the template that matches the problem:

| Symptom | Template |
|---|---|
| `pip install` / `sumo-qa-install` failed, or first-run setup is broken | [Install / setup problem](.github/ISSUE_TEMPLATE/install_setup_problem.yml) |
| Install worked, but the host (Claude Code, VS Code + Copilot, JetBrains, Cursor, …) does not surface tools or skills correctly | [Host compatibility problem](.github/ISSUE_TEMPLATE/host_compatibility.yml) |
| The wrong sumo-qa skill ran for a prompt (or none ran when one should have) | [Skill routed wrong](.github/ISSUE_TEMPLATE/skill_routed_wrong.yml) |
| A skill ran, but its QA output was generic, wrong, or missed something | [QA output quality issue](.github/ISSUE_TEMPLATE/qa_output_quality.yml) |
| You want a new workflow, skill, or host integration | [Feature / workflow request](.github/ISSUE_TEMPLATE/feature_request.yml) |
| Reproducible defect that does not fit the above | [Bug report](.github/ISSUE_TEMPLATE/bug_report.yml) |

## License

[Apache 2.0](LICENSE). See [NOTICE](NOTICE) for attribution requirements that apply to forks and redistributors.

## More docs

- [AGENTS.md](AGENTS.md) — AI-agent bootstrap and per-host setup
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — three layers, host delivery, knowledge authority
- [docs/SKILLS.md](docs/SKILLS.md) — every skill with its Iron Law
- [docs/TOOLS.md](docs/TOOLS.md) — every MCP entry point
- [docs/INSTALL.md](docs/INSTALL.md) — per-host install detail and troubleshooting
- [docs/CONTENT-FORMATS.md](docs/CONTENT-FORMATS.md) — schemas + worked examples for adding team standards, knowledge, change rules, and test data (incl. swapping ISTQB out)
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — env vars
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — local dev
- [docs/TEST-DATA.md](docs/TEST-DATA.md) — known-good test-data catalogue
- [docs/REPO-MAP.md](docs/REPO-MAP.md) — QA-native repo-map artifact under `.sumo-qa/`: schema, scanner, and the scan / diff-impact / query tools that consume it (issues #155, #156)
- [docs/RISK-LEDGER.md](docs/RISK-LEDGER.md) — risk-to-test traceability ledger: the structured appendix to the markdown-first verdict, its row schema and evidence-status vocabulary, and when not to use it (issue #144)
- [docs/SCORECARD.md](docs/SCORECARD.md) — QA readiness scorecard: composes the risk ledger + context bundle + optional coverage/mutation into a *derived* readiness recommendation (ready / blocked / insufficient_evidence / ready-with-accepted-residuals) — an evidence summary, not a predictive quality score (issue #151)
- [docs/EXPORT.md](docs/EXPORT.md) — deterministic export of already-structured QA test cases to versioned JSON, a markdown table, or (flat-only) CSV: the case schema, the format set, the side-effect-free contract, and the import-mapping caveat (issue #148)
- [docs/QA-REPORT.md](docs/QA-REPORT.md) — local QA report: the static `.sumo-qa/qa-report.html` page composed from the persisted artifacts, the four honest artifact states, and a readiness verdict derived by the #151 `QaScorecard` engine (issue #157)
- [docs/PERSONA.md](docs/PERSONA.md) — optional Sumo-sensei voice (off by default)
