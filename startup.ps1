[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$SkipAntV,
    [switch]$SkipHarness,
    [switch]$SkipNodeGateway,
    [switch]$NoStart,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$nodeGatewayRoot = Join-Path $repoRoot "backend-node"
$antvRoot = Join-Path $repoRoot "pipelines\infographic\antv_renderer"
$harnessRoot = Join-Path $repoRoot "deepseek-harness"
$frontendRoot = Join-Path $repoRoot "frontend"
$stateRoot = Join-Path $repoRoot "artifacts\.state"
$logRoot = Join-Path $stateRoot "startup-logs"
$startedProcesses = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $false)][string]$WorkingDirectory = $repoRoot
    )
    Push-Location $WorkingDirectory
    try {
        & $Name @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$Name failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

function Require-Command {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$InstallHint
    )
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "$Name is required but was not found. $InstallHint"
    }
    return $command
}

function Resolve-Python {
    foreach ($candidate in @("py", "python")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -eq $command) { continue }
        try {
            $version = (& $command.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
            $parts = $version -split '\.'
            if ($parts.Count -ge 2 -and [int]$parts[0] -eq 3 -and [int]$parts[1] -ge 13) {
                return $command
            }
        }
        catch {
            # Try the next Python launcher when this candidate is not usable.
        }
    }
    throw "Python 3.13+ is required but was not found. Install it from https://www.python.org/downloads/windows/"
}

function Assert-NodeVersion {
    param([Parameter(Mandatory = $true)][string]$Executable)
    $versionText = (& $Executable --version).Trim()
    if ($versionText -notmatch '^v(\d+)\.(\d+)') {
        throw "Unable to determine the Node.js version from $Executable."
    }
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    if ($major -lt 22 -or ($major -eq 22 -and $minor -lt 19)) {
        throw "Node.js 22.19+ is required because the frozen DeepSeek Harness workspace targets Node 22. Install Node.js LTS from https://nodejs.org/"
    }
}

function Import-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        if ($trimmed -notmatch '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { continue }
        $name = $Matches[1]
        $value = $Matches[2].Trim()
        if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $existing = [Environment]::GetEnvironmentVariable($name, "Process")
        if ([string]::IsNullOrWhiteSpace($existing)) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Get-EnvValue([string]$Name) {
    return [Environment]::GetEnvironmentVariable($Name, "Process")
}

function Assert-LocalConfiguration {
    $critical = @("MONGODB_URI", "JWT_ACCESS_SECRET", "JWT_REFRESH_SECRET")
    $invalid = @($critical | Where-Object {
        $value = Get-EnvValue $_
        [string]::IsNullOrWhiteSpace($value) -or $value -match '<[^>]+>' -or $value -match '^replace-with-'
    })
    if ($invalid.Count -gt 0) {
        throw "Configure these values in .env before startup: $($invalid -join ', '). MongoDB Atlas and JWT secrets are required."
    }
    if ((Get-EnvValue "JWT_ACCESS_SECRET").Length -lt 32 -or (Get-EnvValue "JWT_REFRESH_SECRET").Length -lt 32) {
        throw "JWT_ACCESS_SECRET and JWT_REFRESH_SECRET must each be at least 32 characters."
    }
    if ((Get-EnvValue "JWT_ACCESS_SECRET") -eq (Get-EnvValue "JWT_REFRESH_SECRET")) {
        throw "JWT_ACCESS_SECRET and JWT_REFRESH_SECRET must be different values."
    }
    if ((Get-EnvValue "MONGODB_URI") -notmatch '^mongodb(\+srv)?://') {
        throw "MONGODB_URI must be a mongodb:// or mongodb+srv:// connection string."
    }
    $sameSiteValue = Get-EnvValue "COOKIE_SAME_SITE"
    if ([string]::IsNullOrWhiteSpace($sameSiteValue)) { $sameSiteValue = "lax" }
    $sameSite = $sameSiteValue.ToLower()
    if ($sameSite -notin @("lax", "strict", "none")) {
        throw "COOKIE_SAME_SITE must be lax, strict, or none."
    }
    $secureValue = Get-EnvValue "COOKIE_SECURE"
    if ([string]::IsNullOrWhiteSpace($secureValue)) { $secureValue = "false" }
    if ($sameSite -eq "none" -and $secureValue.ToLower() -ne "true") {
        throw "COOKIE_SAME_SITE=none requires COOKIE_SECURE=true."
    }
    if ([string]::IsNullOrWhiteSpace((Get-EnvValue "GOOGLE_CLIENT_ID")) -or [string]::IsNullOrWhiteSpace((Get-EnvValue "GOOGLE_CLIENT_SECRET")) -or (Get-EnvValue "GOOGLE_CLIENT_ID") -match '<[^>]+>' -or (Get-EnvValue "GOOGLE_CLIENT_SECRET") -match '<[^>]+>') {
        Write-Warning "Google OAuth is not configured; the gateway will start but browser sign-in will be unavailable."
    }
}

function Get-Port([string]$Name, [int]$Fallback) {
    $value = Get-EnvValue $Name
    $port = 0
    if ([string]::IsNullOrWhiteSpace($value) -or -not [int]::TryParse($value, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        return $Fallback
    }
    return $port
}

function Assert-PortFree([int]$Port, [string]$Service) {
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        $owners = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
        throw "$Service cannot start because port $Port is already in use by process $owners."
    }
}

function Start-LocalService {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )
    $stdout = Join-Path $logRoot "$Name.out.log"
    $stderr = Join-Path $logRoot "$Name.err.log"
    $argumentLine = ($Arguments | ForEach-Object {
        $argument = [string]$_
        if ($argument -match '[\s"]') { '"' + $argument.Replace('"', '\"') + '"' } else { $argument }
    }) -join " "
    $process = Start-Process -FilePath $FilePath -ArgumentList $argumentLine -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    $startedProcesses.Add($process)
    Write-Host "$Name started (PID $($process.Id)). Logs: $stdout"
    return $process
}

function Stop-StartedServices {
    foreach ($process in $startedProcesses) {
        try {
            if (-not $process.HasExited) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
        }
        catch { }
    }
}

function Wait-Http {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Service,
        [int]$TimeoutSeconds = 60
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                return
            }
        }
        catch {
            # The service may still be importing its dependency graph.
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    throw "$Service did not become ready at $Url. Check $logRoot\$Service.err.log"
}

try {
    Set-Location $repoRoot
    foreach ($requiredPath in @($nodeGatewayRoot, $frontendRoot, $repoRoot)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Container)) {
            throw "Required repository directory is missing: $requiredPath"
        }
    }
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

    $envFile = Join-Path $repoRoot ".env"
    $exampleFile = Join-Path $repoRoot ".env.example"
    if (-not (Test-Path -LiteralPath $exampleFile -PathType Leaf)) {
        throw "Unified environment template is missing: $exampleFile"
    }
    if (-not (Test-Path -LiteralPath $envFile)) {
        Copy-Item -LiteralPath $exampleFile -Destination $envFile
        Write-Warning "Created .env from .env.example. Fill MongoDB Atlas, JWT, Google, and provider values, then rerun startup.ps1."
    }
    Import-DotEnv $envFile
    if (-not $SkipNodeGateway) {
        Assert-LocalConfiguration
    }

    $pythonCommand = Resolve-Python
    $needsNode = -not $SkipNodeGateway -or -not $SkipAntV -or -not $SkipHarness
    $nodeCommand = $null
    $npmCommand = $null
    if ($needsNode) {
        $nodeCommand = Require-Command "node" "Install Node.js 22 LTS or newer from https://nodejs.org/"
        $npmCommand = Require-Command "npm" "Install Node.js 22 LTS or newer from https://nodejs.org/"
        Assert-NodeVersion $nodeCommand.Source
    }
    if (-not $SkipHarness) {
        $pnpmCommand = Get-Command "pnpm" -ErrorAction SilentlyContinue
        if ($null -eq $pnpmCommand) {
            Write-Host "pnpm was not found; installing the pinned pnpm runtime..."
            Invoke-Checked $npmCommand.Source @("install", "--global", "pnpm@11.7.0")
            $pnpmCommand = Require-Command "pnpm" "Restart PowerShell after installing pnpm and rerun startup.ps1."
        }
    }
    $uvCommand = Get-Command "uv" -ErrorAction SilentlyContinue
    if ($null -eq $uvCommand) {
        Write-Host "uv was not found; bootstrapping it with Python..."
        Invoke-Checked $pythonCommand.Source @("-m", "pip", "install", "--user", "uv")
        $scriptsPath = (& $pythonCommand.Source -c "import sysconfig; print(sysconfig.get_path('scripts'))").Trim()
        $uvCandidate = Join-Path $scriptsPath "uv.exe"
        if (-not (Test-Path -LiteralPath $uvCandidate)) {
            throw "uv was installed but could not be located at $uvCandidate. Restart PowerShell and rerun startup.ps1."
        }
        $uvExecutable = $uvCandidate
    }
    else {
        $uvExecutable = $uvCommand.Source
    }

    if (-not $SkipInstall) {
        Write-Host "Installing the locked Python environment..."
        Invoke-Checked $uvExecutable @("sync", "--locked")

        if (-not $SkipAntV) {
            Write-Host "Installing the pinned AntV renderer..."
            Invoke-Checked $npmCommand.Source @("ci", "--ignore-scripts", "--no-audit", "--no-fund") $antvRoot
        }
        if (-not $SkipHarness) {
            Write-Host "Installing the frozen DeepSeek Harness workspace..."
            Invoke-Checked $pnpmCommand.Source @("install", "--frozen-lockfile") $harnessRoot
        }
        if (-not $SkipNodeGateway) {
            Write-Host "Installing the locked Node gateway dependencies..."
            Invoke-Checked $npmCommand.Source @("ci", "--ignore-scripts", "--no-audit", "--no-fund") $nodeGatewayRoot
        }
    }

    $pythonPort = Get-Port "SUDARSHAN_API_PORT" 8000
    $nodePort = Get-Port "PORT" 8080
    $frontendPort = Get-Port "SUDARSHAN_FRONTEND_PORT" 3000
    if (-not $NoStart) {
        Assert-PortFree $pythonPort "Python orchestrator/pipelines API"
        if (-not $SkipNodeGateway) { Assert-PortFree $nodePort "Node gateway" }
        Assert-PortFree $frontendPort "Frontend"
    }

    if (-not $SkipNodeGateway) {
        Write-Host "Building MongoDB Atlas collections and indexes..."
        Invoke-Checked $npmCommand.Source @("run", "db:init", "--silent") $nodeGatewayRoot
    }

    if ($NoStart) {
        Write-Host "Dependency installation and database initialization complete. Services were not started (-NoStart)."
        exit 0
    }

    $env:SUDARSHAN_API_PORT = [string]$pythonPort
    $env:PORT = [string]$nodePort
    $env:SUDARSHAN_FRONTEND_PORT = [string]$frontendPort
    $pythonProcess = Start-LocalService "python-api" $uvExecutable @("run", "python", "-m", "api.server") $repoRoot
    Wait-Http "http://127.0.0.1:$pythonPort/health" "python-api"

    if (-not $SkipNodeGateway) {
        $nodeProcess = Start-LocalService "node-gateway" $nodeCommand.Source @("src/server.js") $nodeGatewayRoot
        Wait-Http "http://127.0.0.1:$nodePort/readyz" "node-gateway"
    }

    $frontendHost = Get-EnvValue "SUDARSHAN_FRONTEND_HOST"
    if ([string]::IsNullOrWhiteSpace($frontendHost)) { $frontendHost = "127.0.0.1" }
    $frontendProcess = Start-LocalService "frontend" $pythonCommand.Source @("-m", "http.server", [string]$frontendPort, "--bind", $frontendHost, "--directory", $frontendRoot) $repoRoot
    Wait-Http "http://127.0.0.1:$frontendPort/login.html" "frontend"

    $frontendUrl = "http://localhost:$frontendPort/login.html"
    Write-Host ""
    Write-Host "Sudarshan is running locally:" -ForegroundColor Green
    Write-Host "  Frontend:   $frontendUrl"
    Write-Host "  Node API:   http://localhost:$nodePort"
    Write-Host "  Python API: http://localhost:$pythonPort"
    Write-Host "  Logs:       $logRoot"
    if ($OpenBrowser -or (Get-EnvValue "SUDARSHAN_OPEN_BROWSER") -eq "true") {
        Start-Process $frontendUrl
    }
}
catch {
    Stop-StartedServices
    Write-Error $_
    exit 1
}
