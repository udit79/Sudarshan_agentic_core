[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [int[]]$Ports = @(3000, 8000, 8080),
    [switch]$ByPort
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifestPath = Join-Path $repoRoot "artifacts\.state\sudarshan-processes.json"

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
            Stop-Process -Id $processId -Force -ErrorAction Stop
            $stopped++
            Write-Host "Stopped $description."
        }
    }
    return $stopped
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
    $manifestPorts = @($manifest.services | Where-Object { [int]$_.port -gt 0 } | Select-Object -ExpandProperty port -Unique)
    $remaining = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in $manifestPorts })
    if ($remaining.Count -gt 0) {
        $owners = ($remaining | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
        throw "Manifest services stopped, but port(s) remain in use by process(es): $owners. Use -ByPort only after verifying those processes belong to Sudarshan."
    }
    Write-Host "Sudarshan services from the process manifest are clear."
    exit 0
}

$listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in $validPorts })

if ($listeners.Count -eq 0) {
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
        Stop-Process -Id $processId -Force -ErrorAction Stop
        Write-Host "Stopped $description."
    }
}

Start-Sleep -Milliseconds 300
$remaining = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in $validPorts })
if ($remaining.Count -gt 0) {
    $owners = ($remaining | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
    throw "Some requested ports are still in use by process(es): $owners"
}

Write-Host "Sudarshan service ports are clear."
