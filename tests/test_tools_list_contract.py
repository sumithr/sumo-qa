# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Contract test: live tools/list names must exactly equal the committed snapshot.

The snapshot at tests/fixtures/mcp_tools_list_snapshot.json pins the public
MCP tool names in two places, ``required_tools`` and the keys of ``schemas``.
Both must equal the live tools/list name set exactly: adding, removing, or
renaming a tool fails this test until the snapshot is regenerated in the same
PR, so a tool-name change is a deliberate, reviewable contract change.

Only the names are pinned. Schema drift (a tool's inputSchema or outputSchema
changing) is warn-only: it raises a UserWarning, not a failure, so the pinned
schema bodies can still go stale.

The exact set includes the skill tools registered from ``skills/*/SKILL.md``
(unlike ``installer.REQUIRED_TOOL_NAMES``, which excludes them). Adding or
renaming a skill therefore needs
``uv run python scripts/regen_tools_list_snapshot.py`` in the same PR. The test
reads the working tree, not commit state: the server lists skills from
``src/sumo_qa/_data/skills`` when that directory exists, else from repo-root
``skills/``, so a stale ``_data/skills`` copy shadows the working tree for
every test that builds the server (this one, ``test_server.py``,
``test_skill_triggering.py``), the skill manifest, and the regen script.
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
from collections import Counter
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


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    counts = Counter(key for key, _ in pairs)
    duplicates = sorted(key for key, n in counts.items() if n > 1)
    if duplicates:
        raise ValueError(
            f"Duplicate key {duplicates[0]!r} in the tools/list snapshot (all repeats: "
            f"{duplicates}). json.loads would silently keep only the last copy; this "
            "usually means a bad merge. Re-run `uv run python scripts/regen_tools_list_snapshot.py`."
        )
    return dict(pairs)


def _load_snapshot(text: str) -> dict:
    return json.loads(text, object_pairs_hook=_reject_duplicate_keys)


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return _load_snapshot(FIXTURE.read_text(encoding="utf-8"))


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
    schema_names = set(snapshot["schemas"])
    stale_schemas = sorted(schema_names - live_names)
    missing_schemas = sorted(live_names - schema_names)
    duplicates = sorted(n for n, c in Counter(snapshot["required_tools"]).items() if c > 1)
    problems = []
    if duplicates:
        problems.append(f"Duplicate names in required_tools: {duplicates}.")
    if removed or unpinned:
        problems.append(
            f"Live tools/list differs from the snapshot. Removed or renamed: {removed}. "
            f"Registered but missing from the snapshot: {unpinned}."
        )
    if stale_schemas or missing_schemas:
        problems.append(
            f"Snapshot schemas keys differ from live tools/list. Schemas for tools not live: "
            f"{stale_schemas}. Live tools with no schema entry: {missing_schemas}."
        )
    assert not problems, "\n".join([*problems, _REGEN_HINT])


def test_snapshot_tool_set_matches_live(snapshot, live_tools) -> None:
    """The snapshot's tool names must equal the live tools/list names exactly."""
    _assert_tool_set_matches(snapshot, {t["name"] for t in live_tools})


# Pure-logic regression tests: one per equivalence partition of the guard
# (match, missing-from-snapshot, missing-from-live, duplicate-pinned-name,
# stale-schema, missing-schema, name-plus-schema drift together).
# Names share a prefix so a substring match cannot satisfy the positional check.
_LIVE = {"load", "load_more"}


def _snap(required: set[str], schemas: set[str]) -> dict:
    return {"required_tools": sorted(required), "schemas": {n: {} for n in schemas}}


def _listed_under(message: str, label: str, name: str) -> bool:
    """True when ``name`` is an element of the list printed right after ``label``.

    Raises when ``label`` is absent, so a reworded label cannot make a negative
    check pass vacuously.
    """
    assert label in message, f"label {label!r} not in message: {message}"
    pattern = rf"{re.escape(label)} \[[^\]]*'{re.escape(name)}'[^\]]*\]"
    return re.search(pattern, message) is not None


def test_duplicate_schema_key_in_snapshot_json_fails_the_load() -> None:
    text = '{"schemas": {"load": {}, "load_more": {}, "load_more": {}}}'
    with pytest.raises(ValueError, match="Duplicate key 'load_more'"):
        _load_snapshot(text)


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


def test_duplicate_pinned_tool_name_fails_the_guard() -> None:
    snap = _snap(_LIVE, _LIVE)
    snap["required_tools"].append("load_more")
    with pytest.raises(AssertionError) as exc:
        _assert_tool_set_matches(snap, _LIVE)
    msg = str(exc.value)
    assert _listed_under(msg, "Duplicate names in required_tools:", "load_more")
    assert not _listed_under(msg, "Duplicate names in required_tools:", "load")


def test_schema_for_tool_not_live_fails_the_guard() -> None:
    with pytest.raises(AssertionError) as exc:
        _assert_tool_set_matches(_snap(_LIVE, _LIVE | {"loader"}), _LIVE)
    msg = str(exc.value)
    assert _listed_under(msg, "Schemas for tools not live:", "loader")
    assert not _listed_under(msg, "Schemas for tools not live:", "load")
    assert not _listed_under(msg, "Live tools with no schema entry:", "loader")
    assert "Removed or renamed:" not in msg


def test_live_tool_without_schema_entry_fails_the_guard() -> None:
    with pytest.raises(AssertionError) as exc:
        _assert_tool_set_matches(_snap(_LIVE, {"load"}), _LIVE)
    msg = str(exc.value)
    assert _listed_under(msg, "Live tools with no schema entry:", "load_more")
    assert not _listed_under(msg, "Live tools with no schema entry:", "load")
    assert not _listed_under(msg, "Schemas for tools not live:", "load_more")
    assert "Removed or renamed:" not in msg


def test_unregenerated_snapshot_reports_name_and_schema_drift_together() -> None:
    with pytest.raises(AssertionError) as exc:
        _assert_tool_set_matches(_snap({"load"}, {"load"}), _LIVE)
    msg = str(exc.value)
    assert _listed_under(msg, "Registered but missing from the snapshot:", "load_more")
    assert _listed_under(msg, "Live tools with no schema entry:", "load_more")
    assert not _listed_under(msg, "Removed or renamed:", "load_more")
    assert "'load'" not in msg


def test_schema_drift_warns(snapshot, live_tools) -> None:
    """Schemas that have changed since the snapshot emit warnings.

    Warn-only: an inputSchema or outputSchema change raises a UserWarning,
    not a failure.
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
