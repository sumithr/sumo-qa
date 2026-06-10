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

import os
import pathlib
import shlex
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
INSTALL_PS1 = REPO_ROOT / "install.ps1"


def _resolve_bash() -> str | None:
    """Locate a real POSIX bash to run ``install.sh`` with.

    On Windows a bare ``bash`` on PATH is usually the WSL launcher stub
    (``C:\\Windows\\System32\\bash.exe``), which on a CI runner has no distro
    installed: it prints a UTF-16 "no installed distributions" notice and
    exits 1, nothing to do with the wrapper. Prefer Git's bash, fall back to
    whatever ``shutil.which`` finds, and treat the System32 WSL stub as
    unusable so the suite skips on a bash-less host rather than failing on an
    unrelated tool.
    """
    candidates: list[str] = []
    if os.name == "nt":
        candidates += [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
        ]
    found = shutil.which("bash")
    if found:
        candidates.append(found)
    for cand in candidates:
        if cand and pathlib.Path(cand).exists() and "system32" not in cand.lower():
            return cand
    return None


BASH = _resolve_bash()


def _bash_or_skip() -> str:
    """Return the resolved bash, or skip the calling test if none is usable.

    Scoped to the bash-dependent tests only (NOT a module-wide skip), so the
    pwsh-gated tests still run on a Windows host that has PowerShell but no
    git-bash."""
    if BASH is None:
        pytest.skip(
            "no POSIX bash available (bare 'bash' on Windows is the WSL stub, not git-bash)"
        )
    return BASH


def _plan(*args: str) -> subprocess.CompletedProcess:
    """Run ``install.sh --print-plan <args>`` and capture the plan."""
    _bash_or_skip()
    return subprocess.run(
        [BASH, str(INSTALL_SH), "--print-plan", *args],
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
# Doctor runs through the resolved interpreter (`-m sumo_qa.doctor`), NOT the
# bare `sumo-qa-doctor` console script, so verification doesn't depend on pip's
# scripts dir being on PATH (the `pip install --user` case).
DOCTOR = "-m sumo_qa.doctor"


def test_bare_install_plan_delegates_to_canonical_pip_and_installer():
    result = _plan()
    assert result.returncode == 0, result.stderr
    plan = result.stdout
    assert PIP_INSTALL in plan
    assert INSTALLER in plan
    # Exact ordered plan — count + order + per-line tail — so an extra,
    # duplicated, or reordered command cannot slip past the substring checks.
    lines = [ln for ln in plan.splitlines() if ln.strip()]
    assert len(lines) == 3, lines
    assert lines[0].endswith(PIP_INSTALL)
    assert lines[1].endswith(INSTALLER)
    assert lines[2].endswith(DOCTOR)
    # Doctor is the resolved-interpreter module form, never the bare console
    # script (which is PATH-fragile on --user installs).
    assert "sumo-qa-doctor" not in plan


def test_bare_install_plan_runs_doctor_at_the_end():
    plan = _plan().stdout
    assert DOCTOR in plan
    # Doctor must come AFTER the installer step, never before it.
    assert plan.index("sumo_qa.installer") < plan.index("sumo_qa.doctor")


def test_print_plan_survives_a_consumer_that_closes_the_pipe_early():
    """Regression: a reader auditing the plan pipes it into `grep -q`/`head`,
    which closes the pipe after the first match. Under `set -e -o pipefail`
    the next write in install.sh took SIGPIPE (exit 141) / a broken-pipe error
    that failed the whole pipeline. --print-plan only prints and must exit 0
    even when its consumer stops reading early.

    `| true` is a consumer that never reads and exits immediately, so install.sh
    writes into a pipe with no reader — a deterministic broken pipe. Under an
    explicit `pipefail` shell, an unguarded install.sh dies (exit 141) and that
    propagates; with the guard it exits 0."""
    _bash_or_skip()
    pipeline = f"{shlex.quote(BASH)} {shlex.quote(str(INSTALL_SH))} --print-plan --update | true"
    for _ in range(5):
        result = subprocess.run(
            [BASH, "-o", "pipefail", "-c", pipeline],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, (
            f"--print-plan must survive an early pipe close, got rc="
            f"{result.returncode}\n{result.stderr}"
        )


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


def test_host_is_forwarded_to_the_doctor():
    # P1: a host-scoped install must scope the doctor too. Otherwise the
    # doctor's VS Code workspace check FAILs whenever cwd lacks .vscode/mcp.json,
    # and a successful `--host claude-code` install exits nonzero.
    for host in ("claude-code", "vscode", "jetbrains"):
        plan = _plan("--host", host).stdout
        doctor_line = next(ln for ln in plan.splitlines() if DOCTOR in ln)
        assert f"--host {host}" in doctor_line, doctor_line
    # Doctor-only mode forwards the host too.
    plan = _plan("--doctor", "--host", "claude-code").stdout
    doctor_line = next(ln for ln in plan.splitlines() if DOCTOR in ln)
    assert "--host claude-code" in doctor_line
    # A bare (all-host) install must NOT add a stray --host to the doctor.
    plan = _plan().stdout
    doctor_line = next(ln for ln in plan.splitlines() if DOCTOR in ln)
    assert "--host" not in doctor_line


def test_unverified_host_is_rejected_not_passed_through():
    result = _plan("--host", "emacs")
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "emacs" in combined
    # A rejected host must NOT emit a pip/installer command — refusing beats
    # passing an unknown flag down to the installer.
    assert "pip install sumo-qa" not in result.stdout
    assert INSTALLER not in result.stdout


def test_uninstall_routes_to_the_canonical_installer_uninstall():
    # --uninstall now routes to the canonical installer's ownership-aware
    # --uninstall path (no longer a deferral). The wrapper itself must run
    # nothing destructive: no pip uninstall, no rm of user data.
    result = _plan("--uninstall")
    assert result.returncode == 0, result.stderr
    plan = result.stdout
    # The plan delegates the uninstall to the canonical installer.
    assert f"{INSTALLER} --uninstall" in plan
    # No doctor after uninstall — nothing to verify once config is removed.
    assert DOCTOR not in plan
    assert "sumo-qa-doctor" not in plan
    # The wrapper itself never runs anything destructive.
    assert "pip uninstall" not in plan
    assert "rm " not in plan


def test_doctor_flag_runs_only_doctor():
    result = _plan("--doctor")
    assert result.returncode == 0, result.stderr
    plan = result.stdout
    assert DOCTOR in plan
    # A bare --doctor run is verification only; it must not reinstall.
    assert "pip install sumo-qa" not in plan


@pytest.mark.parametrize(
    "flags",
    [
        ("--uninstall", "--update"),
        ("--update", "--doctor"),
        ("--doctor", "--uninstall"),
    ],
)
def test_conflicting_mode_flags_are_rejected_not_silently_overridden(flags):
    # Two mode flags must error, not silently let precedence win — a user who
    # asked to --uninstall must never get an --update.
    result = _plan(*flags)
    assert result.returncode != 0, result.stdout
    combined = result.stdout + result.stderr
    assert "onflicting" in combined  # "Conflicting"/"conflicting"
    for flag in flags:
        assert flag in combined, f"error should name the conflicting flag {flag}"
    # A rejected, ambiguous invocation must emit no delegated command.
    assert "pip install" not in result.stdout
    assert INSTALLER not in result.stdout


def test_failing_delegated_command_propagates_nonzero_exit(tmp_path):
    # Regression guard for the swallowed-exit-code bug: a delegated command
    # that exits non-zero must make the wrapper exit with THAT code, not 0.
    # Drive the real exec path (not --print-plan) with SUMO_QA_PYTHON pointed
    # at a stub interpreter that exits 7; the wrapper's first plan step
    # (`$PYTHON -m pip install ...`) then fails deterministically.
    stub = tmp_path / "fail_python.sh"
    stub.write_text("#!/bin/sh\nexit 7\n")
    stub.chmod(0o755)
    _bash_or_skip()
    result = subprocess.run(
        [BASH, str(INSTALL_SH)],  # real exec path, NOT --print-plan
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={"PATH": "/usr/bin:/bin", "SUMO_QA_PYTHON": str(stub)},
    )
    assert result.returncode == 7, (result.returncode, result.stdout, result.stderr)
    # The friendly failure message still names the exact failing command.
    assert "command failed" in result.stderr.lower()
    assert "pip install sumo-qa" in result.stderr


def test_space_containing_interpreter_path_is_one_token_in_plan(tmp_path):
    # Regression guard: SUMO_QA_PYTHON is a SINGLE interpreter path, not a
    # whitespace-split command line. A path containing a space must be treated
    # as one argv token — never split into two words (which would exec the
    # wrong path) and never glob-expanded. The printed plan must render it as a
    # single quoted, copy-pasteable token that matches what is executed.
    interp = tmp_path / "with space" / "python"
    interp.parent.mkdir()
    interp.write_text("#!/bin/sh\nexit 0\n")
    interp.chmod(0o755)
    _bash_or_skip()
    result = subprocess.run(
        [BASH, str(INSTALL_SH), "--print-plan"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={"PATH": "/usr/bin:/bin", "SUMO_QA_PYTHON": str(interp)},
    )
    assert result.returncode == 0, result.stderr
    pip_line = next(line for line in result.stdout.splitlines() if PIP_INSTALL in line)
    # The full path appears verbatim, single-quoted as ONE token...
    assert f"'{interp}'" in pip_line
    # ...and is NOT split at the space into a separate "space/python" word: with
    # the full path correctly single-quoted, removing that token leaves no
    # "space/python" residue; a bad two-word split would leave it behind.
    assert "space/python" not in pip_line.replace(f"'{interp}'", "")


def test_space_containing_interpreter_path_execs_as_one_token(tmp_path):
    # Drive the REAL exec path (not --print-plan) with SUMO_QA_PYTHON pointed
    # at a stub interpreter whose directory name contains a space. The stub
    # echoes the program path it was launched as; the wrapper must invoke the
    # full quoted path, not a truncated first word. The stub exits 0 so the
    # delegated pip/installer steps "succeed" without a real install.
    interp = tmp_path / "with space" / "python"
    interp.parent.mkdir()
    interp.write_text('#!/bin/sh\necho "LAUNCHED_AS:[$0]"\nexit 0\n')
    interp.chmod(0o755)
    _bash_or_skip()
    result = subprocess.run(
        [BASH, str(INSTALL_SH)],  # real exec path, install mode
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={"PATH": "/usr/bin:/bin", "SUMO_QA_PYTHON": str(interp)},
    )
    # The stub was launched with the FULL space-containing path as $0, proving
    # the wrapper exec'd it as a single token (a split would have tried to run
    # "<dir>/with", which does not exist and would fail command-not-found).
    assert f"LAUNCHED_AS:[{interp}]" in result.stdout, (
        result.returncode,
        result.stdout,
        result.stderr,
    )


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
    # Same canonical delegation targets as install.sh. The plan is built as
    # argv arrays (call operator, no Invoke-Expression), so assert on the
    # argv fragments rather than a single reconstructed command string.
    assert "'pip', 'install', 'sumo-qa'" in text
    assert "'pip', 'install', '--upgrade', 'sumo-qa'" in text
    assert "'sumo_qa.installer'" in text
    # Doctor via the resolved interpreter (-m sumo_qa.doctor), not the bare
    # console script — the argv-fragment form, matching install.sh.
    assert "'sumo_qa.doctor'" in text
    # Same mode switches.
    for switch in ("Update", "Doctor", "Uninstall", "PrintPlan"):
        assert switch in text, f"install.ps1 is missing the -{switch} switch"
    # Same verified host set.
    for host in ("claude-code", "vscode", "jetbrains"):
        assert host in text, f"install.ps1 is missing the {host} host mapping"
    # The public -Host flag is preserved via an alias even though the internal
    # parameter is renamed ($TargetHost) to avoid shadowing PowerShell's
    # read-only automatic $Host variable.
    assert "[Alias('Host')]" in text
    assert "$TargetHost" in text
    assert "param([string]$Host)" not in text  # never re-introduce the shadow


def test_powershell_wrapper_does_not_use_invoke_expression():
    # The exec path runs argv via the call operator, not Invoke-Expression,
    # so a SUMO_QA_PYTHON value with PowerShell metacharacters cannot inject.
    # Ignore comment lines (the rationale comments reference the term by name).
    for line in INSTALL_PS1.read_text().splitlines():
        code = line.split("#", 1)[0]
        assert "Invoke-Expression" not in code, line


def test_powershell_uninstall_routes_to_canonical_installer():
    # Static-only check (CI's Windows leg confirms at runtime): -Uninstall now
    # routes to the canonical installer's ownership-aware --uninstall path, NOT
    # a deferral. The wrapper itself runs nothing destructive directly.
    text = INSTALL_PS1.read_text()
    # Inspect the actual `'uninstall' {` switch-case BODY, not the
    # `$mode = 'uninstall'` assignment. The case ends at its closing brace, the
    # first `\n    }` at case indentation.
    uninstall_body = text.split("'uninstall' {", 1)[1].split("\n    }", 1)[0]
    # Routes the --uninstall flag to the canonical installer via Add-Cmd.
    assert "'sumo_qa.installer', '--uninstall'" in uninstall_body
    assert "Add-Cmd" in uninstall_body
    # No doctor after uninstall.
    assert "sumo_qa.doctor" not in uninstall_body
    assert "Add-Doctor" not in uninstall_body
    # Non-destructive: the body never auto-runs an uninstall or removes data
    # itself (the canonical installer does the ownership-aware removal).
    assert "Invoke-Expression" not in uninstall_body
    assert "Start-Process" not in uninstall_body
    assert "& 'pip'" not in uninstall_body
    assert "& pip" not in uninstall_body
    assert "Remove-Item" not in uninstall_body
    assert "pip uninstall" not in uninstall_body


def test_powershell_does_not_whitespace_split_the_interpreter_override():
    # Parity with install.sh: SUMO_QA_PYTHON is a single interpreter path, so
    # install.ps1 must NOT split it on whitespace (which would break a path
    # containing a space, e.g. 'C:\Program Files\Python\python'). The argv
    # array is built directly from the single value, not via `-split`.
    text = INSTALL_PS1.read_text()
    assert "$pythonArgv = @($python)" in text
    # The old whitespace-splitting form must never be reintroduced.
    assert "$python -split" not in text


@pytest.mark.skipif(
    shutil.which("pwsh") is None and shutil.which("powershell") is None,
    reason="no PowerShell interpreter available to parse install.ps1",
)
def test_powershell_space_path_binds_as_one_token():
    # pwsh-gated functional parity for the space-path fix: drive -PrintPlan
    # with SUMO_QA_PYTHON set to a path containing a space and assert it is
    # rendered as a single quoted token, not split into two words.
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    import os

    env = dict(os.environ)
    env["SUMO_QA_PYTHON"] = "/tmp/with space/python"
    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(INSTALL_PS1), "-PrintPlan"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    pip_line = next(line for line in result.stdout.splitlines() if "pip install sumo-qa" in line)
    # The full space-containing path is one quoted token...
    assert "'/tmp/with space/python'" in pip_line
    # ...never split into "/tmp/with" + "space/python".
    assert "/tmp/with " not in pip_line.replace("'/tmp/with space/python'", "")


@pytest.mark.skipif(
    shutil.which("pwsh") is None and shutil.which("powershell") is None,
    reason="no PowerShell interpreter available to parse install.ps1",
)
def test_powershell_host_flag_still_forwards_vscode():
    # Guard that the space-path fix did not break host-flag forwarding.
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(INSTALL_PS1), "-PrintPlan", "-Host", "vscode"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    installer_line = next(
        line for line in result.stdout.splitlines() if "sumo_qa.installer" in line
    )
    assert "--vscode" in installer_line


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
