# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Pydantic output models for the structured sumo-qa MCP tools.

FastMCP auto-derives ``outputSchema`` on each tool from the function's return-
type annotation when that annotation is a Pydantic BaseModel. Models here
mirror the shapes the tools already return — they do NOT add, rename, or
re-type fields. Drift between a model and the tool's actual return is a bug
in this file, not in the tool.

Error envelope: every tool can also return the existing dict-based
``{"isError": True, "error": {...}}`` shape on failure (built by
``server._error_envelope``). That shape is modelled by :class:`ErrorEnvelope`
below, and each tool's annotated return is ``ModelName | ErrorEnvelope`` —
Pydantic accepts both branches and FastMCP emits a discriminated union
outputSchema keyed on ``isError``. Using a bare ``dict`` here would emit
``additionalProperties: true`` on the error arm and silently widen the
public outputSchema, defeating the contract this module exists to provide.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Re-used scalar shapes. Kept in sync with sumo_qa.tdm_models — when the
# underlying domain model changes, mirror the change here.
_ConfidenceLevel = Literal["low", "medium", "high"]
_FreshnessStatus = Literal["fresh", "aging", "stale", "unknown", "not_applicable"]


class _StrictBase(BaseModel):
    """Base for every output model.

    ``extra="forbid"`` means an unmodelled key in the dict the tool returns
    will raise a ``ValidationError``. That makes drift loud in tests rather
    than silently widening the public outputSchema.

    ``__test__ = False`` keeps pytest from trying to collect the
    ``TestData*`` model classes as test classes.
    """

    model_config = ConfigDict(extra="forbid")
    __test__ = False


class _ErrorDetail(_StrictBase):
    """Inner payload of the MCP tool error envelope."""

    type: str = Field(description="Exception class name (e.g. 'ValueError', 'FileNotFoundError').")
    message: str = Field(
        description=(
            "Cleaned exception message; '(no message)' when the exception was raised with no args."
        )
    )
    actionable_hint: str = Field(
        description="One-line hint the host surfaces to the user with a concrete next step."
    )


class ErrorEnvelope(_StrictBase):
    """The MCP tool error envelope returned by ``sumo_qa.server._error_envelope``.

    Used as the typed alternative to a bare ``dict`` in every tool's return
    annotation. Without this, FastMCP would emit an unconstrained
    ``additionalProperties: true`` schema arm, allowing any shape through and
    defeating the outputSchema contract.

    ``isError`` is ``Literal[True]`` so Pydantic + FastMCP treat it as a
    discriminator, routing between each tool's success model and this
    envelope in the emitted ``anyOf``/``oneOf`` schema.
    """

    isError: Literal[True] = Field(
        description="Marks the response as an error per the MCP error-shape convention."
    )
    error: _ErrorDetail = Field(
        description="Structured error payload with type, message, and actionable_hint."
    )


class _Confidence(_StrictBase):
    level: _ConfidenceLevel = Field(description="One of low / medium / high.")
    reason: str = Field(description="Why this confidence level was assigned.")


class _Freshness(_StrictBase):
    status: _FreshnessStatus = Field(
        description="Freshness category derived from last_validated_at."
    )
    last_validated_at: datetime | None = Field(
        default=None,
        description="UTC timestamp the entry was last validated, if known.",
    )
    age_days: int | None = Field(
        default=None,
        description="Days since last validation, or null when not applicable.",
    )
    reason: str = Field(description="Human-readable rationale for the freshness status.")


class _Entry(_StrictBase):
    id: str = Field(description="Stable, human-readable catalogue identifier.")
    environment: str = Field(description="Target environment (e.g. integration, staging).")
    domain: str = Field(description="Domain folder under knowledge/test_data/ this entry lives in.")
    product_id: str | None = Field(default=None, description="Optional product identifier.")
    sku: str | None = Field(default=None, description="Optional SKU identifier.")
    scenario_tags: list[str] = Field(
        default_factory=list,
        description="Scenario tags this entry is suitable for.",
    )
    known_valid_for: list[str] = Field(
        default_factory=list,
        description="Use-case labels the entry has been validated against.",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Operational constraints to honour when using this entry.",
    )
    owner: str = Field(description="Team or individual responsible for this entry.")
    last_validated_at: datetime | None = Field(
        default=None,
        description="UTC timestamp the entry was last validated.",
    )
    confidence: _ConfidenceLevel = Field(
        default="low", description="Catalogued confidence level for the entry."
    )
    source: str = Field(description="Provenance of the entry (e.g. qa-curated, imported).")
    notes: str = Field(default="", description="Free-text notes about this entry.")
    validation_source: str = Field(
        default="catalogue",
        description="Where the entry's validation history comes from.",
    )


class _ValidationResult(_StrictBase):
    entry_id: str = Field(description="Catalogue id of the entry that was validated.")
    valid: bool = Field(description="True when the validator could not find any blocking issues.")
    confidence: _Confidence = Field(description="Confidence in the validation result.")
    freshness: _Freshness = Field(description="Freshness metadata for the validated entry.")
    validation_source: str = Field(
        description="Identifier of the validator that produced this result."
    )
    validation_reason: str = Field(description="Why the validator reached this verdict.")
    checked_at: datetime = Field(description="UTC timestamp the validation was performed.")
    issues: list[str] = Field(
        default_factory=list,
        description="List of blocking issues; empty when valid is true.",
    )


class _SearchResult(_StrictBase):
    entry: _Entry = Field(description="The catalogue entry that matched.")
    validation: _ValidationResult = Field(
        description="Validation result computed for this entry against the active validator."
    )
    suitability_reason: str = Field(
        description="Why this entry was considered suitable for the query."
    )
    rank_score: int = Field(description="Internal ranking score; higher is better.")


# ---------------------------------------------------------------------------
# Tool output models
# ---------------------------------------------------------------------------


class TestDataRequirementsOutput(_StrictBase):
    """Output of ``sumo_qa_explain_test_data_requirements``."""

    tool: Literal["sumo_qa_explain_test_data_requirements"] = Field(
        default="sumo_qa_explain_test_data_requirements",
        description="Tool discriminator; always the literal tool name.",
    )
    summary: str = Field(description="One-line summary of the test-data shape required.")
    domain: str = Field(description="Resolved domain the requirements were scoped to.")
    environment: str | None = Field(
        default=None,
        description="Resolved environment the requirements were scoped to, if supplied.",
    )
    required_entity_characteristics: list[str] = Field(
        default_factory=list,
        description="Characteristics the entity under test must have.",
    )
    resource_state_conditions: list[str] = Field(
        default_factory=list,
        description="Required starting state of the resource under test.",
    )
    scenario_preconditions: list[str] = Field(
        default_factory=list,
        description="Preconditions that must be satisfied before running the scenario.",
    )
    downstream_dependencies: list[str] = Field(
        default_factory=list,
        description="Upstream/downstream systems the test interacts with.",
    )
    edge_case_recommendations: list[str] = Field(
        default_factory=list,
        description="Named edge cases worth covering.",
    )
    what_not_to_use: list[str] = Field(
        default_factory=list,
        description="Data shapes explicitly out of bounds for this scenario.",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Operational assumptions the requirements rely on.",
    )
    confidence: _Confidence = Field(description="Confidence in the requirements reasoning.")
    freshness: _Freshness = Field(
        description="Freshness metadata; not-applicable for requirements reasoning."
    )
    validation_source: str = Field(
        description="Identifier of the reasoning path that produced these requirements."
    )


class TestDataFindOutput(_StrictBase):
    """Output of ``sumo_qa_find_test_data``."""

    tool: Literal["sumo_qa_find_test_data"] = Field(
        default="sumo_qa_find_test_data",
        description="Tool discriminator; always the literal tool name.",
    )
    query: dict[str, object] = Field(
        description="Echo of the query filters applied (environment, domain, tags, etc.)."
    )
    results: list[_SearchResult] = Field(
        default_factory=list,
        description="Ranked matches; highest rank_score first.",
    )
    total_count: int = Field(
        default=0,
        description="Total number of matches before pagination.",
    )
    has_more: bool = Field(
        default=False,
        description="True when there are further pages beyond next_offset.",
    )
    next_offset: int | None = Field(
        default=None,
        description="Offset to pass to the next call, or null when there are no more pages.",
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="Filters the caller could supply to narrow the search.",
    )
    confidence: _Confidence = Field(description="Aggregate confidence across the returned matches.")
    freshness: _Freshness = Field(description="Freshness metadata of the top match.")
    validation_source: str = Field(
        description="Identifier of the validator that produced per-result validations."
    )


class TestDataValidateOutput(_StrictBase):
    """Output of ``sumo_qa_validate_test_data``."""

    tool: Literal["sumo_qa_validate_test_data"] = Field(
        default="sumo_qa_validate_test_data",
        description="Tool discriminator; always the literal tool name.",
    )
    entry: _Entry = Field(description="The catalogue entry that was validated.")
    validation: _ValidationResult = Field(description="Validation result for the entry.")


class TestDataRegisterOutput(_StrictBase):
    """Output of ``sumo_qa_register_known_good_test_data``."""

    tool: Literal["sumo_qa_register_known_good_test_data"] = Field(
        default="sumo_qa_register_known_good_test_data",
        description="Tool discriminator; always the literal tool name.",
    )
    action: Literal["created", "updated", "duplicate"] = Field(
        description="Whether the entry was newly created, updated in place, or matched a duplicate."
    )
    entry: _Entry = Field(description="The entry as persisted in the catalogue.")
    validation: _ValidationResult = Field(description="Validation result for the persisted entry.")
    catalogue_path: str = Field(description="Filesystem path the entry was written to.")
    duplicate_of: str | None = Field(
        default=None,
        description="Catalogue id of the existing duplicate when action is 'duplicate'.",
    )


# ---------------------------------------------------------------------------
# External-skills tools (delegate to external_skills.py)
# ---------------------------------------------------------------------------


class SearchExternalSkillsOutput(_StrictBase):
    """Output of ``sumo_qa_search_external_skills``."""

    query: str = Field(description="Echo of the search query the caller supplied.")
    command: list[str] = Field(
        description="The argv list executed (npx + skills CLI args) for traceability."
    )
    raw_output: str = Field(
        description="ANSI-stripped stdout from the Skills CLI; one candidate per line."
    )
    stderr: str = Field(
        description="ANSI-stripped stderr from the Skills CLI; usually empty on success."
    )
    hint: str = Field(description="Guidance for the host LLM on how to parse raw_output.")


class CheckExternalSkillInstalledOutput(_StrictBase):
    """Success-shape output of ``sumo_qa_check_external_skill_installed``.

    The underlying function returns ``None`` when the skill is not installed;
    that branch is preserved at the server-wiring layer via a
    ``CheckExternalSkillInstalledOutput | None`` annotation rather than
    modelled here.
    """

    name: str = Field(
        description="Canonical skill name (hyphen/underscore-normalised) as discovered on disk."
    )
    path: str = Field(description="POSIX path to the installed SKILL.md file.")
    agent: str = Field(
        description="Agent flavour the skill is installed for (codex / claude-code / agents)."
    )
    # Resolved on-disk scope, never the "auto" input — see external_skills.py
    # _candidate_paths which emits only "project" or "global".
    scope: Literal["project", "global"] = Field(
        description="Where the skill is installed: project (cwd-relative) or global (home-relative)."
    )


class InstallExternalSkillOutput(_StrictBase):
    """Output of ``sumo_qa_install_external_skill``."""

    skill: str = Field(description="Echo of the skill name the caller requested.")
    source: str = Field(description="Source URL or registry the skill was installed from.")
    scope: Literal["project", "global"] = Field(
        description="Install scope: project (cwd-relative) or global (home-relative)."
    )
    agent: str = Field(description="Agent flavour the skill was installed for.")
    command: list[str] = Field(
        description="The argv list executed (npx + skills CLI args) for traceability."
    )
    installed: CheckExternalSkillInstalledOutput | None = Field(
        description=(
            "Discovered on-disk location after install, or null when the post-install "
            "check could not find a SKILL.md."
        )
    )
    raw_output: str = Field(description="ANSI-stripped stdout from the Skills CLI install run.")
    stderr: str = Field(description="ANSI-stripped stderr from the Skills CLI install run.")


class ExecuteExternalSkillOutput(_StrictBase):
    """Output of ``sumo_qa_execute_external_skill``."""

    skill: str = Field(description="Canonical skill name as discovered on disk.")
    path: str = Field(description="POSIX path to the SKILL.md that was loaded.")
    agent: str = Field(description="Agent flavour the skill is installed for.")
    scope: Literal["project", "global"] = Field(
        description="Install scope the loaded skill came from."
    )
    intent: str = Field(
        description="Echo of the intent the caller passed; empty string when none supplied."
    )
    skill_body: str = Field(
        description="Verbatim contents of SKILL.md, ready to hand to the host LLM."
    )
    execution_prompt: str = Field(
        description="Fixed handoff prompt instructing the host to follow the loaded SKILL.md."
    )


class CapabilityWorkflow(_StrictBase):
    """One core QA workflow surfaced by ``sumo_qa_capabilities``."""

    workflow: str = Field(description="Short human name of the workflow.")
    sample_prompt: str = Field(description="An example user prompt that triggers this workflow.")
    target_skill: str = Field(
        description="The sumo-qa skill this workflow routes to (an existing skills/<name>)."
    )
    outcome: str = Field(description="One-line description of what the workflow produces.")


class CapabilitiesOutput(_StrictBase):
    """Output of ``sumo_qa_capabilities``.

    A compact, read-only map of sumo-qa's core QA workflows. Discovery only —
    it does not replace the ``using-sumo-qa`` entry router or
    ``sumo_qa_deciding_approach``; it just answers "what can sumo-qa do?".
    """

    tool: Literal["sumo_qa_capabilities"] = Field(
        default="sumo_qa_capabilities",
        description="Tool discriminator; always the literal tool name.",
    )
    workflows: list[CapabilityWorkflow] = Field(
        description="Core QA workflows, each with a sample prompt and the skill it routes to."
    )


class RepoMapScanOutput(_StrictBase):
    """Compact summary of a ``sumo_qa_scan_repo`` invocation.

    Deliberately omits the full ``nodes`` / ``edges`` arrays — those can be
    tens of thousands of entries on a large repo and would blow past the
    host's per-tool token budget. Callers that need the full artifact pass
    a ``write_to`` path and read it from disk, or use the
    ``sumo_qa.repo_map_scanner.scan_repo`` Python API directly.
    """

    tool: Literal["sumo_qa_scan_repo"] = Field(
        default="sumo_qa_scan_repo",
        description="Tool discriminator; always the literal tool name.",
    )
    root: str = Field(description="Absolute, resolved root path that was scanned.")
    name: str | None = Field(
        default=None,
        description="Project name (resolved from the root directory's basename).",
    )
    git_commit: str | None = Field(
        default=None,
        description="HEAD commit SHA when root IS a git toplevel; null otherwise.",
    )
    schema_version: str = Field(
        description="Schema version of the underlying RepoMap artifact (currently '1.0')."
    )
    generator_version: str = Field(description="Generator version string passed by the caller.")
    generated_at: datetime = Field(description="UTC timestamp when this scan ran.")
    node_count: int = Field(description="Total number of nodes in the produced artifact.")
    nodes_by_type: dict[str, int] = Field(
        default_factory=dict,
        description="Per-type counts (e.g. {'source_file': 46, 'test_file': 101}).",
    )
    edge_count: int = Field(description="Total number of edges in the produced artifact.")
    edges_by_type: dict[str, int] = Field(
        default_factory=dict,
        description="Per-type counts (e.g. {'likely_tests': 20}).",
    )
    edges_by_confidence: dict[str, int] = Field(
        default_factory=dict,
        description="Per-confidence counts (e.g. {'high': 18, 'medium': 2}).",
    )
    command_count: int = Field(description="Total number of commands extracted.")
    commands_by_kind: dict[str, int] = Field(
        default_factory=dict,
        description="Per-kind counts (e.g. {'test': 1, 'lint': 1, 'other': 7}).",
    )
    warning_count: int = Field(description="Total number of warnings emitted by the scan.")
    warnings_by_kind: dict[str, int] = Field(
        default_factory=dict,
        description="Per-kind counts (e.g. {'unsupported_language': 11, 'skipped_file': 1}).",
    )
    artifact_path: str | None = Field(
        default=None,
        description="Absolute path the full artifact was written to, when write_to was provided.",
    )
    artifact_bytes: int | None = Field(
        default=None,
        description="Size of the written artifact in bytes, when write_to was provided.",
    )


class _ImpactNodeSummary(_StrictBase):
    """Compact node projection inside :class:`DiffImpactOutput`."""

    id: str = Field(description="Node id, e.g. 'file:src/app.py'.")
    type: str = Field(description="Node type from the repo-map vocabulary.")
    path: str = Field(description="Repo-relative path.")
    has_mapped_tests: bool = Field(
        description="True when at least one likely_tests edge targets this node."
    )


class DiffImpactOutput(_StrictBase):
    """Compact result of ``sumo_qa_analyze_diff_impact``.

    Bounded by the size of the changeset, not the repo — safe to return inline.
    """

    tool: Literal["sumo_qa_analyze_diff_impact"] = Field(
        default="sumo_qa_analyze_diff_impact",
        description="Tool discriminator; always the literal tool name.",
    )
    root: str = Field(description="Resolved root path analysed.")
    base_ref: str | None = Field(
        default=None, description="Git base ref used to derive changed files, when given."
    )
    changed_file_count: int = Field(description="Number of input changed paths considered.")
    changed_nodes: list[_ImpactNodeSummary] = Field(
        default_factory=list, description="Changed paths that resolved to a repo-map node."
    )
    affected_nodes: list[_ImpactNodeSummary] = Field(
        default_factory=list, description="One-hop neighbours of the changed nodes."
    )
    related_tests: list[str] = Field(
        default_factory=list, description="Paths of tests that likely exercise the changes."
    )
    unmapped_files: list[str] = Field(
        default_factory=list, description="Changed paths with no node in the map."
    )
    risk_surface: list[str] = Field(
        default_factory=list,
        description="Changed source paths with no mapped test (the QA gap).",
    )
    suggested_inspections: list[str] = Field(
        default_factory=list, description="Paths the host LLM should open to inspect."
    )
    warning_count: int = Field(description="Number of warnings (stale, live-scan fallback, etc.).")
    warnings_by_kind: dict[str, int] = Field(
        default_factory=dict, description="Per-kind warning counts."
    )
    is_stale: bool = Field(description="True when the map's git_commit differs from current HEAD.")
    used_live_scan: bool = Field(
        description="True when no artifact was found and the map was scanned live."
    )
    artifact_path: str | None = Field(
        default=None, description="Resolved path of the loaded repo-map artifact, when used."
    )
    overlay_path: str | None = Field(
        default=None, description="Path the diff-impact overlay was written to, when requested."
    )
    overlay_bytes: int | None = Field(
        default=None, description="Size of the written overlay in bytes, when requested."
    )


class _QueryMatchSummary(_StrictBase):
    """One bounded match inside :class:`RepoMapQueryOutput`."""

    kind: Literal["node", "command"] = Field(
        description="Whether the match is a repo-map node or an extracted command."
    )
    id: str = Field(description="Node id (e.g. 'file:src/app.py') or 'command:<name>'.")
    type: str = Field(
        description="Node type for a node match, or command kind for a command match."
    )
    path: str = Field(
        description="Repo-relative path for a node, or the command's source file for a command."
    )
    tags: list[str] = Field(
        default_factory=list, description="Node tags; empty for a command match."
    )
    match_reason: str = Field(
        description="Why this entity matched (dimension + matched value), for relevance judging."
    )
    score: int = Field(description="Internal rank; higher is a stronger match.")


class RepoMapQueryOutput(_StrictBase):
    """Compact result of ``sumo_qa_query_repo_map``.

    Bounded by ``limit``, never the full artifact. Carries a freshness summary
    (``generated_at`` / ``git_commit`` / ``is_stale`` / ``used_live_scan``) so
    the host can judge how much to trust the map without a second call.
    """

    tool: Literal["sumo_qa_query_repo_map"] = Field(
        default="sumo_qa_query_repo_map",
        description="Tool discriminator; always the literal tool name.",
    )
    root: str = Field(description="Resolved root path whose map was queried.")
    query: str = Field(description="Echo of the query string the caller supplied.")
    limit: int = Field(description="Maximum number of matches returned.")
    types_filter: list[str] = Field(
        default_factory=list,
        description="Node types / 'command' the search was restricted to, if any.",
    )
    matches: list[_QueryMatchSummary] = Field(
        default_factory=list, description="Top-ranked matches, highest score first."
    )
    total_matches: int = Field(
        description="Total matches before the limit was applied (so the host knows if truncated)."
    )
    truncated: bool = Field(description="True when total_matches exceeded the limit.")
    schema_version: str = Field(description="Schema version of the queried map (currently '1.0').")
    generator_version: str = Field(description="Generator version recorded in the map.")
    generated_at: datetime = Field(description="UTC timestamp the queried map was generated.")
    git_commit: str | None = Field(
        default=None, description="git_commit recorded in the map, when present."
    )
    is_stale: bool = Field(description="True when the map's git_commit differs from current HEAD.")
    used_live_scan: bool = Field(
        description="True when no artifact was found and the map was scanned live."
    )
    artifact_path: str | None = Field(
        default=None, description="Resolved path of the loaded repo-map artifact, when used."
    )
    warning_count: int = Field(description="Number of warnings (stale, live-scan fallback, etc.).")
    warnings_by_kind: dict[str, int] = Field(
        default_factory=dict, description="Per-kind warning counts."
    )
