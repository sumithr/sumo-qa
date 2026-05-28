# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Load + validation envelope for the repo-map artifact (issue #155).

``load_repo_map`` accepts an already-parsed dict, a :class:`pathlib.Path`, or
a string path, and returns a validated :class:`RepoMap` model. Every failure
mode raises :class:`RepoMapValidationError` with a stable ``kind`` so
downstream tools (skills, CLI, MCP wrappers) can branch on the category
rather than parsing free-form messages.

Categorisation prefers an actionable, specific ``kind`` over Pydantic's
verbatim error type — ``schema_version_mismatch`` is surfaced before
Pydantic sees the payload so a stale artifact doesn't masquerade as a
generic literal-type error, and ``vocab_error`` distinguishes
out-of-catalogue enum values (a node type typo) from a wrong-type-entirely
mistake (a string where a list was expected).

``exc.path`` is JSON-pointer-ish — it joins Pydantic's loc segments with
``/`` but does NOT escape ``~`` or ``/`` per RFC 6901. Strict JSON Pointer
escaping is deferred to a later slice; the first-slice fields and the
``extra="forbid"`` constraint mean neither character can appear inside a
field name today.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from sumo_qa.repo_map_models import SCHEMA_VERSION, RepoMap

ValidationErrorKind = Literal[
    "malformed_json",
    "schema_version_mismatch",
    "missing_field",
    "unknown_field",
    "vocab_error",
    "type_error",
    "io_error",
]


class RepoMapValidationError(ValueError):
    def __init__(
        self,
        *,
        kind: ValidationErrorKind,
        message: str,
        path: str | None = None,
        source: str | None = None,
    ) -> None:
        self.kind = kind
        self.message = message
        self.path = path
        self.source = source
        prefix = f"[{kind}]"
        location = f" at {path}" if path else ""
        super().__init__(f"{prefix}{location}: {message}")


def load_repo_map(source: Path | str | dict) -> RepoMap:
    """Load and validate a repo-map artifact.

    ``source`` can be a parsed dict (e.g. from an in-memory generator), a
    :class:`pathlib.Path`, or a string path to a JSON file on disk.
    """
    if isinstance(source, dict):
        return _validate(source, source_label=None)
    path = Path(source)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RepoMapValidationError(
            kind="io_error",
            message=f"could not read repo-map file: {exc}",
            source=str(path),
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RepoMapValidationError(
            kind="malformed_json",
            message=f"invalid JSON at line {exc.lineno} col {exc.colno}: {exc.msg}",
            source=str(path),
        ) from exc
    return _validate(data, source_label=str(path))


def _validate(data: object, *, source_label: str | None) -> RepoMap:
    # Pre-check schema_version only when it's a string so we give a clear
    # "your artifact says 2.0, this build is 1.0" message for the common
    # drift case. Non-string values (null, numbers, lists) fall through to
    # Pydantic's literal-mismatch handler, which categorises as vocab_error.
    if isinstance(data, dict):
        version = data.get("schema_version")
        if isinstance(version, str) and version != SCHEMA_VERSION:
            raise RepoMapValidationError(
                kind="schema_version_mismatch",
                message=(
                    f"artifact schema_version is {version!r}; this build expects {SCHEMA_VERSION!r}"
                ),
                path="/schema_version",
                source=source_label,
            )
    try:
        return RepoMap.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = "/" + "/".join(str(p) for p in first["loc"])
        raise RepoMapValidationError(
            kind=_classify_pydantic_error(first["type"]),
            message=first["msg"],
            path=location,
            source=source_label,
        ) from exc


def _classify_pydantic_error(error_type: str) -> ValidationErrorKind:
    if error_type == "missing":
        return "missing_field"
    if error_type == "extra_forbidden":
        return "unknown_field"
    if error_type == "literal_error":
        return "vocab_error"
    return "type_error"
