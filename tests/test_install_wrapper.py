"""Behaviour tests for the thin ``install.sh`` wrapper.

The wrapper is a thin command router around the canonical Python installer
(``python -m pip install sumo-qa`` + ``python -m sumo_qa.installer`` +
``sumo-qa-doctor``). It must NOT become a second installer implementation,
so the only logic worth testing is its flag parsing and the exact commands
it would delegate to.

To make that logic observable without side effects (no real pip install, no
host-config writes), the wrapper supports a ``--print-plan`` mode: it prints
the exact commands it WOULD run, one per line, and exits 0 without executing
any of them. Every test below drives that mode and asserts on the printed
plan — a decision table over (mode x host) -> delegated command, plus an
equivalence-partition split between verified and rejected hosts.

Why subprocess (not sourcing the script): the wrapper's contract is "given
these argv, route to these commands"; running it the way a user runs it is
the only test that exercises real shell arg parsing, quoting, and exit codes.
"""

import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
INSTALL_PS1 = REPO_ROOT / "install.ps1"


def _plan(*args: str) -> subprocess.CompletedProcess:
    """Run ``install.sh --print-plan <args>`` and capture the plan."""
    return subprocess.run(
        ["bash", str(INSTALL_SH), "--print-plan", *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


# The wrapper resolves a concrete interpreter at runtime (``python3`` or
# ``python``), so assert on the interpreter-agnostic command tail — that is
# the load-bearing contract ("delegates to the canonical pip + installer"),
# not which interpreter name happens to be on this machine's PATH.
PIP_INSTALL = "-m pip install sumo-qa"
PIP_UPGRADE = "-m pip install --upgrade sumo-qa"
INSTALLER = "-m sumo_qa.installer"


def test_bare_install_plan_delegates_to_canonical_pip_and_installer():
    result = _plan()
    assert result.returncode == 0, result.stderr
    plan = result.stdout
    assert PIP_INSTALL in plan
    assert INSTALLER in plan


def test_bare_install_plan_runs_doctor_at_the_end():
    plan = _plan().stdout
    assert "sumo-qa-doctor" in plan
    # Doctor must come AFTER the installer step, never before it.
    assert plan.index(INSTALLER) < plan.index("sumo-qa-doctor")


def test_update_plan_delegates_to_pip_upgrade():
    result = _plan("--update")
    assert result.returncode == 0, result.stderr
    plan = result.stdout
    assert PIP_UPGRADE in plan
    # Update still re-runs the installer to refresh host configs/symlinks.
    assert INSTALLER in plan


def test_host_flag_is_forwarded_to_the_installer():
    plan = _plan("--host", "vscode").stdout
    installer_line = next(line for line in plan.splitlines() if INSTALLER in line)
    assert "--vscode" in installer_line


def test_jetbrains_host_maps_to_jetbrains_installer_flag():
    plan = _plan("--host", "jetbrains").stdout
    installer_line = next(line for line in plan.splitlines() if INSTALLER in line)
    assert "--jetbrains" in installer_line


def test_unverified_host_is_rejected_not_passed_through():
    result = _plan("--host", "emacs")
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "emacs" in combined
    # A rejected host must NOT emit a pip/installer command — refusing beats
    # passing an unknown flag down to the installer.
    assert "pip install sumo-qa" not in result.stdout
    assert INSTALLER not in result.stdout


def test_uninstall_is_a_documented_deferral_not_a_destructive_action():
    result = _plan("--uninstall")
    combined = result.stdout + result.stderr
    # Deferred on purpose: the wrapper must NOT run a real uninstall, because
    # it cannot prove it owns the host config entries it would remove.
    assert "pip uninstall" not in result.stdout
    # It must point the user at the documented manual uninstall steps.
    assert "docs/INSTALL.md" in combined or "INSTALL.md" in combined


def test_doctor_flag_runs_only_doctor():
    result = _plan("--doctor")
    assert result.returncode == 0, result.stderr
    plan = result.stdout
    assert "sumo-qa-doctor" in plan
    # A bare --doctor run is verification only; it must not reinstall.
    assert "pip install sumo-qa" not in plan


# --- install.ps1 (Windows PowerShell parity) -----------------------------
#
# pwsh is rarely available on the dev/CI runners that gate this repo, so the
# parity tests below are text-based static checks (technique: static
# analysis) that run anywhere. The one test that needs a real PowerShell
# parser is gated on pwsh and skips cleanly when it is absent — documented in
# the issue's test plan as "PowerShell parser check if feasible locally".


def test_powershell_wrapper_exists_for_parity():
    assert INSTALL_PS1.is_file(), "install.ps1 must ship alongside install.sh"


def test_powershell_wrapper_covers_the_same_modes_and_hosts():
    text = INSTALL_PS1.read_text()
    # Same canonical delegation targets as install.sh.
    assert "-m pip install sumo-qa" in text
    assert "-m pip install --upgrade sumo-qa" in text
    assert "-m sumo_qa.installer" in text
    assert "sumo-qa-doctor" in text
    # Same mode switches.
    for switch in ("Update", "Doctor", "Uninstall", "PrintPlan"):
        assert switch in text, f"install.ps1 is missing the -{switch} switch"
    # Same verified host set.
    for host in ("claude-code", "vscode", "jetbrains"):
        assert host in text, f"install.ps1 is missing the {host} host mapping"


def test_powershell_uninstall_is_deferred_not_destructive():
    text = INSTALL_PS1.read_text()
    # Must route to the documented manual steps, never auto-run pip uninstall
    # outside the quoted guidance block.
    assert "docs/INSTALL.md#uninstall" in text
    assert "Invoke-Expression" not in text.split("'uninstall'")[1].split("}")[0]


@pytest.mark.skipif(
    shutil.which("pwsh") is None and shutil.which("powershell") is None,
    reason="no PowerShell interpreter available to parse install.ps1",
)
def test_powershell_wrapper_parses():
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    # -NoProfile -Command with the AST parser: parses the file without
    # executing it; non-empty $errors means a syntax error.
    script = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{INSTALL_PS1}',[ref]$tokens,[ref]$errors)|Out-Null;"
        "if($errors){$errors|ForEach-Object{Write-Error $_.Message};exit 1}"
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
