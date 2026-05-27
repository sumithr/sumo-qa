# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for host-aware MCP command selection for Claude Desktop on macOS.

Closes issue #181: the installer must not write a Claude Desktop config
pointing at a source-checkout venv command (``.venv``/``venv``/``env``/
``.tox``/``.nox``) on macOS, because the Claude.app launch context cannot
read those venvs.

Three layers under test, mirroring the issue's acceptance criteria:

* The path-pattern predicate (``_is_unsafe_for_claude_desktop``) — boundary
  value analysis on the venv layouts vs. stable install locations.
* The Claude-Desktop-scoped command selector
  (``_select_safe_command_for_claude_desktop``) — decision tables across
  (only-unsafe, only-safe, both, neither) on Darwin and the non-Darwin
  pass-through.
* ``main()`` — refuses to mutate Claude Desktop config and returns non-zero
  when no safe command exists on Darwin.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sumo_qa import installer

# ---------------------------------------------------------------------------
# Predicate — boundary value analysis on path patterns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/Users/me/proj/.venv/bin/sumo-qa",
        "/Users/me/proj/venv/bin/sumo-qa",
        "/Users/me/proj/env/bin/sumo-qa",
        "/Users/me/proj/.tox/py313/bin/sumo-qa",
        "/Users/me/proj/.nox/test/bin/sumo-qa",
    ],
)
def test_predicate_flags_source_checkout_venv_on_darwin(path: str) -> None:
    """Source-checkout venv shapes are unsafe for Claude Desktop on Darwin."""
    assert installer._is_unsafe_for_claude_desktop(path, "Darwin") is True


@pytest.mark.parametrize(
    "path",
    [
        "/usr/local/bin/sumo-qa",
        "/opt/homebrew/bin/sumo-qa",
        "/Users/me/.pyenv/versions/3.13.13/bin/sumo-qa",
        "/Users/me/.local/bin/sumo-qa",
        "/Users/me/.local/pipx/venvs/sumo-qa/bin/sumo-qa",
    ],
)
def test_predicate_accepts_stable_install_locations_on_darwin(path: str) -> None:
    """User/global install locations (pyenv, pipx, brew, /usr/local) are safe."""
    assert installer._is_unsafe_for_claude_desktop(path, "Darwin") is False


@pytest.mark.parametrize("system", ["Linux", "Windows"])
def test_predicate_passthrough_off_darwin(system: str) -> None:
    """Predicate is macOS-scoped per the issue — non-Darwin always returns False."""
    assert installer._is_unsafe_for_claude_desktop("/proj/.venv/bin/sumo-qa", system) is False


def test_predicate_does_not_false_positive_on_substring_matches() -> None:
    """A directory name like ``environment`` or ``venvs`` (plural) is not a
    Python venv layout — the predicate must match directory segments, not
    substrings, otherwise legitimate paths get refused.
    """
    assert (
        installer._is_unsafe_for_claude_desktop("/Users/me/environment/bin/sumo-qa", "Darwin")
        is False
    )
    assert (
        installer._is_unsafe_for_claude_desktop(
            "/Users/me/.local/share/venvs/sumo-qa/bin/sumo-qa", "Darwin"
        )
        is False
    )


# ---------------------------------------------------------------------------
# Selection — decision table over (unsafe-present, safe-present, system)
# ---------------------------------------------------------------------------


def _make_path_with_sumo_qa(tmp_path: Path, subpath: str) -> Path:
    """Create a directory containing an executable ``sumo-qa`` and return it."""
    target_dir = tmp_path / subpath
    target_dir.mkdir(parents=True, exist_ok=True)
    binary = target_dir / "sumo-qa"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    return target_dir


def test_selector_prefers_safe_command_when_unsafe_is_first_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the .venv binary shadows a stable one, Claude Desktop must
    pick the stable one — the user has a working install, the installer
    just has to find it past the source checkout."""
    unsafe_dir = _make_path_with_sumo_qa(tmp_path, "repo/.venv/bin")
    safe_dir = _make_path_with_sumo_qa(tmp_path, ".pyenv/versions/3.13/bin")

    monkeypatch.setenv("PATH", f"{unsafe_dir}{':'}{safe_dir}")

    result = installer._select_safe_command_for_claude_desktop("Darwin")

    assert result is not None
    assert result.args == []
    assert result.command == str(safe_dir / "sumo-qa")


def test_selector_returns_none_when_only_unsafe_available_on_darwin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a source-checkout venv on PATH on Darwin → caller must refuse."""
    unsafe_dir = _make_path_with_sumo_qa(tmp_path, "repo/.venv/bin")
    monkeypatch.setenv("PATH", str(unsafe_dir))

    assert installer._select_safe_command_for_claude_desktop("Darwin") is None


def test_selector_returns_fast_path_when_first_match_already_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The common case: a global install is on PATH and works fine."""
    safe_dir = _make_path_with_sumo_qa(tmp_path, "homebrew/bin")
    monkeypatch.setenv("PATH", str(safe_dir))

    result = installer._select_safe_command_for_claude_desktop("Darwin")

    assert result is not None
    assert result.command == str(safe_dir / "sumo-qa")


def test_selector_accepts_unsafe_on_linux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The macOS Desktop privacy restriction does not apply on Linux —
    a source-checkout venv command is fine for Claude Desktop there."""
    unsafe_dir = _make_path_with_sumo_qa(tmp_path, "repo/.venv/bin")
    monkeypatch.setenv("PATH", str(unsafe_dir))

    result = installer._select_safe_command_for_claude_desktop("Linux")

    assert result is not None
    assert result.command == str(unsafe_dir / "sumo-qa")


def test_iter_skips_empty_path_segments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``PATH`` with an empty middle segment (``/foo::/bar``) must not
    cause ``Path('') / "sumo-qa"`` lookups — the iterator skips it."""
    safe_dir = _make_path_with_sumo_qa(tmp_path, "bin")
    monkeypatch.setenv("PATH", f"::{safe_dir}::")

    candidates = installer._iter_sumo_qa_on_path()

    assert candidates == [str(safe_dir / "sumo-qa")]


# ---------------------------------------------------------------------------
# main() — refuse to mutate Claude Desktop config and return non-zero
# ---------------------------------------------------------------------------


def test_main_refuses_to_mutate_claude_desktop_when_only_unsafe_on_darwin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When --claude-desktop is requested on Darwin and only a project-venv
    sumo-qa exists on PATH, main() must return non-zero, print the safer
    install options, leave any existing claude_desktop_config.json
    untouched, **and** not spawn the unsafe binary via the verify step.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(installer.platform, "system", lambda: "Darwin")

    # Pre-existing config with another server — the installer must not touch it.
    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "claude_desktop_config.json"
    pre_existing = {"mcpServers": {"obsidian": {"command": "/usr/local/bin/uvx"}}}
    config_path.write_text(json.dumps(pre_existing), encoding="utf-8")
    snapshot = config_path.read_text(encoding="utf-8")

    # PATH carries only the unsafe shape.
    unsafe_dir = _make_path_with_sumo_qa(tmp_path, "repo/.venv/bin")
    monkeypatch.setenv("PATH", str(unsafe_dir))

    # If the refusal path ever spawned the unsafe binary, the verify step
    # would call _verify_mcp_responds and we'd see it touched. A real
    # subprocess spawn from the test fixture's placeholder shell stub
    # would also slow the run, so guard both signals.
    verify_calls: list[object] = []
    monkeypatch.setattr(
        installer, "_verify_mcp_responds", lambda cmd: verify_calls.append(cmd) or True
    )

    with patch.object(installer.sys, "argv", ["sumo-qa-install", "--claude-desktop"]):
        rc = installer.main()

    assert rc != 0, "main() must signal failure when no safe command is available"
    assert config_path.read_text(encoding="utf-8") == snapshot, (
        "claude_desktop_config.json must not be mutated on the refusal path"
    )
    assert verify_calls == [], "refusal path must not spawn the unsafe binary via the verify step"
    captured = capsys.readouterr()
    err = captured.out + captured.err
    assert "claude desktop" in err.lower() or "claude_desktop" in err.lower()
    assert "venv" in err.lower(), "refusal message should name the unsafe condition"


def test_main_verifies_safe_command_when_unsafe_shadowed_it_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When PATH has an unsafe ``.venv`` binary first and a safe one
    later, Claude Desktop is wired to the safe one — and the post-install
    verify must probe THAT binary, not the unsafe ``shutil.which`` winner.
    Probing the unsafe one is a misleading "all good" signal: the user
    thinks the install was verified, but the binary they verified isn't
    the one Claude Desktop will launch.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(installer.platform, "system", lambda: "Darwin")

    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)

    unsafe_dir = _make_path_with_sumo_qa(tmp_path, "repo/.venv/bin")
    safe_dir = _make_path_with_sumo_qa(tmp_path, "homebrew/bin")
    # Unsafe first → shutil.which picks it as mcp_cmd; selector skips past
    # it to safe_dir for cd_cmd. Verify must follow cd_cmd, not mcp_cmd.
    monkeypatch.setenv("PATH", f"{unsafe_dir}{':'}{safe_dir}")

    captured: list[installer.McpCommand] = []
    monkeypatch.setattr(installer, "_verify_mcp_responds", lambda cmd: captured.append(cmd) or True)

    with patch.object(installer.sys, "argv", ["sumo-qa-install", "--claude-desktop"]):
        installer.main()

    assert len(captured) == 1, "verify must run exactly once on the success path"
    assert captured[0].command == str(safe_dir / "sumo-qa"), (
        "verify must probe the safe binary Claude Desktop will launch, "
        "not the unsafe one shutil.which picked first"
    )


def test_main_refusal_message_when_no_sumo_qa_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When NO ``sumo-qa`` exists on PATH at all (rather than just no safe
    one), the user needs a different next step — install one — not
    'reinstall from a different shell'. The refusal message must
    distinguish the two cases.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(installer.platform, "system", lambda: "Darwin")

    config_dir = home / "Library" / "Application Support" / "Claude"
    config_dir.mkdir(parents=True)

    # Empty PATH dir: no sumo-qa anywhere.
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setenv("PATH", str(empty_dir))

    # main() also calls _install_mcp_binary which would fall through to
    # the python -m sumo_qa module form. Stub the verify step so we don't
    # spawn it.
    monkeypatch.setattr(installer, "_verify_mcp_responds", lambda _cmd: True)

    with patch.object(installer.sys, "argv", ["sumo-qa-install", "--claude-desktop"]):
        rc = installer.main()

    assert rc != 0
    captured = capsys.readouterr()
    err = captured.out + captured.err
    assert "no sumo-qa installation" in err.lower(), (
        "no-candidates branch must say 'no sumo-qa installation' so the user "
        "knows to install one, not just reinstall from a different shell"
    )
