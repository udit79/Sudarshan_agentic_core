param(
    [switch]$SkipInstall,
    [switch]$SkipAntV,
    [switch]$SkipHarness,
    [switch]$SkipNodeGateway,
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
if ($SkipNodeGateway) { $arguments += "-SkipNodeGateway" }
if ($NoStart) { $arguments += "-NoStart" }
if ($OpenBrowser) { $arguments += "-OpenBrowser" }
& $startup @arguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
