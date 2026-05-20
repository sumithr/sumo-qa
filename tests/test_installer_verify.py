# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for ``_verify_mcp_responds`` — JSON-RPC + tools/list verification.

These exercise the hardened verification step that replaces the legacy
``'"result"' in proc.stdout`` substring check. The new behaviour:

  1. Drives an ``initialize`` + ``notifications/initialized`` + ``tools/list``
     handshake against the spawned MCP — one message at a time, reading each
     response BEFORE sending the next. Critically, stdin stays open until
     both responses have arrived (closing it early signals EOF to FastMCP's
     async stdio transport and cancels the in-flight tools/list response —
     that was the ubuntu install-smoke flake's root cause).
  2. Parses each stdout line as JSON-RPC, defensively skipping non-JSON noise.
  3. Asserts the ``initialize`` response is well-formed (jsonrpc=2.0, id=1,
     dict result, no error envelope).
  4. Asserts every entry in ``REQUIRED_TOOL_NAMES`` appears in the
     ``tools/list`` response.

Production code stays untouched outside ``installer.py``. All
``subprocess.Popen`` calls are mocked with a ``_FakeProc`` that mirrors just
enough of the real interface (stdin.write/flush/close, stdout.readline,
stderr.read, poll, terminate, wait, kill).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from unittest.mock import patch

import pytest

from sumo_qa import installer


@pytest.fixture(autouse=True)
def _select_always_ready(monkeypatch):
    """Patch ``installer.select.select`` so the production POSIX-select branch
    in ``_read_json_rpc_response`` never actually touches our FakeStream's
    bogus file descriptor.

    The default is "stdout is always ready", which is what the test FakeProc
    models — data is always available because we pre-loaded the queue.
    Individual tests can override this fixture's effect by re-monkeypatching
    inside their own body (see ``test_verify_handles_timeout``)."""

    def _ready(rlist, wlist, xlist, timeout=None):  # noqa: ARG001
        return list(rlist), [], []

    monkeypatch.setattr(installer.select, "select", _ready)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _initialize_ok() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "sumo-qa", "version": "test"},
            "capabilities": {},
        },
    }


def _tools_list_response(tool_names: list[str], req_id: int = 2) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"tools": [{"name": n} for n in tool_names]},
    }


def _mcp_cmd() -> installer.McpCommand:
    return installer.McpCommand(command="/fake/sumo-qa", args=[])


class _FakeStream:
    """Minimal stand-in for a Popen pipe.

    Supports ``write`` / ``flush`` / ``close`` (no-op writes; we don't assert
    on stdin contents here — the request-by-request structure is verified
    via the order-of-reads in ``test_verify_sends_messages_one_at_a_time``).
    Supports ``readline`` returning one line at a time from a queue, then an
    empty string for EOF.
    """

    def __init__(self, lines: Iterable[str] | None = None) -> None:
        self._queue: list[str] = list(lines or [])
        self.writes: list[str] = []
        self.closed = False

    def write(self, data: str) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def readline(self) -> str:
        if not self._queue:
            return ""
        return self._queue.pop(0)

    def read(self, _size: int = -1) -> str:
        rest = "".join(self._queue)
        self._queue.clear()
        return rest

    def fileno(self) -> int:
        # The production code uses ``select.select(..., proc.stdout, ...)`` on
        # POSIX. Test cases patch ``select.select`` so this number is never
        # actually dereferenced — but ``hasattr(stdout, 'fileno')`` AND a
        # successful ``fileno()`` call gate which branch the verifier takes.
        # Returning a constant dummy descriptor keeps the test on the
        # production select-branch (the one ubuntu install-smoke exercises).
        return -1


class _FakeProc:
    """Stand-in for ``subprocess.Popen`` used by ``_verify_mcp_responds``.

    Models stdin (write-only), stdout (line iterator), stderr (read-only),
    plus the lifecycle methods the production code touches: ``poll``,
    ``terminate``, ``wait``, ``kill``.
    """

    def __init__(
        self,
        stdout_lines: Iterable[str] | None = None,
        stderr_text: str = "",
        *,
        exited: bool = False,
    ) -> None:
        self.stdin = _FakeStream()
        self.stdout = _FakeStream(stdout_lines)
        self.stderr = _FakeStream([stderr_text] if stderr_text else [])
        self.returncode: int | None = 0 if exited else None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        # Once stdout is drained, behave as if the process has exited.
        if not self.stdout._queue:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode


def _lines(*objs: dict) -> list[str]:
    """Build a list of newline-terminated JSON-RPC lines for FakeProc stdout."""
    return [json.dumps(o) + "\n" for o in objs]


def _full_handshake_proc(extra_tools: list[str] | None = None) -> _FakeProc:
    """Build a FakeProc that returns the canonical happy-path handshake."""
    extras = list(installer.REQUIRED_TOOL_NAMES) + (extra_tools or [])
    return _FakeProc(_lines(_initialize_ok(), _tools_list_response(extras)))


# Patch target for the Popen swap. Centralising the path keeps every test
# pointing at the same indirection so renames stay shallow.
_POPEN_TARGET = "sumo_qa.installer.subprocess.Popen"


# ---------------------------------------------------------------------------
# REQUIRED_TOOL_NAMES constant
# ---------------------------------------------------------------------------


def test_required_tool_names_constant_is_defined() -> None:
    """The constant exists and lists the 14 canonical sumo-qa tools."""
    assert hasattr(installer, "REQUIRED_TOOL_NAMES")
    assert isinstance(installer.REQUIRED_TOOL_NAMES, tuple)
    # 4 test-data + 6 knowledge loaders + 4 external skills = 14.
    assert len(installer.REQUIRED_TOOL_NAMES) == 14
    assert "sumo_qa_explain_test_data_requirements" in installer.REQUIRED_TOOL_NAMES
    assert "sumo_qa_load_classifications" in installer.REQUIRED_TOOL_NAMES
    assert "sumo_qa_install_external_skill" in installer.REQUIRED_TOOL_NAMES


def test_verify_timeout_constant_matches_legacy() -> None:
    """The new ``_VERIFY_TIMEOUT_SECONDS`` constant pins the same 10s budget
    the legacy ``subprocess.run(timeout=10)`` used. If this is loosened the
    install-smoke window for failure detection widens accordingly — keep the
    value explicit and reviewable."""
    assert installer._VERIFY_TIMEOUT_SECONDS == 10


# ---------------------------------------------------------------------------
# _verify_mcp_responds — failure paths
# ---------------------------------------------------------------------------


def test_verify_rejects_initialize_with_error_key(capsys) -> None:
    """An ``initialize`` response carrying ``error`` is rejected even when the
    stdout still contains the substring ``"result"`` (catches the legacy
    substring-check behaviour — do not weaken this payload).
    """
    # ``result: null`` forces the bytes ``"result"`` into stdout, so the OLD
    # ``'"result"' in proc.stdout`` check would have falsely passed. The new
    # shape-aware code must still reject on the ``error`` envelope.
    init_err = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": None,
        "error": {"code": -32600, "message": "bad request"},
    }
    line = json.dumps(init_err) + "\n"
    assert '"result"' in line  # guard: legacy substring check would have passed
    proc = _FakeProc([line])
    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "error" in out.lower()


def test_verify_rejects_initialize_with_wrong_id(capsys) -> None:
    """No response carries ``id == 1`` — verification times out waiting."""
    # An id=99 line is consumed as "extra noise" by _read_json_rpc_response;
    # the reader keeps going until stdout EOFs, at which point it returns
    # None and the caller treats that as a missing-initialize-response.
    wrong_id = {"jsonrpc": "2.0", "id": 99, "result": {"capabilities": {}}}
    proc = _FakeProc(_lines(wrong_id))
    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    # The message must name the missing id.
    assert "id=1" in out or "initialize" in out.lower()


def test_verify_rejects_initialize_with_non_dict_result(capsys) -> None:
    """``result`` must be a dict; a string is rejected."""
    bad_shape = {"jsonrpc": "2.0", "id": 1, "result": "not-a-dict"}
    proc = _FakeProc(_lines(bad_shape))
    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "result" in out.lower()


def test_verify_rejects_tools_list_missing_required_tools(capsys) -> None:
    """``tools/list`` missing required tools fails with a list of missing names."""
    proc = _FakeProc(_lines(_initialize_ok(), _tools_list_response(["sumo_qa_find_test_data"])))
    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    # At least one missing tool must be named in the failure message.
    assert "sumo_qa_explain_test_data_requirements" in out


def test_verify_rejects_tools_list_with_wrong_id(capsys) -> None:
    """A ``tools/list`` response with no id=2 is rejected (no fallback)."""
    proc = _FakeProc(
        _lines(
            _initialize_ok(),
            _tools_list_response(list(installer.REQUIRED_TOOL_NAMES), req_id=42),
        )
    )
    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "id=2" in out or "tools/list" in out.lower()


def test_verify_rejects_initialize_with_wrong_jsonrpc_version(capsys) -> None:
    """``jsonrpc`` field must be exactly the string ``'2.0'``."""
    bad_ver = {"jsonrpc": "1.0", "id": 1, "result": {"capabilities": {}}}
    proc = _FakeProc(_lines(bad_ver))
    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "jsonrpc" in out.lower()


def test_verify_rejects_tools_list_with_error_envelope(capsys) -> None:
    """An ``error`` envelope on the tools/list response is rejected."""
    tools_err = {
        "jsonrpc": "2.0",
        "id": 2,
        "error": {"code": -32601, "message": "method not found"},
    }
    proc = _FakeProc(_lines(_initialize_ok(), tools_err))
    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "tools/list" in out.lower()
    assert "error" in out.lower()


def test_verify_rejects_tools_list_when_tools_is_not_a_list(capsys) -> None:
    """``result.tools`` must be a list; a dict is rejected with a clear message."""
    bad_tools = {"jsonrpc": "2.0", "id": 2, "result": {"tools": {"oops": "not-a-list"}}}
    proc = _FakeProc(_lines(_initialize_ok(), bad_tools))
    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "tools" in out.lower()


def test_verify_rejects_tools_list_non_dict_result(capsys) -> None:
    """``tools/list.result`` must be a dict containing ``tools``."""
    bad_tools = {"jsonrpc": "2.0", "id": 2, "result": "not-a-dict"}
    proc = _FakeProc(_lines(_initialize_ok(), bad_tools))
    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out


def test_verify_handles_deadline_exceeded_at_loop_top(capsys, monkeypatch) -> None:
    """If ``time.monotonic()`` ticks past the deadline between iterations, the
    next pass through the loop must raise ``_VerifyTimeout`` immediately —
    without burning another ``select.select`` call. Pins the early-bail arm
    at the top of ``_read_json_rpc_response``'s while-loop."""

    # First call: deadline = 0 + 10 = 10. Subsequent calls jump past it.
    times = iter([0.0, 1000.0, 1001.0])

    def fake_monotonic() -> float:
        return next(times)

    monkeypatch.setattr(installer.time, "monotonic", fake_monotonic)
    proc = _FakeProc()
    proc.poll = lambda: None  # type: ignore[assignment]
    # Stub select so even if execution reaches it (it shouldn't), the test
    # still terminates instead of hitting our dummy fileno.
    monkeypatch.setattr(installer.select, "select", lambda *_a, **_kw: ([], [], []))

    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "10s" in out or "timeout" in out.lower()


def test_verify_handles_timeout(capsys, monkeypatch) -> None:
    """When ``select`` reports no data AND ``poll()`` says the process is
    still alive, ``_read_json_rpc_response`` raises ``_VerifyTimeout`` and the
    verifier surfaces a "did not respond within Ns" warning.

    Pins the live-but-silent server arm — distinct from
    ``test_verify_handles_server_exited_with_no_response``, which exercises
    the "process exited cleanly with no output" arm a few lines up."""

    # Stdout that never produces an id=1 line.
    proc = _FakeProc()
    # Keep poll() returning None so the reader takes the timeout arm,
    # not the "process exited" arm.
    proc.poll = lambda: None  # type: ignore[assignment]

    # Stub select to report "no data ready" — the timeout path fires from
    # inside the select arm.
    monkeypatch.setattr(installer.select, "select", lambda *_args, **_kw: ([], [], []))

    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "10s" in out or "timeout" in out.lower()


def test_verify_handles_empty_stdout(capsys) -> None:
    """Empty stdout (server crashed silently) is treated as failure, and the
    stderr hint is surfaced for the user."""
    proc = _FakeProc([], stderr_text="boom")
    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    # _dump_proc_streams should have echoed the stderr hint for the user.
    assert "boom" in out


def test_verify_handles_malformed_json_line(capsys) -> None:
    """A non-JSON log line must not crash parsing; valid responses still apply."""
    proc = _FakeProc(
        [
            "this is not json at all\n",
            json.dumps(_initialize_ok()) + "\n",
            json.dumps(_tools_list_response(list(installer.REQUIRED_TOOL_NAMES))) + "\n",
        ]
    )
    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is True
    out = capsys.readouterr().out
    assert "all required tools present" in out


def test_verify_passes_on_full_handshake(capsys) -> None:
    """All required tools present (plus extras) => True; success line printed.

    Also verifies the Popen-based code wrote all three JSON-RPC messages to
    stdin in the right order and the right shape — request-by-request, not
    one big blob.
    """
    proc = _full_handshake_proc(extra_tools=["future_tool_added_later"])
    with patch(_POPEN_TARGET, return_value=proc) as popen:
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is True
    out = capsys.readouterr().out
    assert "MCP responded with" in out
    assert "all required tools present" in out

    # The spawned process was created with the McpCommand argv.
    popen_argv = popen.call_args.args[0]
    assert popen_argv == ["/fake/sumo-qa"]

    # All three messages were written to stdin, in order, one per write.
    writes = [w for w in proc.stdin.writes if w.strip()]
    assert len(writes) >= 3
    parsed = [json.loads(w.strip()) for w in writes]
    methods = [m.get("method") for m in parsed]
    assert methods.index("initialize") < methods.index("notifications/initialized")
    assert methods.index("notifications/initialized") < methods.index("tools/list")


def test_verify_sends_tools_list_only_after_reading_initialize(capsys) -> None:
    """The fix's core guarantee: tools/list isn't written to stdin until the
    initialize response has been read off stdout. Models the race that the
    legacy ``subprocess.run(input=...)`` lost on ubuntu — there, stdin was
    closed before the server flushed the tools/list response.

    We verify by observing that after we've drained the initialize line from
    stdout, the second write contains ``notifications/initialized`` and the
    third contains ``tools/list``."""
    proc = _full_handshake_proc()
    with patch(_POPEN_TARGET, return_value=proc):
        installer._verify_mcp_responds(_mcp_cmd())

    writes = [w.strip() for w in proc.stdin.writes if w.strip()]
    parsed = [json.loads(w) for w in writes]
    # First message must be initialize. (Cannot assert "initialize was read
    # before tools/list was written" without a deeper hook — this is the
    # observable shape that pins the ordering.)
    assert parsed[0].get("method") == "initialize"
    assert parsed[1].get("method") == "notifications/initialized"
    assert parsed[2].get("method") == "tools/list"


def test_verify_keeps_stdin_open_during_handshake(capsys) -> None:
    """While reading the initialize response, stdin must remain open — the
    rewrite's whole point. ``stdin.close()`` only happens in the finally
    block after both responses have been collected (or the timeout path
    has run)."""
    close_order: list[str] = []
    proc = _full_handshake_proc()

    real_close = proc.stdin.close

    def tracking_close() -> None:
        close_order.append("stdin")
        real_close()

    proc.stdin.close = tracking_close  # type: ignore[assignment]

    # Patch the FakeProc.stdout.readline so we can record when close was
    # called relative to reads.
    real_readline = proc.stdout.readline
    read_log: list[str] = []

    def tracking_readline() -> str:
        line = real_readline()
        # Record the close-state at the time the line came out.
        read_log.append("closed" if proc.stdin.closed else "open")
        return line

    proc.stdout.readline = tracking_readline  # type: ignore[assignment]

    with patch(_POPEN_TARGET, return_value=proc):
        assert installer._verify_mcp_responds(_mcp_cmd()) is True

    # During every successful read of an id-bearing response line, stdin
    # must still have been open. Close happens AFTER all I/O.
    assert read_log
    assert all(state == "open" for state in read_log), read_log
    assert close_order == ["stdin"]


def test_verify_terminates_process_after_handshake(capsys) -> None:
    """Once verification succeeds, the spawned process must be terminated —
    otherwise sumo-qa-install leaks a long-running MCP server."""
    proc = _full_handshake_proc()
    with patch(_POPEN_TARGET, return_value=proc):
        installer._verify_mcp_responds(_mcp_cmd())

    assert proc.terminated is True


def test_verify_terminates_process_on_failure(capsys) -> None:
    """On failure the process is still cleaned up — no orphan."""
    proc = _FakeProc(_lines({"jsonrpc": "2.0", "id": 1, "result": "not-a-dict"}))
    with patch(_POPEN_TARGET, return_value=proc):
        installer._verify_mcp_responds(_mcp_cmd())

    assert proc.terminated is True


def test_verify_handles_server_exited_with_no_response(capsys, monkeypatch) -> None:
    """If ``select`` reports no data AND ``poll()`` shows the process exited,
    the reader returns ``None`` so the caller can surface a "no initialize
    response" warning. This pins the 989-990 arm — process-died-before-reply,
    distinct from a true timeout."""
    proc = _FakeProc()

    # First select call: no data. poll() returns 0 (exited cleanly with no
    # output) so _read_json_rpc_response should return None.
    monkeypatch.setattr(installer.select, "select", lambda *_a, **_kw: ([], [], []))
    proc.poll = lambda: 0  # type: ignore[assignment]

    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out
    # The "no initialize response" branch must have fired.
    assert "initialize" in out.lower()


def test_verify_skips_blank_lines_between_responses(capsys) -> None:
    """Bare blank lines (`"\\n"`) between JSON-RPC responses are not EOF — the
    reader must continue scanning. Pins the `if not stripped: continue` arm."""
    proc = _FakeProc(
        [
            "\n",  # blank line — must NOT be treated as EOF
            json.dumps(_initialize_ok()) + "\n",
            "\n",  # another blank between responses
            json.dumps(_tools_list_response(list(installer.REQUIRED_TOOL_NAMES))) + "\n",
        ]
    )
    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is True


def test_verify_skips_non_dict_json_values_on_the_wire(capsys) -> None:
    """A line that parses to a JSON array or string (not an object) must be
    skipped as noise. Pins the `not isinstance(value, dict)` arm in
    ``_read_json_rpc_response``."""
    proc = _FakeProc(
        [
            "[1, 2, 3]\n",  # valid JSON, but not an object
            '"a-bare-string"\n',  # valid JSON, but not an object
            json.dumps(_initialize_ok()) + "\n",
            json.dumps(_tools_list_response(list(installer.REQUIRED_TOOL_NAMES))) + "\n",
        ]
    )
    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is True


def test_verify_dump_streams_when_stderr_select_reports_nothing(capsys, monkeypatch) -> None:
    """When ``select`` on stderr reports "no data ready", the diagnostics path
    must still complete without raising — covers the empty-stderr-select arm
    of ``_dump_proc_streams``."""
    proc = _FakeProc(_lines({"jsonrpc": "2.0", "id": 1, "result": "not-a-dict"}))

    call_count = {"n": 0}

    def select_first_ready_then_empty(rlist, _wlist, _xlist, _timeout=None):
        # First call (stdout read for id=1): say "ready" so the line is read.
        # Subsequent calls (stderr drain in _dump_proc_streams): say "no data".
        call_count["n"] += 1
        if call_count["n"] == 1:
            return list(rlist), [], []
        return [], [], []

    monkeypatch.setattr(installer.select, "select", select_first_ready_then_empty)

    with patch(_POPEN_TARGET, return_value=proc):
        result = installer._verify_mcp_responds(_mcp_cmd())

    assert result is False
    out = capsys.readouterr().out
    assert "WARNING" in out


# ---------------------------------------------------------------------------
# _parse_json_rpc_lines — direct unit tests (private helper, but worth pinning)
# ---------------------------------------------------------------------------


def test_parse_json_rpc_lines_skips_empty_and_malformed() -> None:
    """Empty strings and non-JSON noise are filtered; valid JSON is parsed."""
    stdout = (
        "\n"
        "log line that isn't JSON\n"
        + json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
        + "\n"
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": []}})
        + "\n"
    )
    parsed = installer._parse_json_rpc_lines(stdout)

    assert len(parsed) == 2
    assert parsed[0]["id"] == 1
    assert parsed[1]["id"] == 2


def test_parse_json_rpc_lines_skips_non_dict_json() -> None:
    """A bare JSON array or string at the line level is skipped — only objects count."""
    stdout = '"a-string"\n[1, 2, 3]\n{"jsonrpc": "2.0", "id": 1, "result": {}}\n'
    parsed = installer._parse_json_rpc_lines(stdout)

    assert len(parsed) == 1
    assert parsed[0]["id"] == 1


# ---------------------------------------------------------------------------
# Drift guard: REQUIRED_TOOL_NAMES vs the live MCP tool registry
# ---------------------------------------------------------------------------


def test_required_tool_names_matches_live_registry() -> None:
    """If someone adds an @mcp.tool to server.py, REQUIRED_TOOL_NAMES must
    be updated in lock-step. The verify-fn's subset check would silently
    accept a missing entry today — this test prevents that drift.

    Skill-prompt tools (registered dynamically via register_skills_as_prompts,
    one per skills/<name>/SKILL.md on disk) are excluded: they're filesystem-
    driven, so enumerating them in a static tuple would churn on every skill
    add. We compute the skill-prompt names from the same source the registrar
    walks, then subtract them before comparing against REQUIRED_TOOL_NAMES."""
    from sumo_qa import skill_prompts
    from sumo_qa.server import build_mcp_server

    mcp = build_mcp_server()
    live_tool_names = set(mcp._tool_manager._tools.keys())

    # Compute the dynamic skill-prompt tool names the same way the registrar
    # does (directory name with `-` -> `_`). Subtract to leave only the
    # static @mcp.tool decorators declared in server.py.
    skills_dir = skill_prompts._skills_dir()
    skill_tool_names = set()
    if skills_dir.is_dir():
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
                skill_tool_names.add(skill_dir.name.replace("-", "_"))

    static_tool_names = live_tool_names - skill_tool_names
    expected = set(installer.REQUIRED_TOOL_NAMES)
    missing_from_required = static_tool_names - expected
    extra_in_required = expected - static_tool_names

    assert missing_from_required == set(), (
        f"server.py registers tools not in REQUIRED_TOOL_NAMES: "
        f"{sorted(missing_from_required)}. Update installer.REQUIRED_TOOL_NAMES "
        f"(and the dispatch comment groups) when adding new @mcp.tool decorators."
    )
    assert extra_in_required == set(), (
        f"REQUIRED_TOOL_NAMES lists tools no longer registered in server.py: "
        f"{sorted(extra_in_required)}. Remove from the tuple."
    )
