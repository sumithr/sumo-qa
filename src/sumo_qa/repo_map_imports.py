# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Import-edge orchestrator for the repo-map (#354).

``infer_imports_edges(nodes, root_path)`` turns the scanner's source nodes into
language-agnostic ``imports`` edges via tree-sitter + the per-language
resolvers. It is the one entry point the scanner calls (after
``_infer_likely_tests_edges``), gated internally on tree-sitter availability so
the scanner stays oblivious to the optional dependency.

Pipeline per source node:

1. dispatch the node's language to its resolver (skip languages with no
   resolver — unsupported, not an error);
2. ``extract`` the raw imports from the file bytes (tree-sitter);
3. ``resolve`` each raw import to repo-relative paths;
4. map each resolved path to its node id and emit an edge **only between nodes
   that exist in the map** (the same no-dangling-edges discipline as
   ``_infer_likely_tests_edges``);
5. tag confidence — ``high`` for module-level / class-body imports, ``medium``
   for function-local / lazy imports;
6. dedup to the strongest signal per ``(source, target)`` and sort
   deterministically by ``(source, target)``.

When the ``[treesitter]`` extra is absent, ``infer_imports_edges`` returns an
empty edge list plus a graceful-degradation :class:`RepoMapWarning`; the
scanner still emits ``likely_tests`` edges and the map stays valid.
"""

from __future__ import annotations

from pathlib import Path

from sumo_qa.repo_map_models import EdgeConfidence, RepoMapEdge, RepoMapNode, RepoMapWarning
from sumo_qa.repo_map_resolvers import get_resolver
from sumo_qa.repo_map_treesitter import TREESITTER_AVAILABLE

# Confidence ranking, strongest first, so dedup can keep the strongest signal
# per (source, target) pair. Mirrors the model's EdgeConfidence Literal.
_CONFIDENCE_RANK: dict[EdgeConfidence, int] = {"high": 3, "medium": 2, "low": 1}

_MISSING_EXTRA_MESSAGE = (
    "imports edges skipped - pip install sumo-qa[treesitter] to enable the import graph"
)

# Cap per-file source read (bounded, deterministic) - matches the scanner's
# usage-signal read cap so a pathological file can't blow memory.
_MAX_SOURCE_READ_BYTES = 2_000_000


def infer_imports_edges(
    nodes: list[RepoMapNode],
    root_path: Path,
    warnings: list[RepoMapWarning] | None = None,
) -> list[RepoMapEdge]:
    """Infer ``imports`` edges for the source nodes in ``nodes``.

    ``root_path`` is the repo root the node paths are relative to (files are
    read from there). ``warnings`` is the scanner's warning list; when the
    ``[treesitter]`` extra is absent, a graceful-degradation warning is
    appended to it (when provided) and an empty edge list is returned. Edges
    are emitted only between nodes present in ``nodes``, deduped to the
    strongest confidence per ``(source, target)``, and sorted by
    ``(source, target)``.
    """
    if not TREESITTER_AVAILABLE:
        if warnings is not None:
            warnings.append(
                RepoMapWarning(kind="unsupported_language", message=_MISSING_EXTRA_MESSAGE)
            )
        return []

    file_set = {node.path for node in nodes}
    node_id_by_path = {node.path: node.id for node in nodes}

    # (source_id, target_id) -> best edge so far (strongest confidence wins).
    edges_by_pair: dict[tuple[str, str], RepoMapEdge] = {}

    for node in nodes:
        if node.type != "source_file" or node.language is None:
            continue
        resolver = get_resolver(node.language)
        if resolver is None:
            continue  # language with no resolver: skipped silently (not an error)
        src = _read_source(root_path / node.path)
        if src is None:
            continue
        for raw in resolver.extract(src):
            confidence: EdgeConfidence = "medium" if raw.function_local else "high"
            for target_path in resolver.resolve(node.path, raw, file_set):
                # resolve only returns paths in file_set, and file_set is the
                # node paths, so every resolved path maps to a known node id.
                target_id = node_id_by_path[target_path]
                # No self-edges: a file whose import resolves back to itself
                # (e.g. a package barrel importing its own package) gets no edge.
                if target_id == node.id:
                    continue
                _record(edges_by_pair, node.id, target_id, confidence, raw.module)

    return sorted(edges_by_pair.values(), key=lambda e: (e.source, e.target))


def _record(
    edges_by_pair: dict[tuple[str, str], RepoMapEdge],
    source_id: str,
    target_id: str,
    confidence: EdgeConfidence,
    module: str,
) -> None:
    """Keep the strongest-confidence edge per ``(source, target)`` pair.

    A pair seen at ``high`` then again at ``medium`` (a module-level and a
    later lazy import of the same target) collapses to one ``high`` edge.
    """
    key = (source_id, target_id)
    existing = edges_by_pair.get(key)
    if (
        existing is not None
        and _CONFIDENCE_RANK[existing.confidence] >= _CONFIDENCE_RANK[confidence]
    ):
        return
    edges_by_pair[key] = RepoMapEdge(
        source=source_id,
        target=target_id,
        type="imports",
        confidence=confidence,
        reason=f"imports {module}" if module else "imports (relative)",
    )


def _read_source(abs_path: Path) -> bytes | None:
    """Read a source file as bytes, bounded; ``None`` on an unreadable file.

    An unreadable file yields no edges rather than raising, matching the
    scanner's tolerance for transient IO failures mid-walk.
    """
    try:
        with abs_path.open("rb") as fh:
            return fh.read(_MAX_SOURCE_READ_BYTES)
    except OSError:
        return None
