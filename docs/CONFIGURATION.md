# Configuration

Environment variables sumo-qa reads. All optional — the package ships with a working set of standards, rules, and known-good test data.

## `QA_STANDARDS_PATH`

Defaults to the bundled `standards/packs`. Override to point at your team's own versioned YAML standards packs. The loader picks up every `*.yaml` / `*.yml` file in the directory.

## `QA_RULES_PATH`

Defaults to the bundled `standards/rules/change_rules.yaml`. Override to point at your team's own change-classification rules. Each classification (e.g. `api_contract_change`, `security_change`) maps to `must_consider`, `suggested_test_types`, `test_design_techniques`, `quality_characteristics`, `risk_templates`.

## `QA_TEST_DATA_PATH`

Defaults to the bundled `knowledge/test_data`. Override to point at your team's own test-data catalogue root. Subdirectories under this path become `domain` values. See [docs/TEST-DATA.md](TEST-DATA.md) for the entry shape.

## `QA_DISABLE_HOST_SAMPLING`

Set to `1` / `true` / `yes` to skip the host-LLM call and return deterministic-only output. Useful when the host doesn't support MCP sampling, when a team wants cost-free responses, or for testing the deterministic floor in isolation. Without sampling, the AI-shaped fields fall back to structural skeletons (see [docs/APPROACHES.md](APPROACHES.md) for what the fallback does in `sumo_qa_decide_approach`).

## `SUMO_QA_DEBUG_DIR`

When set to a writable directory, every tool invocation captures `args`, `output`, and the rendered markdown trace to `<dir>/<timestamp>-<tool>/`. Used for offline review of MCP exchanges without re-running the host. Source: [`src/sumo_qa/debug_capture.py`](../src/sumo_qa/debug_capture.py).

## `SUMO_QA_TARGET_REPO`

Used by the evaluation harness ([`src/sumo_qa/evaluation.py`](../src/sumo_qa/evaluation.py)) to resolve repo-relative paths in evaluation fixtures. Set to the absolute path of the repository under evaluation. Has no effect on normal MCP runtime.

## Setting env vars in the host MCP config

```json
{
  "mcpServers": {
    "sumo-qa": {
      "command": "sumo-qa-mcp",
      "env": {
        "QA_STANDARDS_PATH": "/abs/path/to/team-standards/packs",
        "QA_RULES_PATH": "/abs/path/to/team-standards/rules/change_rules.yaml",
        "QA_TEST_DATA_PATH": "/abs/path/to/team-test-data",
        "QA_DISABLE_HOST_SAMPLING": "0",
        "SUMO_QA_DEBUG_DIR": "/tmp/sumo-qa-debug"
      }
    }
  }
}
```
