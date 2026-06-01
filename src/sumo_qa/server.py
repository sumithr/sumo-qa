# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
import json
import os
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from sumo_qa.capabilities import build_capabilities
from sumo_qa.debug_capture import maybe_capture
from sumo_qa.external_skills import (
    check_external_skill_installed as _check_external_skill_installed,
)
from sumo_qa.external_skills import (
    execute_external_skill as _execute_external_skill,
)
from sumo_qa.external_skills import (
    hint_for_exception as _hint_for_external_skill_exception,
)
from sumo_qa.external_skills import (
    install_external_skill as _install_external_skill,
)
from sumo_qa.external_skills import (
    search_external_skills as _search_external_skills,
)
from sumo_qa.ingest import IngestValidationError, ingest_pack
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_approaches as _load_approaches,
)
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_classifications as _load_classifications,
)
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_principles as _load_principles,
)
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_rules as _load_rules,
)
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_standards as _load_standards,
)
from sumo_qa.knowledge_loaders import (
    sumo_qa_load_techniques as _load_techniques,
)
from sumo_qa.server_schemas import (
    CapabilitiesOutput,
    CheckExternalSkillInstalledOutput,
    DiffImpactOutput,
    ErrorEnvelope,
    ExecuteExternalSkillOutput,
    FormatContextBundleOutput,
    FormatRiskLedgerOutput,
    InstallExternalSkillOutput,
    RepoMapQueryOutput,
    RepoMapScanOutput,
    SearchExternalSkillsOutput,
    TestDataFindOutput,
    TestDataRegisterOutput,
    TestDataRequirementsOutput,
    TestDataValidateOutput,
)
from sumo_qa.skill_prompts import register_skills_as_prompts
from sumo_qa.tools import QAShiftLeftService

# Reusable actionable hints for isError envelopes. Hosts surface these to the
# user when a tool fails, so they should describe a concrete next step rather
# than restate the error.
_HINT_LOCAL_FILES_MISSING = (
    "If the working tree or knowledge/test_data/ is missing files, confirm the repo is checked out."
)
_HINT_TEST_DATA_WRITE = (
    "If the write fails, confirm `knowledge/test_data/` is writable and the entry's "
    "`domain` field matches an existing folder."
)
_HINT_INVALID_SCOPE = "Pass scope='global' or scope='project'."
_HINT_INGEST = (
    "Pass a native md/yaml file (principles.md, techniques.md, classifications.md, "
    "approaches.md, a standards-pack *.yaml, or change_rules.yaml). Convert other "
    "formats (PDF/PPTX/URL) to markdown first via the sumo-qa-suggesting-external-skill flow."
)
_HINT_SCAN_REPO = (
    "Pass an existing directory path. Use an absolute path or one relative to the "
    "MCP server's working directory."
)
_HINT_DIFF_IMPACT = (
    "Pass an existing repo directory plus either changed_files=[...] or "
    "base_ref='<git ref>'. The repo-map artifact is optional — without it the "
    "tool scans live."
)
_HINT_QUERY_REPO_MAP = (
    "Pass an existing repo directory plus a non-blank query. Optional: "
    "types=['test_file', ...] to restrict, limit>=0 to bound results. The "
    "repo-map artifact is optional — without it the tool scans live."
)
_HINT_FORMAT_LEDGER = (
    "Pass rows=[{risk_id, risk, source_anchor, test, evidence_status, residual}, ...]. "
    "evidence_status is one of planned/passing/failing/stale/accepted_residual; "
    "residual is one of open/accepted/mitigated/blocker. Identify the risks "
    "yourself — this tool only validates and formats them, it never infers risk."
)
_HINT_FORMAT_CONTEXT_BUNDLE = (
    "Pass a bundle dict with optional issue_summary, pr_summary, head_sha, "
    "changed_files=[{path, change_kind}], test_evidence/ci_status="
    "{result, freshness, source}, and user_constraints. freshness is one of "
    "fresh/stale/unknown/absent; result is one of passing/failing/mixed/not_run; "
    "source is one of manual/local_git/github/ci_provider/other. Everything but "
    "schema is optional — a partial bundle is fine. Supply local_head_sha to "
    "detect a bundle-vs-local-state conflict. No network call; gather facts yourself."
)


def _error_envelope(exc: BaseException, actionable_hint: str) -> dict[str, Any]:
    """Wrap an exception in the MCP `isError` envelope.

    The host surfaces `error.actionable_hint` to the user when the protocol
    error pattern is suppressed in favour of structured tool output.
    """
    return {
        "isError": True,
        "error": {
            "type": exc.__class__.__name__,
            "message": str(exc).strip() or "(no message)",
            "actionable_hint": actionable_hint,
        },
    }


def _package_version() -> str:
    """Return the installed sumo-qa version string for use as a default
    ``generator_version`` on repo-map scans. Uses importlib.metadata so the
    string matches whatever the wheel / editable install actually advertises."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return f"sumo-qa {version('sumo-qa')}"
        except PackageNotFoundError:  # pragma: no cover -- dev source-tree fallback
            return "sumo-qa (unreleased)"
    except ImportError:  # pragma: no cover -- importlib.metadata stdlib on 3.10+
        return "sumo-qa (unknown)"


def _build_scan_summary(
    repo_map: Any,
    artifact_path: str | None = None,
    artifact_bytes: int | None = None,
) -> RepoMapScanOutput:
    """Collapse a :class:`RepoMap` into the compact :class:`RepoMapScanOutput`.

    The host gets per-type counts, not the full node/edge arrays — a real
    scan against this repo produces 240 nodes and an 83KB JSON; collapsing
    to counts keeps the per-tool response inside any reasonable host budget
    while still surfacing the shape the caller needs to decide next steps.
    """
    from collections import Counter

    nodes_by_type = Counter(n.type for n in repo_map.nodes)
    edges_by_type = Counter(e.type for e in repo_map.edges)
    edges_by_confidence = Counter(e.confidence for e in repo_map.edges)
    commands_by_kind = Counter(c.kind for c in repo_map.commands)
    warnings_by_kind = Counter(w.kind for w in repo_map.warnings)
    return RepoMapScanOutput(
        root=repo_map.project.root,
        name=repo_map.project.name,
        git_commit=repo_map.project.git_commit,
        schema_version=repo_map.schema_version,
        generator_version=repo_map.project.generator_version,
        generated_at=repo_map.project.generated_at,
        node_count=len(repo_map.nodes),
        nodes_by_type=dict(nodes_by_type),
        edge_count=len(repo_map.edges),
        edges_by_type=dict(edges_by_type),
        edges_by_confidence=dict(edges_by_confidence),
        command_count=len(repo_map.commands),
        commands_by_kind=dict(commands_by_kind),
        warning_count=len(repo_map.warnings),
        warnings_by_kind=dict(warnings_by_kind),
        artifact_path=artifact_path,
        artifact_bytes=artifact_bytes,
    )


def _build_impact_summary(
    impact: Any,
    *,
    root: str,
    base_ref: str | None,
    is_stale: bool,
    used_live_scan: bool,
    artifact_path: str | None,
    overlay_path: str | None,
    overlay_bytes: int | None,
    changed_file_count: int,
) -> DiffImpactOutput:
    """Collapse a :class:`DiffImpact` into the compact :class:`DiffImpactOutput`."""
    from collections import Counter

    warnings_by_kind = Counter(w.kind for w in impact.warnings)
    return DiffImpactOutput(
        root=root,
        base_ref=base_ref,
        changed_file_count=changed_file_count,
        changed_nodes=[n.model_dump() for n in impact.changed_nodes],
        affected_nodes=[n.model_dump() for n in impact.affected_nodes],
        related_tests=impact.related_tests,
        unmapped_files=impact.unmapped_files,
        risk_surface=impact.risk_surface,
        suggested_inspections=impact.suggested_inspections,
        warning_count=len(impact.warnings),
        warnings_by_kind=dict(warnings_by_kind),
        is_stale=is_stale,
        used_live_scan=used_live_scan,
        artifact_path=artifact_path,
        overlay_path=overlay_path,
        overlay_bytes=overlay_bytes,
    )


def _load_map_with_fallback(
    root_path: Path, artifact_path: str | None
) -> tuple[Any, str | None, bool, Any]:
    """Load a repo-map for ``root_path``: persisted artifact preferred, live-scan fallback.

    Returns ``(repo_map, artifact_used, used_live_scan, foreign_warning)``. A
    foreign artifact (its ``project.root`` != ``root_path``) is ignored — its
    node paths would be measured against a different tree — and the live scan
    runs instead, with ``foreign_warning`` set so the caller can surface why.
    Shared by ``sumo_qa_analyze_diff_impact`` and ``sumo_qa_query_repo_map``.
    """
    from sumo_qa.repo_map_models import RepoMapWarning
    from sumo_qa.repo_map_scanner import scan_repo
    from sumo_qa.repo_map_validation import load_repo_map

    repo_map = None
    artifact_used: str | None = None
    foreign_warning: Any = None
    if artifact_path is not None:
        cand = Path(artifact_path)
        if not cand.is_absolute():
            cand = root_path / cand
        if cand.is_file():
            loaded = load_repo_map(cand)
            if Path(loaded.project.root).resolve() == root_path.resolve():
                repo_map = loaded
                artifact_used = str(cand.resolve())
            else:
                foreign_warning = RepoMapWarning(
                    kind="other",
                    message=(
                        f"ignored repo-map at {cand!s}: its project.root "
                        f"{loaded.project.root!r} does not match scan root "
                        f"{root_path.resolve()!s}"
                    ),
                )
    used_live_scan = False
    if repo_map is None:
        repo_map = scan_repo(root_path, generator_version=_package_version())
        used_live_scan = True
    return repo_map, artifact_used, used_live_scan, foreign_warning


def _detect_staleness(root_path: Path, repo_map: Any) -> tuple[bool, str | None]:
    """Return ``(is_stale, current_head)``: stale when the map's recorded
    git_commit differs from current HEAD.

    Never blocks — a missing HEAD or a map without a git_commit is simply not
    stale (the comparison needs both sides). ``current_head`` is returned so a
    caller can name the differing sha in a warning."""
    from sumo_qa.repo_map_scanner import _detect_git_commit

    current = _detect_git_commit(root_path)
    is_stale = (
        current is not None
        and repo_map.project.git_commit is not None
        and current != repo_map.project.git_commit
    )
    return is_stale, current


def _build_query_summary(
    result: Any,
    *,
    root: str,
    repo_map: Any,
    is_stale: bool,
    used_live_scan: bool,
    artifact_path: str | None,
    warnings: list,
) -> RepoMapQueryOutput:
    """Collapse a :class:`RepoMapQueryResult` + freshness into :class:`RepoMapQueryOutput`.

    ``limit`` is taken from ``result.limit`` (the effective, clamped value), so
    the output reflects the limit actually applied rather than the raw request.
    """
    from collections import Counter

    warnings_by_kind = Counter(w.kind for w in warnings)
    return RepoMapQueryOutput(
        root=root,
        query=result.query,
        limit=result.limit,
        types_filter=result.types_filter,
        matches=[m.model_dump() for m in result.matches],
        total_matches=result.total_matches,
        truncated=result.truncated,
        schema_version=repo_map.schema_version,
        generator_version=repo_map.project.generator_version,
        generated_at=repo_map.project.generated_at,
        git_commit=repo_map.project.git_commit,
        is_stale=is_stale,
        used_live_scan=used_live_scan,
        artifact_path=artifact_path,
        warning_count=len(warnings),
        warnings_by_kind=dict(warnings_by_kind),
    )


def build_service() -> QAShiftLeftService:
    standards_path = Path(os.environ.get("QA_STANDARDS_PATH", "standards/packs"))
    rules_path = Path(os.environ.get("QA_RULES_PATH", "standards/rules/change_rules.yaml"))
    test_data_path = Path(os.environ.get("QA_TEST_DATA_PATH", "knowledge/test_data"))
    return QAShiftLeftService.from_standards_path(standards_path, rules_path, test_data_path)


def build_mcp_server(service: QAShiftLeftService | None = None) -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise RuntimeError("The MCP SDK is not installed. Run `pip install -e .`.") from exc

    qa_service = service or build_service()
    mcp = FastMCP(
        "sumo-qa",
        instructions=(
            "ROUTING DIRECTIVE — for any QA-shaped request (testing, test plan, "
            "test strategy, test approach, regression scope, risk-based testing, "
            "exploratory testing, code review for safety-to-merge, scaffolding "
            "tests, TDD, mutation testing, finding or validating test data, QA "
            "audit, designing a test pyramid), you MUST call sumo-qa tools "
            "before producing QA advice. Start with the entry router "
            "`sumo_qa_using_sumo_qa`; it picks the right sub-skill. Do not "
            "answer QA questions from general training-data knowledge. "
            "When citing principles, techniques, classifications, or "
            "approaches, first load them via `sumo_qa_load_principles`, "
            "`sumo_qa_load_techniques`, `sumo_qa_load_classifications`, or "
            "`sumo_qa_load_approaches` — cite the loaded catalogue, not "
            "remembered material. If the catalogue is silent, say so "
            "explicitly rather than supplementing from training data.\n\n"
            "sumo-qa — senior-QA-shaped MCP server + skills library. "
            "Created by Sumith Ramsookbhai (https://github.com/sumithr). "
            "Licensed under Apache-2.0; please preserve the NOTICE file when redistributing."
        ),
        website_url="https://github.com/sumithr/sumo-qa",
    )

    # Standard annotation patterns. The QA test-data reasoning tools are read-only
    # and idempotent. Only `sumo_qa_register_known_good_test_data` writes to disk,
    # and even then the operation is additive (never deletes), so
    # destructiveHint stays false.
    _read_only_local = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    _writer_local = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
    _read_only_external = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
    _read_only_external_local = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    _writer_external = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_explain_test_data_requirements(
        question: str,
        environment: str = "",
        domain: str = "",
    ) -> TestDataRequirementsOutput | ErrorEnvelope:
        """Explain what test data shape and characteristics are needed for a scenario.

        Returns: required entity characteristics, resource-state conditions,
        scenario preconditions, downstream dependencies, edge cases, and
        explicit "what NOT to use" guidance. Domain-neutral by design — works
        for any domain (auth, billing, retail, infrastructure, ML, etc.).
        Optional `environment` (e.g. "integration") and `domain` are folded
        into the analysis.

        Common natural-language phrasings that map to this tool:
        "what data do I need to test X", "what test data should I look for to
        cover X", "what records / accounts / fixtures do I need for X",
        "what's the minimum data setup for X", "what edge-case data should I
        test".
        """
        try:
            output = qa_service.qa_explain_test_data_requirements(question, environment, domain)
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_LOCAL_FILES_MISSING)
        captured = maybe_capture(
            tool="sumo_qa_explain_test_data_requirements",
            args={
                "question": question,
                "environment": environment,
                "domain": domain,
            },
            output=output,
        )
        return captured  # type: ignore[return-value]

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_find_test_data(
        environment: str = "",
        domain: str = "",
        scenario_tags: Annotated[
            list | None,
            Field(
                default=None,
                description="Scenario tags to match against catalogue entries.",
                examples=[["boundary_input", "degraded_dependency"]],
            ),
        ] = None,
        known_valid_for: Annotated[
            list | None,
            Field(
                default=None,
                description="Use-case labels the entry has been validated for.",
                examples=[["boundary input validation"]],
            ),
        ] = None,
        product_id: str = "",
        sku: str = "",
        limit: int = 5,
        offset: int = 0,
    ) -> TestDataFindOutput | ErrorEnvelope:
        """Search the local known-good test data catalogue for entries that match a scenario.

        Returns: ranked matches with confidence, freshness, and suitability
        reasons. Reads the local YAML catalogue under `knowledge/test_data/`
        only; no external lookups. Optional `scenario_tags` and `known_valid_for`
        narrow the search.

        Pagination: pass `offset` to skip the first N matches, and read
        `total_count`, `has_more`, and `next_offset` on the response to walk
        pages. When `has_more` is false, `next_offset` is null.

        Common natural-language phrasings that map to this tool:
        "find me test data for X", "do we have a known-good record for X",
        "give me an account / fixture / record that does X", "is there a
        fixture for X", "what test data is available for X".
        """
        try:
            output = qa_service.qa_find_test_data(
                environment,
                domain,
                scenario_tags,
                known_valid_for,
                product_id,
                sku,
                limit,
                offset,
            )
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_LOCAL_FILES_MISSING)
        captured = maybe_capture(
            tool="sumo_qa_find_test_data",
            args={
                "environment": environment,
                "domain": domain,
                "scenario_tags": scenario_tags,
                "known_valid_for": known_valid_for,
                "product_id": product_id,
                "sku": sku,
                "limit": limit,
                "offset": offset,
            },
            output=output,
        )
        return captured  # type: ignore[return-value]

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_validate_test_data(
        entry_id: str | None = None,
        entry: dict | None = None,
    ) -> TestDataValidateOutput | ErrorEnvelope:
        """Validate a test data entry without provisioning or mutating downstream systems.

        Returns: validation result with confidence level, freshness status, and
        an explained reason. Accepts either `entry_id` (looked up in the
        catalogue) or `entry` (a full record dict).

        Common natural-language phrasings that map to this tool:
        "is this test data still valid", "validate this record", "is entry X
        still good", "check if X is fresh".
        """
        try:
            output = qa_service.qa_validate_test_data(entry_id, entry)
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_LOCAL_FILES_MISSING)
        captured = maybe_capture(
            tool="sumo_qa_validate_test_data",
            args={
                "entry_id": entry_id,
                "entry": entry,
            },
            output=output,
        )
        return captured  # type: ignore[return-value]

    @mcp.tool(annotations=_writer_local)
    def sumo_qa_register_known_good_test_data(
        entry: dict,
    ) -> TestDataRegisterOutput | ErrorEnvelope:
        """Add or update a known-good test data entry in the local YAML catalogue.

        Detects duplicates by environment + domain + product/SKU + scenario
        overlap. Writes to `knowledge/test_data/<domain>/known_good.yaml`.

        Arg shape — pass `entry` as a literal dict, NOT a YAML string. Example:

            sumo_qa_register_known_good_test_data(entry={
                "id": "billing-overdue-invoice-001",
                "environment": "staging",
                "domain": "billing",
                "scenario_tags": ["overdue_invoice", "dunning_eligible"],
                "known_valid_for": ["dunning workflow testing"],
                "constraints": ["Reset overdue flag after test."],
                "owner": "billing-platform",
                "last_validated_at": "2026-05-16T09:00:00Z",
                "confidence": "high",
                "source": "qa-curated",
                "notes": "Overdue invoice usable for dunning-flow testing.",
            })

        Common natural-language phrasings that map to this tool:
        "save this as known-good test data", "register this fixture so the team
        can reuse it", "promote this record to known-good", "update the
        validated timestamp on entry X", "add this record to the catalogue".
        """
        try:
            output = qa_service.qa_register_known_good_test_data(entry)
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_TEST_DATA_WRITE)
        captured = maybe_capture(
            tool="sumo_qa_register_known_good_test_data",
            args={
                "entry": entry,
            },
            output=output,
        )
        return captured  # type: ignore[return-value]

    @mcp.tool(annotations=_writer_local)
    def sumo_qa_ingest_knowledge_pack(
        source: str,
        scope: str = "project",
        content_type: str | None = None,
    ) -> dict[str, Any]:
        """Adds or replaces team QA knowledge/standards/rules from a local native file.

        Accepts a path to a native sumo-qa file or a directory of them:
        principles.md, techniques.md, classifications.md, approaches.md, a
        standards-pack *.yaml, or change_rules.yaml. Validates the content and
        writes a normalized copy into a user-writable pack. The `scope` argument
        selects where it lands: `'project'` (<cwd>/.sumo-qa, the current repo
        only) or `'global'` (the user data dir, every repo) — the right scope is
        a user choice worth confirming. Loader precedence is env var > project >
        global > bundled > repo root.

        A PDF / PPTX / URL or any other non-native source is not parsed here; it
        returns an `unsupported_source` result that routes through the
        `sumo-qa-suggesting-external-skill` flow to convert the source to
        markdown, which is then re-ingested with an explicit `content_type`.

        Common natural-language phrasings that map to this tool:
        "add this to the knowledge base", "replace our principles", "load our
        team standards pack", "use these change rules", "ingest this QA pack".
        """
        try:
            output: dict[str, Any] = ingest_pack(source, scope=scope, content_type=content_type)
        except (IngestValidationError, ValueError, OSError) as exc:
            output = _error_envelope(exc, _HINT_INGEST)
        return maybe_capture(
            tool="sumo_qa_ingest_knowledge_pack",
            args={"source": source, "scope": scope, "content_type": content_type},
            output=output,
        )

    def _register_knowledge_loaders(mcp):
        """Register the 7 knowledge-provider tools.

        Each tool is a thin wrapper around a markdown read. The host LLM picks
        from the returned catalogue; this server does no inference."""

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_load_classifications() -> str:
            """Return the canonical change classifications as plain text. The
            host LLM picks which apply to a given change."""
            return _load_classifications()

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_load_approaches() -> str:
            """Return the canonical QA approaches as plain text. The host LLM
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
        def sumo_qa_load_standards(classification: str | None = None) -> str:
            """Return the team's loaded standards packs as plain text. Optional
            classification filter is metadata-based and accepts comma-separated
            values (packs whose frontmatter declares any requested
            classification); no keyword inference."""
            return _load_standards(classification=classification)

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_load_rules(classification: str | None = None) -> str:
            """Return the team's loaded change rules as plain text. Optional
            classification filter accepts single or comma-separated values and
            returns matching rule entries; no keyword inference."""
            return _load_rules(classification=classification)

    _register_knowledge_loaders(mcp)

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_capabilities() -> CapabilitiesOutput:
        """Return a compact, read-only map of sumo-qa's core QA workflows — each
        with a sample prompt, the skill it routes to, and a one-line outcome. A
        discovery aid for "what can sumo-qa do?"; does NOT replace the
        using-sumo-qa entry router or sumo_qa_deciding_approach."""
        return build_capabilities()

    @mcp.tool(annotations=_writer_local)
    def sumo_qa_scan_repo(
        root: str,
        generator_version: str | None = None,
        write_to: str | None = None,
    ) -> RepoMapScanOutput | ErrorEnvelope:
        """Walk a repository and return a compact summary of its QA-relevant
        shape: per-type node counts, likely_tests edge counts by confidence,
        command counts by kind, warning counts by kind. Optionally writes the
        full schema-validated ``.sumo-qa/repo-map.json`` artifact to disk via
        ``write_to``.

        Common natural-language phrasings that map to this tool:
        "map this repo", "scan the repo and tell me what's here", "give me a
        QA-shaped inventory of this project", "what tests exercise what
        sources in this repo", "generate the repo-map artifact for X".

        ``root`` is the repository to scan (absolute or relative to the MCP
        server's working directory). ``generator_version`` defaults to the
        installed sumo-qa version. ``write_to`` is optional — when set, the
        full artifact is written to that JSON path, deterministic on the
        same repo state except for ``project.generated_at``.
        """
        from sumo_qa.repo_map_scanner import scan_repo as _scan_repo

        output: RepoMapScanOutput | dict[str, Any]
        try:
            resolved_version = generator_version or _package_version()
            repo_map = _scan_repo(root, generator_version=resolved_version)
            artifact_path: str | None = None
            artifact_bytes: int | None = None
            if write_to is not None:
                # Resolve a relative write_to against the SCANNED root, not the
                # MCP server's cwd — the conventional `.sumo-qa/repo-map.json`
                # must land under the repo being mapped so downstream consumers
                # find it, even when root != server cwd.
                target = Path(write_to)
                if not target.is_absolute():
                    target = Path(root) / target
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = json.dumps(repo_map.model_dump(mode="json"), indent=2)
                target.write_text(payload, encoding="utf-8")
                artifact_path = str(target.resolve())
                artifact_bytes = target.stat().st_size
            output = _build_scan_summary(
                repo_map,
                artifact_path=artifact_path,
                artifact_bytes=artifact_bytes,
            )
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_SCAN_REPO)
        return maybe_capture(  # type: ignore[return-value]
            tool="sumo_qa_scan_repo",
            args={
                "root": root,
                "generator_version": generator_version,
                "write_to": write_to,
            },
            output=output,  # type: ignore[arg-type]
        )

    @mcp.tool(annotations=_writer_local)
    def sumo_qa_analyze_diff_impact(
        root: str,
        base_ref: str | None = None,
        changed_files: list[str] | None = None,
        artifact_path: str | None = ".sumo-qa/repo-map.json",
        write_overlay: bool = False,
    ) -> DiffImpactOutput | ErrorEnvelope:
        """Map a set of changed files onto the repo-map to report which tests
        likely exercise them, which changed sources have no mapped test (the
        risk surface), one-hop affected nodes, unmapped files, and whether the
        map is stale relative to HEAD.

        Common natural-language phrasings that map to this tool:
        "what does this diff affect", "which tests cover my changes", "what's
        the risk surface of this branch", "what should I re-test after these
        edits", "analyse the impact of the changes against main".

        ``root`` is the repository. Supply ``changed_files`` (repo-relative
        paths) OR ``base_ref`` (any git ref; changed files are the diff against
        the merge-base of ``base_ref`` and HEAD, so changes that landed on the
        base after the branch diverged don't leak in). The repo-map is read
        from ``artifact_path`` when present and falls back to a live scan
        otherwise; an artifact for a different project root is ignored.
        ``write_overlay`` writes ``.sumo-qa/diff-impact.json`` under ``root``.
        """
        from sumo_qa.repo_map_impact import analyze_diff_impact, changed_files_from_git
        from sumo_qa.repo_map_models import RepoMapWarning

        output: DiffImpactOutput | dict[str, Any]
        try:
            root_path = Path(root)
            if not root_path.is_dir():
                raise ValueError(f"root must be a directory: {root_path!s}")

            # 1. Load the map (artifact preferred, live-scan fallback; foreign
            #    artifact ignored — see _load_map_with_fallback).
            repo_map, artifact_used, used_live_scan, foreign_artifact_warning = (
                _load_map_with_fallback(root_path, artifact_path)
            )

            # 2. Resolve changed files.
            if changed_files is not None:
                resolved = sorted(set(changed_files))
            elif base_ref is not None:
                resolved = changed_files_from_git(root_path, base_ref)
            else:
                raise ValueError("provide changed_files or base_ref")

            # 3. Staleness (never blocks).
            is_stale, current = _detect_staleness(root_path, repo_map)

            # 4. Analyse + attach wrapper-level warnings.
            impact = analyze_diff_impact(repo_map, resolved)
            if foreign_artifact_warning is not None:
                impact.warnings.append(foreign_artifact_warning)
            elif used_live_scan:
                # Only the genuine no-artifact case gets this message; a
                # rejected foreign artifact already has its own warning above.
                impact.warnings.append(
                    RepoMapWarning(
                        kind="other",
                        message="no repo-map artifact found; scanned live",
                    )
                )
            if is_stale:
                impact.warnings.append(
                    RepoMapWarning(
                        kind="stale",
                        message=(
                            f"repo-map git_commit {repo_map.project.git_commit} "
                            f"differs from HEAD {current}"
                        ),
                    )
                )

            # 5. Overlay.
            overlay_path: str | None = None
            overlay_bytes: int | None = None
            if write_overlay:
                target = root_path / ".sumo-qa" / "diff-impact.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = json.dumps(impact.model_dump(mode="json"), indent=2)
                target.write_text(payload, encoding="utf-8")
                overlay_path = str(target.resolve())
                overlay_bytes = target.stat().st_size

            output = _build_impact_summary(
                impact,
                root=str(root_path.resolve()),
                base_ref=base_ref,
                is_stale=bool(is_stale),
                used_live_scan=used_live_scan,
                artifact_path=artifact_used,
                overlay_path=overlay_path,
                overlay_bytes=overlay_bytes,
                changed_file_count=len(resolved),
            )
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_DIFF_IMPACT)
        return maybe_capture(  # type: ignore[return-value]
            tool="sumo_qa_analyze_diff_impact",
            args={
                "root": root,
                "base_ref": base_ref,
                "changed_files": changed_files,
                "artifact_path": artifact_path,
                "write_overlay": write_overlay,
            },
            output=output,  # type: ignore[arg-type]
        )

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_query_repo_map(
        root: str,
        query: str,
        limit: int = 10,
        types: list[str] | None = None,
        artifact_path: str | None = ".sumo-qa/repo-map.json",
    ) -> RepoMapQueryOutput | ErrorEnvelope:
        """Search the repo-map for the components, tests, CI checks, configs, or
        commands that match a query, returning a bounded, ranked list with
        enough metadata (id, path, type, tags, match reason) to open the files
        directly — never the full artifact.

        Common natural-language phrasings that map to this tool:
        "find the repo-map node for X", "which tests are mapped to the billing
        module", "list the CI workflows in the map", "what commands does the
        repo-map know about", "search the map for files tagged mcp".

        ``root`` is the repository. ``query`` matches case-insensitively across
        node id, path, file name, type, category, and tags, and across command
        names and kinds; results rank exact identity above substring hits.
        ``limit`` caps the returned matches (``total_matches`` still reports the
        full count). ``types`` restricts the search to given node types and/or
        the literal ``"command"``. The repo-map is read from ``artifact_path``
        when present and falls back to a live scan otherwise; an artifact for a
        different project root is ignored.
        """
        from sumo_qa.repo_map_models import RepoMapWarning
        from sumo_qa.repo_map_query import query_repo_map as _query_repo_map

        output: RepoMapQueryOutput | dict[str, Any]
        try:
            root_path = Path(root)
            if not root_path.is_dir():
                raise ValueError(f"root must be a directory: {root_path!s}")

            # Load the map (artifact preferred, live-scan fallback; foreign
            # artifact ignored), then judge staleness vs HEAD. Shared with the
            # diff-impact tool so both surfaces behave identically.
            repo_map, artifact_used, used_live_scan, foreign_warning = _load_map_with_fallback(
                root_path, artifact_path
            )
            is_stale, current = _detect_staleness(root_path, repo_map)

            result = _query_repo_map(repo_map, query, limit=limit, types=types)

            # Mirror diff-impact's warning surface: foreign-artifact rejection,
            # live-scan fallback, and staleness. The query never blocks on any
            # of them — they ride along as warnings so the host can fall back to
            # direct repo inspection when the map is missing or stale.
            warnings: list[RepoMapWarning] = []
            if foreign_warning is not None:
                warnings.append(foreign_warning)
            elif used_live_scan:
                warnings.append(
                    RepoMapWarning(kind="other", message="no repo-map artifact found; scanned live")
                )
            if is_stale:
                warnings.append(
                    RepoMapWarning(
                        kind="stale",
                        message=(
                            f"repo-map git_commit {repo_map.project.git_commit} "
                            f"differs from HEAD {current}"
                        ),
                    )
                )

            output = _build_query_summary(
                result,
                root=str(root_path.resolve()),
                repo_map=repo_map,
                is_stale=bool(is_stale),
                used_live_scan=used_live_scan,
                artifact_path=artifact_used,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_QUERY_REPO_MAP)
        return maybe_capture(  # type: ignore[return-value]
            tool="sumo_qa_query_repo_map",
            args={
                "root": root,
                "query": query,
                "limit": limit,
                "types": types,
                "artifact_path": artifact_path,
            },
            output=output,  # type: ignore[arg-type]
        )

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_format_risk_ledger(
        rows: list[dict[str, Any]],
        max_rows: int = 25,
    ) -> FormatRiskLedgerOutput | ErrorEnvelope:
        """Validate and render a risk-to-test traceability ledger as a markdown
        appendix (issue #144). FILE/FORMAT PLUMBING ONLY — the host LLM identifies
        the risks; this tool never infers them.

        Each row is a dict with: ``risk_id`` (stable within this response),
        ``risk`` (the statement), ``source_anchor`` (file:line or domain term),
        ``test`` (a test id OR a 'planned: …' check), ``evidence_status`` (one of
        planned / passing / failing / stale / accepted_residual), ``residual``
        (one of open / accepted / mitigated / blocker), and an optional
        ``repo_map_node_id`` linking to a ``.sumo-qa/repo-map.json`` node.

        Returns the rendered markdown table (the structured appendix the
        markdown-first verdict carries), a one-line compact summary, the row
        count, and the count of uncovered blockers (rows that are not passing,
        not accepted, and marked residual=blocker — the signal the review
        workflow uses to refuse safe-to-merge). The table is bounded by
        ``max_rows`` so a large ledger stays inside the host token budget.
        """
        from sumo_qa.ledger_format import compact_summary, format_ledger_markdown
        from sumo_qa.ledger_models import LEDGER_SCHEMA_VERSION
        from sumo_qa.ledger_validation import load_ledger

        output: FormatRiskLedgerOutput | dict[str, Any]
        try:
            ledger = load_ledger({"schema_version": LEDGER_SCHEMA_VERSION, "rows": rows})
            blockers = sum(1 for row in ledger.rows if row.is_uncovered_blocker())
            output = FormatRiskLedgerOutput(
                row_count=len(ledger.rows),
                uncovered_blocker_count=blockers,
                markdown=format_ledger_markdown(ledger, max_rows=max_rows),
                compact_summary=compact_summary(ledger),
                truncated=len(ledger.rows) > max(max_rows, 0),
            )
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_FORMAT_LEDGER)
        return maybe_capture(  # type: ignore[return-value]
            tool="sumo_qa_format_risk_ledger",
            args={"rows": rows, "max_rows": max_rows},
            output=output,  # type: ignore[arg-type]
        )

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_format_context_bundle(
        bundle: dict[str, Any],
        local_head_sha: str | None = None,
        max_files: int = 40,
    ) -> FormatContextBundleOutput | ErrorEnvelope:
        """Validate and render a host-neutral issue/PR CONTEXT BUNDLE as a
        compact markdown brief for QA review/planning (issue #149). FILE/FORMAT
        PLUMBING ONLY — the host gathers the facts; this tool never inspects a
        repo, makes a network call, or assumes GitHub. A partial/empty bundle is
        first-class: when little is supplied, the consuming skill falls back to
        direct repo inspection.

        Common natural-language phrasings that map to this tool:
        "build the review context bundle", "format this PR/issue context for
        review", "render the context bundle with its freshness", "summarise the
        diff/CI/test facts I gathered".

        ``bundle`` is a dict with optional ``issue_summary``, ``pr_summary``,
        ``head_sha``, ``changed_files`` (each ``{path, change_kind}``),
        ``test_evidence`` / ``ci_status`` (each ``{result, freshness, source}``,
        plus optional ``captured_at`` / ``detail``), and ``user_constraints``.
        ``freshness`` is one of fresh/stale/unknown/absent; only a FRESH PASS is
        safety-supporting — a stale, unknown, or absent fact is rendered with an
        explicit "do not claim safety from it" warning. Supply ``local_head_sha``
        (the host's live local head) to detect a bundle-vs-local-state conflict;
        when the shas differ the brief calls out the divergence instead of
        trusting either side. ``max_files`` bounds the changed-file list.
        """
        from sumo_qa.context_bundle_format import (
            compact_summary as _bundle_summary,
        )
        from sumo_qa.context_bundle_format import (
            format_context_bundle_markdown,
        )
        from sumo_qa.context_bundle_models import detect_local_conflict
        from sumo_qa.context_bundle_validation import load_context_bundle

        output: FormatContextBundleOutput | dict[str, Any]
        try:
            validated = load_context_bundle(bundle)
            output = FormatContextBundleOutput(
                markdown=format_context_bundle_markdown(
                    validated, local_head_sha=local_head_sha, max_files=max_files
                ),
                compact_summary=_bundle_summary(validated, local_head_sha=local_head_sha),
                changed_file_count=len(validated.changed_files),
                stale_evidence_fields=validated.stale_evidence_fields(),
                untrustworthy_evidence_fields=validated.untrustworthy_evidence_fields(),
                conflict=detect_local_conflict(validated, local_head_sha),
            )
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_FORMAT_CONTEXT_BUNDLE)
        return maybe_capture(  # type: ignore[return-value]
            tool="sumo_qa_format_context_bundle",
            args={"bundle": bundle, "local_head_sha": local_head_sha, "max_files": max_files},
            output=output,  # type: ignore[arg-type]
        )

    @mcp.tool(annotations=_read_only_external)
    def sumo_qa_search_external_skills(query: str) -> SearchExternalSkillsOutput | ErrorEnvelope:
        """Search the Skills CLI registry for external agent skills.

        Returns the ANSI-stripped CLI output verbatim plus a one-line hint on
        how to read it. No structured parsing — the host LLM interprets the
        raw text so format drift in the Skills CLI doesn't break the flow.
        """
        try:
            output = _search_external_skills(query)
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _hint_for_external_skill_exception(exc))
        return maybe_capture(  # type: ignore[return-value]
            tool="sumo_qa_search_external_skills",
            args={"query": query},
            output=output,
        )

    @mcp.tool(annotations=_read_only_external_local)
    def sumo_qa_check_external_skill_installed(
        skill: str,
        scope: str = "auto",
    ) -> CheckExternalSkillInstalledOutput | ErrorEnvelope | None:
        """Locate an installed external SKILL.md file for Codex, Claude, or agents paths.

        Returns the first matching path for project or global skill locations,
        or null when the skill is absent.
        """
        try:
            output = _check_external_skill_installed(skill, scope=scope)
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _hint_for_external_skill_exception(exc))
        return maybe_capture(  # type: ignore[return-value]
            tool="sumo_qa_check_external_skill_installed",
            args={"skill": skill, "scope": scope},
            output=output,  # type: ignore[arg-type]
        )

    @mcp.tool(annotations=_writer_external)
    def sumo_qa_install_external_skill(
        skill: str,
        source: str = "https://github.com/vercel-labs/skills",
        scope: str = "project",
        agent: str = "codex",
        confirmed: bool = False,
    ) -> InstallExternalSkillOutput | ErrorEnvelope:
        """Install an external agent skill through the Skills CLI.

        The confirmed flag records that the host received explicit user
        approval before invoking the install operation.
        """
        try:
            output = _install_external_skill(
                skill=skill,
                source=source,
                scope=scope,
                agent=agent,
                confirmed=confirmed,
            )
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _hint_for_external_skill_exception(exc))
        return maybe_capture(  # type: ignore[return-value]
            tool="sumo_qa_install_external_skill",
            args={
                "skill": skill,
                "source": source,
                "scope": scope,
                "agent": agent,
                "confirmed": confirmed,
            },
            output=output,
        )

    @mcp.tool(annotations=_read_only_external_local)
    def sumo_qa_execute_external_skill(
        skill: str,
        intent: str = "",
        scope: str = "auto",
    ) -> ExecuteExternalSkillOutput | ErrorEnvelope:
        """Load an installed external SKILL.md and return the execution handoff.

        The payload contains the skill body plus the original intent so the
        host can follow the external workflow in the current conversation.
        """
        try:
            output = _execute_external_skill(skill=skill, intent=intent, scope=scope)
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _hint_for_external_skill_exception(exc))
        return maybe_capture(  # type: ignore[return-value]
            tool="sumo_qa_execute_external_skill",
            args={"skill": skill, "intent": intent, "scope": scope},
            output=output,
        )

    register_skills_as_prompts(mcp)
    return mcp


def main() -> None:
    build_mcp_server().run()
