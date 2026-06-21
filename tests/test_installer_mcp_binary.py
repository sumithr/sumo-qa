# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from sumo_qa import installer

# mutmut-subprocess-spawning: spawns ``python -m sumo_qa.installer`` from a
# fresh interpreter, so it MUST be excluded from the mutmut gate via
# [tool.mutmut].pytest_add_cli_args in pyproject.toml. Installer imports
# trampoline-injected modules transitively without MUTANT_UNDER_TEST.

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def test_fast_path_returns_resolved_binary_without_subprocess_call(capsys) -> None:
    """When sumo-qa is already on PATH the function returns immediately.

    Asserts no subprocess.run is called — neither for module-fallback probing
    nor for the now-removed uv path.
    """
    existing = "/usr/local/bin/sumo-qa"
    with (
        patch("sumo_qa.installer.shutil.which", return_value=existing),
        patch("sumo_qa.installer.subprocess.run") as run,
    ):
        result = installer._install_mcp_binary()

    assert result == installer.McpCommand(command=str(Path(existing).resolve()), args=[])
    run.assert_not_called()
    out = capsys.readouterr().out
    assert "Using existing sumo-qa binary" in out


def test_module_fallback_when_script_not_on_path(capsys) -> None:
    """Script not on PATH → fall back to `<sys.executable> -m sumo_qa`, never invoke uv.

    This is the canonical Windows-cmd-with-MS-Store-Python case: pip installed
    sumo-qa.exe into a Scripts dir that isn't on PATH. The installer must
    detect that `sumo_qa` is importable in the current interpreter and use
    the module-invocation form, NOT silently fall back to uv.
    """
    with (
        patch("sumo_qa.installer.shutil.which", return_value=None),
        patch("sumo_qa.installer.subprocess.run") as run,
    ):
        result = installer._install_mcp_binary()

    assert result == installer.McpCommand(
        command=sys.executable,
        args=["-m", "sumo_qa"],
    )
    # Critical: no subprocess.run call. No uv install, no module-import probe.
    # The current interpreter is already proof that `import sumo_qa` works
    # (we got here by running installer.py, which lives inside the package).
    run.assert_not_called()
    out = capsys.readouterr().out
    assert "uv" not in out.lower()
    assert "python -m sumo_qa" in out or "-m sumo_qa" in out


# ---------------------------------------------------------------------------
# _detect_install_mode — wheel-bundled vs editable / git-clone branches
# ---------------------------------------------------------------------------


def test_detect_install_mode_wheel_branch(tmp_path: Path) -> None:
    """When _data/skills exists next to the module, returns wheel-mode tuple."""
    module_dir = tmp_path / "sumo_qa"
    module_dir.mkdir()
    bundled = module_dir / "_data" / "skills"
    bundled.mkdir(parents=True)

    repo_root, skills_src = installer._detect_install_mode(
        module_dir=module_dir, bundled_skills=bundled
    )

    assert repo_root == module_dir
    assert skills_src == bundled


def test_detect_install_mode_editable_branch(tmp_path: Path) -> None:
    """When no bundled _data/skills, returns repo-root + skills dir."""
    repo_root = tmp_path / "repo"
    src_dir = repo_root / "src"
    module_dir = src_dir / "sumo_qa"
    module_dir.mkdir(parents=True)
    (repo_root / "pyproject.toml").write_text("[project]\nname='sumo-qa'\n", encoding="utf-8")
    bundled = module_dir / "_data" / "skills"  # does NOT exist

    detected_root, skills_src = installer._detect_install_mode(
        module_dir=module_dir, bundled_skills=bundled
    )

    assert detected_root == repo_root
    assert skills_src == repo_root / "skills"


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
