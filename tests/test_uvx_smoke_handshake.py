# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Regression test for the install-smoke uvx-spawn handshake bug.

Confirmed reproducible on PR #141 ubuntu CI: the smoke step used
`subprocess.communicate()` which writes the full payload then closes stdin.
The mcp library's `lowlevel.Server.run()` cancels every in-flight handler
when stdin EOF is read (mcp/server/lowlevel/server.py:685-690 — the
"Transport closed: cancel in-flight handlers" branch). On Linux's epoll
scheduler the cancel beats the tools/list handler's stdout write, so the
id==2 response never reaches the client.

This test pins the stdin-handling contract via a deterministic mock server
that mirrors the cancel-on-EOF behaviour: tools/list response is delayed
300ms; stdin EOF during that window cancels the response. A correct
`run_handshake` keeps stdin open until id==2 is observed; an incorrect
one (e.g. `subprocess.communicate()`) closes too early and the assertion
fails.

Technique: state transition testing — the test pins the ordering
`payload-sent → response-received → stdin-closed`, distinguishing it from
the broken `payload-sent → stdin-closed → response-cancelled`.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys


def _find_repo_root() -> pathlib.Path:
    """Walk up to a directory containing both pyproject.toml and scripts/.

    Robust to mutmut's layout (which copies tests/ into mutants/tests/ but
    not scripts/), matching the pattern used by other tests in this repo.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "scripts").is_dir():
            return candidate
    raise RuntimeError(f"cannot locate repo root from {here}")


REPO_ROOT = _find_repo_root()
SCRIPT = REPO_ROOT / "scripts" / "uvx_smoke_handshake.py"
MOCK_SERVER = REPO_ROOT / "tests" / "fixtures" / "mock_slow_mcp_server.py"

# Load the script as a module so the test can call its functions directly.
# Register in sys.modules BEFORE exec_module because @dataclass looks up the
# class's containing module via sys.modules during decoration — exec_module
# would fail with `'NoneType' object has no attribute '__dict__'` otherwise.
_MODULE_NAME = "_uvx_smoke_handshake"
_spec = importlib.util.spec_from_file_location(_MODULE_NAME, SCRIPT)
assert _spec is not None and _spec.loader is not None
handshake_mod = importlib.util.module_from_spec(_spec)
sys.modules[_MODULE_NAME] = handshake_mod
_spec.loader.exec_module(handshake_mod)


def test_handshake_captures_delayed_response_against_slow_mock() -> None:
    """Pin the stdin-handling contract.

    `run_handshake` must keep stdin open until the id==2 response has been
    read off stdout, otherwise the mock's cancel-on-EOF branch fires (just
    like the real mcp library does) and the response is lost.

    A correct implementation:
      - Writes init + notif + tools/list, flushes stdin
      - Reads stdout (e.g. via a draining thread) until id==2 arrives
      - THEN closes stdin and reaps

    A broken implementation (e.g. `subprocess.communicate(payload)`) closes
    stdin immediately, triggering the cancel, and `result.success` stays
    False — exactly the bug observed on PR #141 ubuntu CI.
    """
    cmd = [sys.executable, str(MOCK_SERVER)]
    result = handshake_mod.run_handshake(cmd, deadline_secs=5.0)
    assert result.success is True, (
        "handshake should keep stdin open until id==2 received; "
        f"got success={result.success!r}, id2={result.id2!r}, "
        f"tool_count={result.tool_count}, "
        f"stderr={result.stderr[:300]!r}"
    )
    assert result.tool_count == 2, (
        f"mock server returns 2 tools (sumo_qa_load_classifications + "
        f"sumo_qa_load_approaches); got {result.tool_count}: {result.tool_names!r}"
    )
