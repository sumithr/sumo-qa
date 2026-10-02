# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Contract test: live tools/list names must exactly equal the committed snapshot.

The snapshot at tests/fixtures/mcp_tools_list_snapshot.json pins the public
MCP tool names in two places, ``required_tools`` and the keys of ``schemas``.
Both must equal the live tools/list name set exactly: adding, removing, or
renaming a tool fails this test until the snapshot is regenerated in the same
PR, so a tool-name change is a deliberate, reviewable contract change.

Only the names are pinned. Schema drift (a tool's inputSchema or outputSchema
changing) is warn-only today, so the pinned schema bodies can still go stale.

The exact set includes the skill tools registered from ``skills/*/SKILL.md``
(unlike ``installer.REQUIRED_TOOL_NAMES``, which excludes them). Adding or
renaming a skill therefore needs
``uv run python scripts/regen_tools_list_snapshot.py`` in the same PR, and an
uncommitted work-in-progress skill directory under ``skills/`` makes this test
fail locally.
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
import re
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


_REGEN_HINT = (
    "If this is intentional, run `uv run python scripts/regen_tools_list_snapshot.py` "
    "and commit the diff with a one-line rationale."
)


def _assert_tool_set_matches(snapshot: dict, live_names: set[str]) -> None:
    pinned = set(snapshot["required_tools"])
    removed = sorted(pinned - live_names)
    unpinned = sorted(live_names - pinned)
    assert not removed and not unpinned, (
        f"Live tools/list differs from the snapshot. Removed or renamed: {removed}. "
        f"Registered but missing from the snapshot: {unpinned}.\n{_REGEN_HINT}"
    )
    schema_names = set(snapshot["schemas"])
    stale_schemas = sorted(schema_names - live_names)
    missing_schemas = sorted(live_names - schema_names)
    assert not stale_schemas and not missing_schemas, (
        f"Snapshot schemas keys differ from live tools/list. Schemas for tools not live: "
        f"{stale_schemas}. Live tools with no schema entry: {missing_schemas}.\n{_REGEN_HINT}"
    )


def test_snapshot_tool_set_matches_live(snapshot, live_tools) -> None:
    """The snapshot's tool names must equal the live tools/list names exactly."""
    _assert_tool_set_matches(snapshot, {t["name"] for t in live_tools})


# Pure-logic regression tests (#500): one per equivalence partition of the guard
# (match, missing-from-snapshot, missing-from-live, schemas-mismatch). Names share
# a prefix so a substring match cannot satisfy the positional check.
_LIVE = {"load", "load_more"}


def _snap(required: set[str], schemas: set[str]) -> dict:
    return {"required_tools": sorted(required), "schemas": {n: {} for n in schemas}}


def _listed_under(message: str, label: str, name: str) -> bool:
    """True when ``name`` is an element of the list printed right after ``label``."""
    pattern = rf"{re.escape(label)} \[[^\]]*'{re.escape(name)}'[^\]]*\]"
    return re.search(pattern, message) is not None


def test_guard_passes_when_names_and_schemas_match_live() -> None:
    _assert_tool_set_matches(_snap(_LIVE, _LIVE), _LIVE)


def test_snapshot_missing_a_registered_tool_fails_the_guard() -> None:
    with pytest.raises(AssertionError) as exc:
        _assert_tool_set_matches(_snap({"load"}, _LIVE), _LIVE)
    msg = str(exc.value)
    assert _listed_under(msg, "Registered but missing from the snapshot:", "load_more")
    assert not _listed_under(msg, "Removed or renamed:", "load_more")
    assert not _listed_under(msg, "Registered but missing from the snapshot:", "load")


def test_pinned_tool_no_longer_live_fails_the_guard() -> None:
    with pytest.raises(AssertionError) as exc:
        _assert_tool_set_matches(_snap(_LIVE, _LIVE), {"load"})
    msg = str(exc.value)
    assert _listed_under(msg, "Removed or renamed:", "load_more")
    assert not _listed_under(msg, "Registered but missing from the snapshot:", "load_more")
    assert not _listed_under(msg, "Removed or renamed:", "load")


def test_schema_keys_differing_from_live_fail_the_guard() -> None:
    with pytest.raises(AssertionError) as exc:
        _assert_tool_set_matches(_snap(_LIVE, {"load", "loader"}), _LIVE)
    msg = str(exc.value)
    assert _listed_under(msg, "Live tools with no schema entry:", "load_more")
    assert _listed_under(msg, "Schemas for tools not live:", "loader")
    assert not _listed_under(msg, "Live tools with no schema entry:", "load")


def test_schema_drift_warns(snapshot, live_tools) -> None:
    """Schemas that have changed since the snapshot emit warnings.

    Warn-only initially so the snapshot can land without forcing immediate
    schema-stability work. Promote to a hard assertion in a follow-up PR.
    """
    live_by_name = {t["name"]: t for t in live_tools}
    for name, pinned in snapshot["schemas"].items():
        if name not in live_by_name:
            continue  # absence already caught by the exact-set guard
        live = live_by_name[name]
        if pinned.get("inputSchema") != live.get("inputSchema"):
            warnings.warn(f"{name}: inputSchema changed since snapshot", UserWarning, stacklevel=1)
        if pinned.get("outputSchema") != live.get("outputSchema"):
            warnings.warn(f"{name}: outputSchema changed since snapshot", UserWarning, stacklevel=1)
