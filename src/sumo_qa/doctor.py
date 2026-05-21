# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""sumo-qa-doctor — read-only setup and host compatibility diagnostics.

Shipped as the ``sumo-qa-doctor`` console script (exposed via
``[project.scripts]`` in pyproject.toml) and as ``python -m sumo_qa.doctor``.

Runs a fixed sequence of read-only checks against the local sumo-qa install
and the host configs the ``sumo-qa-install`` installer would write to.
Never mutates any file on disk. Prints a human-readable report by default
or a JSON document with ``--json``.

The JSON shape is INTERNAL until sumo-qa 1.0 — see docs/INSTALL.md.

Doctor never modifies installer.py — every read-only probe it needs is
imported from installer's existing public + private surface. That keeps
the installer's existing test suite passing unchanged across this change.
"""

from __future__ import annotations

import collections
import json
import shutil
import subprocess
import sys as _sys
import time
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path as _Path
from typing import Literal

from sumo_qa import installer as _installer
from sumo_qa.installer import (
    REQUIRED_TOOL_NAMES,
    McpCommand,
    _read_json_rpc_response,
    _start_stdout_reader,
    _terminate,
    _VerifyTimeout,
)

# Re-export the names doctor's surface relies on so callers (and tests)
# can reach them via ``sumo_qa.doctor`` without importing installer.
__all__ = [
    "CheckResult",
    "McpCommand",
    "REQUIRED_TOOL_NAMES",
    "check_binary_discoverable",
    "check_install_mode",
    "check_python_version",
    "main",
    "run_mcp_probe",
]

# Mirrors ``installer._VERIFY_TIMEOUT_SECONDS`` but kept independent so a
# future doctor-specific tuning (longer for slow CI, shorter for interactive
# use) doesn't have to touch the installer's hardened install-time budget.
_HANDSHAKE_TIMEOUT_SECONDS = 10

# Truncate stderr captured from a crashed server. Matches the installer's
# ``_DUMP_STREAM_CHARS`` value so bug reports and doctor reports line up.
_STDERR_DUMP_CHARS = 300

Status = Literal["OK", "WARN", "FAIL"]


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one diagnostic check.

    ``check_id`` is stable across releases (machine-parseable). ``status``
    is one of ``OK`` / ``WARN`` / ``FAIL``. ``summary`` is a one-line human
    description. ``fix`` is the exact shell command the user should run
    (``None`` when no fix applies — OK records, or WARN records that are
    purely informational).
    """

    check_id: str
    status: Status
    summary: str
    fix: str | None = None
    details: dict = field(default_factory=dict)


def check_python_version() -> CheckResult:
    """Report the interpreter version and the installed sumo-qa package version.

    Always ``OK`` — Python <3.10 is rejected by pyproject.toml's
    ``requires-python = ">=3.10"`` before this script can even import, so
    the check is a disclosure not a gate. The two strings end up in install
    bug reports and let support distinguish "user is on the wrong Python"
    from "user is on a stale sumo-qa".
    """
    py = ".".join(str(p) for p in _sys.version_info[:3])
    try:
        pkg = _pkg_version("sumo-qa")
    except PackageNotFoundError:  # pragma: no cover -- defensive; not pip-installed
        pkg = "unknown (not installed via pip)"
    return CheckResult(
        check_id="python_version",
        status="OK",
        summary=f"Python {py}; sumo-qa {pkg}",
        details={"python_version": py, "sumo_qa_version": pkg},
    )


_HANDSHAKE_FIX = "Run `sumo-qa-install` and re-run `sumo-qa-doctor`."


def _handshake_fail(
    *,
    summary: str,
    kind: str,
    stderr: str = "",
    exit_code: int | None = None,
) -> tuple[CheckResult, CheckResult]:
    """Build the two CheckResults returned when the JSON-RPC handshake fails.

    The first record carries the structured failure; the second flags
    ``tools_list_complete`` as skipped (we never got far enough to drive
    ``tools/list``). Keeps the rendering layer free of conditional shape.
    """
    details: dict = {"kind": kind}
    if stderr:
        details["stderr"] = stderr[:_STDERR_DUMP_CHARS]
    if exit_code is not None:
        details["exit_code"] = exit_code
    handshake = CheckResult(
        check_id="mcp_handshake",
        status="FAIL",
        summary=summary,
        fix=_HANDSHAKE_FIX,
        details=details,
    )
    tools = CheckResult(
        check_id="tools_list_complete",
        status="FAIL",
        summary="skipped — MCP handshake did not complete",
    )
    return handshake, tools


def run_mcp_probe(mcp_cmd: McpCommand) -> tuple[CheckResult, CheckResult]:
    """Drive an ``initialize`` + ``tools/list`` handshake and return two
    structured CheckResult records: one for the handshake, one for tool
    coverage.

    Failure classes (all FAIL status):

    - ``timeout``: the server didn't respond within
      ``_HANDSHAKE_TIMEOUT_SECONDS``.
    - ``nonzero_exit``: the server exited before responding; first 300 chars
      of stderr captured in ``details["stderr"]``.
    - ``malformed_jsonrpc``: a response arrived but failed shape validation
      (missing id, wrong ``jsonrpc`` version, error envelope, non-dict
      ``result``).
    - ``missing_tools``: ``tools/list`` returned a strict subset of
      ``REQUIRED_TOOL_NAMES``; names listed in ``details["missing"]``.

    On success both records carry status ``OK``.
    """
    init_req = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "sumo-qa-doctor", "version": "1"},
            },
        }
    )
    initialized_note = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    tools_req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

    proc = subprocess.Popen(  # noqa: S603 -- argv comes from a trusted McpCommand
        mcp_cmd.as_subprocess_argv(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    line_queue = _start_stdout_reader(proc)
    deadline = time.monotonic() + _HANDSHAKE_TIMEOUT_SECONDS
    extra: list[str] = []
    pending: collections.deque[dict] = collections.deque()
    init_resp: dict | None = None
    tools_resp: dict | None = None
    timed_out = False

    try:
        proc.stdin.write(init_req + "\n")
        proc.stdin.flush()
        init_resp = _read_json_rpc_response(
            line_queue=line_queue,
            expected_id=1,
            deadline=deadline,
            extra_lines=extra,
            pending_responses=pending,
        )
        if init_resp is not None:
            proc.stdin.write(initialized_note + "\n")
            proc.stdin.flush()
            proc.stdin.write(tools_req + "\n")
            proc.stdin.flush()
            tools_resp = _read_json_rpc_response(
                line_queue=line_queue,
                expected_id=2,
                deadline=deadline,
                extra_lines=extra,
                pending_responses=pending,
            )
    except _VerifyTimeout:
        timed_out = True
    except (BrokenPipeError, OSError):  # pragma: no cover -- defensive
        timed_out = True
    finally:
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except Exception:  # pragma: no cover -- defensive cleanup; noqa: BLE001
            pass

    # Drain stderr only after the process has had a chance to exit, so the
    # read never blocks on a stalled server.
    stderr_text = ""
    try:
        if proc.stderr is not None and proc.poll() is not None:
            stderr_text = (proc.stderr.read() or "")[:_STDERR_DUMP_CHARS]
    except Exception:  # pragma: no cover -- defensive; noqa: BLE001
        pass
    exit_code = proc.poll()
    _terminate(proc)

    # --- handshake classification ---
    if timed_out:
        return _handshake_fail(
            summary=(f"MCP handshake timeout — no response within {_HANDSHAKE_TIMEOUT_SECONDS}s"),
            kind="timeout",
            stderr=stderr_text,
            exit_code=exit_code,
        )
    if init_resp is None:
        # No id=1 response arrived before EOF. Distinguish "server crashed"
        # (non-zero exit) from "server exited cleanly without answering".
        if exit_code not in (None, 0):
            return _handshake_fail(
                summary=(f"MCP exited non-zero ({exit_code}) before responding to initialize"),
                kind="nonzero_exit",
                stderr=stderr_text,
                exit_code=exit_code,
            )
        return _handshake_fail(
            summary="MCP did not return an initialize response",
            kind="no_response",
            stderr=stderr_text,
            exit_code=exit_code,
        )
    if init_resp.get("jsonrpc") != "2.0":
        return _handshake_fail(
            summary=(
                f"initialize response missing jsonrpc='2.0' (got {init_resp.get('jsonrpc')!r})"
            ),
            kind="malformed_jsonrpc",
            stderr=stderr_text,
            exit_code=exit_code,
        )
    if "error" in init_resp:
        err = init_resp["error"]
        if isinstance(err, dict):
            msg = f"{err.get('code')}: {err.get('message')}"
        else:
            msg = str(err)
        return _handshake_fail(
            summary=f"initialize returned error envelope ({msg})",
            kind="initialize_error",
            stderr=stderr_text,
            exit_code=exit_code,
        )
    if not isinstance(init_resp.get("result"), dict):
        return _handshake_fail(
            summary=(
                "initialize response 'result' is not a dict "
                f"(got {type(init_resp.get('result')).__name__})"
            ),
            kind="malformed_jsonrpc",
            stderr=stderr_text,
            exit_code=exit_code,
        )

    handshake_ok = CheckResult(
        check_id="mcp_handshake",
        status="OK",
        summary="MCP initialize handshake succeeded",
        details={"kind": "ok"},
    )

    # --- tools/list classification ---
    if tools_resp is None:
        return handshake_ok, CheckResult(
            check_id="tools_list_complete",
            status="FAIL",
            summary="MCP did not return a tools/list response",
            fix=_HANDSHAKE_FIX,
        )
    if "error" in tools_resp:
        err = tools_resp["error"]
        return handshake_ok, CheckResult(
            check_id="tools_list_complete",
            status="FAIL",
            summary=f"tools/list returned error envelope: {err!r}",
            fix=_HANDSHAKE_FIX,
        )
    res = tools_resp.get("result")
    if not isinstance(res, dict):
        return handshake_ok, CheckResult(
            check_id="tools_list_complete",
            status="FAIL",
            summary=(f"tools/list 'result' is not a dict (got {type(res).__name__})"),
        )
    tools = res.get("tools", [])
    if not isinstance(tools, list):
        return handshake_ok, CheckResult(
            check_id="tools_list_complete",
            status="FAIL",
            summary="tools/list 'result.tools' is not a list",
        )
    advertised = {t.get("name") for t in tools if isinstance(t, dict)}
    missing = [n for n in REQUIRED_TOOL_NAMES if n not in advertised]
    if missing:
        return handshake_ok, CheckResult(
            check_id="tools_list_complete",
            status="FAIL",
            summary=f"tools/list is missing {len(missing)} required tool(s)",
            fix=(f"Run `sumo-qa-install` to re-register the server. Missing: {', '.join(missing)}"),
            details={
                "missing": missing,
                "advertised_count": sum(1 for n in advertised if isinstance(n, str)),
            },
        )
    return handshake_ok, CheckResult(
        check_id="tools_list_complete",
        status="OK",
        summary=f"all {len(REQUIRED_TOOL_NAMES)} required tools advertised",
        details={"advertised_count": len(advertised)},
    )


def check_binary_discoverable() -> CheckResult:
    """Report whether the ``sumo-qa`` console-script wrapper is on ``PATH``,
    or if we're falling back to ``python -m sumo_qa``.

    ``OK`` either way — both are supported invocations. The fallback path
    emits a non-``None`` ``fix`` so hosts that strictly need a binary
    (some JetBrains UI add flows, niche corporate proxies that won't accept
    a Python interpreter as the MCP command) get an actionable command.
    """
    existing = shutil.which("sumo-qa")
    if existing is not None:
        resolved = str(_Path(existing).resolve())
        return CheckResult(
            check_id="binary_discoverable",
            status="OK",
            summary=f"sumo-qa on PATH at {resolved}",
            details={"mode": "path", "binary_path": resolved},
        )
    return CheckResult(
        check_id="binary_discoverable",
        status="OK",
        summary=(f"sumo-qa not on PATH; falling back to `{_sys.executable} -m sumo_qa`"),
        fix=(
            "Add your pip Scripts directory to PATH, or re-install via "
            "`python -m pip install --user sumo-qa` and confirm `which sumo-qa` "
            "resolves."
        ),
        details={"mode": "module", "interpreter": _sys.executable},
    )


def check_install_mode(module_dir: _Path | None = None) -> CheckResult:
    """Disclose whether sumo-qa is running from a built wheel or an editable
    install. Always ``OK`` — drives the "I edited skills/X but the change
    isn't visible" support flow.

    Mirrors ``installer._detect_install_mode`` without exiting on a missing
    repo root: doctor reports the live state, it never fixes anything, so a
    half-installed layout produces a diagnostic, not ``sys.exit``.
    """
    md = module_dir if module_dir is not None else _Path(_installer.__file__).resolve().parent
    bundled = md / "_data" / "skills"
    if bundled.is_dir():
        return CheckResult(
            check_id="install_mode",
            status="OK",
            summary=f"wheel install (bundled skills at {bundled})",
            details={"mode": "wheel", "skills_path": str(bundled)},
        )
    repo_root = md.parent.parent
    return CheckResult(
        check_id="install_mode",
        status="OK",
        summary=f"editable install (skills/ under {repo_root})",
        details={"mode": "editable", "skills_path": str(repo_root / "skills")},
    )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover -- wired in Task 11
    """Stub. Filled in by the CLI surface task."""
    return 0
