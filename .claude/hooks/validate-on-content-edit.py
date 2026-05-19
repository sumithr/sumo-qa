#!/usr/bin/env python3
"""PostToolUse hook: run sumo-qa-validate when knowledge/ or standards/ files change.

Mirrors the pre-commit `sumo-qa-validate` hook (.pre-commit-config.yaml:122) but
fires during the edit loop instead of at commit time. Faster feedback when a
schema or knowledge change breaks the strict loaders.

Output channel: exit 2 with stderr — Claude Code surfaces the stderr to the
assistant so the next turn can react to a validation failure.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def find_repo_root(start: Path) -> Path:
    """Walk up looking for pyproject.toml or .git; fall back to start.

    The hook compares edit paths against repo-relative WATCHED_PREFIXES, so
    the anchor must be the repo root regardless of where the session's cwd
    happens to be. Anchoring to cwd causes the validator to silently skip
    content edits whenever Claude is launched from a subdirectory.
    """
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").is_file() or (candidate / ".git").exists():
            return candidate
    return start


WATCHED_PREFIXES = ("knowledge/", "standards/", "src/sumo_qa/validate_content.py")


def candidate_paths(tool_name: str, tool_input: dict) -> list[str]:
    # MultiEdit edits a single file via multiple find/replace pairs; its
    # schema has `file_path` at the top level (not inside `edits[]`). The
    # v1 of this function read per-edit file_path and silently skipped
    # every MultiEdit invocation because the resulting list was empty.
    if tool_name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        return [path] if path else []
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

    relevant = False
    for raw in candidate_paths(tool_name, tool_input):
        try:
            rel = Path(raw).resolve().relative_to(repo_root).as_posix()
        except (ValueError, OSError):
            continue
        if any(rel.startswith(p) for p in WATCHED_PREFIXES):
            relevant = True
            break

    if not relevant:
        return 0

    result = subprocess.run(
        ["sumo-qa-validate"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return 0

    print(
        f"sumo-qa-validate failed after content edit. Output:\n{result.stdout}\n{result.stderr}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
