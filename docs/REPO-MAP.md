# Repo-map artifact

The repo-map artifact, `repo-map.json` written under the project's
`.sumo-qa/` directory, is a versioned, schema-validated map of the
repository plus QA-relevant evidence anchors: tests, manifests, CI configs,
fixtures, migrations. It exists so QA workflows can answer four questions
deterministically rather than re-walking the repo each session:

- what exists
- what can break
- what tests or checks appear to exercise it
- what evidence is stale, missing, or unmapped

This page describes the schema (issue #155), the scanner that populates it,
and the consumers built on it: the `sumo_qa_scan_repo`, `sumo_qa_analyze_diff_impact`,
and `sumo_qa_query_repo_map` MCP tools (#156). The local QA report (#157)
composes this artifact (plus the other `.sumo-qa` artifacts) into a static
HTML page; see [QA-REPORT.md](QA-REPORT.md).

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
      "reason": "usage: references server"
    }
  ],
  "commands": [],
  "warnings": []
}
```

`project` carries the freshness metadata callers need to spot stale evidence:
`generated_at`, `generator_version`, `root`, and (when available) `git_commit`.
Both `generated_at` and `generator_version` are required, missing freshness
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

Unknown fields and unknown enum values are rejected, Pydantic's
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

Edge `source`/`target` endpoints are NOT yet checked for node-membership;
the follow-up generator slice defines id conventions for external
references (e.g. third-party imports). Until then, a producer can emit an
edge pointing at any string id.

## Generating the artifact

From a terminal, the memorable product command:

```console
$ sumo-qa analyze            # scans the current directory
$ sumo-qa analyze /path/to/repo
Analyzed /path/to/repo
  wrote .sumo-qa/repo-map.json (240 nodes, 20 edges, 9 commands)
  ...
  next: sumo-qa status /path/to/repo
```

`sumo-qa analyze [path]` walks the repo and writes the schema-validated
`.sumo-qa/repo-map.json` artifact, then prints a concise per-type summary and
the next command. `--json` emits a machine-readable document instead (the
same per-type counts plus the written `artifact_path`). It calls the same
`scan_repo` service the MCP layer uses, so the artifact is byte-compatible on
the same repo state.

`sumo-qa status [path]` reports whether the artifact exists, its schema
version, whether it is stale relative to `HEAD`, and the next command to run;
`--json` for automation. A missing or stale artifact points back at
`sumo-qa analyze`. (Bare `sumo-qa` with no subcommand still launches the MCP
server, the host launch contract is unchanged. Setup diagnostics stay under
`sumo-qa-doctor`.)

In Python, the underlying service:

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
- **Edges** of type `likely_tests`: inferred from two language-agnostic
  signals so the mapping is not tied to a fixed filename-suffix table: a
  **usage** signal (a test file's **import statements** name a source stem,
  robust across languages; only import-style lines are read, so an incidental
  mention of a common word can't fabricate an edge) and a **name-convention**
  signal mapping a test's stem to its source stem (`test_X` / `X_test`,
  `.test`/`.spec`, and CamelCase families `FooTest` / `FooTests` / `FooSpec` /
  `FooIT` / `FooITCase` → `Foo` for Kotlin/Java/Scala/Swift). `confidence` is
  `high` for a unique name match or a name+usage corroboration, `medium` for an
  ambiguous-name-only or usage-only match. A pair found by both signals
  collapses to one corroborated edge.
  Note the CamelCase mapping applies to files **already classified as tests**
  (by the `tests`/`test` directory convention or the unambiguous
  `test_`/`_test`/`.test`/`.spec` suffixes): a bare `*Test`/`*Spec`/`*IT` name
  is NOT treated as a test on its own, so a production class like
  `src/main/kotlin/ExperimentTest.kt` is not misclassified (and dropped off the
  risk surface). The cost is that tests in a custom source set outside a test
  directory (e.g. Gradle's `src/integrationTest`) aren't auto-detected by name:
  a safe miss (the source stays on the risk surface).
- **Edges** of type `imports`: a resolved, language-agnostic import graph built
  via tree-sitter (the import-edge layer). The scanner parses each source file,
  resolves each import to the repo-relative file(s) it references, and emits an
  edge `source → target` **only between nodes that already exist in the map**
  (no dangling edges, same discipline as `likely_tests`). `confidence` is
  `high` for a module-level or class-body import (tight coupling) and `medium`
  for a function-local / lazy import (deferred coupling); the strongest signal
  per `(source, target)` is kept when a pair is seen more than once.

  A language's resolver capabilities activate in two distinct steps, and the
  difference matters when reading a map:

  - **Extension activated**: the scanner owns the language's file extensions,
    so they classify as source/test nodes, stamp a language id that dispatches
    to the registered resolver, and every resolution rule that needs only the
    importing file's path works end to end through `scan_repo`. A contract
    test (`tests/test_repo_map_resolver_scanner_contract.py`) pins every
    resolver-declared extension to scanner ownership so the two metadata
    surfaces cannot silently drift; explicitly ambiguous extensions live in
    its one documented exception mapping (`.h` stamps `cpp` as the documented
    ambiguous-header default while the shared include extractor serves both C
    and C++, and a `.c` translation unit stays `c`).
  - **Repository context activated**: resolution rules that need
    per-repository configuration or cross-file indexes activate only when a
    scan-local preparation pass derives that context from the repository
    itself. The preparation foundation ships with the Rust,
    TypeScript/JavaScript, PHP, and C# slices: each scan prepares a fresh,
    scan-scoped resolver, never mutating the registered one, so sequential and
    concurrent scans share nothing, and an unreadable or malformed config
    degrades to path-only resolution with one deterministic `other` warning per
    affected file. Languages whose context derivation has not landed yet (#484)
    deliberately **under-edge**: no edge is emitted rather than a guessed one.

  Every registered resolver is extension activated: **Python** (the reference
  resolver: relative-import dot-anchoring, PEP-328 implicit namespace
  packages, an absolute-import source-root walk-up, specifier submodule
  probing; wildcard `from x import *` and qualified specifiers skipped),
  **TypeScript/JavaScript** (relative-path resolution with extension probing
  and `index.*` barrels; bare specifiers dropped as external), **Go**,
  **Ruby**, **Java** (fully-qualified, wildcard, and static imports against
  source roots; `java.*` / `javax.*` and other external packages dropped),
  **Rust**, and, activated by #483:

  - **C/C++** (#359): a quoted `#include "x"` resolves against the including
    file's own directory by exact spelling (POSIX forward-slash spellings;
    an MSVC-style backslash spelling never resolves). Header extensions are
    never synthesized (`#include "config"` does not match `config.h`),
    conventional `include/`/`src/` roots are never guessed, and angle-bracket,
    macro, absolute/directory-spelled, and repo-root-escaping includes emit
    no edge.
  - **PHP**: a relative `require`/`include` (including `__DIR__`-anchored
    forms) resolves at scan time with no Composer context; PSR-4 `use`
    mapping is additionally repository context activated (see below).
  - **C#**: `.cs` files classify, stamp `csharp`, and reach the registered
    resolver. A `using` names a namespace, not a file, so its fan-out needs a
    cross-file, per-project index (repository context activated below, #542).

  **Rust** is additionally repository context activated (#358): each scan
  derives scan-local crate context from the repository's own sources and
  `Cargo.toml` editions, resolving provable bare current-scope imports
  (`mod foo;` plus `use foo::Bar;` under an explicit 2018+ edition,
  workspace-inherited editions included), cross-file inline-module
  references, and mixed lib+bin root modules by walked crate membership.
  Ambiguity under-edges: a shared module declared by both roots, an unknown
  or 2015 edition, or an undeclared bare head emits no edge rather than a
  guessed one.

  **TypeScript/JavaScript** is additionally repository context activated
  (#484): each scan derives a scan-local index of the repository's own
  `tsconfig.json` files (keyed by their own directory) and resolves each
  importer's non-relative specifiers against its NEAREST applicable config, so
  `paths`/`baseUrl` aliases resolve to real files without flattening unrelated
  workspaces' alias tables into one. A missing config is the silent path-only
  fallback; an unreadable or malformed config degrades to path-only with one
  deterministic `other` warning per affected file.

  **PHP** is additionally repository context activated (#484): each scan
  reads every `composer.json` and resolves PSR-4 `use` imports against the
  autoload roots (production and dev, #479's precedence) of each importer's
  NEAREST manifest, anchored to that manifest's own directory, so one
  Composer package's map never resolves an import written in a sibling
  package. A missing manifest is the normal path-only fallback; an unreadable
  or unusable one degrades the same way plus one deterministic `other`
  warning, never aborting the scan.

  **C#** is likewise repository context activated (#542): each scan builds a
  `namespace -> declaring files` index scoped to each `.csproj` PROJECT
  boundary (the nearest ancestor directory holding one, classified as a
  manifest node so its location is visible to the preparation pass). A
  `.csproj`'s LOCATION marks that boundary and the namespace-index grouping: an
  SDK-style project globs the `.cs` files beneath its directory, so the manifest
  only needs to be present. A `using` fans out within the importer's own project
  and into any project it explicitly references (see below); a namespace
  declared in an UNREFERENCED different project does not resolve, so there is no
  repository-global fan-out once project ownership is known. A `using
  global::X.Y` names the same namespace as `using X.Y` (the `global::` alias
  qualifier only forces root-namespace lookup), so it is stripped and both
  resolve identically (#548). A `.cs` file with no owning `.csproj` falls back
  to path-only resolution (no fan-out, and no warning, since the config is
  merely absent rather than broken). The only "unusable" case is an UNREADABLE
  or non-UTF-8 `.csproj`: its location still bounds the project (so its files
  never leak into an ancestor project), but its namespaces stay unindexed, so
  every `using` beneath it falls back to path-only resolution with one
  deterministic `other` warning. A UTF-8 `.csproj` whose XML is invalid is NOT
  unusable: the boundary holds and its `.cs` namespaces still index.
  `System.*` and external assemblies always drop. A `global using` emits the
  edge from its own declaring file; re-applying one file's global usings to its
  sibling files is a documented limitation (the per-file extract/resolve
  contract has no implicit-import hook).

  **C# `<ProjectReference>` cross-project edges (#548):** per-project scoping
  has one explicit escape hatch. An SDK `.csproj` names its build dependencies
  with `<ProjectReference Include="..\Other\Other.csproj" />`; when that element
  is present, a `using` in the referencing project also fans out into the
  referenced project's declarers, so a namespace declared in an explicitly
  referenced project resolves. This is the one place the manifest's XML is
  parsed (tolerantly, matching by local name so an old-style project's MSBuild
  XML namespace does not hide the element); the boundary and the namespace-index
  grouping stay location-only. References are DIRECT ONLY, not transitive: if A
  references B and B references C, a `using` in A resolves into B but not into C.
  Include paths use MSBuild backslashes, resolved relative to the referencing
  `.csproj`'s own directory. A manifest that is unreadable, non-UTF-8, or
  malformed XML contributes no references (its own boundary and namespaces are
  unaffected); a scanned `.csproj` declaring a DTD is refused, closing the XML
  entity-expansion denial-of-service vector. A bad `.csproj` never aborts the
  scan.

  Capabilities that await repository context (#484): C/C++ resolution through
  configured include directories (quoted includes beyond the importer's own
  directory, and angle-bracket includes through proven roots, preferably from
  `compile_commands.json`).

  This layer is **optional**: it needs the `tree-sitter` parser, shipped as the
  `sumo-qa[treesitter]` extra. With the extra absent the scan still succeeds: it
  records a `RepoMapWarning` and emits only `likely_tests` edges, so the map
  stays valid (the warning prevents a consumer reading "no import edges" as "no
  dependencies"). `configured_by` edges remain deferred.
- **Commands** extracted from `pyproject.toml` (`[project.scripts]`) and
  `package.json` (`scripts`). For `package.json`, the script `kind`
  (`test`/`lint`/`format`/`build`/`other`) is guessed from the script
  name. `pyproject.toml` scripts are categorised as `other` until a
  follow-up adds smarter detection.
- **Warnings** for files that didn't classify (`unsupported_language`),
  files that were intentionally skipped (`skipped_file`, e.g. images,
  archives, compiled binaries), and config input a resolver's scan-local
  preparation could not use (`other`, e.g. a malformed `Cargo.toml`: one
  deterministic warning per affected file, never an aborted scan).

Determinism: nodes are sorted by path; edges by `(source, target)`;
commands by `(source, name)`. Fingerprints are content-hashed, so only
files that actually changed get a new fingerprint. `project.generated_at`
is the only field that churns on each run.

Persisting the artifact is optional, the scanner returns a `RepoMap`
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
and where is the test evidence missing?", without re-reasoning about the repo
from scratch.

It reports:

- **`related_tests`**: tests that likely exercise the changed files (walked
  from `likely_tests` edges).
- **`risk_surface`**: changed `source_file` paths with **no** mapped test.
  This is the gap a reviewer cares about most.
- **`probable_mapping_gap`**: true when test files exist but the map produced
  no `likely_tests` edges, so the whole risk surface is a probable missed
  convention (e.g. an unusual CamelCase layout), not true zero coverage. Lets a
  consumer distinguish "the mapper couldn't link these" from "these are
  genuinely untested".
- **`affected_nodes`**: one-hop neighbours of the changed nodes, ranked by
  coupling strength. Each carries a `connecting_confidence` (the strongest
  confidence of any edge linking it to the changeset) and the list is ordered
  high → medium → low, so the load-bearing neighbours (tight, module-level
  imports) rank above the lazy ones (function-local imports).
- **`unmapped_files`**: changed paths absent from the map (new files, or a
  stale map).
- **`is_stale`**: true when the map's `git_commit` differs from current HEAD.

Each changed/affected node carries a tri-state `has_mapped_tests`: a real
true/false verdict **only for `source_file` nodes**; `null` (the key is always
present) for every other node type, in both the tool result and the persisted
`diff-impact.json` overlay. The mapped-tests question is meaningless for docs,
fixtures, config, or test files themselves, a vacuous "no" there must never
read as a coverage gap. `risk_surface` stays the headline signal and is
unchanged: changed source files with no mapped test, and only those.

Changed files come from either an explicit list or a git base ref. For a base
ref the diff is taken against the **merge-base** of the ref and `HEAD` (the
fork point, the same set GitHub's "Files changed" shows), so changes that
landed on the base after the branch diverged don't leak in; committed and
uncommitted tracked changes on the branch are both included. The map is read
from `.sumo-qa/repo-map.json` when present and falls back to a live scan
otherwise, so the tool works before any artifact is written. On the first run
of an unmapped repo the live scan is **persisted** to that path (reported as
`persisted_map_path`) so the run leaves a discoverable artifact instead of
re-scanning every call; pass `artifact_path=None` to opt out. An artifact whose
`project.root` does not match the scan root is ignored (with a warning) in
favour of a live scan, and is left untouched, auto-persist only fires on the
genuine no-artifact path. With `write_overlay=true` it also writes a
`diff-impact.json` overlay under `.sumo-qa/`.

The pure analysis lives in `src/sumo_qa/repo_map_impact.py`
(`analyze_diff_impact`); the MCP tool in `src/sumo_qa/server.py` is a thin
wrapper that loads the map, resolves the diff, detects staleness, and writes
the optional overlay.

## Query

`sumo_qa_query_repo_map(root, query, limit=10, types=None)` is a bounded,
read-only search over the map. It answers "where is the component / test / CI
check / config / command that matches X?" without returning the full artifact:
the host gets just enough metadata (node id, path, type, tags, a match reason)
to open the files directly.

- The `query` matches case-insensitively across node id, path, file name,
  type, category, and tags, and across command names and kinds. Results rank
  **exact identity** (a node id, a command name) above evidence-type / tag /
  category hits, above bare substring hits; ties break on id for determinism.
- `limit` caps the returned matches; `total_matches` always reports the full
  count and `truncated` flags when the limit hid some, so the host knows when
  to narrow the query rather than assuming it saw everything.
- `types` restricts the search to given node types (`test_file`, `ci_workflow`,
  …) and/or the literal `"command"`.
- Like diff-impact, the map is read from `.sumo-qa/repo-map.json` when present
  and falls back to a live scan otherwise; a foreign-root artifact is ignored,
  and the response carries a freshness summary (`generated_at`, `git_commit`,
  `is_stale`, `used_live_scan`) plus the same staleness / live-scan warnings.
  Missing or stale state never blocks, it rides along as a warning so the host
  can fall back to direct repo inspection.

The pure ranking lives in `src/sumo_qa/repo_map_query.py` (`query_repo_map`);
the MCP tool in `src/sumo_qa/server.py` is the thin wrapper that loads the map,
detects staleness, and attaches the freshness summary.

### Skill consumption

The review, preparing-for-work, and strategising skills prefer repo-map
evidence when `.sumo-qa/repo-map.json` is present and fall back to a repo walk
when it is absent. The map is an **input accelerator, never a verdict**:
`sumo-qa-reviewing-before-merge` still refuses a safe-to-merge claim without
fresh test evidence, `related_tests` are candidates to run and `risk_surface`
entries are candidate uncovered anchors, neither is proof of coverage. When
`probable_mapping_gap` is set the review reads the risk surface as a missed
test↔source mapping (verify against the test tree) rather than zero coverage,
and never attributes it to a missing or unscanned repo-map.

## Commit vs cache

The artifact is a **local cache** by default, the deterministic generator
(follow-up slice) regenerates it from the working tree, and the freshness
fields let consumers detect staleness. Most teams should add the
`.sumo-qa/` directory to `.gitignore` once the generator lands.

Teams that *want* shared lookup tables (e.g. CI compares the committed map
against the regenerated one to flag silently-renamed files) can commit it
instead, `nodes`, `edges`, `commands`, and `warnings` are deterministic on
the same repo state, so the structural diff stays clean. `generated_at`
churns on every run; CI use-cases should diff with that field masked, or
regenerate locally before comparison.

## Scope by slice

| Slice | Lands |
|---|---|
| 1 | Schema models, validation envelope, golden fixture |
| 2 | `sumo_qa.repo_map_scanner.scan_repo`, deterministic local walker; `likely_tests` edge inference; command extraction from `pyproject.toml` / `package.json` |
| 3 | `sumo_qa_scan_repo` MCP tool, host-callable wrapper that returns a compact summary and optionally writes the artifact |
| 4 | `sumo_qa_analyze_diff_impact`, first consumer of the map (diff → related tests + risk surface) |
| 5 | `sumo_qa_query_repo_map`, bounded ranked search over the map; wiring of `sumo-qa-reviewing-before-merge`, `sumo-qa-preparing-for-work`, and `sumo-qa-strategising` to prefer the map when present and fall back to a repo walk when absent |
| 6 | `sumo-qa analyze` / `sumo-qa status` CLI commands (#160): terminal-facing wrappers over the same `scan_repo` / load+validate services, with `--json`; bare `sumo-qa` still launches the MCP server |
| 7 | Local QA report (#157): `sumo-qa report` / `sumo_qa_generate_qa_report` compose the repo-map, diff-impact, risk-ledger, and context-bundle artifacts into the static `.sumo-qa/qa-report.html` page with honest not-available states ([QA-REPORT.md](QA-REPORT.md)) |
| import-edge layer | `imports` edges via tree-sitter (the optional `sumo-qa[treesitter]` extra); per-language resolvers with scanner-owned extensions (#483) run their path-only rules at scan time, repository-context capabilities land per language via the #484 preparation pass (Rust #358, C# #542); every consumer inherits dependency-awareness because the one-hop traversal is already generic over `edge.type` |

`configured_by` and `command_runs` edges are deferred. The scanner emits
`likely_tests` edges always, and `imports` edges when the `[treesitter]` extra
is installed (it degrades gracefully to `likely_tests`-only with a warning when
the extra is absent).
