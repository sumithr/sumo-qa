# Repo-map artifact

The repo-map artifact — `repo-map.json` written under the project's
`.sumo-qa/` directory — is a versioned, schema-validated map of the
repository plus QA-relevant evidence anchors: tests, manifests, CI configs,
fixtures, migrations. It exists so QA workflows can answer four questions
deterministically rather than re-walking the repo each session:

- what exists
- what can break
- what tests or checks appear to exercise it
- what evidence is stale, missing, or unmapped

This page describes the first-slice schema (issue #155). The deterministic
local generator, MCP/CLI surfaces, diff-impact extension, and report renderer
ship in follow-up slices (#155 slice 2, #156, #160, #157).

## Shape

```json
{
  "schema_version": "1.0",
  "project": {
    "root": "/repo",
    "name": "example",
    "git_commit": "abc123",
    "generated_at": "2026-05-28T00:00:00+00:00",
    "generator_version": "sumo-qa 0.16.0"
  },
  "nodes": [
    {
      "id": "file:src/sumo_qa/server.py",
      "type": "source_file",
      "path": "src/sumo_qa/server.py",
      "language": "python",
      "category": "app",
      "tags": ["mcp"],
      "fingerprint": "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    }
  ],
  "edges": [
    {
      "source": "file:tests/test_capabilities.py",
      "target": "file:src/sumo_qa/server.py",
      "type": "likely_tests",
      "confidence": "medium",
      "reason": "path/name convention"
    }
  ],
  "commands": [],
  "warnings": []
}
```

`project` carries the freshness metadata callers need to spot stale evidence:
`generated_at`, `generator_version`, `root`, and (when available) `git_commit`.
Both `generated_at` and `generator_version` are required — missing freshness
metadata is a validation failure, not a silently-acceptable omission.

## First-slice vocabulary

The node, edge, command, and warning kinds are pinned to small `Literal`
catalogues. Adding a new value is a schema-version bump, not an open
extension:

| Field | Values |
|---|---|
| `nodes[].type` | `source_file`, `test_file`, `docs`, `config`, `ci_workflow`, `manifest`, `fixture`, `migration_schema`, `infrastructure` |
| `edges[].type` | `likely_tests`, `imports`, `configured_by` |
| `edges[].confidence` | `low`, `medium`, `high` |
| `commands[].kind` | `test`, `build`, `lint`, `format`, `ci_job`, `other` |
| `warnings[].kind` | `skipped_file`, `unsupported_language`, `stale`, `schema_drift`, `other` |

Unknown fields and unknown enum values are rejected — Pydantic's
`extra="forbid"` plus literal types means downstream consumers can trust the
vocabulary without defensive shimming. Additional schema invariants enforced
in slice 1:

- `project.generated_at` must be timezone-aware; naive datetimes are
  rejected so freshness math stays meaningful.
- `nodes[].fingerprint`, when present, must match `sha256:<64 lowercase
  hex>`. Other hash algorithms are a schema-version bump, not a soft
  extension.
- `nodes[].id` values are unique within the artifact; duplicates would
  silently collapse downstream lookups.

Edge `source`/`target` endpoints are NOT yet checked for node-membership —
the follow-up generator slice defines id conventions for external
references (e.g. third-party imports). Until then, a producer can emit an
edge pointing at any string id.

## Loading + validation

```python
from pathlib import Path

from sumo_qa.repo_map_validation import RepoMapValidationError, load_repo_map

artifact = Path(".sumo-qa") / "repo-map.json"
try:
    repo_map = load_repo_map(artifact)
except RepoMapValidationError as exc:
    # exc.kind: "malformed_json" | "schema_version_mismatch" |
    #           "missing_field" | "unknown_field" | "vocab_error" |
    #           "type_error" | "io_error"
    # exc.path: JSON-pointer-ish path into the artifact ("/project/generated_at")
    # exc.source: the file path, if one was provided
    ...
```

`load_repo_map` accepts a `dict`, a `pathlib.Path`, or a `str` path. Every
failure mode raises `RepoMapValidationError` with a stable `kind`, so tools
can branch on the category rather than parsing free-form messages.

`schema_version_mismatch` fires before Pydantic sees the payload so a stale
artifact (e.g. generated against a 2.x build) doesn't masquerade as a generic
literal-type error.

## Commit vs cache

The artifact is a **local cache** by default — the deterministic generator
(follow-up slice) regenerates it from the working tree, and the freshness
fields let consumers detect staleness. Most teams should add the
`.sumo-qa/` directory to `.gitignore` once the generator lands.

Teams that *want* shared lookup tables (e.g. CI compares the committed map
against the regenerated one to flag silently-renamed files) can commit it
instead — `nodes`, `edges`, `commands`, and `warnings` are deterministic on
the same repo state, so the structural diff stays clean. `generated_at`
churns on every run; CI use-cases should diff with that field masked, or
regenerate locally before comparison.

## Scope of this slice

The slice 1 PR adds:

- Pydantic models (`sumo_qa.repo_map_models`) for the shape above
- A load + validation envelope (`sumo_qa.repo_map_validation.load_repo_map`)
  returning a typed model or a categorised `RepoMapValidationError`
- A round-trip-tested fixture under `tests/fixtures/repo_map/`

The deterministic scanner, the MCP/CLI surface, the diff-impact artifact,
and the static report all live in follow-up slices.
