# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Contract test: live tools/list must remain a superset of the committed snapshot.

The snapshot at tests/fixtures/mcp_tools_list_snapshot.json pins the public
MCP surface. Adding a tool is fine (the live response grows). Removing or
renaming a tool fails this test until the snapshot is regenerated in the
same PR — that regen acts as a deliberate, reviewable contract change.

Schema drift (input/output schema fields changing) emits a warning today;
this can tighten to a hard assertion in a follow-up once schemas settle.
"""

# mutmut-subprocess-spawning: spawns a fresh Python interpreter that imports the
# sumo_qa package (``-m sumo_qa``, transitively importing the mutated modules),
# so it MUST be excluded from the mutmut gate via
# [tool.mutmut].pytest_add_cli_args in pyproject.toml — otherwise it crashes the
# trampoline (KeyError: 'MUTANT_UNDER_TEST') and silently disarms the gate. The
# tests/test_mutmut_subprocess_exclusions.py guard enforces this marker↔ignore
# pairing loudly at PR time. See docs/DEVELOPMENT.md § Mutation testing.

from __future__ import annotations

import json
import os
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "mcp_tools_list_snapshot.json"


def _live_tools_list() -> list[dict]:
    src_path = str(REPO_ROOT / "src")
    existing = os.environ.get("PYTHONPATH", "")
    pythonpath = f"{src_path}{os.pathsep}{existing}" if existing else src_path
    proc = subprocess.Popen(
        [sys.executable, "-m", "sumo_qa"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": pythonpath},
        text=True,
    )
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
                        "clientInfo": {"name": "t", "version": "0"},
                    },
                }
            )
            + "\n"
        )
        proc.stdin.flush()
        proc.stdout.readline()
        proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
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
        return json.loads(proc.stdout.readline())["result"]["tools"]
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


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def live_tools() -> list[dict]:
    return _live_tools_list()


def test_required_tools_are_all_present(snapshot, live_tools) -> None:
    """Every name pinned in the snapshot must be in the live tools/list."""
    live_names = {t["name"] for t in live_tools}
    missing = sorted(set(snapshot["required_tools"]) - live_names)
    assert not missing, (
        f"Tools removed or renamed without snapshot update: {missing}.\n"
        "If this is intentional, run `uv run python scripts/regen_tools_list_snapshot.py` "
        "and commit the diff with a one-line rationale."
    )


def test_schema_drift_warns(snapshot, live_tools) -> None:
    """Schemas that have changed since the snapshot emit warnings.

    Warn-only initially so the snapshot can land without forcing immediate
    schema-stability work. Promote to a hard assertion in a follow-up PR.
    """
    live_by_name = {t["name"]: t for t in live_tools}
    for name, pinned in snapshot["schemas"].items():
        if name not in live_by_name:
            continue  # absence already caught above
        live = live_by_name[name]
        if pinned.get("inputSchema") != live.get("inputSchema"):
            warnings.warn(f"{name}: inputSchema changed since snapshot", UserWarning, stacklevel=1)
        if pinned.get("outputSchema") != live.get("outputSchema"):
            warnings.warn(f"{name}: outputSchema changed since snapshot", UserWarning, stacklevel=1)
