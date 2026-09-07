[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [int[]]$Ports = @(3000, 8000, 8080)
)

$ErrorActionPreference = "Stop"

$validPorts = @($Ports | Where-Object { $_ -ge 1 -and $_ -le 65535 } | Select-Object -Unique)
if ($validPorts.Count -eq 0) {
    throw "Provide at least one valid TCP port between 1 and 65535."
}

$listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in $validPorts })

if ($listeners.Count -eq 0) {
    Write-Host "No listening Sudarshan services found on port(s): $($validPorts -join ', ')."
    exit 0
}

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
