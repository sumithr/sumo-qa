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

This page describes the schema (issue #155), the scanner that populates it,
and the consumers built on it: the `sumo_qa_scan_repo`, `sumo_qa_analyze_diff_impact`,
and `sumo_qa_query_repo_map` MCP tools (#156). The report renderer ships in a
follow-up slice (#157).

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

## Generating the artifact

```python
from pathlib import Path

from sumo_qa.repo_map_scanner import scan_repo

repo_map = scan_repo(Path("."), generator_version="sumo-qa 0.16.0")
# repo_map.nodes / .edges / .commands / .warnings populated
```

`scan_repo(root, *, generator_version)` walks the repo deterministically and
returns a validated `RepoMap`. It prefers `git ls-files` (respects
`.gitignore`, picks up only tracked files); outside a git repo, it falls back
to a manual walk that skips known cache and vendored directories
(`.git`, `node_modules`, `__pycache__`, `.venv`, `dist`, `build`,
`.tox`, `mutants`, `.sumo-qa`, etc).

What the slice-2 scanner produces:

- **Nodes** for the full first-slice vocabulary. Each carries its detected
  language, a SHA-256 fingerprint of the file content, and the relative path.
- **Edges** of type `likely_tests` only — inferred by name convention
  (`tests/test_X.py` → `*/X.py`, also handling `X_test.py` and `.test`/
  `.spec` suffixes). `confidence` is `high` for a unique source match,
  `medium` when multiple sources share the stem. `imports` and
  `configured_by` are deferred; they need #156's diff-impact context to
  be worth computing.
- **Commands** extracted from `pyproject.toml` (`[project.scripts]`) and
  `package.json` (`scripts`). For `package.json`, the script `kind`
  (`test`/`lint`/`format`/`build`/`other`) is guessed from the script
  name. `pyproject.toml` scripts are categorised as `other` until a
  follow-up adds smarter detection.
- **Warnings** for files that didn't classify (`unsupported_language`)
  or were intentionally skipped (`skipped_file` — e.g. images, archives,
  compiled binaries).

Determinism: nodes are sorted by path; edges by `(source, target)`;
commands by `(source, name)`. Fingerprints are content-hashed, so only
files that actually changed get a new fingerprint. `project.generated_at`
is the only field that churns on each run.

Persisting the artifact is optional — the scanner returns a `RepoMap`
in-process. To write it to disk where downstream tooling will look:

```python
import json
from pathlib import Path

out = Path(".sumo-qa") / "repo-map.json"
out.parent.mkdir(exist_ok=True)
out.write_text(
    json.dumps(repo_map.model_dump(mode="json"), indent=2),
    encoding="utf-8",
)
```

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

## Diff-impact analysis

`sumo_qa_analyze_diff_impact` is the first consumer of the map. Given a set of
changed files it answers the QA-native question "what does this change touch,
and where is the test evidence missing?" — without re-reasoning about the repo
from scratch.

It reports:

- **`related_tests`** — tests that likely exercise the changed files (walked
  from `likely_tests` edges).
- **`risk_surface`** — changed `source_file` paths with **no** mapped test.
  This is the gap a reviewer cares about most.
- **`affected_nodes`** — one-hop neighbours of the changed nodes.
- **`unmapped_files`** — changed paths absent from the map (new files, or a
  stale map).
- **`is_stale`** — true when the map's `git_commit` differs from current HEAD.

Changed files come from either an explicit list or a git base ref. For a base
ref the diff is taken against the **merge-base** of the ref and `HEAD` (the
fork point — the same set GitHub's "Files changed" shows), so changes that
landed on the base after the branch diverged don't leak in; committed and
uncommitted tracked changes on the branch are both included. The map is read
from `.sumo-qa/repo-map.json` when present and falls back to a live scan
otherwise, so the tool works before any artifact is written. An artifact whose
`project.root` does not match the scan root is ignored (with a warning) in
favour of a live scan. With `write_overlay=true` it also writes a
`diff-impact.json` overlay under `.sumo-qa/`.

The pure analysis lives in `src/sumo_qa/repo_map_impact.py`
(`analyze_diff_impact`); the MCP tool in `src/sumo_qa/server.py` is a thin
wrapper that loads the map, resolves the diff, detects staleness, and writes
the optional overlay.

## Query

`sumo_qa_query_repo_map(root, query, limit=10, types=None)` is a bounded,
read-only search over the map. It answers "where is the component / test / CI
check / config / command that matches X?" without returning the full artifact —
the host gets just enough metadata (node id, path, type, tags, a match reason)
to open the files directly.

- The `query` matches case-insensitively across node id, path, file name,
  type, category, and tags, and across command names and kinds. Results rank
  **exact identity** (a node id, a command name) above evidence-type / tag /
  category hits, above bare substring hits; ties break on id for determinism.
- `limit` caps the returned matches; `total_matches` always reports the full
  count and `truncated` flags when the limit hid some — so the host knows when
  to narrow the query rather than assuming it saw everything.
- `types` restricts the search to given node types (`test_file`, `ci_workflow`,
  …) and/or the literal `"command"`.
- Like diff-impact, the map is read from `.sumo-qa/repo-map.json` when present
  and falls back to a live scan otherwise; a foreign-root artifact is ignored,
  and the response carries a freshness summary (`generated_at`, `git_commit`,
  `is_stale`, `used_live_scan`) plus the same staleness / live-scan warnings.
  Missing or stale state never blocks — it rides along as a warning so the host
  can fall back to direct repo inspection.

The pure ranking lives in `src/sumo_qa/repo_map_query.py` (`query_repo_map`);
the MCP tool in `src/sumo_qa/server.py` is the thin wrapper that loads the map,
detects staleness, and attaches the freshness summary.

### Skill consumption

The review, preparing-for-work, and strategising skills prefer repo-map
evidence when `.sumo-qa/repo-map.json` is present and fall back to a repo walk
when it is absent. The map is an **input accelerator, never a verdict**:
`sumo-qa-reviewing-before-merge` still refuses a safe-to-merge claim without
fresh test evidence — `related_tests` are candidates to run and `risk_surface`
entries are candidate uncovered anchors, neither is proof of coverage.

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

## Scope by slice

| Slice | Lands |
|---|---|
| 1 | Schema models, validation envelope, golden fixture |
| 2 | `sumo_qa.repo_map_scanner.scan_repo` — deterministic local walker; `likely_tests` edge inference; command extraction from `pyproject.toml` / `package.json` |
| 3 | `sumo_qa_scan_repo` MCP tool — host-callable wrapper that returns a compact summary and optionally writes the artifact |
| 4 | `sumo_qa_analyze_diff_impact` — first consumer of the map (diff → related tests + risk surface) |
| 5 (this PR) | `sumo_qa_query_repo_map` — bounded ranked search over the map; wiring of `sumo-qa-reviewing-before-merge`, `sumo-qa-preparing-for-work`, and `sumo-qa-strategising` to prefer the map when present and fall back to a repo walk when absent |

`imports`, `configured_by`, and `command_runs` edges are deferred. The
scanner produces only `likely_tests` — enough for the slice-4 diff-impact
tool to map a changed source file to its candidate tests, which is the first
downstream consumer.
