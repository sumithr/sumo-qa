# Configuration

All optional. Defaults work out of the box after `pip install sumo-qa && sumo-qa-install`.

| Env var | Default | Purpose |
|---|---|---|
| `QA_STANDARDS_PATH` | bundled `_data/standards/packs` / repo `standards/packs` | Override the team's loaded standards packs |
| `QA_RULES_PATH` | bundled `_data/standards/rules/change_rules.yaml` / repo `standards/rules/change_rules.yaml` | Override the team's loaded change rules |
| `QA_TEST_DATA_PATH` | bundled `_data/knowledge/test_data` / repo `knowledge/test_data` | Override the known-good test data catalogue |
| `QA_KNOWLEDGE_PATH` | bundled `_data/knowledge` / repo `knowledge` | Override the canonical knowledge catalogues (classifications, approaches, principles, techniques, specialty_tools) |
| `SUMO_QA_DEBUG_DIR` | unset | Directory to capture per-tool-call args + output as JSON for debugging / grading |

## Example: custom team standards

```json
{
  "mcpServers": {
    "sumo-qa": {
      "command": "sumo-qa",
      "env": {
        "QA_STANDARDS_PATH": "/abs/path/to/team-standards/packs",
        "QA_RULES_PATH": "/abs/path/to/team-standards/rules/change_rules.yaml",
        "QA_TEST_DATA_PATH": "/abs/path/to/team-test-data"
      }
    }
  }
}
```

## Debugging

```json
{
  "mcpServers": {
    "sumo-qa": {
      "command": "sumo-qa",
      "env": {
        "SUMO_QA_DEBUG_DIR": "/tmp/sumo-qa-debug"
      }
    }
  }
}
```

Each tool call writes a JSON file under `SUMO_QA_DEBUG_DIR` capturing the args and output. Useful for grading skill-driven output and reproducing host-side issues.
