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

from datetime import datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

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

EdgeType = Literal[
    "likely_tests",
    "imports",
    "configured_by",
    "command_runs",
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


class RepoMapProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str
    name: str | None = None
    git_commit: str | None = None
    generated_at: datetime
    generator_version: str


class RepoMapNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: NodeType
    path: str
    language: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    fingerprint: str | None = None


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

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    project: RepoMapProject
    nodes: list[RepoMapNode] = Field(default_factory=list)
    edges: list[RepoMapEdge] = Field(default_factory=list)
    commands: list[RepoMapCommand] = Field(default_factory=list)
    warnings: list[RepoMapWarning] = Field(default_factory=list)
