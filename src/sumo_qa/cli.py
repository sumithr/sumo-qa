# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""sumo-qa — the product-grade command surface (issue #160, first slice).

Three subcommands wrap the same deterministic services the MCP tools use,
so a user can run the QA-native repo-understanding loop from a terminal:

- ``sumo-qa analyze [path]`` — walk the repo via
  :func:`sumo_qa.repo_map_scanner.scan_repo` and write the schema-validated
  ``.sumo-qa/repo-map.json`` artifact, the same writer ``sumo_qa_scan_repo``
  drives. Prints a concise per-type summary and the next command.
- ``sumo-qa status [path]`` — report whether the artifact exists, its schema
  version, freshness (recorded ``git_commit`` vs current HEAD), and the next
  recommended command.
- ``sumo-qa report [path]`` — compose the persisted ``.sumo-qa`` artifacts
  into the static ``.sumo-qa/qa-report.html`` page via the #157 report
  builder/renderer, with honest not-available states for anything missing.

All take ``--json`` for automation; the JSON shape is INTERNAL until
sumo-qa 1.0 but its keys are kept stable within the 1.x line so scripts can
rely on them.

``sumo-qa-doctor`` stays the diagnostics command (issue #160 keeps it as-is).
The MCP ``sumo_qa_scan_repo`` tool is unchanged; this CLI calls the same
service functions rather than duplicating any of their logic, so the artifact
the CLI writes and the artifact the MCP tool writes are byte-compatible on the
same repo state.

The command output never names a specific host or implies a host-specific
plugin is installed (issue #160 AC: host-neutral).
"""

from __future__ import annotations

import argparse
import json as _json
import sys as _sys
from pathlib import Path
from typing import Any

# Shared #155/#157 service layer — the SAME functions the MCP tools call. The
# CLI adds no parsing/scanning logic of its own; it composes these.
from sumo_qa.repo_map_scanner import _detect_git_commit, scan_repo
from sumo_qa.repo_map_validation import RepoMapValidationError, load_repo_map
from sumo_qa.report_builder import generate_report, write_run_summary
from sumo_qa.report_html import render_report_html
from sumo_qa.server import _build_scan_summary, _package_version

# The conventional artifact location under a scanned repo. Mirrors the
# ``.sumo-qa/repo-map.json`` default the MCP scan / diff-impact tools use.
REPO_MAP_RELPATH = ".sumo-qa/repo-map.json"

# The conventional QA-report location, mirrored by sumo_qa_generate_qa_report.
QA_REPORT_RELPATH = ".sumo-qa/qa-report.html"

# Memorable next-step commands surfaced in human + JSON output.
_NEXT_AFTER_ANALYZE = "sumo-qa status"
_NEXT_RUN_ANALYZE = "sumo-qa analyze"


def _resolve_root(path: str | None) -> Path:
    """Resolve the target repo path (defaults to the current directory)."""
    return Path(path).resolve() if path else Path.cwd().resolve()


def _emit(payload: dict[str, Any], *, as_json: bool, human: str) -> None:
    """Write either the JSON document or the human-readable text to stdout."""
    if as_json:
        _sys.stdout.write(_json.dumps(payload, indent=2) + "\n")
    else:
        _sys.stdout.write(human if human.endswith("\n") else human + "\n")


def _cmd_analyze(root: Path, *, as_json: bool) -> int:
    """Generate ``.sumo-qa/repo-map.json`` via the #155 scanner and report.

    Returns 0 on success, 2 when ``root`` is not a directory (the actionable
    error case). The summary is built with the SAME ``_build_scan_summary`` the
    MCP ``sumo_qa_scan_repo`` tool uses, so the reported shape matches.
    """
    if not root.is_dir():
        _sys.stderr.write(
            f"sumo-qa analyze: {root} is not a directory. "
            f"Pass an existing repository path (or omit it to use the current directory).\n"
        )
        return 2

    repo_map = scan_repo(root, generator_version=_package_version())
    artifact = root / REPO_MAP_RELPATH
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        _json.dumps(repo_map.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    summary = _build_scan_summary(
        repo_map,
        # ``as_posix()`` keeps the --json automation contract OS-independent:
        # Windows would otherwise emit backslash separators in ``artifact_path``.
        artifact_path=artifact.as_posix(),
        artifact_bytes=artifact.stat().st_size,
    )

    # Carry the analyzed root into the suggested next command so that, run from
    # any cwd, `sumo-qa status {root}` inspects the repo just analyzed — mirroring
    # the way status builds its own next_command. Use the resolved ``root``,
    # normalised to posix (``as_posix()``) so the suggestion is OS-stable just
    # like ``artifact_path``; forward slashes are valid paths on Windows for
    # pathlib/argparse, so the command stays runnable there.
    next_command = f"{_NEXT_AFTER_ANALYZE} {root.as_posix()}"

    payload: dict[str, Any] = {"command": "analyze", **summary.model_dump(mode="json")}
    payload["next_command"] = next_command

    nodes_by_type = ", ".join(f"{k}={v}" for k, v in sorted(summary.nodes_by_type.items()))
    human = (
        f"Analyzed {summary.root}\n"
        f"  wrote {REPO_MAP_RELPATH} ({summary.node_count} nodes, "
        f"{summary.edge_count} edges, {summary.command_count} commands)\n"
        f"  {nodes_by_type or 'no classified nodes'}\n"
        f"  next: {next_command}"
    )
    _emit(payload, as_json=as_json, human=human)
    return 0


def _status_payload(root: Path) -> dict[str, Any]:
    """Build the status document for ``root`` (shared by human + JSON paths).

    Reads the artifact through the #155 validator and compares its recorded
    ``git_commit`` against current HEAD via the scanner's ``_detect_git_commit``
    — the same staleness signal the MCP tools use.
    """
    artifact = root / REPO_MAP_RELPATH
    base: dict[str, Any] = {
        "command": "status",
        "root": str(root),
        # ``as_posix()`` keeps the --json automation contract OS-independent:
        # Windows would otherwise emit backslash separators in ``artifact_path``.
        "artifact_path": artifact.as_posix(),
        "artifact_present": False,
        "schema_version": None,
        "generator_version": None,
        "generated_at": None,
        "git_commit": None,
        "current_commit": _detect_git_commit(root),
        "is_stale": False,
        "validation_error": None,
        "next_command": f"{_NEXT_RUN_ANALYZE} {root.as_posix()}",
        "summary": (
            f"No repo-map artifact at {REPO_MAP_RELPATH}. Run `{_NEXT_RUN_ANALYZE}` to generate it."
        ),
    }

    if not artifact.is_file():
        return base

    base["artifact_present"] = True
    try:
        repo_map = load_repo_map(artifact)
    except RepoMapValidationError as exc:
        # A present-but-unreadable artifact: report it, point at re-analyze.
        base["validation_error"] = exc.kind
        base["summary"] = (
            f"Found {REPO_MAP_RELPATH} but could not read it ({exc.kind}). "
            f"Run `{_NEXT_RUN_ANALYZE}` to regenerate it."
        )
        base["next_command"] = f"{_NEXT_RUN_ANALYZE} {root.as_posix()}"
        return base

    current = base["current_commit"]
    recorded = repo_map.project.git_commit
    is_stale = current is not None and recorded is not None and current != recorded

    base["schema_version"] = repo_map.schema_version
    base["generator_version"] = repo_map.project.generator_version
    base["generated_at"] = repo_map.project.generated_at.isoformat()
    base["git_commit"] = recorded
    base["is_stale"] = is_stale

    if is_stale:
        # ``is_stale`` is only True when both commits are non-None (see above),
        # but mypy cannot narrow ``recorded``/``current`` through the bool, so
        # assert it explicitly before slicing.
        assert recorded is not None and current is not None
        base["next_command"] = f"{_NEXT_RUN_ANALYZE} {root.as_posix()}"
        base["summary"] = (
            f"Repo-map is STALE: recorded commit {recorded[:8]} differs from "
            f"current HEAD {current[:8]}. Run `{_NEXT_RUN_ANALYZE}` to refresh it."
        )
    else:
        # Fresh, or freshness unknown (no git on either side) — either way the
        # artifact is usable; the natural next step is impact analysis, but that
        # lands in a later slice, so we simply confirm freshness here.
        base["next_command"] = f"{_NEXT_RUN_ANALYZE} {root.as_posix()}"
        base["summary"] = (
            f"Repo-map present and fresh (schema {repo_map.schema_version}, "
            f"generated {base['generated_at']})."
        )
    return base


def _cmd_status(root: Path, *, as_json: bool) -> int:
    """Report artifact presence / schema version / freshness / next command.

    A missing target directory is a usage error (exit 2), not a "no artifact"
    state — reporting "no artifact" under a directory that does not exist would
    be misleading. The guard mirrors ``_cmd_analyze`` (same message shape and
    exit code) and applies to both human and ``--json`` modes, since analyze
    itself writes the actionable text to stderr in both.
    """
    if not root.is_dir():
        _sys.stderr.write(
            f"sumo-qa status: {root} is not a directory. "
            f"Pass an existing repository path (or omit it to use the current directory).\n"
        )
        return 2

    payload = _status_payload(root)

    if as_json:
        _emit(payload, as_json=True, human="")
        return 0

    lines = [f"Status for {payload['root']}", f"  {payload['summary']}"]
    if payload["artifact_present"] and payload["validation_error"] is None:
        freshness = "stale" if payload["is_stale"] else "fresh"
        lines.append(
            f"  artifact: {REPO_MAP_RELPATH} | schema {payload['schema_version']} | {freshness}"
        )
    lines.append(f"  next: {payload['next_command']}")
    _emit(payload, as_json=False, human="\n".join(lines))
    return 0


def _cmd_report(root: Path, *, as_json: bool) -> int:
    """Compose the persisted ``.sumo-qa`` artifacts into the static QA report.

    Writes (or overwrites — it is a regenerated artifact, like the repo-map)
    ``.sumo-qa/qa-report.html`` under ``root`` via the #157 builder/renderer.
    A repo with no artifacts at all still succeeds: every absent source renders
    an honest not-available state, so exit 0 means "report written", never
    "everything is green". The missing-directory guard mirrors analyze/status.
    """
    if not root.is_dir():
        _sys.stderr.write(
            f"sumo-qa report: {root} is not a directory. "
            f"Pass an existing repository path (or omit it to use the current directory).\n"
        )
        return 2

    report = generate_report(root, generator_version=_package_version())
    artifact = root / QA_REPORT_RELPATH
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(render_report_html(report), encoding="utf-8")
    # Persist the compact run summary the NEXT report's delta line reads.
    write_run_summary(root, report)

    statuses = {a.kind: a.status for a in report.artifacts}
    # A usable repo-map points forward to status; anything else (missing,
    # invalid, stale) points back at analyze to (re)generate it.
    next_command = (
        f"{_NEXT_AFTER_ANALYZE} {root.as_posix()}"
        if statuses["repo_map"] == "available"
        else f"{_NEXT_RUN_ANALYZE} {root.as_posix()}"
    )
    state = report.readiness.state
    state_label = state.replace("_", " ")

    payload: dict[str, Any] = {
        "command": "report",
        "root": str(root),
        # ``as_posix()`` keeps the --json automation contract OS-independent,
        # mirroring analyze/status.
        "artifact_path": artifact.as_posix(),
        "artifact_bytes": artifact.stat().st_size,
        "readiness_state": state,
        "readiness_reasons": list(report.readiness.reasons),
        "artifacts": statuses,
        "changed_component_count": len(report.changed_components),
        "affected_component_count": len(report.affected_components),
        "related_test_count": len(report.related_tests),
        "risk_count": len(report.risks),
        "uncovered_blocker_count": report.uncovered_blocker_count,
        "warning_count": len(report.warnings),
        "next_command": next_command,
        "summary": f"QA report written to {QA_REPORT_RELPATH}; readiness is {state_label}.",
    }

    statuses_line = ", ".join(f"{kind}={status}" for kind, status in statuses.items())
    reasons_line = "; ".join(report.readiness.reasons) or "all composed signals are green"
    human = (
        f"QA report for {root}\n"
        f"  wrote {QA_REPORT_RELPATH} ({payload['artifact_bytes']} bytes)\n"
        f"  readiness: {state_label} ({reasons_line})\n"
        f"  artifacts: {statuses_line}\n"
        f"  next: {next_command}"
    )
    _emit(payload, as_json=as_json, human=human)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sumo-qa",
        description=(
            "sumo-qa product commands. Analyze a repository into a QA-native "
            "repo-map artifact and inspect its freshness. Run `sumo-qa-doctor` "
            "for install diagnostics."
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="{analyze,status,report}")

    p_analyze = sub.add_parser(
        "analyze",
        help="Scan a repo and write .sumo-qa/repo-map.json.",
        description=(
            "Walk the repository and write the schema-validated "
            ".sumo-qa/repo-map.json artifact, then print a concise summary."
        ),
    )
    p_analyze.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Repository path to analyze (defaults to the current directory).",
    )
    p_analyze.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON document instead of human-readable text.",
    )

    p_status = sub.add_parser(
        "status",
        help="Report repo-map artifact presence, schema version, and freshness.",
        description=(
            "Report whether .sumo-qa/repo-map.json exists, its schema version, "
            "whether it is stale relative to HEAD, and the next command to run."
        ),
    )
    p_status.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Repository path to inspect (defaults to the current directory).",
    )
    p_status.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON document instead of human-readable text.",
    )

    p_report = sub.add_parser(
        "report",
        help="Generate the static QA report at .sumo-qa/qa-report.html.",
        description=(
            "Compose the persisted .sumo-qa artifacts (repo-map, diff-impact, "
            "risk-ledger, context-bundle) into a self-contained static HTML QA "
            "report, with honest not-available states for anything missing."
        ),
    )
    p_report.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Repository path to report on (defaults to the current directory).",
    )
    p_report.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON document instead of human-readable text.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``sumo-qa`` product CLI.

    Exit codes: 0 on success, 2 on a usage error (no subcommand) or a missing
    target directory. ``status`` treats a missing artifact as a reportable
    state (exit 0), not an error — the message points at ``sumo-qa analyze``.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help(_sys.stderr)
        return 2

    root = _resolve_root(args.path)
    if args.command == "analyze":
        return _cmd_analyze(root, as_json=args.json)
    if args.command == "status":
        return _cmd_status(root, as_json=args.json)
    # argparse restricts ``command`` to the registered subparsers, so the only
    # remaining value here is "report".
    return _cmd_report(root, as_json=args.json)


def console_main() -> None:
    """Entry point for the ``sumo-qa`` console script.

    Dispatches between the product CLI and the MCP stdio server so a single
    memorable binary serves both:

    - ``sumo-qa analyze ...`` / ``sumo-qa status ...`` → the product CLI here.
    - ``sumo-qa --help`` / ``-h`` / a mistyped subcommand / any flag-led argv →
      the product CLI too, so argparse prints usage or an error instead of the
      binary silently dropping into the stdio server and blocking on stdin.
    - bare ``sumo-qa`` (empty argv) → ``sumo_qa.server.main``, preserving the
      launch contract every host config and ``sumo-qa-doctor`` probe depends on
      (the MCP server is started by invoking ``sumo-qa`` with no arguments over
      stdio).

    The bare-launch case is load-bearing: only an EMPTY ``argv`` reaches the
    server here. Any first token — a product subcommand, a ``-``/``--`` flag, or
    an unknown word — is handed to :func:`main`, which lets argparse emit usage
    or a clear error to a terminal user rather than hang.
    """
    argv = _sys.argv[1:]
    if argv:
        # A non-empty argv is a CLI invocation: a product subcommand, a help
        # flag, or a mistyped token. Route it all to argparse via ``main`` so a
        # terminal user gets usage/errors, never a silent stdio-server hang.
        _sys.exit(main(argv))
    # Bare invocation (empty argv) launches the MCP server, unchanged. ``main``
    # (the server entry point) is imported lazily here, but note FastMCP itself
    # is only imported inside ``server.build_mcp_server()`` — which the product
    # CLI path never calls — so it is that deferral, not this one, that spares
    # the CLI the FastMCP import cost (``sumo_qa.server`` is already imported at
    # this module's top for ``_build_scan_summary`` / ``_package_version``).
    from sumo_qa.server import main as _server_main

    _server_main()


if __name__ == "__main__":  # pragma: no cover -- main guard for `python -m sumo_qa.cli`
    _sys.exit(main())
