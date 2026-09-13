[CmdletBinding()]
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
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$nodeGatewayRoot = Join-Path $repoRoot "backend-node"
$antvRoot = Join-Path $repoRoot "pipelines\infographic\antv_renderer"
$harnessRoot = Join-Path $repoRoot "deepseek-harness"
$useHarness = -not $SkipHarness
$landingRoot = Join-Path $repoRoot "landing page\landing page"
$stateRoot = Join-Path $repoRoot "artifacts\.state"
$logRoot = Join-Path $stateRoot "startup-logs"
$processManifestPath = Join-Path $stateRoot "sudarshan-processes.json"
$startedProcesses = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()
$startedServices = [System.Collections.Generic.List[object]]::new()

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
        throw "Node.js 22.19+ is required because the selected Node workspace targets Node 22. Install Node.js LTS from https://nodejs.org/"
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

function Resolve-MongoSrvUriForWindows {
    $uri = Get-EnvValue "MONGODB_URI"
    if ([string]::IsNullOrWhiteSpace($uri) -or $uri -notmatch '^mongodb\+srv://') {
        return
    }
    if ($uri -notmatch '^mongodb\+srv://(?<authority>[^/]+)(?<path>/[^?]*)?(?:\?(?<query>.*))?$') {
        throw "MONGODB_URI is not a valid MongoDB SRV connection string."
    }

    $authority = $Matches.authority
    $path = $Matches.path
    if ([string]::IsNullOrWhiteSpace($path)) { $path = "/" }
    $query = $Matches.query
    $atIndex = $authority.LastIndexOf("@")
    $userinfo = ""
    $mongoHost = $authority
    if ($atIndex -ge 0) {
        $userinfo = $authority.Substring(0, $atIndex)
        $mongoHost = $authority.Substring($atIndex + 1)
    }
    if ($mongoHost -match ":\d+$") {
        throw "MONGODB_URI SRV host must not include a port."
    }

    try {
        $srvRecords = @(Resolve-DnsName -Name "_mongodb._tcp.$mongoHost" -Type SRV -ErrorAction Stop | Where-Object Type -eq "SRV")
    }
    catch {
        throw "MongoDB Atlas SRV lookup failed through Windows DNS for $mongoHost. Check the active DNS/VPN connection. $($_.Exception.Message)"
    }
    try {
        $txtRecords = @(Resolve-DnsName -Name $mongoHost -Type TXT -ErrorAction Stop | Where-Object Type -eq "TXT")
    }
    catch {
        $txtRecords = @()
    }
    if ($srvRecords.Count -eq 0) {
        throw "MongoDB Atlas returned no SRV hosts for $mongoHost."
    }

    $options = [ordered]@{}
    foreach ($record in $txtRecords) {
        foreach ($text in @($record.Strings)) {
            foreach ($pair in ([string]$text -split "&")) {
                if ($pair -match "^([^=]+)=(.*)$" -and -not $options.Contains($Matches[1])) {
                    $options[$Matches[1]] = $Matches[2]
                }
            }
        }
    }
    foreach ($pair in @([string]$query -split "&")) {
        if ($pair -match "^([^=]+)=(.*)$") {
            $options[$Matches[1]] = $Matches[2]
        }
    }
    if (-not $options.Contains("tls") -and -not $options.Contains("ssl")) {
        $options["tls"] = "true"
    }

    $seeds = ($srvRecords | Sort-Object Priority, Weight | ForEach-Object {
        "$($_.NameTarget.TrimEnd('.')):$($_.Port)"
    }) -join ","
    $queryText = (($options.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join "&")
    $credentialPrefix = if ([string]::IsNullOrWhiteSpace($userinfo)) { "" } else { "$userinfo@" }
    $convertedUri = "mongodb://$credentialPrefix$seeds$path`?$queryText"
    [Environment]::SetEnvironmentVariable("MONGODB_URI", $convertedUri, "Process")
    Write-Host "Resolved MongoDB Atlas SRV records through Windows DNS for Node.js."
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

function Write-FrontendRuntimeConfig {
    param(
        [Parameter(Mandatory = $true)][int]$NodePort,
        [Parameter(Mandatory = $true)][int]$PythonPort,
        [Parameter(Mandatory = $true)][int]$HarnessPort
    )
    $configPath = Join-Path $landingRoot "public\runtime-config.local.js"
    $gatewayOrigin = Get-EnvValue "SUDARSHAN_FRONTEND_API_ORIGIN"
    if ([string]::IsNullOrWhiteSpace($gatewayOrigin)) { $gatewayOrigin = "http://localhost:$NodePort" }
    $fastApiOrigin = Get-EnvValue "SUDARSHAN_FRONTEND_FASTAPI_ORIGIN"
    if ([string]::IsNullOrWhiteSpace($fastApiOrigin)) { $fastApiOrigin = "http://localhost:$PythonPort" }
    $harnessUrl = Get-EnvValue "SUDARSHAN_HARNESS_URL"
    if ([string]::IsNullOrWhiteSpace($harnessUrl)) { $harnessUrl = "http://localhost:$HarnessPort/" }
    $config = [ordered]@{
        apiOrigin = $gatewayOrigin.TrimEnd('/')
        fastApiOrigin = $fastApiOrigin.TrimEnd('/')
        harnessUrl = $harnessUrl
    } | ConvertTo-Json -Compress
    Set-Content -LiteralPath $configPath -Value @"
window.SUDARSHAN_RUNTIME_CONFIG = $config;
window.SUDARSHAN_API_ORIGIN = window.SUDARSHAN_RUNTIME_CONFIG.apiOrigin;
window.SUDARSHAN_FASTAPI_ORIGIN = window.SUDARSHAN_RUNTIME_CONFIG.fastApiOrigin;
window.SUDARSHAN_HARNESS_URL = window.SUDARSHAN_RUNTIME_CONFIG.harnessUrl;
"@ -Encoding utf8
}

function Assert-PortFree([int]$Port, [string]$Service) {
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        $owners = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
        throw "$Service cannot start because port $Port is already in use by process $owners."
    }
}

function Stop-ExistingManifestServices {
    if (-not (Test-Path -LiteralPath $processManifestPath -PathType Leaf)) { return }
    try {
        $manifest = Get-Content -LiteralPath $processManifestPath -Raw | ConvertFrom-Json
    }
    catch {
        Write-Warning "Ignoring unreadable stale process manifest: $processManifestPath"
        Remove-Item -LiteralPath $processManifestPath -Force -ErrorAction SilentlyContinue
        return
    }
    $manifestRoot = [IO.Path]::GetFullPath([string]$manifest.repo_root)
    $currentRoot = [IO.Path]::GetFullPath($repoRoot)
    if ($manifestRoot.TrimEnd('\') -ine $currentRoot.TrimEnd('\')) {
        throw "Refusing to stop processes from another repository: $manifestRoot"
    }
    foreach ($service in @($manifest.services)) {
        $processId = 0
        if (-not [int]::TryParse([string]$service.pid, [ref]$processId) -or $processId -le 0) { continue }
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -eq $process) { continue }
        Write-Host "Stopping existing $($service.name) (PID $processId) for restart..."
        Stop-Process -Id $processId -Force -ErrorAction Stop
    }
    Remove-Item -LiteralPath $processManifestPath -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 400
}

function Start-LocalService {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $false)][int]$Port = 0
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
    $startedServices.Add([ordered]@{
        name = $Name
        pid = $process.Id
        port = $Port
        stdout = $stdout
        stderr = $stderr
    })
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
    if (Test-Path -LiteralPath $processManifestPath -PathType Leaf) {
        Remove-Item -LiteralPath $processManifestPath -Force -ErrorAction SilentlyContinue
    }
}

function Write-ProcessManifest {
    $payload = [ordered]@{
        schema_version = 1
        repo_root = $repoRoot
        started_at = (Get-Date).ToUniversalTime().ToString("o")
        services = @($startedServices.ToArray())
    }
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $processManifestPath -Encoding UTF8
}

function Wait-Http {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Service,
        [int]$TimeoutSeconds = 60,
        [System.Diagnostics.Process]$Process = $null,
        [switch]$AcceptUnauthorized
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            if ($null -ne $Process -and $Process.HasExited) {
                $errorLog = Join-Path $logRoot "$Service.err.log"
                $diagnostic = if (Test-Path -LiteralPath $errorLog) { (Get-Content -LiteralPath $errorLog -Tail 20 -ErrorAction SilentlyContinue) -join "`n" } else { "No stderr log was created." }
                throw "$Service exited before becoming ready (PID $($Process.Id)).`n$diagnostic"
            }
            # Keep this compatible with Windows PowerShell 5.1 as well as
            # PowerShell 7; -SkipHttpErrorCheck exists only in newer shells.
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
            if (($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) -or ($AcceptUnauthorized -and $response.StatusCode -eq 401)) {
                return
            }
        }
        catch {
            $statusCode = 0
            try { $statusCode = [int]$_.Exception.Response.StatusCode } catch { }
            if ($AcceptUnauthorized -and $statusCode -eq 401) { return }
            # The service may still be importing its dependency graph.
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    throw "$Service did not become ready at $Url. Check $logRoot\$Service.err.log"
}

try {
    Set-Location $repoRoot
    foreach ($requiredPath in @($nodeGatewayRoot, $landingRoot, $repoRoot)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Container)) {
            throw "Required repository directory is missing: $requiredPath"
        }
    }
    if ($useHarness -and -not (Test-Path -LiteralPath $harnessRoot -PathType Container)) {
        throw "DeepSeek Harness directory is missing: $harnessRoot"
    }
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    if ($ForceRestart) {
        Stop-ExistingManifestServices
    }
    foreach ($artifactDirectory in @(
        (Join-Path $repoRoot "artifacts\presentations"),
        (Join-Path $repoRoot "artifacts\videos"),
        (Join-Path $repoRoot "artifacts\.state\quality_reports"),
        (Join-Path $repoRoot "artifacts\.state\memory-events")
    )) {
        New-Item -ItemType Directory -Path $artifactDirectory -Force | Out-Null
    }

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
    $needsNode = $true
    $nodeCommand = $null
    $npmCommand = $null
    if ($needsNode) {
        $nodeCommand = Require-Command "node" "Install Node.js 22 LTS or newer from https://nodejs.org/"
        # Windows PowerShell resolves `npm` to npm.ps1, which cannot be
        # launched by Start-Process. Prefer the native npm.cmd shim so both
        # dependency commands and the Vite child process work in PS 5.1.
        $npmCommand = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
        if ($null -eq $npmCommand) {
            $npmCommand = Require-Command "npm" "Install Node.js 22 LTS or newer from https://nodejs.org/"
        }
        Assert-NodeVersion $nodeCommand.Source
    }
    if ($useHarness) {
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
        if ($useHarness) {
            Write-Host "Installing the frozen DeepSeek Harness workspace..."
            Invoke-Checked $pnpmCommand.Source @("install", "--frozen-lockfile") $harnessRoot
        }
        if (-not $SkipNodeGateway) {
            Write-Host "Installing the locked Node gateway dependencies..."
            Invoke-Checked $npmCommand.Source @("ci", "--ignore-scripts", "--no-audit", "--no-fund") $nodeGatewayRoot
        }
        Write-Host "Installing the locked landing frontend dependencies..."
        Invoke-Checked $npmCommand.Source @("ci", "--no-audit", "--no-fund") $landingRoot
    }

    if ($useHarness) {
        Write-Host "Building the complete Sudarshan Harness client bundles..."
        # The Harness client packages consume generated remote contracts from
        # the host library build. Build the complete client graph because the
        # runtime loader composes every registered client package, not only the
        # three Sudarshan packages customized by this repository.
        Invoke-Checked $npmCommand.Source @("run", "build:lib:host") $harnessRoot
        # The aggregate client tsconfig currently includes browser tests and
        # source-linked workspace edges that fail its type-only validation in
        # this checkout. Startup needs the emitted project-reference artifacts
        # for tsdown; the normal typecheck remains a separate CI concern.
        Invoke-Checked $nodeCommand.Source @(
            "node_modules/typescript/bin/tsc",
            "-b",
            "tsconfig.client.json",
            "--noCheck"
        ) $harnessRoot
        $tsdownCommand = Join-Path $harnessRoot "node_modules\.bin\tsdown.cmd"
        if (-not (Test-Path -LiteralPath $tsdownCommand -PathType Leaf)) {
            throw "Harness build tool is missing: $tsdownCommand"
        }
        Invoke-Checked $tsdownCommand @("--env.DSH_BUILD_FACE", "client") $harnessRoot
        # dsh web serves the application shell from apps/web/dist. The host
        # and client library builds above do not produce that Vite artifact;
        # without it, authenticated requests reach the Harness but return 404.
        Invoke-Checked $pnpmCommand.Source @(
            "--filter", "@deepseek-ai/dsh-web-frontend",
            "run", "build"
        ) $harnessRoot
    }

    $pythonPort = Get-Port "SUDARSHAN_API_PORT" 8000
    $nodePort = Get-Port "PORT" 8080
    $landingPort = Get-Port "SUDARSHAN_FRONTEND_PORT" 4173
    $harnessPort = Get-Port "SUDARSHAN_HARNESS_PORT" 3080
    Write-FrontendRuntimeConfig -NodePort $nodePort -PythonPort $pythonPort -HarnessPort $harnessPort
    if (-not $NoStart) {
        Assert-PortFree $pythonPort "Python orchestrator/pipelines API"
        if (-not $SkipNodeGateway) { Assert-PortFree $nodePort "Node gateway" }
        Assert-PortFree $landingPort "Landing app"
        if ($useHarness) { Assert-PortFree $harnessPort "DeepSeek Harness" }
    }

    if (-not $SkipNodeGateway -and -not $SkipDatabaseInit) {
        Resolve-MongoSrvUriForWindows
        Write-Host "Building MongoDB Atlas collections and indexes..."
        Invoke-Checked $npmCommand.Source @("run", "db:init", "--silent") $nodeGatewayRoot
    }

    if ($NoStart) {
        Write-Host "Dependency installation and database initialization complete. Services were not started (-NoStart)."
        exit 0
    }

    $viteShim = Join-Path $landingRoot "node_modules\.bin\vite.cmd"
    if (-not (Test-Path -LiteralPath $viteShim -PathType Leaf)) {
        throw "Landing dependencies are missing. Rerun startup.ps1 without -SkipInstall so the landing package can run npm ci."
    }

    $env:SUDARSHAN_API_PORT = [string]$pythonPort
    $env:PORT = [string]$nodePort
    $env:SUDARSHAN_FRONTEND_PORT = [string]$landingPort
    $env:SUDARSHAN_HARNESS_PORT = [string]$harnessPort
    $pythonProcess = Start-LocalService "python-api" $uvExecutable @("run", "python", "-m", "api.server") $repoRoot -Port $pythonPort
    Wait-Http "http://127.0.0.1:$pythonPort/health" "python-api" -Process $pythonProcess

    if (-not $SkipNodeGateway) {
        $nodeProcess = Start-LocalService "node-gateway" $nodeCommand.Source @("src/server.js") $nodeGatewayRoot -Port $nodePort
        Wait-Http "http://127.0.0.1:$nodePort/readyz" "node-gateway" -Process $nodeProcess
    }

    if ($useHarness) {
        # The gateway and Harness intentionally share the gateway access-token
        # verification boundary. Pass the secret only to the Harness child so
        # its clean URL can honor the authenticated Google session; do not leak
        # the secret into the landing or gateway process environment.
        $previousHarnessGatewaySecret = [Environment]::GetEnvironmentVariable("SUDARSHAN_GATEWAY_ACCESS_SECRET", "Process")
        $jwtAccessSecret = Get-EnvValue "JWT_ACCESS_SECRET"
        $configuredHarnessGatewaySecret = Get-EnvValue "SUDARSHAN_GATEWAY_ACCESS_SECRET"
        if (-not [string]::IsNullOrWhiteSpace($configuredHarnessGatewaySecret) -and $configuredHarnessGatewaySecret -ne $jwtAccessSecret) {
            throw "SUDARSHAN_GATEWAY_ACCESS_SECRET must exactly match JWT_ACCESS_SECRET because the Harness validates the gateway access JWT."
        }
        if ([string]::IsNullOrWhiteSpace($jwtAccessSecret)) {
            throw "JWT_ACCESS_SECRET is required when the DeepSeek Harness is enabled."
        }
        $env:SUDARSHAN_GATEWAY_ACCESS_SECRET = $jwtAccessSecret
        try {
            $harnessProcess = Start-LocalService "deepseek-harness" $nodeCommand.Source @("--import", "tsx/esm", "apps/cli/src/bin.ts", "web", "--no-open", "--port", [string]$harnessPort) $harnessRoot -Port $harnessPort
        }
        finally {
            if ($null -eq $previousHarnessGatewaySecret) {
                Remove-Item Env:SUDARSHAN_GATEWAY_ACCESS_SECRET -ErrorAction SilentlyContinue
            }
            else {
                $env:SUDARSHAN_GATEWAY_ACCESS_SECRET = $previousHarnessGatewaySecret
            }
        }
        Wait-Http "http://127.0.0.1:$harnessPort/" "deepseek-harness" -Process $harnessProcess -AcceptUnauthorized
    }

    $landingHost = Get-EnvValue "SUDARSHAN_FRONTEND_HOST"
    if ([string]::IsNullOrWhiteSpace($landingHost)) { $landingHost = "127.0.0.1" }
    $landingProcess = Start-LocalService "landing" $npmCommand.Source @("run", "dev", "--", "--host", $landingHost, "--port", [string]$landingPort) $landingRoot -Port $landingPort
    Wait-Http "http://127.0.0.1:$landingPort/login.html" "landing" -Process $landingProcess

    $landingUrl = "http://localhost:$landingPort/"
    $harnessUrl = "http://localhost:$harnessPort/"
    Write-Host ""
    Write-Host "Sudarshan is running locally:" -ForegroundColor Green
    Write-Host "  Landing:    $landingUrl"
    if ($useHarness) { Write-Host "  Harness:    $harnessUrl" }
    Write-Host "  Node API:   http://localhost:$nodePort"
    Write-Host "  Python API: http://localhost:$pythonPort"
    Write-Host "  Logs:       $logRoot"
    Write-ProcessManifest
    Write-Host "  Process manifest: $processManifestPath"
    if ($OpenBrowser -or (Get-EnvValue "SUDARSHAN_OPEN_BROWSER") -eq "true") {
        Start-Process $landingUrl
    }
}
catch {
    Stop-StartedServices
    Write-Error $_.Exception.Message
    if (Test-Path -LiteralPath $logRoot -PathType Container) {
        foreach ($errorLog in @(Get-ChildItem -LiteralPath $logRoot -Filter "*.err.log" -File -ErrorAction SilentlyContinue)) {
            $lines = @(Get-Content -LiteralPath $errorLog.FullName -Tail 12 -ErrorAction SilentlyContinue)
            if ($lines.Count -gt 0) {
                Write-Error ("--- " + $errorLog.Name + " ---`n" + ($lines -join "`n"))
            }
        }
    }
    Write-Host "Startup failed. Review logs under $logRoot and run .\stop-servers.ps1 before retrying." -ForegroundColor Yellow
    exit 1
}
