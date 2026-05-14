# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Smoke tests for the SessionStart hook.

The hook ships in `hooks/session-start` and is registered by
`hooks/hooks.json` (Claude Code) and `hooks/hooks-cursor.json` (Cursor).
Its job: read `skills/using-sumo-qa/SKILL.md` and emit a host-appropriate
JSON envelope so the agent reliably loads the QA workflow router on every
conversation start.

These tests don't exercise the host runtime — they verify that the script
itself produces well-formed JSON containing the skill body, and that the
plugin/hook manifests reference the right paths.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = ROOT / "hooks" / "session-start"
USING_SKILL = ROOT / "skills" / "using-sumo-qa" / "SKILL.md"


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="Bash hook test not applicable on Windows (the hook is for macOS/Linux plugin runtimes; the `bash` on Windows runners is the WSL stub, not Git Bash)",
)
def test_session_start_emits_valid_json_with_skill_content() -> None:
    """Default (no host env vars) → SDK-standard `additionalContext` envelope.

    The agent's first turn relies on the hook embedding the full
    using-sumo-qa skill body — without it the Iron Law enforcement is gone.
    """
    result = subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        capture_output=True,
        text=True,
        env={
            k: v
            for k, v in os.environ.items()
            if k not in {"CLAUDE_PLUGIN_ROOT", "CURSOR_PLUGIN_ROOT", "COPILOT_CLI"}
        },
        timeout=10,
    )

    assert result.returncode == 0, f"hook exited non-zero: {result.stderr}"
    payload = json.loads(result.stdout)
    assert "additionalContext" in payload
    context = payload["additionalContext"]
    # The Iron Law must be present — that's the whole reason for the hook.
    assert "NO QA WORK WITHOUT FIRST DECIDING THE APPROACH" in context
    # And the EXTREMELY_IMPORTANT wrapper that makes the agent take it seriously.
    assert "<EXTREMELY_IMPORTANT>" in context


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="Bash hook test not applicable on Windows (the hook is for macOS/Linux plugin runtimes; the `bash` on Windows runners is the WSL stub, not Git Bash)",
)
def test_session_start_uses_claude_code_envelope_when_plugin_root_set() -> None:
    """Claude Code sets `CLAUDE_PLUGIN_ROOT` → nested `hookSpecificOutput`."""
    env = {k: v for k, v in os.environ.items() if k not in {"CURSOR_PLUGIN_ROOT", "COPILOT_CLI"}}
    env["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
    result = subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, f"hook exited non-zero: {result.stderr}"
    payload = json.loads(result.stdout)
    assert "hookSpecificOutput" in payload
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert (
        "NO QA WORK WITHOUT FIRST DECIDING THE APPROACH"
        in payload["hookSpecificOutput"]["additionalContext"]
    )


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="Bash hook test not applicable on Windows (the hook is for macOS/Linux plugin runtimes; the `bash` on Windows runners is the WSL stub, not Git Bash)",
)
def test_session_start_uses_cursor_envelope_when_cursor_root_set() -> None:
    """Cursor sets `CURSOR_PLUGIN_ROOT` → snake_case `additional_context`."""
    env = {k: v for k, v in os.environ.items() if k not in {"COPILOT_CLI"}}
    env["CURSOR_PLUGIN_ROOT"] = str(ROOT)
    result = subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, f"hook exited non-zero: {result.stderr}"
    payload = json.loads(result.stdout)
    assert "additional_context" in payload
    assert "NO QA WORK WITHOUT FIRST DECIDING THE APPROACH" in payload["additional_context"]


def test_using_sumo_qa_skill_file_exists() -> None:
    """The hook reads this file — if it moves, the hook silently emits an
    error string. Keep the path pinned."""
    assert USING_SKILL.exists(), f"Hook depends on {USING_SKILL} existing"


def test_plugin_manifests_are_valid_json() -> None:
    """All 4 host plugin manifests must be parseable JSON with a `name`."""
    manifests = [
        ROOT / ".claude-plugin" / "plugin.json",
        ROOT / ".claude-plugin" / "marketplace.json",
        ROOT / ".cursor-plugin" / "plugin.json",
        ROOT / ".codex-plugin" / "plugin.json",
    ]
    for manifest_path in manifests:
        assert manifest_path.exists(), f"missing manifest: {manifest_path}"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "name" in data, f"manifest missing `name`: {manifest_path}"


def test_hook_registrations_reference_existing_script() -> None:
    """`hooks/hooks.json` and `hooks/hooks-cursor.json` both register the
    SessionStart hook — verify the run-hook.cmd wrapper they point at exists
    and is executable."""
    run_hook_wrapper = ROOT / "hooks" / "run-hook.cmd"
    assert run_hook_wrapper.exists()
    assert os.access(run_hook_wrapper, os.X_OK), "run-hook.cmd must be executable"
    assert os.access(HOOK_SCRIPT, os.X_OK), "hooks/session-start must be executable"
