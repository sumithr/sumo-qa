# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""First-slice schema models for the QA-native repo-map artifact (issue #155).

Defines the shape of ``.sumo-qa/repo-map.json``: a versioned, schema-validated
artifact that captures the repo structure plus QA-relevant evidence anchors
(tests, manifests, CI configs, fixtures, migrations) downstream skills and CLI
work in #156, #157, and #160 consume.

This module owns the model layer only — node/edge vocabulary, freshness
metadata, schema version. The deterministic generator lives in a follow-up
slice; this slice locks the contract so callers can write conformant artifacts
ahead of generator availability.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION: Final[Literal["1.0"]] = "1.0"

NodeType = Literal[
    "source_file",
    "test_file",
    "docs",
    "config",
    "ci_workflow",
    "manifest",
    "fixture",
    "migration_schema",
    "infrastructure",
]

# `command_runs` is deliberately omitted from the slice-1 vocabulary: commands
# have no stable id field yet, so any edge addressing one would invent its own
# endpoint convention. The follow-up generator slice defines command ids; the
# edge type returns then.
EdgeType = Literal[
    "likely_tests",
    "imports",
    "configured_by",
]

EdgeConfidence = Literal["low", "medium", "high"]

CommandKind = Literal["test", "build", "lint", "format", "ci_job", "other"]

WarningKind = Literal[
    "skipped_file",
    "unsupported_language",
    "stale",
    "schema_drift",
    "other",
]

# Slice 1 enforces SHA-256 fingerprints only. Adding another hash algorithm is
# a schema-version bump, not a soft extension — consumers can rely on the
# format until the version changes.
_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class RepoMapProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str
    name: str | None = None
    git_commit: str | None = None
    generated_at: datetime
    generator_version: str

    @field_validator("generated_at")
    @classmethod
    def _require_aware_datetime(cls, value: datetime) -> datetime:
        # Freshness math (`age_days`, stale-after-N-days) is meaningless on a
        # naive datetime — the absent timezone hides the real elapsed time.
        # Pydantic accepts naive datetimes by default, so we tighten here.
        # A tzinfo whose utcoffset() returns None still counts as naive in
        # Python; check both surfaces.
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value


class RepoMapNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: NodeType
    path: str
    language: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    fingerprint: str | None = None

    @field_validator("fingerprint")
    @classmethod
    def _check_fingerprint_shape(cls, value: str | None) -> str | None:
        if value is not None and not _FINGERPRINT_RE.fullmatch(value):
            raise ValueError("fingerprint must match 'sha256:<64 lowercase hex>'")
        return value


class RepoMapEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    type: EdgeType
    confidence: EdgeConfidence
    reason: str


class RepoMapCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: CommandKind
    source: str
    raw: str | None = None


class RepoMapWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: WarningKind
    message: str
    path: str | None = None


class RepoMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # `schema_version` is required, not defaulted: a versioned artifact must
    # carry its version explicitly so a producer that forgot to stamp the
    # field can't sneak past validation. Python callers pass SCHEMA_VERSION.
    schema_version: Literal["1.0"]
    project: RepoMapProject
    nodes: list[RepoMapNode] = Field(default_factory=list)
    edges: list[RepoMapEdge] = Field(default_factory=list)
    commands: list[RepoMapCommand] = Field(default_factory=list)
    warnings: list[RepoMapWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_unique_node_ids(self) -> RepoMap:
        # Node ids are the lookup key downstream consumers (#156 diff-impact,
        # #157 report) build keyed structures on. Duplicates would silently
        # collapse two nodes into one.
        seen: set[str] = set()
        for node in self.nodes:
            if node.id in seen:
                raise ValueError(f"duplicate node id: {node.id!r}")
            seen.add(node.id)
        return self
