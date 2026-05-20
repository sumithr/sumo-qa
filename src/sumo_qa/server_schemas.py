# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Pydantic output models for the structured sumo-qa MCP tools.

FastMCP auto-derives ``outputSchema`` on each tool from the function's return-
type annotation when that annotation is a Pydantic BaseModel. Models here
mirror the shapes the tools already return — they do NOT add, rename, or
re-type fields. Drift between a model and the tool's actual return is a bug
in this file, not in the tool.

Error envelope: every tool can also return the existing dict-based
``{"isError": True, "error": {...}}`` shape on failure (built by
``server._error_envelope``). To preserve that without modelling the error
path twice, each tool's annotated return is ``ModelName | dict`` — Pydantic
accepts both branches and FastMCP emits a ``oneOf`` outputSchema.
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
