# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from sumo_qa import installer

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr=b"")


def test_installer_module_help_is_path_independent() -> None:
    """`python -m sumo_qa.installer` must work when console scripts are not on PATH."""
    src_path = str(REPO_ROOT / "src")
    existing = os.environ.get("PYTHONPATH", "")
    pythonpath = f"{src_path}{os.pathsep}{existing}" if existing else src_path

    proc = subprocess.run(
        [sys.executable, "-m", "sumo_qa.installer", "--help"],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": pythonpath},
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert proc.returncode == 0
    assert "--claude-code" in proc.stdout
    assert "--vscode" in proc.stdout


# ---------------------------------------------------------------------------
# T6 — _install_mcp_binary path-detection tests
# ---------------------------------------------------------------------------


def test_fast_path_returns_resolved_binary_without_uv_call(capsys) -> None:
    """When sumo-qa is already on PATH the function returns immediately."""
    existing = "/usr/local/bin/sumo-qa"
    with (
        patch("sumo_qa.installer.shutil.which", return_value=existing),
        patch("sumo_qa.installer.subprocess.run") as run,
    ):
        result = installer._install_mcp_binary()

    assert result == Path(existing).resolve()
    run.assert_not_called()
    out = capsys.readouterr().out
    assert "Using existing sumo-qa binary" in out


def test_fallback_uv_install_succeeds_and_which_finds_binary(capsys) -> None:
    """No existing sumo-qa, uv present, uv install succeeds, post-install which returns path."""
    post_install_path = "/home/user/.local/bin/sumo-qa"

    def which_side_effect(name: str):
        if name == "sumo-qa":
            # First call (fast path): not found. Second call (post-install): found.
            if which_side_effect.count == 0:
                which_side_effect.count += 1
                return None
            return post_install_path
        if name == "uv":
            return "/usr/bin/uv"
        return None

    which_side_effect.count = 0

    with (
        patch("sumo_qa.installer.shutil.which", side_effect=which_side_effect),
        patch("sumo_qa.installer.subprocess.run", return_value=_completed()) as run,
    ):
        result = installer._install_mcp_binary()

    assert result == Path(post_install_path).resolve()
    run.assert_called_once()
    uv_cmd = run.call_args.args[0]
    assert uv_cmd[0] == "uv"
    assert "sumo-qa" in uv_cmd


def test_no_sumo_qa_and_no_uv_prints_pip_hint_and_returns_none(capsys) -> None:
    """Both sumo-qa and uv are absent; function prints pip install hint and returns None."""
    with patch("sumo_qa.installer.shutil.which", return_value=None):
        result = installer._install_mcp_binary()

    assert result is None
    out = capsys.readouterr().out
    assert "pip install --upgrade sumo-qa" in out


def test_uv_install_raises_called_process_error_returns_none(capsys) -> None:
    """uv tool install fails with CalledProcessError; function returns None and prints returncode."""

    def which_side_effect(name: str):
        if name == "uv":
            return "/usr/bin/uv"
        return None  # sumo-qa not on PATH

    exc = subprocess.CalledProcessError(returncode=1, cmd=["uv", "tool", "install", "sumo-qa"])

    with (
        patch("sumo_qa.installer.shutil.which", side_effect=which_side_effect),
        patch("sumo_qa.installer.subprocess.run", side_effect=exc),
    ):
        result = installer._install_mcp_binary()

    assert result is None
    out = capsys.readouterr().out
    assert "1" in out  # returncode in error message


def test_uv_install_succeeds_which_misses_but_conventional_path_exists(tmp_path, capsys) -> None:
    """After uv install, which still returns None; a conventional bin location exists."""

    def which_side_effect(name: str):
        if name == "uv":
            return "/usr/bin/uv"
        return None  # sumo-qa never appears on PATH

    fake_candidate = tmp_path / "sumo-qa"
    fake_candidate.touch()

    conventional_paths = [
        Path.home() / ".local" / "bin" / "sumo-qa",
        Path.home() / ".local" / "share" / "uv" / "tools" / "sumo-qa" / "bin" / "sumo-qa",
    ]

    def is_file_side_effect(self: Path) -> bool:
        # Return True only for the first conventional candidate.
        return self == conventional_paths[0]

    with (
        patch("sumo_qa.installer.shutil.which", side_effect=which_side_effect),
        patch("sumo_qa.installer.subprocess.run", return_value=_completed()),
        patch.object(Path, "is_file", is_file_side_effect),
    ):
        result = installer._install_mcp_binary()

    assert result == conventional_paths[0].resolve()


def test_all_fallbacks_miss_prints_restart_hint_and_returns_none(capsys) -> None:
    """uv install succeeds, which returns None, no conventional path exists → None + hint."""

    def which_side_effect(name: str):
        if name == "uv":
            return "/usr/bin/uv"
        return None

    with (
        patch("sumo_qa.installer.shutil.which", side_effect=which_side_effect),
        patch("sumo_qa.installer.subprocess.run", return_value=_completed()),
        patch.object(Path, "is_file", return_value=False),
    ):
        result = installer._install_mcp_binary()

    assert result is None
    out = capsys.readouterr().out
    assert "uv install succeeded" in out


# ---------------------------------------------------------------------------
# _detect_install_mode — wheel-bundled vs editable / git-clone branches
# ---------------------------------------------------------------------------


def test_detect_install_mode_wheel_branch(tmp_path: Path) -> None:
    """When _data/skills exists next to the module, returns wheel-mode tuple."""
    module_dir = tmp_path / "sumo_qa"
    module_dir.mkdir()
    bundled = module_dir / "_data" / "skills"
    bundled.mkdir(parents=True)

    repo_root, skills_src, uv_install_from = installer._detect_install_mode(
        module_dir=module_dir, bundled_skills=bundled
    )

    assert repo_root == module_dir
    assert skills_src == bundled
    assert uv_install_from == []


def test_detect_install_mode_editable_branch(tmp_path: Path) -> None:
    """When no bundled _data/skills, returns repo-root + --from arg."""
    repo_root = tmp_path / "repo"
    src_dir = repo_root / "src"
    module_dir = src_dir / "sumo_qa"
    module_dir.mkdir(parents=True)
    (repo_root / "pyproject.toml").write_text("[project]\nname='sumo-qa'\n", encoding="utf-8")
    bundled = module_dir / "_data" / "skills"  # does NOT exist

    detected_root, skills_src, uv_install_from = installer._detect_install_mode(
        module_dir=module_dir, bundled_skills=bundled
    )

    assert detected_root == repo_root
    assert skills_src == repo_root / "skills"
    assert uv_install_from == ["--from", str(repo_root)]


def test_detect_install_mode_broken_layout_exits(tmp_path: Path, capsys) -> None:
    """When neither bundled skills nor pyproject.toml exists, prints error + exits 1."""
    module_dir = tmp_path / "stray" / "sumo_qa"
    module_dir.mkdir(parents=True)
    bundled = module_dir / "_data" / "skills"  # does NOT exist
    # tmp_path / "stray" is the would-be repo root; no pyproject.toml there.

    import pytest

    with pytest.raises(SystemExit) as exc_info:
        installer._detect_install_mode(module_dir=module_dir, bundled_skills=bundled)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "could not locate bundled skills" in err
