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

    Uninstall is DEFERRED on purpose. The canonical installer has no
    --uninstall subcommand, and a clean uninstall means editing host config
    files (the "sumo-qa" key under mcpServers / servers) this wrapper cannot
    prove it owns. Until the Python installer grows an ownership-aware
    uninstall, the wrapper routes users to docs/INSTALL.md#uninstall.

.PARAMETER Update
    Upgrade the package, refresh host configs, then run the doctor.

.PARAMETER Doctor
    Run the read-only doctor only (no install).

.PARAMETER Uninstall
    Print the documented manual uninstall steps (deferred — runs nothing
    destructive).

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
    [string]$Host,
    [switch]$PrintPlan
)

$ErrorActionPreference = 'Stop'

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
        Write-Error "No 'py' or 'python' found on PATH. Install Python 3, then re-run .\install.ps1"
        exit 1
    }
}

# Verified hosts the installer can target via a single flag. Keep in lockstep
# with python -m sumo_qa.installer; unverified hosts are rejected, never
# passed through as an unknown installer flag.
$HostFlag = @{
    'claude-code' = '--claude-code'
    'vscode'      = '--vscode'
    'jetbrains'   = '--jetbrains'
}

# Determine the mode (install | update | doctor | uninstall).
$mode = 'install'
if ($Update) { $mode = 'update' }
if ($Doctor) { $mode = 'doctor' }
if ($Uninstall) { $mode = 'uninstall' }

$hostFlagValue = ''
if (-not [string]::IsNullOrEmpty($Host)) {
    if (-not $HostFlag.ContainsKey($Host)) {
        Write-Error @"
Unverified host '$Host'.
Verified hosts: claude-code, vscode, jetbrains.
Next: re-run with one of those, or configure your host manually per
docs/INSTALL.md (other MCP hosts section).
"@
        exit 2
    }
    $hostFlagValue = $HostFlag[$Host]
}

# Build the command plan as an ordered list, one command string per element.
$plan = New-Object System.Collections.Generic.List[string]

switch ($mode) {
    'install' {
        $plan.Add("$python -m pip install sumo-qa")
        if ($hostFlagValue) { $plan.Add("$python -m sumo_qa.installer $hostFlagValue") }
        else { $plan.Add("$python -m sumo_qa.installer") }
        $plan.Add('sumo-qa-doctor')
    }
    'update' {
        $plan.Add("$python -m pip install --upgrade sumo-qa")
        if ($hostFlagValue) { $plan.Add("$python -m sumo_qa.installer $hostFlagValue") }
        else { $plan.Add("$python -m sumo_qa.installer") }
        $plan.Add('sumo-qa-doctor')
    }
    'doctor' {
        $plan.Add('sumo-qa-doctor')
    }
    'uninstall' {
        if ($PrintPlan) {
            Write-Output '# uninstall is deferred - no automated uninstall command is run.'
            Write-Output '# See docs/INSTALL.md#uninstall for the manual steps.'
            exit 0
        }
        Write-Warning @"
Automated uninstall is not available yet.

A clean uninstall edits host config files (the "sumo-qa" entry under
mcpServers / servers) that this wrapper cannot prove it owns, so it will not
guess and risk removing your other MCP servers.

Follow the documented manual steps instead:

  docs/INSTALL.md#uninstall

In short: 'pip uninstall sumo-qa', then remove the "sumo-qa" entry from each
host config you configured (Claude Code, Claude Desktop, VS Code, JetBrains).
Your .sumo-qa repo artifacts are yours to keep or delete; the uninstall never
touches them.
"@
        exit 0
    }
}

if ($PrintPlan) {
    foreach ($cmd in $plan) { Write-Output $cmd }
    exit 0
}

# Execute the plan. On failure, surface the exact failing command and the
# next safe manual step, then stop.
foreach ($cmd in $plan) {
    Write-Output "+ $cmd"
    Invoke-Expression $cmd
    if ($LASTEXITCODE -ne 0) {
        Write-Error @"

Command failed (exit $LASTEXITCODE):
  $cmd

Next safe step: run that command yourself to see the full error, then check
docs/INSTALL.md for the per-host manual install path. Nothing was deleted;
re-running .\install.ps1 is safe.
"@
        exit $LASTEXITCODE
    }
}

Write-Output ''
Write-Output 'Done. If a host was configured, restart it (or open a fresh chat) so it'
Write-Output 'picks up the sumo-qa MCP server and skills.'
