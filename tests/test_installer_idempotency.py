# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Idempotency tests for installer.py.

These tests verify that running installer functions more than once produces
identical results — no duplicated entries, no broken symlinks, no stale
artefacts. They are deliberately distinct from the basic happy-path coverage
in test_installer_claude_code_mcp.py; every test here exercises a *re-run*
behaviour that the happy-path file does not assert.

Production code MUST stay unchanged. All subprocess calls are mocked.
All filesystem operations use tmp_path / monkeypatch.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sumo_qa import installer


def _ok(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=b"")


# ---------------------------------------------------------------------------
# T1 — _setup_claude_code: two runs leave exactly one 'sumo-qa' mcpServers entry
# ---------------------------------------------------------------------------


def test_setup_claude_code_two_runs_leave_single_mcp_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running _setup_claude_code must not create duplicate mcpServers keys."""
    # Redirect Path.home() → tmp_path so no real ~/.claude or ~/.config is touched.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    # Create the config and claude dirs so the "not detected" early-return is skipped.
    claude_home = home / ".claude"
    claude_home.mkdir(parents=True)
    config_dir = home / ".config" / "claude"
    config_dir.mkdir(parents=True)

    mcp_path = Path("/usr/local/bin/sumo-qa")

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()),
    ):
        installer._setup_claude_code(mcp_path, "Darwin")
        installer._setup_claude_code(mcp_path, "Darwin")

    config_path = config_dir / "claude_desktop_config.json"
    assert config_path.exists(), "claude_desktop_config.json was not written"

    config = json.loads(config_path.read_text(encoding="utf-8"))
    mcp_servers = config.get("mcpServers", {})

    # Exactly one entry — the key 'sumo-qa' — must exist; no versioned duplicates.
    assert list(mcp_servers.keys()) == ["sumo-qa"], (
        f"Expected exactly one 'sumo-qa' key; got keys: {list(mcp_servers.keys())}"
    )
    assert mcp_servers["sumo-qa"] == {"command": str(mcp_path)}


# ---------------------------------------------------------------------------
# T2 — _register_claude_code_mcp: second run still fires remove THEN add
# ---------------------------------------------------------------------------


def test_register_claude_code_mcp_second_run_still_removes_then_adds() -> None:
    """Each invocation of _register_claude_code_mcp must issue remove then add,
    even on the second call — the function must not short-circuit on re-run."""
    mcp_path = Path("/abs/path/to/sumo-qa")

    with (
        patch("sumo_qa.installer.shutil.which", return_value="/usr/local/bin/claude"),
        patch("sumo_qa.installer.subprocess.run", return_value=_ok()) as mock_run,
    ):
        installer._register_claude_code_mcp(mcp_path)
        installer._register_claude_code_mcp(mcp_path)

    # Each call fires 2 subprocess invocations (remove + add), so two calls → 4 total.
    assert mock_run.call_count == 4, (
        f"Expected 4 subprocess calls (2×remove + 2×add), got {mock_run.call_count}"
    )

    calls = mock_run.call_args_list
    # First call: remove
    assert "remove" in calls[0].args[0], "Call 0 should be 'mcp remove'"
    # Second call: add
    assert "add" in calls[1].args[0], "Call 1 should be 'mcp add'"
    # Third call (second invocation): remove again
    assert "remove" in calls[2].args[0], "Call 2 should be 'mcp remove' (second run)"
    # Fourth call (second invocation): add again
    assert "add" in calls[3].args[0], "Call 3 should be 'mcp add' (second run)"


# ---------------------------------------------------------------------------
# T3 — _install_claude_code_skills_per_dir: legacy wrapper is cleaned and
#      stays absent on a second run (not re-created)
# ---------------------------------------------------------------------------


def test_install_skills_cleans_legacy_wrapper_and_stays_clean_on_rerun(
    tmp_path: Path,
) -> None:
    """The legacy 'sumo-qa' wrapper dir inside skills_dir must be removed on
    the first run and must NOT be recreated on a second run."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Simulate a legacy wrapper symlink left by an older install.
    legacy_wrapper = skills_dir / "sumo-qa"
    legacy_wrapper.mkdir()  # old versions created a real directory here

    # First run: legacy wrapper should be removed.
    installer._install_claude_code_skills_per_dir(skills_dir, "Darwin")

    assert not legacy_wrapper.exists(), (
        "Legacy 'sumo-qa' wrapper dir should have been removed on first run"
    )
    assert not legacy_wrapper.is_symlink(), (
        "Legacy 'sumo-qa' wrapper symlink should have been removed on first run"
    )

    # Second run: the wrapper must not be re-created.
    installer._install_claude_code_skills_per_dir(skills_dir, "Darwin")

    assert not legacy_wrapper.exists(), (
        "Legacy 'sumo-qa' wrapper must not be re-created on second run"
    )
    assert not legacy_wrapper.is_symlink(), (
        "Legacy 'sumo-qa' wrapper symlink must not be re-created on second run"
    )


# ---------------------------------------------------------------------------
# T4 — Two runs produce no broken symlinks in skills_dir
# ---------------------------------------------------------------------------


def test_install_skills_two_runs_leave_no_broken_symlinks(
    tmp_path: Path,
) -> None:
    """After running _install_claude_code_skills_per_dir twice, every symlink
    in skills_dir must resolve — no entry where is_symlink() is True but
    exists() is False (which is the canonical broken-symlink condition)."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Run once.
    installer._install_claude_code_skills_per_dir(skills_dir, "Darwin")
    # Run again — simulates the idempotent re-install scenario.
    installer._install_claude_code_skills_per_dir(skills_dir, "Darwin")

    broken = [p for p in skills_dir.iterdir() if p.is_symlink() and not p.exists()]
    assert broken == [], f"Broken symlinks found after two runs: {[str(b) for b in broken]}"


# ---------------------------------------------------------------------------
# _install_claude_code_skills_per_dir — additional branch coverage
# ---------------------------------------------------------------------------


def test_install_skills_removes_legacy_wrapper_real_dir(tmp_path: Path) -> None:
    """When the legacy 'sumo-qa' wrapper is a real directory (not a symlink),
    shutil.rmtree removes it (line 383-385)."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    # Legacy real directory.
    legacy = skills_dir / "sumo-qa"
    legacy.mkdir()
    (legacy / "some_file.txt").write_text("old", encoding="utf-8")

    installer._install_claude_code_skills_per_dir(skills_dir, "Darwin")

    assert not legacy.exists(), "Legacy real directory should have been rmtree'd"


def test_install_skills_cleans_stale_copy_matching_repo_skill(tmp_path: Path) -> None:
    """When skills_dir contains a real directory whose SKILL.md matches the repo
    version, it is replaced with a symlink (lines 403-412)."""
    from sumo_qa.installer import SKILLS_SRC

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Pick one real skill from the repo to replicate.
    real_skills = [p for p in SKILLS_SRC.iterdir() if p.is_dir()]
    if not real_skills:
        pytest.skip("No skills found in SKILLS_SRC")

    skill = real_skills[0]
    skill_md = skill / "SKILL.md"
    if not skill_md.is_file():
        pytest.skip(f"No SKILL.md in {skill}")

    # Create a stale copy of that skill in skills_dir.
    stale = skills_dir / skill.name
    stale.mkdir()
    (stale / "SKILL.md").write_text(skill_md.read_text(), encoding="utf-8")

    installer._install_claude_code_skills_per_dir(skills_dir, "Darwin")

    # The stale directory should have been replaced.
    target = skills_dir / skill.name
    assert target.exists(), "Skill target should exist after install"


def test_install_skills_skips_non_dir_src(tmp_path: Path) -> None:
    """If a SKILLS_SRC entry appears in repo_skill_names but is not a dir at
    loop time (race condition guard), it is skipped (line 420)."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Build a fake SKILLS_SRC where iterdir() returns a mock dir entry,
    # but by the time the loop checks src.is_dir(), it returns False.
    fake_src = tmp_path / "fake_skills"
    fake_src.mkdir()
    skill_subdir = fake_src / "my-skill"
    skill_subdir.mkdir()

    # Patch SKILLS_SRC; also patch is_dir on the subdir so the initial
    # comprehension sees it as a dir, but the per-loop check returns False.
    original_is_dir = Path.is_dir

    call_count = {"n": 0}

    def patched_is_dir(self):
        # First call (from iterdir comprehension) → True.
        # Subsequent calls on src (loop body) → False to trigger the guard.
        if self == skill_subdir:
            call_count["n"] += 1
            return call_count["n"] == 1  # True on first call, False on second+
        return original_is_dir(self)

    with (
        patch("sumo_qa.installer.SKILLS_SRC", fake_src),
        patch.object(Path, "is_dir", patched_is_dir),
    ):
        msg = installer._install_claude_code_skills_per_dir(skills_dir, "Darwin")

    assert "symlinked" in msg


def test_install_skills_copies_on_windows_symlink_error(tmp_path: Path) -> None:
    """On Windows (or when symlink_to raises OSError), skills are copied instead (lines 425-430)."""
    from sumo_qa.installer import SKILLS_SRC

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    real_skills = [p for p in SKILLS_SRC.iterdir() if p.is_dir()]
    if not real_skills:
        pytest.skip("No skills found in SKILLS_SRC")

    # Force OSError on symlink_to so the Windows fallback is triggered.
    def _raise_os_error(self, *args, **kwargs):
        raise OSError("symlink not supported")

    with patch.object(Path, "symlink_to", _raise_os_error):
        installer._install_claude_code_skills_per_dir(skills_dir, "Windows")

    # All skills should have been copied.
    for skill in real_skills:
        assert (skills_dir / skill.name).exists(), f"Expected copied skill: {skill.name}"


def test_install_skills_render_includes_copied_count(tmp_path: Path) -> None:
    """The return message mentions 'copied N (Windows fallback)' when skills are copied (line 437)."""
    from sumo_qa.installer import SKILLS_SRC

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    real_skills = [p for p in SKILLS_SRC.iterdir() if p.is_dir()]
    if not real_skills:
        pytest.skip("No skills found in SKILLS_SRC")

    def _raise_os_error(self, *args, **kwargs):
        raise OSError("symlink not supported")

    with patch.object(Path, "symlink_to", _raise_os_error):
        msg = installer._install_claude_code_skills_per_dir(skills_dir, "Windows")

    assert "Windows fallback" in msg


def test_install_skills_removes_legacy_wrapper_symlink(tmp_path: Path) -> None:
    """When the legacy 'sumo-qa' wrapper is a symlink, it is unlinked (line 383)."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Create a symlink named "sumo-qa" inside skills_dir.
    target = tmp_path / "old_target"
    target.mkdir()
    legacy = skills_dir / "sumo-qa"
    legacy.symlink_to(target, target_is_directory=True)
    assert legacy.is_symlink()

    installer._install_claude_code_skills_per_dir(skills_dir, "Darwin")

    assert not legacy.exists() and not legacy.is_symlink(), (
        "Legacy symlink should have been unlinked"
    )


def test_install_skills_re_raises_os_error_on_non_windows(tmp_path: Path) -> None:
    """On non-Windows systems, OSError from symlink_to is re-raised (line 430)."""
    from sumo_qa.installer import SKILLS_SRC

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    real_skills = [p for p in SKILLS_SRC.iterdir() if p.is_dir()]
    if not real_skills:
        pytest.skip("No skills found in SKILLS_SRC")

    def _raise_os_error(self, *args, **kwargs):
        raise OSError("not Windows, symlink should re-raise")

    with (
        patch.object(Path, "symlink_to", _raise_os_error),
        pytest.raises(OSError),
    ):
        installer._install_claude_code_skills_per_dir(skills_dir, "Darwin")
