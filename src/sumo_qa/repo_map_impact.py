# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Diff-impact analysis over a loaded repo-map (issue #156 slice 4).

``analyze_diff_impact(repo_map, changed_files)`` is pure: no I/O, no git, no
clock. Given an already-loaded :class:`RepoMap` and a list of repo-relative
changed paths, it reports the directly changed nodes, one-hop affected nodes,
likely related tests, unmapped files, and the risk surface (changed source
files with no mapped test). ``changed_files_from_git`` is the only git-touching
helper and lives here so the MCP wrapper stays thin.

Slice 4 walks ``likely_tests`` edges — the only edge type the scanner emits
today. The one-hop neighbour logic is generic over ``edge.type``, so it will
pick up ``imports`` / ``configured_by`` automatically once those are inferred.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable
from pathlib import Path

from sumo_qa.repo_map_models import DiffImpact, ImpactNode, RepoMap, RepoMapWarning


def analyze_diff_impact(repo_map: RepoMap, changed_files: Iterable[str]) -> DiffImpact:
    """Map ``changed_files`` onto ``repo_map``. Pure; output lists are sorted."""
    changed = sorted(set(changed_files))
    # Path -> node. Safe against collisions: a RepoMap enforces unique node ids
    # (RepoMap._check_unique_node_ids) and the scanner derives id as
    # ``file:{path}``, so one path maps to exactly one node for any
    # scanner-produced map.
    node_by_path = {n.path: n for n in repo_map.nodes}
    node_by_id = {n.id: n for n in repo_map.nodes}

    # Only consider edges whose BOTH endpoints resolve to known nodes — a
    # loaded artifact can carry a dangling edge (the validator doesn't enforce
    # endpoint existence), and one-hop expansion must not invent nodes.
    edges = [e for e in repo_map.edges if e.source in node_by_id and e.target in node_by_id]

    def _has_mapped_tests(node_id: str) -> bool:
        return any(e.type == "likely_tests" and e.target == node_id for e in edges)

    def _mapped_tests_verdict(node) -> bool | None:
        # Tri-state: the mapped-tests question is only meaningful for source
        # files. Every other node type carries None so a vacuous "no" on a
        # docs/fixture/test row can never render as a coverage gap.
        if node.type != "source_file":
            return None
        return _has_mapped_tests(node.id)

    changed_ids = {node_by_path[p].id for p in changed if p in node_by_path}

    changed_nodes: list[ImpactNode] = []
    unmapped_files: list[str] = []
    related_tests: set[str] = set()
    risk_surface: list[str] = []

    for path in changed:
        node = node_by_path.get(path)
        if node is None:
            unmapped_files.append(path)
            continue
        verdict = _mapped_tests_verdict(node)
        changed_nodes.append(
            ImpactNode(id=node.id, type=node.type, path=node.path, has_mapped_tests=verdict)
        )
        for e in edges:
            if e.type == "likely_tests" and e.target == node.id:
                related_tests.add(node_by_id[e.source].path)
        if verdict is False:
            risk_surface.append(node.path)

    affected_ids: set[str] = set()
    for e in edges:
        if e.source in changed_ids and e.target not in changed_ids:
            affected_ids.add(e.target)
        if e.target in changed_ids and e.source not in changed_ids:
            affected_ids.add(e.source)

    affected_nodes = [
        ImpactNode(
            id=node_by_id[nid].id,
            type=node_by_id[nid].type,
            path=node_by_id[nid].path,
            has_mapped_tests=_mapped_tests_verdict(node_by_id[nid]),
        )
        for nid in affected_ids
    ]

    suggested = sorted(set(unmapped_files) | {n.path for n in affected_nodes})

    # Probable mapping gap (#266): the repo HAS test files, yet the map carries
    # zero `likely_tests` edges, so every changed source reads as risk surface.
    # That signature is a convention the mapper missed (the Kotlin
    # false-positive), not true zero coverage — flag it so a consumer doesn't
    # narrate "no tests". A map WITH some edges and a single uncovered file is
    # real partial coverage, not a gap.
    warnings: list[RepoMapWarning] = []
    test_files_present = any(n.type == "test_file" for n in repo_map.nodes)
    # Use the dangling-filtered `edges`, not repo_map.edges: a likely_tests edge
    # whose endpoints don't both resolve is not a usable mapping, so it must not
    # mask a probable mapping gap.
    no_likely_edges = not any(e.type == "likely_tests" for e in edges)
    probable_mapping_gap = bool(risk_surface) and test_files_present and no_likely_edges
    if probable_mapping_gap:
        warnings.append(
            RepoMapWarning(
                kind="other",
                message=(
                    "probable mapping gap, not zero coverage: test files are present but "
                    "the repo-map has no likely_tests edges, so all changed sources appear "
                    "as risk surface. The test-to-source mapping likely missed this repo's "
                    "conventions. Inspect the test tree directly before treating these as "
                    "uncovered."
                ),
            )
        )

    return DiffImpact(
        changed_nodes=sorted(changed_nodes, key=lambda n: n.path),
        affected_nodes=sorted(affected_nodes, key=lambda n: n.path),
        related_tests=sorted(related_tests),
        unmapped_files=sorted(unmapped_files),
        risk_surface=sorted(risk_surface),
        suggested_inspections=suggested,
        warnings=warnings,
        probable_mapping_gap=probable_mapping_gap,
    )


def _git_env() -> dict[str, str]:
    """os.environ without ``GIT_*`` — see repo_map_scanner._git_env for the
    inherited-GIT_DIR leakage rationale. Replicated (not imported) to keep the
    one-liner local; both modules must strip the same prefix."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def changed_files_from_git(root: Path | str, base_ref: str) -> list[str]:
    """Repo-relative paths this branch changed relative to ``base_ref``.

    Diffs the working tree against ``merge-base(base_ref, HEAD)`` — the fork
    point — so files changed *on the base* after the branch diverged don't
    leak in as false positives (the same semantics GitHub's "Files changed"
    uses), while committed AND uncommitted tracked changes on this branch are
    both included. ``-z`` keeps non-ASCII / spaced paths intact (git quotes
    them otherwise). Raises ``ValueError`` if ``root`` is not the toplevel of a
    git repo (the scanner's cross-check, so an ancestor repo can't leak)."""
    root_path = Path(root).resolve()
    git_env = _git_env()
    toplevel = subprocess.run(
        ["git", "-C", str(root_path), "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=True,
        env=git_env,
    )
    repo_root = Path(toplevel.stdout.decode("utf-8").strip()).resolve()
    if repo_root != root_path:
        raise ValueError(f"{root_path!s} is not a git repository toplevel")
    merge_base = subprocess.run(
        ["git", "-C", str(root_path), "merge-base", base_ref, "HEAD"],
        capture_output=True,
        check=True,
        env=git_env,
    )
    fork_point = merge_base.stdout.decode("utf-8").strip()
    result = subprocess.run(
        ["git", "-C", str(root_path), "diff", "--name-only", "-z", fork_point],
        capture_output=True,
        check=True,
        env=git_env,
    )
    return sorted(p.decode("utf-8") for p in result.stdout.split(b"\0") if p)
