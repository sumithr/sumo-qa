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

WATCHED_PREFIXES = ("knowledge/", "standards/", "src/sumo_qa/validate_content.py")


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

    relevant = False
    for raw in candidate_paths(tool_name, tool_input):
        try:
            rel = Path(raw).resolve().relative_to(cwd).as_posix()
        except (ValueError, OSError):
            continue
        if any(rel.startswith(p) for p in WATCHED_PREFIXES):
            relevant = True
            break

    if not relevant:
        return 0

    result = subprocess.run(
        ["sumo-qa-validate"],
        cwd=cwd,
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
