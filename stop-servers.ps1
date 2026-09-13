[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [int[]]$Ports = @(4173, 3080, 8000, 8080),
    [switch]$ByPort
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifestPath = Join-Path $repoRoot "artifacts\.state\sudarshan-processes.json"

function Stop-ProcessTree([int]$ProcessId) {
    if ($ProcessId -le 0) { return }
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $process) { return }
    & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Get-ListeningProcessIds([int]$Port) {
    $ids = @()
    try {
        $ids = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique)
    }
    catch {
        $ids = @()
    }
    if ($ids.Count -gt 0) { return @($ids | ForEach-Object { [int]$_ }) }

    $fallback = [System.Collections.Generic.List[int]]::new()
    foreach ($line in @(netstat.exe -ano -p tcp 2>$null)) {
        $parts = ([string]$line).Trim() -split '\s+'
        if ($parts.Count -lt 5 -or $parts[3] -ne 'LISTENING') { continue }
        $local = $parts[1]
        $colon = $local.LastIndexOf(':')
        if ($colon -lt 0) { continue }
        $localPort = 0
        $owner = 0
        if ([int]::TryParse($local.Substring($colon + 1), [ref]$localPort) -and
            $localPort -eq $Port -and [int]::TryParse($parts[4], [ref]$owner) -and $owner -gt 0 -and
            -not $fallback.Contains($owner)) {
            $fallback.Add($owner)
        }
    }
    return @($fallback.ToArray())
}

function Get-ListeningPorts([int[]]$Ports) {
    $owners = [System.Collections.Generic.List[object]]::new()
    foreach ($port in $Ports) {
        foreach ($processId in @(Get-ListeningProcessIds $port)) {
            $owners.Add([pscustomobject]@{LocalPort=$port;OwningProcess=$processId})
        }
    }
    return @($owners.ToArray())
}

function Stop-ManifestServices {
    param([Parameter(Mandatory = $true)]$Manifest)

    $stopped = 0
    foreach ($service in @($Manifest.services)) {
        $processId = 0
        if (-not [int]::TryParse([string]$service.pid, [ref]$processId) -or $processId -le 0) {
            Write-Warning "Ignoring invalid PID in the Sudarshan process manifest: $($service.pid)"
            continue
        }
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            Write-Host "Process $processId for $($service.name) is already stopped."
            continue
        }
        $description = "$($service.name) (PID $processId)"
        if ($PSCmdlet.ShouldProcess($description, "Stop")) {
            Stop-ProcessTree $processId
            $stopped++
            Write-Host "Stopped $description."
        }
    }
    return $stopped
}

function Get-ManifestPorts {
    param([Parameter(Mandatory = $true)]$Manifest)
    $ports = [System.Collections.Generic.List[int]]::new()
    foreach ($service in @($Manifest.services)) {
        $port = 0
        if ([int]::TryParse([string]$service.port, [ref]$port) -and $port -ge 1 -and $port -le 65535 -and -not $ports.Contains($port)) {
            $ports.Add($port)
        }
    }
    return @($ports.ToArray())
}

$validPorts = @($Ports | Where-Object { $_ -ge 1 -and $_ -le 65535 } | Select-Object -Unique)
if ($validPorts.Count -eq 0) {
    throw "Provide at least one valid TCP port between 1 and 65535."
}

$manifest = $null
if (-not $ByPort -and (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    }
    catch {
        Write-Warning "Sudarshan process manifest is unreadable; falling back to explicit port scan."
    }
}

if ($null -ne $manifest -and @($manifest.services).Count -gt 0) {
    Stop-ManifestServices $manifest | Out-Null
    Remove-Item -LiteralPath $manifestPath -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 300
    $manifestPorts = Get-ManifestPorts $manifest
    $remaining = @(Get-ListeningPorts $manifestPorts)
    if ($remaining.Count -gt 0) {
        $owners = ($remaining | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
        throw "Manifest services stopped, but port(s) remain in use by process(es): $owners. Use -ByPort only after verifying those processes belong to Sudarshan."
    }
    Write-Host "Sudarshan services from the process manifest are clear."
    exit 0
}

$listeners = @(Get-ListeningPorts $validPorts)

if ($listeners.Count -eq 0) {
    Remove-Item -LiteralPath $manifestPath -Force -ErrorAction SilentlyContinue
    Write-Host "No listening services found on port(s): $($validPorts -join ', ')."
    exit 0
}

Write-Warning "No usable Sudarshan process manifest was found. Scanning the requested ports; use this fallback only after checking the owners."

$processIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique |
    Where-Object { $_ -notin @(0, 4) })

foreach ($processId in $processIds) {
    $boundPorts = @($listeners | Where-Object OwningProcess -eq $processId |
        Select-Object -ExpandProperty LocalPort -Unique)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        Write-Warning "Process $processId owns port(s) $($boundPorts -join ', ') but is no longer running."
        continue
    }

    $description = "$($process.ProcessName) (PID $processId) on port(s) $($boundPorts -join ', ')"
    if ($PSCmdlet.ShouldProcess($description, "Stop")) {
        Stop-ProcessTree $processId
        Write-Host "Stopped $description."
    }
}

Start-Sleep -Milliseconds 300
$remaining = @(Get-ListeningPorts $validPorts)
if ($remaining.Count -gt 0) {
    $owners = ($remaining | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
    throw "Some requested ports are still in use by process(es): $owners"
}

Remove-Item -LiteralPath $manifestPath -Force -ErrorAction SilentlyContinue
Write-Host "Sudarshan service ports are clear."
