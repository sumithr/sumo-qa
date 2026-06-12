# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
import json
import os
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from sumo_qa import paths
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
from sumo_qa.feedback_memory import (
    ACTIONS as _FEEDBACK_ACTIONS,
)
from sumo_qa.feedback_memory import (
    FeedbackValidationError,
)
from sumo_qa.feedback_memory import (
    capture_feedback as _capture_feedback,
)
from sumo_qa.feedback_memory import (
    delete_feedback as _delete_feedback,
)
from sumo_qa.feedback_memory import (
    list_feedback as _list_feedback,
)
from sumo_qa.feedback_memory import (
    update_feedback as _update_feedback,
)
from sumo_qa.ingest import IngestValidationError, ingest_pack
from sumo_qa.ingest import _write_atomic as _write_atomic
from sumo_qa.knowledge_loaders import (
    load_catalogue as _load_catalogue,
)
from sumo_qa.knowledge_loaders import (
    load_catalogue_entry as _load_catalogue_entry,
)
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
    ExportTestCasesOutput,
    FormatContextBundleOutput,
    FormatQaScorecardOutput,
    FormatRiskLedgerOutput,
    GenerateQAReportOutput,
    InstallExternalSkillOutput,
    RepoMapQueryOutput,
    RepoMapScanOutput,
    SearchExternalSkillsOutput,
    TestDataFindOutput,
    TestDataRegisterOutput,
    TestDataRequirementsOutput,
    TestDataValidateOutput,
)
from sumo_qa.skill_manifest import (
    list_skill_manifests as _list_skill_manifests,
)
from sumo_qa.skill_manifest import (
    load_skill_context as _load_skill_context,
)
from sumo_qa.skill_prompts import register_skills_as_prompts
from sumo_qa.skill_resources import register_skill_resources
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
_HINT_FEEDBACK_MEMORY = (
    "Pass action='capture'|'update'|'delete'|'list'. capture/update need an entry "
    "with scope, trigger_signal, recommended_probe, source_note (and optional "
    "last_reviewed). Store only your own short summary — never raw code, diffs, "
    "secrets, or pasted issue/PR bodies. Only persist with explicit user confirmation."
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
_HINT_FORMAT_SCORECARD = (
    "Compose the scorecard from already-produced artifacts (identify nothing "
    "here): ledger_rows=[...] (the #144 risk rows), context_bundle={...} (the "
    "#149 bundle), and optional coverage={line_percent, freshness} / "
    "mutation={survivors, killed, freshness}. freshness is one of "
    "fresh/stale/unknown/absent. Every part is optional — an empty payload "
    "derives insufficient_evidence. The recommendation is DERIVED, never "
    "asserted; you cannot pass 'ready'."
)
_HINT_EXPORT_TEST_CASES = (
    "Pass test_cases=[{id, title, preconditions, steps, expected_result, "
    "priority, evidence_status, optional linked_risk_id}, ...] and "
    "format='json'|'markdown'|'csv'. priority is one of critical/high/medium/low; "
    "evidence_status is one of planned/passing/failing/stale/accepted_residual. "
    "csv is only for flat outlines (<=1 precondition and <=1 step per case). "
    "Identify the cases yourself — this tool only validates and renders them, it "
    "never infers a case. Without output_path it is side-effect free: it returns "
    "text and writes nothing. output_path is optional; when given it must be under "
    "the project export root and must not overwrite an existing file."
)
_HINT_GENERATE_QA_REPORT = (
    "Pass an existing repo directory. Every artifact is optional — missing ones "
    "render as honest not-available states, never an error. risk_ledger_rows "
    "takes the same row shape as sumo_qa_format_risk_ledger; context_bundle the "
    "same dict as sumo_qa_format_context_bundle. Without write_to nothing is "
    "written; pass write_to='.sumo-qa/qa-report.html' to persist the page under "
    "the target repo."
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


def _resolve_export_target(output_path: str) -> Path:
    """Resolve+confine a host-supplied export ``output_path`` to the project
    export root (``<cwd>/.sumo-qa/exports``), reusing the #92 paths discipline.

    A relative path resolves against the exports root; an absolute path is taken
    as-is. After ``.resolve()`` (which collapses ``..`` and follows existing
    symlinks) the target — and its parent — must stay within the resolved exports
    root, else an out-of-root write is refused with a typed
    :class:`ExportValidationError`. The caller then writes via the atomic
    O_NOFOLLOW openat/renameat discipline (:func:`_write_atomic`) so that even if
    the validated parent is swapped for a symlink before the write, the temp-file
    creation and rename refuse to follow it out of root (TOCTOU-safe).
    """
    from sumo_qa.export_validation import ExportValidationError

    exports_root = paths.export_dir("project").resolve()
    candidate = Path(output_path)
    if not candidate.is_absolute():
        candidate = exports_root / candidate
    resolved = candidate.resolve()
    if not (
        resolved.is_relative_to(exports_root)
        and resolved.parent.resolve().is_relative_to(exports_root)
    ):
        raise ExportValidationError(
            kind="value_error",
            message=(
                f"output_path resolves to {resolved} which is outside the project "
                f"export root {exports_root}; refusing to write outside the project "
                "export root"
            ),
        )
    return resolved


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
    persisted_map_path: str | None,
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
        probable_mapping_gap=impact.probable_mapping_gap,
        suggested_inspections=impact.suggested_inspections,
        warning_count=len(impact.warnings),
        warnings_by_kind=dict(warnings_by_kind),
        is_stale=is_stale,
        used_live_scan=used_live_scan,
        artifact_path=artifact_path,
        persisted_map_path=persisted_map_path,
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


def _strip_schema_titles(node: Any) -> Any:
    """Recursively drop auto-generated ``title`` keys from a JSON schema.

    Pydantic emits a Title-Cased echo of every field name ("Base Ref",
    "Artifact Path") plus a ``<model>Arguments`` title per input model. Those
    titles carry no signal for the host LLM — tool selection reads the tool
    ``description``, argument filling reads ``properties``/``type``, and
    structured-output validators key on ``properties``/``required`` — yet
    measured across the full always-on ``tools/list`` they cost ~3.3k approx
    tokens, paid on every turn the server is connected. Stripping them is
    lossless for routing, argument filling, and output validation."""
    if isinstance(node, dict):
        return {k: _strip_schema_titles(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_strip_schema_titles(v) for v in node]
    return node


def _slim_tool_schemas(mcp: Any) -> None:
    """Remove auto-generated schema ``title`` keys from every registered tool's
    input and output schema, in place, once at build time.

    Reaches into the FastMCP tool registry because that is the only surface
    that holds the generated schemas. ``Tool.output_schema`` is a
    ``cached_property`` over ``fn_metadata.output_schema``, so the memoised
    value is dropped after the source dict is stripped, forcing the served
    schema to recompute from the slimmed source. The loop is pinned by
    tests/test_tool_schema_titles.py against the real served ``tools/list``,
    so a future FastMCP internal change fails loudly rather than silently
    re-inflating the surface."""
    for tool in mcp._tool_manager.list_tools():
        tool.parameters = _strip_schema_titles(tool.parameters)
        if tool.fn_metadata.output_schema is not None:
            tool.fn_metadata.output_schema = _strip_schema_titles(tool.fn_metadata.output_schema)
            tool.__dict__.pop("output_schema", None)


def _drop_structured_output(mcp: Any) -> None:
    """Stop emitting an ``outputSchema`` for every tool, once at build time.

    FastMCP derives an ``outputSchema`` from each tool's return annotation and
    ships it in ``tools/list``; measured across this server it is ~18k approx
    tokens — the single largest always-on surface, paid on every turn the
    server is connected. It buys nothing for the host LLM: FastMCP's
    ``convert_result`` ALWAYS computes the same text content via
    ``_convert_to_content`` (a tool's Pydantic return is rendered to indented
    JSON) and only ADDITIONALLY attaches a ``structuredContent`` block when an
    outputSchema is present. The text the model reads is therefore
    byte-for-byte identical with or without the schema — dropping it removes a
    redundant wire-level schema and a duplicate structured block, not signal.

    The tools' return models are still constructed (and so validated) inside
    each tool body, so correctness is unchanged; only the host-side re-
    validation against the published schema goes away. Nulling
    ``output_schema``/``output_model``/``wrap_output`` matches FastMCP's own
    ``structured_output=False`` state, so each tool returns plain text content.

    A post-build pass (over the final tool registry) so it covers every
    registration path — decorators, skill prompts, resources — uniformly,
    mirroring _slim_tool_schemas. Pinned by tests/test_tool_schema_titles.py
    (no ``outputSchema`` served) so a FastMCP internal change fails loudly."""
    for tool in mcp._tool_manager.list_tools():
        fn_metadata = tool.fn_metadata
        fn_metadata.output_schema = None
        fn_metadata.output_model = None
        fn_metadata.wrap_output = False
        tool.__dict__.pop("output_schema", None)


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

    @mcp.tool(annotations=_writer_local)
    def sumo_qa_capture_review_feedback(
        action: str = "list",
        entry: dict[str, Any] | None = None,
        entry_id: str | None = None,
        scope: str = "project",
    ) -> dict[str, Any]:
        """Manage an EXPLICIT, user-confirmed review-feedback memory of recurring QA findings.

        Promotes a recurring review lesson (e.g. "we always miss timezone
        boundaries in billing") into a local, inspectable, reversible memory that
        future planning/review skills consult as an ADVISORY hint — NOT automatic
        learning. `action` selects the operation:

        - `'capture'` — add a new lesson (or replace one with the same `id`).
          Requires `entry` with `scope`, `trigger_signal`, `recommended_probe`,
          `source_note`, and optional `last_reviewed` (ISO-8601; defaults to now).
        - `'update'` — replace the fields of an existing lesson; needs `entry_id`
          plus `entry`.
        - `'delete'` — remove a lesson by `entry_id`.
        - `'list'` (default) — return stored lessons, advisory-flagged. The
          `scope` default is the literal `'project'`, so it lists the current
          repo; pass `scope='global'` for the cross-repo set. An unrecognised
          `scope` returns an error envelope (it is never coerced to project).

        NEVER persist without explicit user confirmation, and NEVER auto-capture
        from a review/prompt/trace. That confirmation gate is the HOST/skill's
        responsibility, not enforced by a tool parameter — the deliberate
        writer-local data-ownership model shared with the risk-ledger and AC
        tools; the `sumo-qa-feedback` CLI correspondingly exposes only list/delete,
        so a capture can never be a fire-and-forget flag. Sensitive input — a raw
        diff hunk, a secret, a code snippet, or a pasted full issue/PR body — is
        REJECTED; only the user's own summary is stored, and a rejected entry is
        never echoed to the debug-capture sink either. Storage reuses the #92 user-writable pack
        location (`project` = <cwd>/.sumo-qa, `global` = the user data dir) under
        a `feedback/` subdir, so it is NOT a second hidden tree. Memory-derived
        probes are ADVISORY: cite them SEPARATELY from bundled ISTQB/rules
        content; they never override canonical classifications or change-rules.

        Common natural-language phrasings that map to this tool:
        "remember that we always miss X in Y", "save this review lesson", "promote
        this recurring finding to team memory", "what review lessons have we
        saved?", "forget the timezone-billing lesson".
        """
        try:
            # Pass `scope` through UNCHANGED — never coerce an unrecognised value
            # to 'project'. The feedback_memory module validates it via
            # `_require_scope` and raises FeedbackValidationError on an invalid
            # scope (e.g. a typo like 'glabal'), which the except below wraps into
            # an error envelope — so a typo surfaces as an error, not a silent
            # write to the project store.
            if action == "capture":
                output: dict[str, Any] = _capture_feedback(entry or {}, scope=scope)
            elif action == "update":
                output = _update_feedback(entry_id or "", entry or {}, scope=scope)
            elif action == "delete":
                output = _delete_feedback(entry_id or "", scope=scope)
            elif action == "list":
                # `list` defaults to the literal 'project' (the tool's default
                # arg) for the current-repo view; pass scope='global' for the
                # cross-repo set. An invalid scope errors via _require_scope.
                output = _list_feedback(scope=scope)
            else:
                output = _error_envelope(
                    FeedbackValidationError(
                        f"unknown action {action!r}; expected one of {list(_FEEDBACK_ACTIONS)}"
                    ),
                    _HINT_FEEDBACK_MEMORY,
                )
        except (FeedbackValidationError, ValueError, OSError) as exc:
            output = _error_envelope(exc, _HINT_FEEDBACK_MEMORY)
        # Never let a REJECTED raw `entry` reach the debug-capture sink. A rejected
        # entry may carry the exact secret / diff / code snippet the validator
        # refused, and `maybe_capture` writes `args` verbatim to disk when
        # SUMO_QA_DEBUG_DIR is set — which would contradict the feature's "sensitive
        # input is rejected, not stored" contract (#145). On a rejection we record
        # only the entry's field NAMES (its shape), never the values. On success the
        # entry passed the sensitivity gate, so capturing it is safe and useful.
        rejected = isinstance(output, dict) and output.get("isError")
        debug_entry: Any = (
            {"_redacted_keys": sorted(entry)} if rejected and isinstance(entry, dict) else entry
        )
        return maybe_capture(
            tool="sumo_qa_capture_review_feedback",
            args={"action": action, "entry": debug_entry, "entry_id": entry_id, "scope": scope},
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

        @mcp.tool(annotations=_read_only_local)
        def sumo_qa_load_catalogue_entry(
            catalogue: str,
            name: str | None = None,
            format: str = "full",
        ) -> str:
            """Load a single catalogue entry, or a whole catalogue in compact
            form, as a JSON string — a lighter alternative to the full-text
            loaders for one of the four prose catalogues: `classifications`,
            `approaches`, `principles`, `techniques`.

            - With `name` set: return one entry. `name` matches the stable slug
              id (`api_contract_change`, `equivalence-partitioning`) or the
              verbatim heading text (case-insensitive).
            - With `name` omitted: return the whole catalogue. `format="full"`
              (default) returns the verbatim catalogue text; `format="compact"`
              returns one lead-line summary per entry.

            `format`: `"full"` (default) returns verbatim entry text marked
            `canonical=true` — safe to cite. `"compact"` returns a truncated
            summary marked `canonical=false` — a navigation/recall aid, NOT a
            citation replacement; load the full form (or the zero-argument
            `sumo_qa_load_*` loader) when exact wording matters.

            Never raises: an unknown catalogue, name, or format returns a JSON
            error envelope listing the valid choices. The existing
            zero-argument `sumo_qa_load_*` loaders are unchanged. Read-only and
            local-only."""
            if name is None:
                payload = _load_catalogue(catalogue, format=format)
            else:
                payload = _load_catalogue_entry(catalogue, name=name, format=format)
            return json.dumps(payload, ensure_ascii=False, indent=2)

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
        otherwise; an artifact for a different project root is ignored. On the
        first run of an unmapped repo the live scan is persisted to
        ``artifact_path`` (reported as ``persisted_map_path``) unless
        ``artifact_path`` is ``None``. ``write_overlay`` writes
        ``.sumo-qa/diff-impact.json`` under ``root``. When test files exist but
        the map has no likely_tests edges, ``probable_mapping_gap`` flags the
        risk surface as a missed-convention gap rather than true zero coverage.
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

            # 1b. Auto-persist on the FIRST run of an unmapped repo (#266): the
            #     genuine no-artifact live scan is written out so the run leaves
            #     a discoverable artifact instead of re-scanning every call. A
            #     rejected FOREIGN artifact is left untouched (don't clobber the
            #     user's file), and artifact_path=None means the caller opted
            #     out of artifact use entirely.
            persisted_map_path: str | None = None
            if used_live_scan and foreign_artifact_warning is None and artifact_path is not None:
                cand = Path(artifact_path)
                if not cand.is_absolute():
                    cand = root_path / cand
                cand.parent.mkdir(parents=True, exist_ok=True)
                cand.write_text(
                    json.dumps(repo_map.model_dump(mode="json"), indent=2), encoding="utf-8"
                )
                persisted_map_path = str(cand.resolve())

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
                # When we persisted the scan, name the artifact so the warning
                # is actionable instead of a dead end (#266).
                if persisted_map_path is not None:
                    message = (
                        f"no repo-map artifact found; scanned live and persisted one to "
                        f"{persisted_map_path} for future runs"
                    )
                else:
                    message = (
                        "no repo-map artifact found; scanned live — run sumo_qa_scan_repo with "
                        "write_to to persist a repo-map for future runs"
                    )
                impact.warnings.append(RepoMapWarning(kind="other", message=message))
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
                persisted_map_path=persisted_map_path,
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

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_format_qa_scorecard(
        ledger_rows: list[dict[str, Any]] | None = None,
        context_bundle: dict[str, Any] | None = None,
        coverage: dict[str, Any] | None = None,
        mutation: dict[str, Any] | None = None,
        scope: str | None = None,
        local_head_sha: str | None = None,
        max_reasons: int = 25,
    ) -> FormatQaScorecardOutput | ErrorEnvelope:
        """Compose a QA READINESS SCORECARD from already-produced evidence and
        DERIVE a readiness recommendation (issue #151). EVIDENCE SUMMARY, NOT a
        predictive quality score — it infers no risk, invents no numeric score,
        and the host can never assert "ready": the verdict is computed.

        Common natural-language phrasings that map to this tool:
        "is this ready to merge/release", "give me a readiness scorecard",
        "summarise QA readiness", "release review summary".

        Inputs are all optional and reuse the existing artifacts — nothing is
        re-defined here:
        * ``ledger_rows`` — the #144 risk-to-test rows (same shape as
          ``sumo_qa_format_risk_ledger``); supplies risk coverage + blockers.
        * ``context_bundle`` — the #149 bundle (same shape as
          ``sumo_qa_format_context_bundle``); supplies test/CI evidence freshness.
        * ``coverage`` / ``mutation`` — optional ``{..., freshness}`` signals;
          absent ⇒ reported as "not measured", never assumed passing, and never
          allowed to outweigh an uncovered high-impact risk.
        * ``scope`` — optional label (a PR title, a release name).
        * ``local_head_sha`` — optional live local head, to flag a stale bundle.

        Returns the four-state recommendation (ready / ready_with_accepted_
        residuals / blocked / insufficient_evidence), ``is_ready`` (true only for
        the two ready states), the uncovered-blocker / residual counts, the
        stale-evidence and not-measured dimension lists, the rendered markdown,
        a one-line ``compact_summary`` to drop inline in short answers, and a
        JSON-able ``serialized`` snapshot a downstream report (#157) can render.
        Readiness is refused whenever a risk is an uncovered blocker or evidence
        is stale — that guarantee is structural, not advisory.
        """
        from sumo_qa.scorecard_format import (
            compact_summary,
            format_scorecard_markdown,
            serialize_scorecard,
        )
        from sumo_qa.scorecard_validation import load_scorecard

        output: FormatQaScorecardOutput | dict[str, Any]
        try:
            card = load_scorecard(
                ledger_rows=ledger_rows,
                context_bundle=context_bundle,
                coverage=coverage,
                mutation=mutation,
                scope=scope,
            )
            serialized = serialize_scorecard(card, local_head_sha=local_head_sha)
            output = FormatQaScorecardOutput(
                recommendation=serialized["recommendation"],
                is_ready=serialized["is_ready"],
                uncovered_blocker_count=serialized["uncovered_blocker_count"],
                open_residual_count=serialized["open_residual_count"],
                accepted_residual_count=serialized["accepted_residual_count"],
                stale_evidence=serialized["stale_evidence"],
                not_measured=serialized["not_measured"],
                markdown=format_scorecard_markdown(
                    card, local_head_sha=local_head_sha, max_reasons=max_reasons
                ),
                compact_summary=compact_summary(card, local_head_sha=local_head_sha),
                serialized=serialized,
            )
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_FORMAT_SCORECARD)
        return maybe_capture(  # type: ignore[return-value]
            tool="sumo_qa_format_qa_scorecard",
            args={
                "ledger_rows": ledger_rows,
                "context_bundle": context_bundle,
                "coverage": coverage,
                "mutation": mutation,
                "scope": scope,
                "local_head_sha": local_head_sha,
                "max_reasons": max_reasons,
            },
            output=output,  # type: ignore[arg-type]
        )

    @mcp.tool(annotations=_writer_local)
    def sumo_qa_export_test_cases(
        test_cases: list[dict[str, Any]],
        format: str = "markdown",
        export_title: str | None = None,
        output_path: str | None = None,
    ) -> ExportTestCasesOutput | ErrorEnvelope:
        """Deterministically EXPORT already-structured QA test cases into one
        documented machine-readable shape (issue #148). FILE/FORMAT PLUMBING ONLY
        — the host LLM identifies the cases; this tool never infers them and never
        inspects a repo. By DEFAULT it is side-effect free (it RETURNS the rendered
        text and writes nothing); a file is persisted ONLY when an explicit
        ``output_path`` is supplied.

        Each case is a dict with: ``id`` (stable within this export), ``title``,
        ``preconditions`` (ordered list, may be empty), ``steps`` (ordered list,
        may be empty), ``expected_result``, optional ``linked_risk_id`` (a risk id
        in a companion risk ledger), ``priority`` (one of critical / high / medium
        / low), and ``evidence_status`` (one of planned / passing / failing /
        stale / accepted_residual — the same vocabulary as the risk ledger).

        ``format`` is one of: ``markdown`` (the DEFAULT human-facing table),
        ``json`` (a versioned, key-sorted, deterministic document), or ``csv``
        (OPTIONAL, and only valid for a *flat* outline — at most one precondition
        and one step per case). An unsupported format, or CSV for a non-flat
        export, returns an error envelope naming the supported formats. Tool-
        specific import mappings may need local adjustment.

        ``export_title`` (optional) names the export as a whole — rendered in the
        markdown header and the JSON top-level ``title``. (It is named
        ``export_title``, not ``title``, so it is distinct from each case's own
        ``title`` and survives the served-schema title-slimming pass.)

        ``output_path`` (optional) is the EXPLICIT file-write carve-out. When
        omitted (the default) nothing is written. When given, the SAME rendered
        bytes are ALSO persisted, confined to the project export root
        (``<cwd>/.sumo-qa/exports``): a relative path resolves under that root, an
        absolute path or ``..`` traversal that escapes it is refused, and an
        already-existing target is refused rather than silently overwritten. The
        write only happens AFTER successful validation+render, so a bad export
        never leaves a file. On a successful write ``written_path`` carries the
        resolved absolute path (else ``None``).

        Returns the rendered ``content``, the chosen ``format``, the stamped
        ``schema_version``, the validated ``test_case_count``, and ``written_path``
        (the persisted location, or ``None`` on the default no-write path).
        """
        from sumo_qa.export_format import export_test_cases
        from sumo_qa.export_models import EXPORT_SCHEMA_VERSION
        from sumo_qa.export_validation import load_test_case_export

        output: ExportTestCasesOutput | dict[str, Any]
        try:
            export = load_test_case_export(
                {
                    "schema_version": EXPORT_SCHEMA_VERSION,
                    "title": export_title,
                    "test_cases": test_cases,
                }
            )
            content = export_test_cases(export, format)
            written_path: str | None = None
            if output_path is not None:
                # Explicit file-write carve-out (#148): persist the SAME rendered
                # bytes, confined to the project export root, only after a clean
                # validate+render. Refuse a silent overwrite of an existing target.
                target = _resolve_export_target(output_path)
                if target.exists():
                    raise FileExistsError(
                        f"refusing to overwrite existing export at {target}; remove "
                        "it or choose another output_path"
                    )
                # _write_atomic mkdir's the dest parent (within the confined
                # root), then writes via an O_NOFOLLOW openat/renameat chain
                # against the parent's dir fd — so even if an attacker swaps the
                # parent for a symlink in the gap after _resolve_export_target,
                # the write refuses to follow it out of root (TOCTOU-safe).
                _write_atomic(target, content)
                written_path = str(target.resolve())
            output = ExportTestCasesOutput(
                format=format,  # type: ignore[arg-type]
                schema_version=export.schema_version,
                test_case_count=len(export.test_cases),
                content=content,
                written_path=written_path,
            )
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_EXPORT_TEST_CASES)
        return maybe_capture(  # type: ignore[return-value]
            tool="sumo_qa_export_test_cases",
            args={
                "test_cases": test_cases,
                "format": format,
                "export_title": export_title,
                "output_path": output_path,
            },
            output=output,  # type: ignore[arg-type]
        )

    @mcp.tool(annotations=_writer_local)
    def sumo_qa_generate_qa_report(
        root: str,
        write_to: str | None = None,
        risk_ledger_rows: list[dict[str, Any]] | None = None,
        context_bundle: dict[str, Any] | None = None,
    ) -> GenerateQAReportOutput | ErrorEnvelope:
        """Compose the persisted ``.sumo-qa`` artifacts (repo map, diff
        impact, risk ledger, context bundle) into the local QA report and
        return a compact readiness summary. The
        rendered HTML body never rides back to the host — pass ``write_to`` to
        persist the self-contained static page and open it from disk.

        Common natural-language phrasings that map to this tool:
        "generate the QA report", "build the QA dashboard for this repo",
        "give me the local QA readiness report", "render qa-report.html".

        ``root`` is the repository to report on (absolute or relative to the
        MCP server's working directory). Every artifact is OPTIONAL: a missing,
        invalid, or stale source renders an explicit honest state. The readiness
        verdict (ready / ready_with_accepted_residuals / blocked /
        insufficient_evidence) is derived by the QaScorecard readiness engine
        from the risk ledger + context bundle — missing data is never reported
        as passing evidence.

        ``risk_ledger_rows`` / ``context_bundle`` are inline overrides for the
        chat flow where the ledger/bundle was built in-conversation and never
        persisted (the same shapes ``sumo_qa_format_risk_ledger`` /
        ``sumo_qa_format_context_bundle`` accept). They take precedence over
        any on-disk file and are validated BEFORE anything is written.

        ``write_to`` is optional — when set, the page is written there
        (relative paths land under the target repo; the conventional value is
        ``.sumo-qa/qa-report.html``). Without it the tool writes nothing.
        """
        from sumo_qa.context_bundle_validation import load_context_bundle as _load_bundle
        from sumo_qa.ledger_models import LEDGER_SCHEMA_VERSION as _LEDGER_SCHEMA_VERSION
        from sumo_qa.ledger_validation import load_ledger as _load_ledger
        from sumo_qa.report_builder import generate_report as _generate_report
        from sumo_qa.report_builder import write_run_summary as _write_run_summary
        from sumo_qa.report_html import render_report_html as _render_report_html

        output: GenerateQAReportOutput | dict[str, Any]
        try:
            root_path = Path(root).resolve()
            if not root_path.is_dir():
                raise NotADirectoryError(f"root must be an existing directory: {root!s}")
            # Validate inline overrides FIRST so a bad payload is an error
            # envelope before any disk read or write happens.
            ledger_override = (
                _load_ledger({"schema_version": _LEDGER_SCHEMA_VERSION, "rows": risk_ledger_rows})
                if risk_ledger_rows is not None
                else None
            )
            bundle_override = _load_bundle(context_bundle) if context_bundle is not None else None
            report = _generate_report(
                root_path,
                generator_version=_package_version(),
                ledger_override=ledger_override,
                bundle_override=bundle_override,
            )
            artifact_path: str | None = None
            artifact_bytes: int | None = None
            if write_to is not None:
                # Resolve a relative write_to against the TARGET root, not the
                # MCP server's cwd — the conventional `.sumo-qa/qa-report.html`
                # must land under the repo being reported on. Unlike the
                # scan_repo precedent, a relative path is CONFINED to that
                # root: a `..`/symlink escape is refused, so a relative
                # request can never write outside the repo it names. An
                # absolute path stays caller-explicit.
                target = Path(write_to)
                if not target.is_absolute():
                    target = (root_path / target).resolve()
                    if not target.is_relative_to(root_path):
                        raise ValueError(
                            f"write_to resolves to {target}, outside the "
                            f"target root {root_path}; pass a path under the "
                            "repo or an explicit absolute path"
                        )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(_render_report_html(report), encoding="utf-8")
                artifact_path = str(target.resolve())
                artifact_bytes = target.stat().st_size
                # A page-writing call also persists the compact run summary
                # the NEXT report's delta line reads; the side-effect-free
                # call (no write_to) writes neither.
                _write_run_summary(root_path, report)
            output = GenerateQAReportOutput(
                root=str(root_path),
                readiness_state=report.readiness.state,
                readiness_reasons=list(report.readiness.reasons),
                artifact_statuses={a.kind: a.status for a in report.artifacts},
                changed_component_count=len(report.changed_components),
                affected_component_count=len(report.affected_components),
                related_test_count=len(report.related_tests),
                risk_count=len(report.risks),
                uncovered_blocker_count=report.uncovered_blocker_count,
                warning_count=len(report.warnings),
                artifact_path=artifact_path,
                artifact_bytes=artifact_bytes,
            )
        except Exception as exc:  # noqa: BLE001
            output = _error_envelope(exc, _HINT_GENERATE_QA_REPORT)
        return maybe_capture(  # type: ignore[return-value]
            tool="sumo_qa_generate_qa_report",
            args={
                "root": root,
                "write_to": write_to,
                "risk_ledger_rows": risk_ledger_rows,
                "context_bundle": context_bundle,
            },
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

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_list_skill_manifests(detail: str = "compact") -> str:
        """Return deterministic metadata for every bundled sumo-qa skill as a
        JSON string — a routing/index aid, NOT the skill bodies.

        `detail` controls how much per-skill index is included (default
        "compact"):
          - "compact" — routing metadata only: skill_name, tool_name (the
            zero-argument skill tool), description (from frontmatter),
            content_hash (sha256 of the SKILL.md) and estimated_tokens_full. NO
            sections[]/modules[] arrays — the cheap all-skill routing slice.
          - "full_index" — the same metadata PLUS each skill's sections[] (id,
            heading, level, estimated_tokens, required) and modules[] (id, path,
            estimated_tokens) index arrays. Section ids are stable heading slugs
            (duplicates get `-2`/`-3` suffixes); required marks the structural
            sections (frontmatter, Iron Law, Checklist, Flow, Red Flags,
            HARD-GATE) when present.

        Once routing has chosen one skill, fetch that skill's section/module
        index with `sumo_qa_load_skill_context(skill_name, mode="manifest")`,
        then a single slice via mode="section"/"module"/"full".

        An unrecognised `detail` returns a JSON error envelope listing the valid
        values rather than raising. Read-only and local-only: no network, no
        extraction, no caching. The existing zero-argument skill tools still
        return full bodies unchanged."""
        return json.dumps(_list_skill_manifests(detail), ensure_ascii=False, indent=2)

    @mcp.tool(annotations=_read_only_local)
    def sumo_qa_load_skill_context(
        skill_name: str | None = None,
        mode: str | None = None,
        section: str | None = None,
        module: str | None = None,
        known_hash: str | None = None,
    ) -> str:
        """Load just one slice of a skill's context as a JSON string, instead of
        the whole SKILL.md body.

        `mode`:
          - "manifest" — routing summary + section list + module list;
          - "section"  — one section's text (pass `section`, an id from the
            manifest);
          - "module"   — one module's text (pass `module`, an id from the
            manifest);
          - "full"     — the entire SKILL.md body, byte-for-byte identical to the
            existing zero-argument skill tool for `skill_name`.

        The section/module/full slices each return `content_hash` (sha256 of the
        returned text) and `estimated_tokens`. Pass `known_hash` to ask "has this
        slice changed since hash X?": a match returns `changed=false` with the
        body omitted (saving the re-send), a mismatch returns `changed=true` with
        the body. This is derived per call — there is NO hidden session cache, so
        it is safe across hosts regardless of MCP session identity.

        Never raises: an unknown skill_name/mode/section/module, a missing
        required arg, or a path-traversal attempt returns a JSON error envelope
        listing the valid choices. Read-only and local-only."""
        return json.dumps(
            _load_skill_context(
                skill_name, mode, section=section, module=module, known_hash=known_hash
            ),
            ensure_ascii=False,
            indent=2,
        )

    register_skills_as_prompts(mcp)
    register_skill_resources(mcp)
    _slim_tool_schemas(mcp)
    _drop_structured_output(mcp)
    return mcp


def main() -> None:
    build_mcp_server().run()
