# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Regenerate tests/fixtures/mcp_tools_list_snapshot.json from the live server.

``required_tools`` and ``schemas`` pin the default (no-config, ``full``)
profile; ``core_tools`` pins the ``core`` profile's names (#806).

Run when a deliberate tool change lands. A tool add, removal, or rename fails
the snapshot guard until this is re-run; a schema edit only warns, but still
regenerate so the pinned schema bodies stay current. Always inspect the diff
before committing: the snapshot exists to make drift visible, so a 'just
regen' workflow defeats the purpose. Include a one-line rationale in the same commit.

Usage:
    uv run python scripts/regen_tools_list_snapshot.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "mcp_tools_list_snapshot.json"


PROFILE_ENV = "SUMO_QA_MCP_PROFILE"


def _spawn(profile: str | None) -> subprocess.Popen:
    src_path = str(REPO_ROOT / "src")
    existing = os.environ.get("PYTHONPATH", "")
    pythonpath = f"{src_path}{os.pathsep}{existing}" if existing else src_path
    env = {k: v for k, v in os.environ.items() if k != PROFILE_ENV}
    if profile is not None:
        env[PROFILE_ENV] = profile
    return subprocess.Popen(
        [sys.executable, "-m", "sumo_qa"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(REPO_ROOT),
        env={**env, "PYTHONPATH": pythonpath},
        text=True,
    )


def _tools_list(profile: str | None) -> list[dict]:
    proc = _spawn(profile)
    try:
        proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "regen", "version": "0"},
                    },
                }
            )
            + "\n"
        )
        proc.stdin.flush()
        proc.stdout.readline()  # initialize result
        proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                }
            )
            + "\n"
        )
        proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                }
            )
            + "\n"
        )
        proc.stdin.flush()
        response = json.loads(proc.stdout.readline())
    finally:
        try:
            proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)

    return response["result"]["tools"]


def main() -> int:
    tools = _tools_list(None)
    snapshot = {
        "core_tools": sorted(t["name"] for t in _tools_list("core")),
        "required_tools": sorted(t["name"] for t in tools),
        "schemas": {
            t["name"]: {
                "inputSchema": t.get("inputSchema"),
                "outputSchema": t.get("outputSchema"),
            }
            for t in tools
        },
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {FIXTURE.relative_to(REPO_ROOT)} with {len(tools)} tools.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
