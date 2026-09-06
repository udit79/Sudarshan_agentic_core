param(
    [switch]$SkipAntV,
    [switch]$SkipHarness
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$antvRoot = Join-Path $repoRoot "pipelines\infographic\antv_renderer"
$harnessRoot = Join-Path $repoRoot "deepseek-harness"
if ([string]::IsNullOrWhiteSpace($env:UV_CACHE_DIR)) {
    $env:UV_CACHE_DIR = Join-Path $repoRoot ".uv-cache"
}

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

function Resolve-Python {
    foreach ($candidate in @("py", "python")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -ne $command) {
            return $command
        }
    }
    throw "Python 3.13+ is required but was not found. Install it from https://www.python.org/downloads/windows/"
}

$pythonCommand = Resolve-Python
$uvCommand = Get-Command "uv" -ErrorAction SilentlyContinue
$uvExecutable = $null
if ($null -ne $uvCommand) {
    $uvExecutable = $uvCommand.Source
}
if ($null -eq $uvCommand) {
    Write-Host "uv was not found; bootstrapping it with Python..."
    Invoke-Checked $pythonCommand.Source @("-m", "pip", "install", "--user", "uv")
    $scriptsPath = (& $pythonCommand.Source -c "import sysconfig; print(sysconfig.get_path('scripts'))").Trim()
    $uvCandidate = Join-Path $scriptsPath "uv.exe"
    if (-not (Test-Path -LiteralPath $uvCandidate)) {
        throw "uv was installed but could not be located at $uvCandidate. Restart PowerShell and rerun setup.ps1."
    }
    $uvExecutable = $uvCandidate
}

if (-not $SkipAntV -or -not $SkipHarness) {
    Require-Command "npm" "Install Node.js LTS from https://nodejs.org/"
}

$pnpmCommand = $null
$pnpmPrefix = @()
if (-not $SkipHarness) {
    $pnpmCommand = Get-Command "pnpm" -ErrorAction SilentlyContinue
    if ($null -ne $pnpmCommand) {
        # Use an installed pnpm binary directly. This avoids a Corepack registry
        # signature lookup when the pinned package manager is already present.
        $pnpmPrefix = @("--config.pm-on-fail=ignore")
    }
    else {
        Write-Host "pnpm was not found; installing the pinned pnpm runtime with npm..."
        Invoke-Checked "npm" @("install", "--global", "pnpm@11.7.0")
        $pnpmCommand = Get-Command "pnpm" -ErrorAction SilentlyContinue
        if ($null -eq $pnpmCommand) {
            throw "pnpm installation completed but pnpm is not on PATH. Restart PowerShell and rerun setup.ps1."
        }
        $pnpmPrefix = @("--config.pm-on-fail=ignore")
    }
}

Push-Location $repoRoot
try {
    Write-Host "Installing Python dependencies..."
    Invoke-Checked $uvExecutable @("sync", "--locked")

    if (-not $SkipAntV) {
        Write-Host "Installing the pinned AntV infographic renderer..."
        Push-Location $antvRoot
        try {
            Invoke-Checked "npm" @("ci", "--ignore-scripts")
        }
        finally {
            Pop-Location
        }
    }

    if (-not $SkipHarness) {
        Write-Host "Installing the pinned DeepSeek Harness workspace..."
        Push-Location $harnessRoot
        try {
            Invoke-Checked $pnpmCommand.Source ($pnpmPrefix + @("install", "--frozen-lockfile"))
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
if (-not $SkipHarness) {
    Write-Host "DeepSeek Harness: deepseek-harness"
}
