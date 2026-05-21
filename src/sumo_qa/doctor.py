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

Design: defence-in-depth against host schema changes
====================================================

Two tiers of checks:

1. **Canonical functional checks** — ``run_mcp_probe`` drives a JSON-RPC
   ``initialize`` + ``tools/list`` handshake against the running server.
   If this passes, sumo-qa is operationally healthy regardless of how it
   was installed. This is the ground-truth answer to "does it work?".

2. **Storage-probe checks** — inspect host-vendor storage (Anthropic's
   ``~/.claude/plugins/installed_plugins.json``, OpenAI's
   ``~/.codex/config.toml``, Claude Desktop / VS Code config files).
   These are diagnostic value-adds: when something is broken, they tell
   the user which config drifted and how to fix it.

Storage-probe checks fall into two risk profiles:

- **Plugin-install registries** (``check_claude_code_plugin``,
  ``check_codex_plugin``) inspect schemas owned by Anthropic / OpenAI.
  These are newer surfaces and the vendor could restructure them. To
  keep schema drift from producing false FAILs, these checks use minimal
  pattern-matching (regex section-header detection for Codex's TOML,
  presence-of-key lookups for Claude's JSON) and fall through to ``OK``
  with a "couldn't determine install state" disclosure when the layout
  doesn't match.

- **Host MCP configs** (``check_claude_code_config``,
  ``check_claude_desktop_config``, ``check_vscode_workspace_config``)
  inspect the same files ``sumo-qa-install`` WRITES. The schemas
  (``mcpServers`` for Claude, ``servers`` for VS Code) are defined by
  the host vendor but consumed by our installer; if the vendor renamed
  a key the installer would break first and these checks would
  correctly flag the resulting broken install. FAIL is the right
  severity here.

Either way, the canonical functional answer comes from ``run_mcp_probe``:
if that passes, sumo-qa is working regardless of what storage probes
recognise. If functional checks pass but storage probes return "not
detected", the install is working through a source the probes don't
recognise — not a failure.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import platform as _platform
import re
import shlex
import shutil
import subprocess
import sys as _sys
import time
from collections.abc import Callable
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
    "check_claude_code_config",
    "check_claude_code_plugin",
    "check_claude_desktop_config",
    "check_codex_plugin",
    "check_install_mode",
    "check_jetbrains_detection",
    "check_python_version",
    "check_vscode_user_misleading",
    "check_vscode_workspace_config",
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
    except PackageNotFoundError:
        # Not pip-installed — running from a source checkout with PYTHONPATH
        # set (or via the pre-commit hook venv that resolves sumo_qa via
        # pythonpath rather than installing the wheel). The doctor's job is
        # to report state, not gate on this — surface the fact and move on.
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


def _claude_code_config_path(home: _Path, system: str) -> _Path:
    """Path to the Claude Code config that ``sumo-qa-install`` would write.

    Mirrors ``installer._setup_claude_code``'s ``config_dir`` resolution.
    NOT the same as ``installer._claude_desktop_config_path`` (which is the
    real Claude Desktop app on macOS — a different file).
    """
    if system == "Windows":  # pragma: no cover -- platform-conditional
        return _Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "claude" / "claude_desktop_config.json"


def _server_entry_resolves(entry: dict) -> bool:
    """Return True if the ``command`` in a host-config server entry still
    resolves to a real executable on disk.

    Catches the "I ``pip uninstall``ed and reinstalled to a different path"
    stale-config case the issue calls out. Treats anything that isn't a
    non-empty string as unresolvable.
    """
    cmd = entry.get("command")
    if not cmd or not isinstance(cmd, str):
        return False
    return _Path(cmd).exists()


def _check_host_config(
    *,
    check_id: str,
    config_path: _Path,
    not_installed_summary: str,
    not_installed_predicate: bool,
    install_flag: str,
    config_schema_key: str,
    on_missing_entry: Callable[[], CheckResult | None] | None = None,
) -> CheckResult:
    """Shared body for host-config checks (Claude Code, Claude Desktop, VS Code).

    Returns OK with ``not_installed_summary`` when ``not_installed_predicate``
    is True (host not present on this machine). Otherwise: checks the config
    file's existence / readability / JSON shape / sumo-qa entry / resolvable
    binary path. Every FAIL ends with the ``sumo-qa-install <install_flag>``
    fix command.

    ``on_missing_entry`` is an optional hook called when the config parses
    fine but has no ``sumo-qa`` entry under ``config_schema_key``. If the
    hook returns a ``CheckResult``, it replaces the default FAIL. Used by
    Claude Code to soften the FAIL when the user is registered via the
    plugin manager instead — the pip-install config is intentionally empty.
    """
    if not_installed_predicate:
        return CheckResult(
            check_id=check_id,
            status="OK",
            summary=not_installed_summary,
        )
    if not config_path.exists():
        return CheckResult(
            check_id=check_id,
            status="FAIL",
            summary=f"{config_path} missing (host config not written)",
            fix=f"Run `sumo-qa-install {install_flag}` to write the config.",
        )
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        return CheckResult(
            check_id=check_id,
            status="FAIL",
            summary=(
                f"{config_path} unreadable (permission/OS error: {exc.__class__.__name__}: {exc})"
            ),
            fix=(f"Fix the permissions on {config_path} so the current user can read it."),
        )
    try:
        config = json.loads(text)
    except json.JSONDecodeError as exc:
        return CheckResult(
            check_id=check_id,
            status="FAIL",
            summary=(
                f"{config_path} is not valid JSON ({exc.msg} at line {exc.lineno}, col {exc.colno})"
            ),
            fix=(
                f"Re-run `sumo-qa-install {install_flag}` to overwrite the corrupt "
                f"config, or hand-edit {config_path} to repair the JSON."
            ),
        )
    entry = (config.get(config_schema_key) or {}).get("sumo-qa")
    if entry is None or not isinstance(entry, dict):
        if on_missing_entry is not None:
            softened = on_missing_entry()
            if softened is not None:
                return softened
        return CheckResult(
            check_id=check_id,
            status="FAIL",
            summary=f"{config_path} has no `sumo-qa` entry under {config_schema_key}",
            fix=f"Run `sumo-qa-install {install_flag}` to register the server.",
        )
    if not _server_entry_resolves(entry):
        return CheckResult(
            check_id=check_id,
            status="FAIL",
            summary=(
                f"{config_path} points at a binary that does not resolve "
                f"({entry.get('command')!r}) — stale config"
            ),
            fix=(f"Run `sumo-qa-install {install_flag}` to refresh the binary path."),
            details={
                "config_path": str(config_path),
                "stale_command": entry.get("command"),
            },
        )
    return CheckResult(
        check_id=check_id,
        status="OK",
        summary=f"{config_path} registers sumo-qa at {entry.get('command')}",
        details={"config_path": str(config_path), "command": entry.get("command")},
    )


_PLUGIN_REINSTALL_FIX = (
    "Run `claude plugin install <marketplace>/sumo-qa` (e.g. "
    "`claude plugin install sumithr/sumo-qa`) to refresh the install."
)


def _find_sumo_qa_plugin_entries(plugins: dict) -> list[tuple[str, dict]]:
    """Return ``(key, entry)`` pairs for every ``sumo-qa@<marketplace>``
    install record in the plugins registry.

    The registry's top-level ``plugins`` map keys by ``<name>@<marketplace>``;
    each value is a list of install records (one per scope: user / project).
    We match on the ``sumo-qa@`` prefix so any marketplace flavour is
    recognised, and flatten the per-scope list so a hybrid install (e.g.
    both user-scope and project-scope) surfaces all records.
    """
    out: list[tuple[str, dict]] = []
    for key, records in plugins.items():
        if not key.startswith("sumo-qa@"):
            continue
        if not isinstance(records, list):
            continue
        for record in records:
            if isinstance(record, dict):
                out.append((key, record))
    return out


def check_claude_code_plugin(home: _Path | None = None) -> CheckResult:
    """Report whether sumo-qa is installed via Claude Code's plugin manager
    (``claude plugin install sumithr/sumo-qa``).

    Plugin install is a self-contained alternative to the pip-install path:
    Claude Code reads ``.claude-plugin/plugin.json`` and registers skills +
    hooks + MCP-server config from the plugin folder. The plugin's
    ``.mcp.json`` declares ``uvx --from ${CLAUDE_PLUGIN_ROOT} sumo-qa`` as
    the server command (Anthropic's canonical pattern per
    https://code.claude.com/docs/en/mcp#plugin-provided-mcp-servers) — uvx
    builds and runs the Python package from whichever directory
    ``${CLAUDE_PLUGIN_ROOT}`` resolves to (the local checkout for
    ``claude --plugin-dir <repo>``, the cache dir for a marketplace
    install). No separate ``pip install sumo-qa`` is required. Users get
    a fully working install from the single ``claude plugin install``
    command (uv is the assumed prerequisite, matching how npx is assumed
    for Node-based plugins).

    Status semantics:
      - OK / "not detected": Claude Code itself isn't on this machine.
      - OK / "no plugins installed": registry missing — pip-install-only user.
      - OK / "no sumo-qa plugin entry": registry present, sumo-qa absent.
      - OK / "registered via plugin manager": sumo-qa entry + install path
        exists.
      - FAIL: entry exists but install path is missing (dangling), or the
        registry file itself is unreadable / malformed JSON.
    """
    h = home or _Path.home()
    claude_home = h / ".claude"
    if not claude_home.exists():
        return CheckResult(
            check_id="claude_code_plugin",
            status="OK",
            summary="Claude Code not detected on this machine",
        )
    registry = claude_home / "plugins" / "installed_plugins.json"
    if not registry.exists():
        return CheckResult(
            check_id="claude_code_plugin",
            status="OK",
            summary=(
                "Claude Code has no plugins installed (no installed_plugins.json) "
                "— pip-install-only user"
            ),
        )
    try:
        text = registry.read_text(encoding="utf-8")
    except OSError as exc:
        return CheckResult(
            check_id="claude_code_plugin",
            status="FAIL",
            summary=(
                f"{registry} unreadable (permission/OS error: {exc.__class__.__name__}: {exc})"
            ),
            fix=f"Fix the permissions on {registry} so the current user can read it.",
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return CheckResult(
            check_id="claude_code_plugin",
            status="FAIL",
            summary=(f"{registry} is not valid JSON ({exc.msg} at line {exc.lineno})"),
            fix=_PLUGIN_REINSTALL_FIX,
        )
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        # Anthropic owns this schema. If a future bump renames `plugins` or
        # restructures the shape, fall through to "no plugin install" rather
        # than FAIL — false-positives on schema drift are worse than missing
        # a real plugin install (which other checks would still catch).
        return CheckResult(
            check_id="claude_code_plugin",
            status="OK",
            summary=(
                f"{registry} has no recognisable `plugins` map — treating as no plugin install"
            ),
        )
    entries = _find_sumo_qa_plugin_entries(plugins)
    if not entries:
        return CheckResult(
            check_id="claude_code_plugin",
            status="OK",
            summary="sumo-qa not installed via plugin manager (no sumo-qa entry)",
        )
    # Take the first record (one install scope is the realistic case);
    # surface the marketplace name so hybrid users see which source is active.
    key, record = entries[0]
    install_path_str = record.get("installPath")
    install_path = _Path(install_path_str) if isinstance(install_path_str, str) else None
    version = record.get("version", "unknown")
    if install_path is None or not install_path.exists():
        return CheckResult(
            check_id="claude_code_plugin",
            status="FAIL",
            summary=(
                f"plugin registry lists {key} v{version} but installPath "
                f"{install_path_str!r} does not exist — dangling install"
            ),
            fix=_PLUGIN_REINSTALL_FIX,
            details={
                "registry_key": key,
                "version": version,
                "install_path": install_path_str,
            },
        )
    return CheckResult(
        check_id="claude_code_plugin",
        status="OK",
        summary=f"sumo-qa registered via Claude Code plugin manager ({key} v{version})",
        details={
            "registry_key": key,
            "version": version,
            "install_path": str(install_path),
        },
    )


# Pattern that matches `[plugins."sumo-qa@<marketplace>"]` section headers
# in Codex's config.toml. We don't pull in a TOML parser dependency just for
# this — the section header is the only signal we need, and a regex
# degrades gracefully if OpenAI ever rearranges the rest of the schema.
# Captures the marketplace name; whitespace-tolerant per TOML's parser.
_CODEX_PLUGIN_SECTION_RE = re.compile(r'^\s*\[plugins\."sumo-qa@([^"]+)"\]\s*$', re.MULTILINE)

_CODEX_PLUGIN_REINSTALL_FIX = (
    "Run `/plugins install sumithr/sumo-qa` from inside Codex (or your usual "
    "sumo-qa marketplace source) to refresh the install."
)


def check_codex_plugin(home: _Path | None = None) -> CheckResult:
    """Report whether sumo-qa is installed via OpenAI Codex's plugin manager
    (``/plugins install sumithr/sumo-qa``).

    Codex stores plugin state in ``~/.codex/config.toml`` under
    ``[plugins."<name>@<marketplace>"]`` sections; the actual content lives
    at ``~/.codex/plugins/cache/<marketplace>/<plugin>/<version>/``.

    Status semantics mirror ``check_claude_code_plugin``:
      - OK / "not detected": Codex CLI isn't on this machine.
      - OK / "config.toml missing": Codex installed but never configured.
      - OK / "no sumo-qa entry": config present, sumo-qa not registered.
      - OK / "registered via plugin manager": entry + cache dir exist.
      - FAIL: entry present but cache dir absent (dangling), or config
        unreadable.

    Defensive parsing — uses a regex on the section header rather than a
    full TOML parser. If OpenAI changes any other part of the schema, the
    check still recognises the section it cares about; if they rename the
    section entirely the check falls through to "no sumo-qa entry" (OK,
    not FAIL) so schema drift doesn't trigger false failures.
    """
    h = home or _Path.home()
    codex_home = h / ".codex"
    if not codex_home.exists():
        return CheckResult(
            check_id="codex_plugin",
            status="OK",
            summary="Codex not detected on this machine",
        )
    config = codex_home / "config.toml"
    if not config.exists():
        return CheckResult(
            check_id="codex_plugin",
            status="OK",
            summary=(f"{config} missing — Codex has no plugins or MCP servers configured"),
        )
    try:
        text = config.read_text(encoding="utf-8")
    except OSError as exc:
        return CheckResult(
            check_id="codex_plugin",
            status="FAIL",
            summary=(f"{config} unreadable (permission/OS error: {exc.__class__.__name__}: {exc})"),
            fix=f"Fix the permissions on {config} so the current user can read it.",
        )
    match = _CODEX_PLUGIN_SECTION_RE.search(text)
    if match is None:
        return CheckResult(
            check_id="codex_plugin",
            status="OK",
            summary="sumo-qa not installed via Codex plugin manager (no sumo-qa entry)",
        )
    marketplace = match.group(1)
    cache_root = codex_home / "plugins" / "cache" / marketplace / "sumo-qa"
    versions: list[str] = []
    if cache_root.exists():
        versions = sorted(
            (p.name for p in cache_root.iterdir() if p.is_dir()),
            reverse=True,
        )
    if not versions:
        return CheckResult(
            check_id="codex_plugin",
            status="FAIL",
            summary=(
                f"Codex registers sumo-qa@{marketplace} in {config} but the "
                f"plugin cache at {cache_root} is missing or empty — dangling install"
            ),
            fix=_CODEX_PLUGIN_REINSTALL_FIX,
            details={"marketplace": marketplace, "cache_root": str(cache_root)},
        )
    version = versions[0]
    return CheckResult(
        check_id="codex_plugin",
        status="OK",
        summary=(f"sumo-qa registered via Codex plugin manager (sumo-qa@{marketplace} v{version})"),
        details={
            "marketplace": marketplace,
            "version": version,
            "cache_root": str(cache_root),
        },
    )


def check_claude_code_config(
    home: _Path | None = None,
    system: str | None = None,
) -> CheckResult:
    """Verify Claude Code's ``claude_desktop_config.json`` is present,
    readable, parseable JSON, and points at a resolvable binary.

    OK with "not detected" when neither ``~/.claude/`` nor the config dir
    exists — that machine isn't running Claude Code, so the check is
    informational, not a failure.

    Cross-references ``check_claude_code_plugin``: when the pip-install
    config has no ``sumo-qa`` entry but the user is registered via the
    plugin manager, soften the FAIL to OK with a disclosure. Plugin-install
    users have a valid setup — the pip-install config is intentionally
    empty for them.
    """
    h = home or _Path.home()
    sys_name = system or _platform.system()
    config_path = _claude_code_config_path(h, sys_name)
    claude_home = h / ".claude"

    def _soften_if_plugin_installed() -> CheckResult | None:
        plugin_check = check_claude_code_plugin(home=h)
        if plugin_check.status == "OK" and "registered via" in plugin_check.summary:
            return CheckResult(
                check_id="claude_code_config",
                status="OK",
                summary=(
                    f"{config_path} has no `sumo-qa` entry — sumo-qa is "
                    "registered via Claude Code's plugin manager instead "
                    "(see claude_code_plugin check)"
                ),
                details={
                    "config_path": str(config_path),
                    "registered_via": "plugin_manager",
                },
            )
        return None

    return _check_host_config(
        check_id="claude_code_config",
        config_path=config_path,
        not_installed_summary="Claude Code not detected on this machine",
        not_installed_predicate=not (claude_home.exists() or config_path.parent.exists()),
        install_flag="--claude-code",
        config_schema_key="mcpServers",
        on_missing_entry=_soften_if_plugin_installed,
    )


def check_claude_desktop_config(
    home: _Path | None = None,
    system: str | None = None,
) -> CheckResult:
    """Verify Claude Desktop's config (separate path from Claude Code on
    macOS) is present, parseable, and resolvable.
    """
    h = home or _Path.home()
    sys_name = system or _platform.system()
    config_path = _installer._claude_desktop_config_path(h, sys_name)
    return _check_host_config(
        check_id="claude_desktop_config",
        config_path=config_path,
        not_installed_summary="Claude Desktop not detected on this machine",
        not_installed_predicate=not config_path.parent.exists(),
        install_flag="--claude-desktop",
        config_schema_key="mcpServers",
    )


def check_vscode_workspace_config(workspace: _Path) -> CheckResult:
    """Verify ``<workspace>/.vscode/mcp.json`` is present, parseable, and
    its sumo-qa entry points at a resolvable binary.

    VS Code's MCP config schema differs from Claude's — the top-level key
    is ``servers`` (not ``mcpServers``) and each entry includes a ``type``
    field. We tolerate either shape on read; ``servers`` wins when both
    are present so the canonical VS Code-native layout is preferred.
    """
    config_path = workspace / ".vscode" / "mcp.json"
    # Shell-quote the workspace path so the printed Fix command stays
    # copy-pasteable when the workspace contains spaces or shell metachars
    # (e.g. "/Users/me/My Project"). Without this, the shell splits on the
    # space and argparse rejects the trailing tokens.
    install_flag = f"--vscode --workspace {shlex.quote(str(workspace))}"
    if not config_path.exists():
        return CheckResult(
            check_id="vscode_workspace_config",
            status="FAIL",
            summary=f"{config_path} missing — VS Code workspace not initialised",
            fix=f"Run `sumo-qa-install {install_flag}` to write the config.",
        )
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        return CheckResult(
            check_id="vscode_workspace_config",
            status="FAIL",
            summary=(
                f"{config_path} unreadable (permission/OS error: {exc.__class__.__name__}: {exc})"
            ),
            fix=f"Fix the permissions on {config_path}.",
        )
    try:
        config = json.loads(text)
    except json.JSONDecodeError as exc:
        return CheckResult(
            check_id="vscode_workspace_config",
            status="FAIL",
            summary=(f"{config_path} is not valid JSON ({exc.msg} at line {exc.lineno})"),
            fix=(f"Re-run `sumo-qa-install {install_flag}` to overwrite the corrupt config."),
        )
    entry = (config.get("servers") or config.get("mcpServers") or {}).get("sumo-qa")
    if entry is None or not isinstance(entry, dict):
        return CheckResult(
            check_id="vscode_workspace_config",
            status="FAIL",
            summary=f"{config_path} has no `sumo-qa` entry under `servers`",
            fix=f"Run `sumo-qa-install {install_flag}` to register the server.",
        )
    if not _server_entry_resolves(entry):
        return CheckResult(
            check_id="vscode_workspace_config",
            status="FAIL",
            summary=(
                f"{config_path} points at a binary that does not resolve "
                f"({entry.get('command')!r}) — stale config"
            ),
            fix=f"Run `sumo-qa-install {install_flag}` to refresh the binary path.",
        )
    return CheckResult(
        check_id="vscode_workspace_config",
        status="OK",
        summary=f"{config_path} registers sumo-qa at {entry.get('command')}",
        details={"config_path": str(config_path), "command": entry.get("command")},
    )


def check_vscode_user_misleading(
    home: _Path | None = None,
    workspace: _Path | None = None,
) -> CheckResult:
    """WARN when ``~/.vscode/mcp.json`` exists alongside a workspace-level
    config. VS Code does NOT read the user-level file — it looks like
    configuration but does nothing, which is a common support gotcha.
    """
    h = home or _Path.home()
    ws = workspace or _Path.cwd()
    user_cfg = h / ".vscode" / "mcp.json"
    if not user_cfg.exists():
        return CheckResult(
            check_id="vscode_user_misleading",
            status="OK",
            summary=(
                "no user-level ~/.vscode/mcp.json present — workspace-level is the right location"
            ),
        )
    return CheckResult(
        check_id="vscode_user_misleading",
        status="WARN",
        summary=(
            f"{user_cfg} exists but VS Code only reads .vscode/mcp.json from a "
            "workspace root — that user-level file is dead config"
        ),
        # Shell-quote both paths so spaces in $HOME or workspace don't break
        # the copy-paste flow (same fix as vscode_workspace_config above).
        fix=(
            f"Delete {shlex.quote(str(user_cfg))} and run `sumo-qa-install "
            f"--vscode --workspace {shlex.quote(str(ws))}` from inside your "
            "project — the workspace-level config is the one VS Code uses."
        ),
        details={"user_config": str(user_cfg), "workspace": str(ws)},
    )


def check_jetbrains_detection(
    home: _Path | None = None,
    system: str | None = None,
) -> CheckResult:
    """Report whether any supported JetBrains IDE is installed.

    The plugin requires manual UI-add (see ``installer._setup_intellij``
    history note) so this check is always ``OK`` — informational. When a
    JetBrains IDE is detected, the ``fix`` carries the exact Settings-UI
    steps the user should follow.
    """
    h = home or _Path.home()
    sys_name = system or _platform.system()
    if sys_name == "Darwin":
        jb_root = h / "Library" / "Application Support" / "JetBrains"
    elif sys_name == "Windows":  # pragma: no cover -- platform-conditional
        jb_root = _Path(os.environ.get("APPDATA", "")) / "JetBrains"
    else:
        jb_root = h / ".config" / "JetBrains"
    if not jb_root.exists():
        return CheckResult(
            check_id="jetbrains_detection",
            status="OK",
            summary="JetBrains IDE not detected on this machine",
        )
    ide_dirs = [
        p
        for p in jb_root.iterdir()
        if p.is_dir()
        and any(p.name.startswith(prefix) for prefix in _installer._JB_IDE_PREFIXES)
        and (p / "options").exists()
    ]
    if not ide_dirs:
        return CheckResult(
            check_id="jetbrains_detection",
            status="OK",
            summary=(f"JetBrains config root {jb_root} found but no supported IDE installation"),
        )
    names = sorted(p.name for p in ide_dirs)
    return CheckResult(
        check_id="jetbrains_detection",
        status="OK",
        summary=(f"detected JetBrains IDE(s): {', '.join(names)} — manual MCP setup required"),
        fix=(
            "Open Settings -> Tools -> AI Assistant -> Model Context Protocol, "
            "click + Add server, Name: sumo-qa, Command: <sumo-qa binary>, "
            "Arguments: leave empty."
        ),
        details={"detected": names, "jetbrains_root": str(jb_root)},
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


# Stable host names exposed via ``--host``. Kept narrow on purpose: doctor's
# job is to validate what the installer would write to, not advertise every
# imaginable MCP-capable surface.
_HOST_CHOICES: tuple[str, ...] = (
    "claude-code",
    "claude-desktop",
    "codex",
    "vscode",
    "jetbrains",
)


def _resolve_mcp_command() -> McpCommand:
    """Mirror ``installer._install_mcp_binary``'s resolution without printing.

    The installer prints its choice (good UX during install); doctor never
    prints from the resolver — every line of output goes through the
    renderer, so callers can swap human / JSON without re-coupling.
    """
    existing = shutil.which("sumo-qa")
    if existing is not None:
        return McpCommand(command=str(_Path(existing).resolve()), args=[])
    return McpCommand(command=_sys.executable, args=["-m", "sumo_qa"])


def _collect_checks(
    *,
    workspace: _Path,
    host_filter: str | None,
) -> list[CheckResult]:
    """Run every check (or just the host-filtered subset) in a fixed order.

    Environment → install mode → binary → MCP handshake → tools/list →
    per-host configs. The ordering matches the user's mental model: "is my
    environment OK?" before "is my host registered?".
    """
    out: list[CheckResult] = [
        check_python_version(),
        check_install_mode(),
        check_binary_discoverable(),
    ]
    handshake, tools = run_mcp_probe(_resolve_mcp_command())
    out.extend([handshake, tools])
    if host_filter in (None, "claude-code"):
        out.append(check_claude_code_config())
        out.append(check_claude_code_plugin())
    if host_filter in (None, "claude-desktop"):
        out.append(check_claude_desktop_config())
    if host_filter in (None, "codex"):
        out.append(check_codex_plugin())
    if host_filter in (None, "vscode"):
        out.append(check_vscode_workspace_config(workspace=workspace))
        out.append(check_vscode_user_misleading(workspace=workspace))
    if host_filter in (None, "jetbrains"):
        out.append(check_jetbrains_detection())
    return out


# ANSI escape sequences for colorised status tags. Kept module-level so the
# renderer is a pure function of (results, use_color) — no globals captured
# at call time, no env-var reads from inside the formatter.
_ANSI_RESET = "\x1b[0m"
_ANSI_BY_STATUS: dict[str, str] = {
    "OK": "\x1b[32m",  # green
    "WARN": "\x1b[33m",  # yellow
    "FAIL": "\x1b[31m",  # red
}


def _stdout_is_tty() -> bool:
    """Return True when stdout is connected to a real terminal. Wrapped so
    tests can override the answer without monkeypatching ``sys.stdout``.
    """
    return _sys.stdout.isatty()


def _should_use_color() -> bool:
    """Decide whether to emit ANSI color codes.

    Honours the de-facto NO_COLOR standard (https://no-color.org/) — any
    non-empty value disables color. Otherwise gates on whether stdout is
    a TTY so piped / redirected output stays escape-code-free.
    """
    if os.environ.get("NO_COLOR"):
        return False
    return _stdout_is_tty()


def _render_human(results: list[CheckResult], *, use_color: bool = False) -> str:
    """Render results as a plain-text report.

    One line per check, followed by an indented ``Fix:`` line where one is
    set. Trailing summary line carries the OK / WARN / FAIL counts so a
    fast scroll-to-bottom is enough to see overall health.

    When ``use_color`` is True, the status tag is wrapped in an ANSI
    color code (green/yellow/red). When False, plain ``[OK]`` / ``[WARN]``
    / ``[FAIL]`` text is used — safe for log files, CI captures, and
    consumers piping stdout to another program.
    """
    lines: list[str] = []
    counts = {"OK": 0, "WARN": 0, "FAIL": 0}
    for r in results:
        counts[r.status] += 1
        if use_color:
            tag = f"{_ANSI_BY_STATUS[r.status]}[{r.status}]{_ANSI_RESET}"
        else:
            tag = f"[{r.status}]"
        lines.append(f"{tag} {r.check_id} — {r.summary}")
        if r.fix:
            lines.append(f"      Fix: {r.fix}")
    lines.append("")
    lines.append(f"Summary: {counts['OK']} OK, {counts['WARN']} WARN, {counts['FAIL']} FAIL")
    return "\n".join(lines) + "\n"


def _render_json(results: list[CheckResult]) -> str:
    """Render results as a JSON document.

    Schema is internal until sumo-qa 1.0 — ``schema_version`` is "0" so
    downstream integrations can detect a future stable contract. Don't
    treat the absence of a stable contract as a contract.
    """
    counts = {"OK": 0, "WARN": 0, "FAIL": 0}
    serialised: list[dict] = []
    for r in results:
        counts[r.status] += 1
        serialised.append(
            {
                "check_id": r.check_id,
                "status": r.status,
                "summary": r.summary,
                "fix": r.fix,
                "details": r.details,
            }
        )
    payload = {
        "schema_version": "0",  # internal — subject to change before sumo-qa 1.0
        "summary": {
            "ok": counts["OK"],
            "warn": counts["WARN"],
            "fail": counts["FAIL"],
        },
        "checks": serialised,
    }
    return json.dumps(payload, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``sumo-qa-doctor`` and ``python -m sumo_qa.doctor``.

    Exit code: 1 when any check reports ``FAIL``; 0 otherwise. ``WARN``
    does not fail the run — WARN is informational ("you have dead config
    sitting around"); FAIL is the actionable severity ("install is broken").
    """
    parser = argparse.ArgumentParser(
        prog="sumo-qa-doctor",
        description=(
            "Run read-only diagnostics on the local sumo-qa install. Reports "
            "the state of every check and prints exact fix commands for "
            "failures. Never writes to disk."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit JSON instead of human-readable output. The schema is internal until sumo-qa 1.0."
        ),
    )
    parser.add_argument(
        "--host",
        choices=_HOST_CHOICES,
        default=None,
        help="Limit host-specific checks to a single host.",
    )
    parser.add_argument(
        "--workspace",
        type=_Path,
        default=None,
        help=(
            "Workspace root for VS Code's .vscode/mcp.json check. Defaults "
            "to the current directory."
        ),
    )
    args = parser.parse_args(argv)

    workspace = args.workspace.resolve() if args.workspace else _Path.cwd().resolve()
    results = _collect_checks(workspace=workspace, host_filter=args.host)

    if args.json:
        rendered = _render_json(results)
    else:
        rendered = _render_human(results, use_color=_should_use_color())
    _sys.stdout.write(rendered)

    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":  # pragma: no cover -- main guard for `python -m sumo_qa.doctor`
    _sys.exit(main())
