param(
    [switch]$SkipAntV
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$antvRoot = Join-Path $repoRoot "pipelines\infographic\antv_renderer"

function Require-Command {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$InstallHint
    )
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is required but was not found. $InstallHint"
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & $Name @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

Require-Command "uv" "Install it from https://docs.astral.sh/uv/getting-started/installation/"
if (-not $SkipAntV) {
    Require-Command "npm" "Install Node.js LTS from https://nodejs.org/"
}

Push-Location $repoRoot
try {
    Write-Host "Installing Python dependencies..."
    Invoke-Checked "uv" @("sync")

    if (-not $SkipAntV) {
        Write-Host "Installing the pinned AntV infographic renderer..."
        Push-Location $antvRoot
        try {
            Invoke-Checked "npm" @("install", "--ignore-scripts")
        }
        finally {
            Pop-Location
        }
    }
}
finally {
    Pop-Location
}

Write-Host "Sudarshan setup complete."
Write-Host "Python environment: .venv"
if (-not $SkipAntV) {
    Write-Host "AntV renderer: pipelines/infographic/antv_renderer"
}
