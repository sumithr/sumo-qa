# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Smoke tests for the SessionStart hook.

The hook ships in `hooks/session-start` and is registered by
`hooks/hooks.json` (Claude Code) and `hooks/hooks-codex.json` (Codex).
Its job: emit a host-appropriate JSON envelope carrying the compact
bootstrap (`hooks/compact-bootstrap.md`, the first-hop rule and a pointer
to the `using_sumo_qa` router) so a QA-shaped request reliably enters
sumo-qa, while a non-QA session never pays for the full router body.
The full `skills/using-sumo-qa/SKILL.md` body is the fallback: injected
when the MCP server cannot launch (no `uvx`) or `SUMO_QA_BOOTSTRAP=full`.

These tests don't exercise the host runtime — they verify that the script
itself produces well-formed JSON containing the skill body, and that the
plugin/hook manifests reference the right paths.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


def _repo_root() -> Path:
    """Walk up from this file until we find the .git ancestor.

    Robust to mutmut's layout: when the mutation gate runs, mutmut copies
    ``tests/`` into ``mutants/tests/`` but does NOT copy ``hooks/`` or
    ``skills/`` (only files under mutation + their tests). A naive
    ``parents[1]`` resolves to ``mutants/`` inside that copy and the hook
    / skill lookups under it fail. Anchoring on ``.git`` always finds the
    real repo root regardless of layout.
    """
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"no .git ancestor of {here!s}")


ROOT = _repo_root()
HOOK_SCRIPT = ROOT / "hooks" / "session-start"
USING_SKILL = ROOT / "skills" / "using-sumo-qa" / "SKILL.md"
COMPACT_BOOTSTRAP = ROOT / "hooks" / "compact-bootstrap.md"
# Present only in the full router body, never in the compact bootstrap.
FULL_BODY_MARKER = "NO QA WORK WITHOUT FIRST DECIDING THE APPROACH"
BOOTSTRAP_TOKEN_BUDGET = 1000


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="Bash hook test not applicable on Windows (the hook is for macOS/Linux plugin runtimes; the `bash` on Windows runners is the WSL stub, not Git Bash)",
)
def test_session_start_emits_valid_json_with_skill_content() -> None:
    """Default (no host env vars) → SDK-standard `additionalContext` envelope.

    The agent's first turn relies on the hook embedding the full
    using-sumo-qa skill body — without it the Iron Law enforcement is gone.
    """
    payload = _run_hook({})
    assert "additionalContext" in payload
    context = payload["additionalContext"]
    # The first-hop pointer must be present: that's the whole reason for the hook.
    assert "using_sumo_qa" in context
    # And the EXTREMELY_IMPORTANT wrapper that makes the agent take it seriously.
    assert "<EXTREMELY_IMPORTANT>" in context


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="Bash hook test not applicable on Windows (the hook is for macOS/Linux plugin runtimes; the `bash` on Windows runners is the WSL stub, not Git Bash)",
)
def test_session_start_uses_claude_code_envelope_when_plugin_root_set() -> None:
    """Claude Code sets `CLAUDE_PLUGIN_ROOT` → nested `hookSpecificOutput`."""
    payload = _run_hook({"CLAUDE_PLUGIN_ROOT": str(ROOT)})
    assert set(payload) == {"hookSpecificOutput"}
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "using_sumo_qa" in payload["hookSpecificOutput"]["additionalContext"]


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="Bash hook test not applicable on Windows (the hook is for macOS/Linux plugin runtimes; the `bash` on Windows runners is the WSL stub, not Git Bash)",
)
def test_session_start_uses_cursor_envelope_when_cursor_root_set() -> None:
    """Cursor sets `CURSOR_PLUGIN_ROOT` → snake_case `additional_context`."""
    payload = _run_hook({"CURSOR_PLUGIN_ROOT": str(ROOT)})
    assert set(payload) == {"additional_context"}
    assert "using_sumo_qa" in payload["additional_context"]


def test_using_sumo_qa_skill_file_exists() -> None:
    """The hook reads this file — if it moves, the hook silently emits an
    error string. Keep the path pinned."""
    assert USING_SKILL.exists(), f"Hook depends on {USING_SKILL} existing"


def test_hook_registrations_reference_existing_script() -> None:
    """`hooks/hooks.json` and `hooks/hooks-cursor.json` both register the
    SessionStart hook — verify the run-hook.cmd wrapper they point at exists
    and is executable."""
    run_hook_wrapper = ROOT / "hooks" / "run-hook.cmd"
    assert run_hook_wrapper.exists()
    assert os.access(run_hook_wrapper, os.X_OK), "run-hook.cmd must be executable"
    assert os.access(HOOK_SCRIPT, os.X_OK), "hooks/session-start must be executable"


# ---------------------------------------------------------------------------
# uvx-detection tests (Task 3 — uv-prereq hardening)
# ---------------------------------------------------------------------------


def _run_hook(extra_env: dict[str, str], uvx_present: bool = True) -> dict:
    """Invoke the hook with a clean env plus *extra_env*, and a doctored PATH
    controlling uvx visibility (the compact-vs-full capability signal)."""
    with tempfile.TemporaryDirectory() as bindir:
        env = {"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin", **extra_env}
        if uvx_present:
            stub = pathlib.Path(bindir) / "uvx"
            stub.write_text("#!/bin/sh\necho 0.5.0\n")
            stub.chmod(0o755)
            env["PATH"] = f"{bindir}:/usr/bin:/bin"
        proc = subprocess.run(
            ["bash", str(HOOK_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)


def _run_hook_with_env(uvx_present: bool) -> dict:
    return _run_hook({"CLAUDE_PLUGIN_ROOT": str(ROOT)}, uvx_present=uvx_present)


def _extract_additional_context(payload: dict) -> str:
    """Pull out the additionalContext string regardless of host wrapper."""
    if "hookSpecificOutput" in payload:
        return payload["hookSpecificOutput"]["additionalContext"]
    if "additional_context" in payload:
        return payload["additional_context"]
    return payload["additionalContext"]


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="Bash hook test not applicable on Windows",
)
def test_session_start_no_warning_when_uvx_present():
    ctx = _extract_additional_context(_run_hook_with_env(uvx_present=True))
    assert "UVX_WARNING" not in ctx
    assert "using_sumo_qa" in ctx


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="Bash hook test not applicable on Windows",
)
def test_session_start_warns_when_uvx_missing():
    ctx = _extract_additional_context(_run_hook_with_env(uvx_present=False))
    assert "UVX_WARNING" in ctx
    assert "astral.sh/uv/install.sh" in ctx
    assert "using-sumo-qa" in ctx  # skill still injected — both signals delivered


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="Bash hook test not applicable on Windows",
)
def test_session_start_warning_appears_before_skill_in_context():
    """Order matters — the warning should be at the start of additionalContext
    so Claude reads the high-priority signal first."""
    ctx = _extract_additional_context(_run_hook_with_env(uvx_present=False))
    warning_idx = ctx.find("UVX_WARNING")
    skill_idx = ctx.find("using-sumo-qa")
    assert warning_idx < skill_idx


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="Bash hook test not applicable on Windows",
)
def test_session_start_emits_user_visible_systemMessage_when_uvx_missing():
    """`additionalContext` is silent context for the LLM; `systemMessage` is
    what Claude Code surfaces to the user in the chat UI. The uvx-missing
    warning must appear in BOTH so the user sees it immediately AND the LLM
    has the install commands in context if asked."""
    payload = _run_hook_with_env(uvx_present=False)
    assert "systemMessage" in payload, (
        "Hook must emit a top-level `systemMessage` when uvx is missing "
        "so Claude Code displays a visible warning to the user; "
        "`additionalContext` alone is silent and the user never sees it."
    )
    msg = payload["systemMessage"]
    assert "uvx" in msg.lower() or "uv" in msg.lower()
    assert "astral.sh/uv/install.sh" in msg or "brew install uv" in msg


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="Bash hook test not applicable on Windows",
)
def test_session_start_no_systemMessage_when_uvx_present():
    """`systemMessage` is for the uvx-missing failure mode only. When uvx is
    on PATH, the hook must not emit a visible warning."""
    payload = _run_hook_with_env(uvx_present=True)
    assert "systemMessage" not in payload, (
        "systemMessage is for the uvx-missing failure mode only; "
        "emitting it on every healthy session would be noise."
    )


_BASH = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="Bash hook test not applicable on Windows",
)


def _approx_tokens(text: str) -> int:
    return (len(text) + 3) // 4


@_BASH
@pytest.mark.parametrize(
    "host_env",
    [{}, {"CLAUDE_PLUGIN_ROOT": str(ROOT)}, {"CURSOR_PLUGIN_ROOT": str(ROOT)}],
    ids=["sdk-default", "claude-code", "cursor"],
)
def test_default_bootstrap_is_compact_and_omits_the_router_body(host_env):
    """A session where the MCP server can launch gets the compact bootstrap
    (within the bootstrap budget), never the full router body, so a non-QA
    session does not pay for QA rules it never uses."""
    ctx = _extract_additional_context(_run_hook(host_env))
    assert _approx_tokens(ctx) <= BOOTSTRAP_TOKEN_BUDGET
    assert FULL_BODY_MARKER not in ctx
    assert COMPACT_BOOTSTRAP.read_text(encoding="utf-8").strip()[:60] in ctx


@_BASH
def test_compact_bootstrap_carries_the_canonical_first_hop_rule():
    """The compact payload is an entry surface: it must state the same
    first-hop and clarify-after-routing rules as the server instructions."""
    from sumo_qa.first_hop import CLARIFY_AFTER_ROUTING, FIRST_HOP_RULE

    ctx = " ".join(_extract_additional_context(_run_hook({})).split())
    assert FIRST_HOP_RULE in ctx
    assert CLARIFY_AFTER_ROUTING in ctx


@_BASH
def test_full_bootstrap_override_injects_the_router_body():
    """`SUMO_QA_BOOTSTRAP=full` injects the full router body for a host whose
    model does not follow the compact pointer."""
    ctx = _extract_additional_context(_run_hook({"SUMO_QA_BOOTSTRAP": "full"}))
    assert FULL_BODY_MARKER in ctx


@_BASH
def test_missing_uvx_falls_back_to_the_full_router_body():
    """No uvx means no MCP server, so the compact pointer to the
    `using_sumo_qa` tool would dangle: the hook injects the full body."""
    ctx = _extract_additional_context(_run_hook_with_env(uvx_present=False))
    assert FULL_BODY_MARKER in ctx


@_BASH
def test_compact_override_wins_even_without_uvx():
    ctx = _extract_additional_context(
        _run_hook({"SUMO_QA_BOOTSTRAP": "compact"}, uvx_present=False)
    )
    assert FULL_BODY_MARKER not in ctx
    assert "UVX_WARNING" in ctx


@_BASH
@pytest.mark.parametrize(
    "host_env",
    [{}, {"CLAUDE_PLUGIN_ROOT": str(ROOT)}, {"CURSOR_PLUGIN_ROOT": str(ROOT)}],
    ids=["sdk-default", "claude-code", "cursor"],
)
@pytest.mark.parametrize("uvx_present", [True, False], ids=["uvx", "no-uvx"])
def test_unknown_bootstrap_value_is_reported_and_treated_as_auto(host_env, uvx_present):
    """An unrecognised SUMO_QA_BOOTSTRAP is named in a one-line diagnostic
    inside every host envelope (the JSON still parses) and auto-detection
    decides the payload, rather than a silent fallback."""
    env = {**host_env, "SUMO_QA_BOOTSTRAP": 'Compact"\\x'}
    ctx = _extract_additional_context(_run_hook(env, uvx_present=uvx_present))
    first_line = ctx.splitlines()[0]
    assert "SUMO_QA_BOOTSTRAP=Compact" in first_line
    assert "using auto" in first_line
    assert (FULL_BODY_MARKER in ctx) is not uvx_present


@_BASH
@pytest.mark.parametrize("value", ["auto", "compact", "full", ""])
def test_recognised_bootstrap_values_emit_no_diagnostic(value):
    ctx = _extract_additional_context(_run_hook({"SUMO_QA_BOOTSTRAP": value}))
    assert "SUMO_QA_BOOTSTRAP" not in ctx


@_BASH
def test_compact_bootstrap_names_the_fallback_when_the_router_tool_is_unavailable():
    """uvx on PATH does not prove the server starts (an offline first launch),
    so the compact payload names the Skill and the file as fallbacks."""
    ctx = _extract_additional_context(_run_hook({}))
    assert "`using-sumo-qa` Skill" in ctx
    assert "skills/using-sumo-qa/SKILL.md" in ctx


@_BASH
@pytest.mark.parametrize(
    "host_env",
    [{}, {"CLAUDE_PLUGIN_ROOT": "x"}, {"CURSOR_PLUGIN_ROOT": "x"}],
    ids=["sdk-default", "claude-code", "cursor"],
)
def test_compact_bootstrap_injects_the_absolute_router_path(tmp_path, host_env):
    """The file fallback names the router by absolute path, substituted into
    every host envelope as valid JSON even when the path needs escaping."""
    root = tmp_path / 'plug "in" \\ & co'
    (root / "skills" / "using-sumo-qa").mkdir(parents=True)
    shutil.copytree(ROOT / "hooks", root / "hooks")
    shutil.copy(USING_SKILL, root / "skills" / "using-sumo-qa" / "SKILL.md")
    with tempfile.TemporaryDirectory() as bindir:
        stub = pathlib.Path(bindir) / "uvx"
        stub.write_text("#!/bin/sh\necho 0.5.0\n")
        stub.chmod(0o755)
        env = {"HOME": os.environ["HOME"], "PATH": f"{bindir}:/usr/bin:/bin", **host_env}
        proc = subprocess.run(
            ["bash", str(root / "hooks" / "session-start")],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
    assert proc.returncode == 0, proc.stderr
    ctx = _extract_additional_context(json.loads(proc.stdout))
    assert f"{root.resolve()}/skills/using-sumo-qa/SKILL.md" in ctx
    assert "${PLUGIN_ROOT}" not in ctx
