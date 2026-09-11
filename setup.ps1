param(
    [switch]$SkipInstall,
    [switch]$SkipAntV,
    [switch]$SkipHarness,
    [switch]$EnableHarness,
    [switch]$SkipNodeGateway,
    [switch]$SkipDatabaseInit,
    [switch]$ForceRestart,
    [switch]$NoStart,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"
# Backward-compatible name retained for existing deployment scripts. The
# canonical one-command backend bootstrap is startup.ps1.
$startup = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "startup.ps1"
$arguments = @()
if ($SkipInstall) { $arguments += "-SkipInstall" }
if ($SkipAntV) { $arguments += "-SkipAntV" }
if ($SkipHarness) { $arguments += "-SkipHarness" }
if ($EnableHarness) { $arguments += "-EnableHarness" }
if ($SkipNodeGateway) { $arguments += "-SkipNodeGateway" }
if ($SkipDatabaseInit) { $arguments += "-SkipDatabaseInit" }
if ($ForceRestart) { $arguments += "-ForceRestart" }
if ($NoStart) { $arguments += "-NoStart" }
if ($OpenBrowser) { $arguments += "-OpenBrowser" }
& $startup @arguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
