# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Bounded query over a loaded repo-map (issue #156).

``query_repo_map(repo_map, query, *, limit, types)`` is pure: no I/O, no git,
no clock. Given an already-loaded :class:`RepoMap` and a free-text query, it
ranks the matching nodes and commands and returns the top ``limit`` as a
compact :class:`RepoMapQueryResult` — never the full artifact. The MCP wrapper
in ``server.py`` is the only thing that touches disk (load the artifact, fall
back to a live scan, attach a freshness summary).

Ranking is a fixed score ladder, strongest first:

    exact node id > exact path > exact command name > evidence type (node type)
    > exact tag > file name > category > command kind
    > path substring > node-id substring > tag substring > command substring

so an exact match on a weaker dimension can never outrank an exact match on a
stronger one. The query is matched case-insensitively; scores are surfaced so a
caller sees the gradient, not just the order. Ties break on ``(id, path)`` for
deterministic output even when two commands share a name across sources.

``limit`` is clamped to :data:`_MAX_LIMIT` so the "bounded" contract holds even
if a caller passes a huge value; the applied limit is echoed back on the result
and ``truncated`` is measured against it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final, get_args

from sumo_qa.repo_map_models import (
    NodeType,
    RepoMap,
    RepoMapCommand,
    RepoMapNode,
    RepoMapQueryMatch,
    RepoMapQueryResult,
)

# Score ladder. Exact node id is the strongest signal, a bare substring the
# weakest. The bands are spaced (and ordered exactly as the module docstring
# states) so an exact match on a weaker dimension can never outrank an exact
# match on a stronger one.
_SCORE_EXACT_ID = 100
_SCORE_EXACT_PATH = 90
_SCORE_COMMAND_NAME = 85
_SCORE_EVIDENCE_TYPE = 80
_SCORE_TAG_EXACT = 75
_SCORE_FILENAME = 70
_SCORE_CATEGORY = 65
_SCORE_COMMAND_KIND = 60
_SCORE_PATH_SUBSTRING = 50
_SCORE_ID_SUBSTRING = 40
_SCORE_TAG_SUBSTRING = 35
_SCORE_COMMAND_SUBSTRING = 25

# Hard ceiling on returned matches. The default limit is small (10); this cap
# only bites a caller that explicitly asks for an unbounded result, keeping the
# tool's output compact enough for the token-budget contract. `truncated` still
# signals when more matched than were returned.
_MAX_LIMIT: Final = 100

# Valid `types` filter values: every node type plus the literal "command".
# Validated up front so a typo ("testfile") fails loudly instead of silently
# returning zero matches.
_VALID_TYPE_FILTERS: Final = frozenset(get_args(NodeType)) | {"command"}


def _score_node(node: RepoMapNode, q: str) -> tuple[int, str] | None:
    """Best (score, reason) for a node against the normalised query, or None."""
    if node.id.lower() == q:
        return _SCORE_EXACT_ID, "exact node id"
    if node.path.lower() == q:
        return _SCORE_EXACT_PATH, "exact path"
    if node.type.lower() == q:
        return _SCORE_EVIDENCE_TYPE, f"evidence type '{node.type}'"
    if any(t.lower() == q for t in node.tags):
        return _SCORE_TAG_EXACT, f"tag '{q}'"
    if node.path.rsplit("/", 1)[-1].lower() == q:
        return _SCORE_FILENAME, "file name"
    if node.category is not None and node.category.lower() == q:
        return _SCORE_CATEGORY, f"category '{node.category}'"
    if q in node.path.lower():
        return _SCORE_PATH_SUBSTRING, f"path contains '{q}'"
    if q in node.id.lower():
        return _SCORE_ID_SUBSTRING, f"node id contains '{q}'"
    if any(q in t.lower() for t in node.tags):
        return _SCORE_TAG_SUBSTRING, f"tag contains '{q}'"
    return None


def _score_command(cmd: RepoMapCommand, q: str) -> tuple[int, str] | None:
    if cmd.name.lower() == q:
        return _SCORE_COMMAND_NAME, f"command name '{cmd.name}'"
    if cmd.kind.lower() == q:
        return _SCORE_COMMAND_KIND, f"command kind '{cmd.kind}'"
    if q in cmd.name.lower():
        return _SCORE_COMMAND_SUBSTRING, f"command name contains '{q}'"
    if cmd.raw is not None and q in cmd.raw.lower():
        return _SCORE_COMMAND_SUBSTRING, f"command contains '{q}'"
    return None


def query_repo_map(
    repo_map: RepoMap,
    query: str,
    *,
    limit: int = 10,
    types: Iterable[str] | None = None,
) -> RepoMapQueryResult:
    """Rank ``repo_map`` nodes and commands against ``query``; return top ``limit``.

    ``types`` restricts the search: pass node-type strings (``test_file``,
    ``ci_workflow``, …) and/or the literal ``"command"``. When given, only
    entities whose type/kind is in the set are searched — so asking for
    ``["source_file"]`` excludes commands. An unknown value raises ``ValueError``
    rather than silently returning nothing. ``limit`` must be >= 0 (clamped to
    ``_MAX_LIMIT``) and ``query`` non-blank; ``total_matches`` always reports the
    full pre-limit count so the caller knows whether the result was truncated.
    """
    if limit < 0:
        raise ValueError("limit must be >= 0")
    q = query.strip().lower()
    if not q:
        raise ValueError("query must not be blank")

    type_filter = set(types) if types is not None else None
    if type_filter is not None:
        unknown = sorted(type_filter - _VALID_TYPE_FILTERS)
        if unknown:
            raise ValueError(
                f"unknown types filter value(s): {unknown}. "
                f"Valid values: {sorted(_VALID_TYPE_FILTERS)}"
            )
    search_commands = type_filter is None or "command" in type_filter

    scored: list[RepoMapQueryMatch] = []

    for node in repo_map.nodes:
        if type_filter is not None and node.type not in type_filter:
            continue
        hit = _score_node(node, q)
        if hit is None:
            continue
        score, reason = hit
        scored.append(
            RepoMapQueryMatch(
                kind="node",
                id=node.id,
                type=node.type,
                path=node.path,
                tags=list(node.tags),
                match_reason=reason,
                score=score,
            )
        )

    if search_commands:
        for cmd in repo_map.commands:
            hit = _score_command(cmd, q)
            if hit is None:
                continue
            score, reason = hit
            scored.append(
                RepoMapQueryMatch(
                    kind="command",
                    id=f"command:{cmd.name}",
                    type=cmd.kind,
                    path=cmd.source,
                    tags=[],
                    match_reason=reason,
                    score=score,
                )
            )

    # Highest score first; ties broken by (id, path) so two commands sharing a
    # name across different source files still sort deterministically.
    scored.sort(key=lambda m: (-m.score, m.id, m.path))

    effective_limit = min(limit, _MAX_LIMIT)
    total = len(scored)
    return RepoMapQueryResult(
        query=query,
        matches=scored[:effective_limit],
        total_matches=total,
        types_filter=sorted(type_filter) if type_filter is not None else [],
        truncated=total > effective_limit,
        limit=effective_limit,
    )
