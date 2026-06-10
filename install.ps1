<#
.SYNOPSIS
    sumo-qa one-command install wrapper (Windows PowerShell).

.DESCRIPTION
    THIN ROUTER ONLY. Windows parity for install.sh. Delegates to the
    canonical Python installer and adds no install logic of its own:

        py -m pip install sumo-qa      # the package (server + skills + knowledge)
        py -m sumo_qa.installer        # the canonical host-config writer
        sumo-qa-doctor                 # read-only post-install verification

    It exists so a first-time user runs ONE command instead of learning the
    pip / installer / doctor split. It must never become a second installer
    implementation, and it never bypasses the installer's own validation.

    Safety: no admin escalation, never deletes user-created .sumo-qa
    artifacts, never removes host config entries it cannot prove it owns. On
    failure it prints the exact command that failed and the next safe manual
    command.

    Uninstall routes to the canonical installer's ownership-aware
    --uninstall path. The Python installer writes a fixed-key entry
    ("sumo-qa" under mcpServers / servers) on install and removes exactly that
    key on uninstall, preserving every other MCP server. The wrapper just
    forwards the flag (plus the host flag, if any); it runs nothing
    destructive itself and never touches your .sumo-qa artifacts or the
    sumo-qa pip package (run 'pip uninstall sumo-qa' separately).

.PARAMETER Update
    Upgrade the package, refresh host configs, then run the doctor.

.PARAMETER Doctor
    Run the read-only doctor only (no install).

.PARAMETER Uninstall
    Remove the host config entries this installer wrote (ownership-aware) —
    the inverse of install; runs no doctor afterward.

.PARAMETER Host
    Limit install to one verified host: claude-code | vscode | jetbrains.

.PARAMETER PrintPlan
    Print the exact commands this script WOULD run, one per line, and exit
    without running anything (used for auditing / parity checks).

.EXAMPLE
    .\install.ps1
    Install for every host the installer detects, then run the doctor.

.EXAMPLE
    .\install.ps1 -Update
    Upgrade the package, refresh host configs, run the doctor.

.EXAMPLE
    .\install.ps1 -Host vscode
    Install for VS Code + Copilot only.
#>

[CmdletBinding()]
param(
    [switch]$Update,
    [switch]$Doctor,
    [switch]$Uninstall,
    # Public CLI flag stays -Host (kept via the alias) for documentation
    # parity, but the internal variable is $TargetHost so it does not shadow
    # PowerShell's read-only automatic $Host variable (which makes -Host fail
    # to bind on some PS versions).
    [Alias('Host')]
    [string]$TargetHost,
    [switch]$PrintPlan
)

$ErrorActionPreference = 'Stop'

# Emit an error message to stderr WITHOUT terminating. Under
# $ErrorActionPreference='Stop', a plain Write-Error throws and aborts before
# the following `exit <code>`, so the script would exit with PS's generic
# code 1 instead of the intended code. Writing straight to the error stream
# keeps our explicit exit codes (e.g. 2 for argument errors) intact.
function Write-ErrLine {
    param([string]$Message)
    [Console]::Error.WriteLine($Message)
}

# Resolve a Python launcher. Prefer the Windows `py` launcher, fall back to
# `python`. ($env:SUMO_QA_PYTHON overrides both, mirroring install.sh.)
$python = $env:SUMO_QA_PYTHON
if ([string]::IsNullOrEmpty($python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $python = 'py'
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $python = 'python'
    }
    else {
        Write-ErrLine "No 'py' or 'python' found on PATH. Install Python 3, then re-run .\install.ps1"
        exit 1
    }
}

# SUMO_QA_PYTHON (and the resolved fallback) is a SINGLE interpreter path or
# executable name, NOT a whitespace-split command line. Treat it as one argv
# element so a path containing spaces (e.g. 'C:\Program Files\Python\python')
# binds as one token and exec's correctly, instead of being split into two
# words that would invoke the wrong path. The default 'py' launcher is a
# single executable; it does not need the multi-word 'py -3' form here.
# @(...) forces an array so `$pythonArgv + @(...)` does array extension, not
# string concatenation.
$pythonArgv = @($python)

# Verified hosts the installer can target via a single flag. Keep in lockstep
# with python -m sumo_qa.installer; unverified hosts are rejected, never
# passed through as an unknown installer flag.
$HostFlag = @{
    'claude-code' = '--claude-code'
    'vscode'      = '--vscode'
    'jetbrains'   = '--jetbrains'
}

# Determine the mode (install | update | doctor | uninstall). Reject more
# than one mode flag rather than silently letting precedence win — a user
# who passed -Uninstall -Update must not get an update.
$modeFlags = @()
if ($Update) { $modeFlags += '-Update' }
if ($Doctor) { $modeFlags += '-Doctor' }
if ($Uninstall) { $modeFlags += '-Uninstall' }
if ($modeFlags.Count -gt 1) {
    Write-ErrLine "Conflicting mode flags: $($modeFlags -join ', '). Choose exactly one of -Update, -Doctor, -Uninstall."
    exit 2
}
$mode = 'install'
if ($Update) { $mode = 'update' }
if ($Doctor) { $mode = 'doctor' }
if ($Uninstall) { $mode = 'uninstall' }

$hostFlagValue = ''
# Validate whenever -Host was supplied at all — including an explicit empty
# string — so `-Host ''` is rejected like any other unverified value (parity
# with install.sh, which exits 2 on an empty host). Omitting -Host entirely
# leaves $PSBoundParameters without the key and falls through to all-host.
if ($PSBoundParameters.ContainsKey('TargetHost')) {
    if (-not $HostFlag.ContainsKey($TargetHost)) {
        Write-ErrLine @"
Unverified host '$TargetHost'.
Verified hosts: claude-code, vscode, jetbrains.
Next: re-run with one of those, or configure your host manually per
docs/INSTALL.md (other MCP hosts section).
"@
        exit 2
    }
    $hostFlagValue = $HostFlag[$TargetHost]
}

# Build the command plan as an ordered list. Each element is an argv array
# (string[]): element[0] is the program, the rest are arguments. Commands run
# via the call operator (&) with splatting — no Invoke-Expression, so a
# SUMO_QA_PYTHON value with PS metacharacters cannot inject.
$plan = New-Object System.Collections.Generic.List[object]

# Helper: append one command's argv to the plan as a flat string[].
function Add-Cmd { param([string[]]$Argv) $plan.Add([string[]]$Argv) }

# Render an argv array as a human-readable, copy-pasteable command line. Any
# token containing whitespace is single-quoted so the printed/echoed line
# matches what is executed (a space-containing interpreter path stays one
# token instead of looking like two words).
function Format-CmdLine {
    param([string[]]$Argv)
    ($Argv | ForEach-Object {
        # Single-quote any token with whitespace OR an embedded single quote,
        # doubling the quote ('') so the rendered line is valid, copy-paste
        # PowerShell even for an odd interpreter path like C:\O'Brien\python.
        if ($_ -match "[\s']") { "'" + ($_ -replace "'", "''") + "'" } else { $_ }
    }) -join ' '
}

switch ($mode) {
    'install' {
        Add-Cmd ($pythonArgv + @('-m', 'pip', 'install', 'sumo-qa'))
        if ($hostFlagValue) { Add-Cmd ($pythonArgv + @('-m', 'sumo_qa.installer', $hostFlagValue)) }
        else { Add-Cmd ($pythonArgv + @('-m', 'sumo_qa.installer')) }
        Add-Cmd @('sumo-qa-doctor')
    }
    'update' {
        Add-Cmd ($pythonArgv + @('-m', 'pip', 'install', '--upgrade', 'sumo-qa'))
        if ($hostFlagValue) { Add-Cmd ($pythonArgv + @('-m', 'sumo_qa.installer', $hostFlagValue)) }
        else { Add-Cmd ($pythonArgv + @('-m', 'sumo_qa.installer')) }
        Add-Cmd @('sumo-qa-doctor')
    }
    'doctor' {
        Add-Cmd @('sumo-qa-doctor')
    }
    'uninstall' {
        # Route to the canonical installer's ownership-aware --uninstall path.
        # No doctor afterward (nothing to verify once config is removed).
        if ($hostFlagValue) { Add-Cmd ($pythonArgv + @('-m', 'sumo_qa.installer', '--uninstall', $hostFlagValue)) }
        else { Add-Cmd ($pythonArgv + @('-m', 'sumo_qa.installer', '--uninstall')) }
    }
}

if ($PrintPlan) {
    foreach ($cmd in $plan) { Write-Output (Format-CmdLine $cmd) }
    exit 0
}

# Emit the friendly failure block and exit with the given code. Shared by
# both failure modes below so the message stays identical.
function Stop-WithFailure {
    param([string]$CmdLine, [int]$Code, [string]$Detail)
    # Write-Host (not Write-Error) so the message prints verbatim without PS
    # decorating it as a terminating error — which would mask the real native
    # exit code behind PS's generic failure stream.
    $tail = if ($Detail) { "`n$Detail" } else { '' }
    Write-Host @"

Command failed (exit ${Code}):
  $CmdLine$tail

Next safe step: run that command yourself to see the full error, then check
docs/INSTALL.md for the per-host manual install path. Nothing was deleted;
re-running .\install.ps1 is safe.
"@
    exit $Code
}

# Execute the plan as argv arrays. On failure, surface the exact failing
# command + next safe step, then stop. Handles BOTH a native non-zero exit
# AND a command-not-found / launch error (which throws under
# $ErrorActionPreference='Stop'), and propagates the real exit code.
foreach ($cmd in $plan) {
    $cmdLine = Format-CmdLine $cmd
    Write-Output "+ $cmdLine"
    $prog = $cmd[0]
    $rest = @($cmd | Select-Object -Skip 1)
    $global:LASTEXITCODE = 0
    try {
        & $prog @rest
    }
    catch {
        # Command-not-found, launch failure, or any terminating error from
        # invoking $prog. Preserve a native exit code if one was set; else 127
        # (the conventional "command not found" code).
        $code = if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { $LASTEXITCODE } else { 127 }
        Stop-WithFailure -CmdLine $cmdLine -Code $code -Detail $_.Exception.Message
    }
    if ($LASTEXITCODE -ne 0) {
        Stop-WithFailure -CmdLine $cmdLine -Code $LASTEXITCODE
    }
}

Write-Output ''
Write-Output 'Done. If a host was configured, restart it (or open a fresh chat) so it'
Write-Output 'picks up the sumo-qa MCP server and skills.'
