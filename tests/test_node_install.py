# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

import subprocess
from unittest.mock import patch

from sumo_qa import node_install


def _completed_process(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_detect_installer_returns_brew_on_darwin_with_brew() -> None:
    with (
        patch("sumo_qa.node_install.sys.platform", "darwin"),
        patch(
            "sumo_qa.node_install.shutil.which",
            side_effect=lambda cmd: "/opt/homebrew/bin/brew" if cmd == "brew" else None,
        ),
    ):
        installer = node_install.detect_installer()

    assert installer is not None
    assert installer.name == "brew"
    assert installer.command == ("brew", "install", "node")
    assert installer.needs_sudo is False


def test_detect_installer_returns_winget_on_windows_with_winget() -> None:
    with (
        patch("sumo_qa.node_install.sys.platform", "win32"),
        patch(
            "sumo_qa.node_install.shutil.which",
            side_effect=lambda cmd: "C:\\winget.exe" if cmd == "winget" else None,
        ),
    ):
        installer = node_install.detect_installer()

    assert installer is not None
    assert installer.name == "winget"
    assert installer.command == ("winget", "install", "OpenJS.NodeJS")
    assert installer.needs_sudo is False


def test_detect_installer_returns_apt_on_linux_with_apt_get() -> None:
    with (
        patch("sumo_qa.node_install.sys.platform", "linux"),
        patch(
            "sumo_qa.node_install.shutil.which",
            side_effect=lambda cmd: "/usr/bin/apt-get" if cmd == "apt-get" else None,
        ),
    ):
        installer = node_install.detect_installer()

    assert installer is not None
    assert installer.name == "apt-get"
    assert installer.command == ("apt-get", "install", "-y", "nodejs", "npm")
    assert installer.needs_sudo is True


def test_detect_installer_returns_dnf_on_linux_with_dnf() -> None:
    def _which(cmd: str) -> str | None:
        if cmd == "dnf":
            return "/usr/bin/dnf"
        return None

    with (
        patch("sumo_qa.node_install.sys.platform", "linux"),
        patch("sumo_qa.node_install.shutil.which", side_effect=_which),
    ):
        installer = node_install.detect_installer()

    assert installer is not None
    assert installer.name == "dnf"
    assert installer.command == ("dnf", "install", "-y", "nodejs", "npm")
    assert installer.needs_sudo is True


def test_detect_installer_prefers_apt_over_dnf_on_linux() -> None:
    # Both present: apt-get wins (Debian/Ubuntu dominant)
    with (
        patch("sumo_qa.node_install.sys.platform", "linux"),
        patch("sumo_qa.node_install.shutil.which", side_effect=lambda cmd: f"/usr/bin/{cmd}"),
    ):
        installer = node_install.detect_installer()

    assert installer is not None
    assert installer.name == "apt-get"


def test_detect_installer_returns_none_when_no_package_manager() -> None:
    with (
        patch("sumo_qa.node_install.sys.platform", "linux"),
        patch("sumo_qa.node_install.shutil.which", return_value=None),
    ):
        assert node_install.detect_installer() is None


def test_detect_installer_returns_none_on_unsupported_platform() -> None:
    with (
        patch("sumo_qa.node_install.sys.platform", "haiku"),
        patch("sumo_qa.node_install.shutil.which", return_value="/usr/bin/something"),
    ):
        assert node_install.detect_installer() is None


def test_install_runs_command_when_no_sudo_needed() -> None:
    installer = node_install.NodeInstaller(
        name="brew", command=("brew", "install", "node"), needs_sudo=False
    )
    captured: dict = {}

    def _capture(args, **kwargs):
        captured["args"] = args
        return _completed_process(stdout="success")

    with patch("sumo_qa.node_install.subprocess.run", side_effect=_capture):
        result = node_install.install(installer)

    assert captured["args"] == ["brew", "install", "node"]
    assert result.installed is True
    assert result.stderr == ""


def test_install_refuses_to_run_when_sudo_required() -> None:
    installer = node_install.NodeInstaller(
        name="apt-get", command=("apt-get", "install", "-y", "nodejs", "npm"), needs_sudo=True
    )
    with patch("sumo_qa.node_install.subprocess.run") as mock_run:
        result = node_install.install(installer)

    mock_run.assert_not_called()
    assert result.installed is False
    assert "sudo" in result.reason.lower()
    assert "apt-get install -y nodejs npm" in result.reason


def test_install_surfaces_stderr_on_failure() -> None:
    installer = node_install.NodeInstaller(
        name="brew", command=("brew", "install", "node"), needs_sudo=False
    )
    with patch(
        "sumo_qa.node_install.subprocess.run",
        return_value=_completed_process(returncode=1, stderr="brew: not authenticated"),
    ):
        result = node_install.install(installer)

    assert result.installed is False
    assert "brew: not authenticated" in result.stderr
    assert "brew: not authenticated" in result.reason
