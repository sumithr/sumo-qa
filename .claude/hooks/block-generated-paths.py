#!/usr/bin/env python3
"""PreToolUse hook: deny Edit/Write to generated, cached, or captured paths.

Why: tests/fixtures/ are byte-for-byte CLI captures (see .pre-commit-config.yaml:46) —
editing masks parser bugs. mutants/, dist/, build/, .coverage, .hypothesis/, and the
*_cache/ dirs are all regenerated artefacts; hand-edits drift away from the
generator and silently rot. node_modules/ and .venv/ are dependencies, not source.
"""

from __future__ import annotations

import fnmatch
import json
import sys
from pathlib import Path


def find_repo_root(start: Path) -> Path:
    """Walk up looking for pyproject.toml or .git; fall back to start.

    The hook compares edit paths against repo-relative deny patterns, so the
    anchor must be the repo root regardless of where the session's cwd
    happens to be. Anchoring to cwd silently allows edits to protected
    paths whenever Claude is launched from (or chdirs into) a subdirectory.
    """
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").is_file() or (candidate / ".git").exists():
            return candidate
    return start


DENY_PATTERNS = [
    "tests/fixtures/**",
    "mutants/**",
    "dist/**",
    "build/**",
    "node_modules/**",
    ".venv/**",
    ".hypothesis/**",
    ".pytest_cache/**",
    ".ruff_cache/**",
    ".mypy_cache/**",
    ".idea/**",
    "**/__pycache__/**",
    ".coverage",
    ".coverage.*",
]


def matches_deny(repo_relative: str) -> str | None:
    for pattern in DENY_PATTERNS:
        if fnmatch.fnmatch(repo_relative, pattern):
            return pattern
    return None


def candidate_paths(tool_name: str, tool_input: dict) -> list[str]:
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        return [path] if path else []
    if tool_name == "MultiEdit":
        return [e.get("file_path") for e in tool_input.get("edits", []) if e.get("file_path")]
    return []


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    cwd = Path(payload.get("cwd") or Path.cwd()).resolve()
    repo_root = find_repo_root(cwd)

    for raw in candidate_paths(tool_name, tool_input):
        try:
            abs_path = Path(raw).resolve()
            rel = abs_path.relative_to(repo_root).as_posix()
        except (ValueError, OSError):
            continue
        matched = matches_deny(rel)
        if matched:
            reason = (
                f"{rel} matches deny pattern '{matched}'. "
                "These paths are generated, cached, or captured — fix the producer, "
                "not the output. Override via the producer (e.g. mutmut run, pytest, "
                "the qaskills CLI capture) or remove the deny pattern from "
                ".claude/hooks/block-generated-paths.py if this is intentional."
            )
            json.dump(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                },
                sys.stdout,
            )
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
