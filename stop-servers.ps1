[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [ValidateRange(1, 65535)]
    [int[]]$Ports = @(3000, 8000, 8080)
)

$connections = @(
    Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $Ports -contains $_.LocalPort }
)

if (-not $connections) {
    Write-Host "No Sudarshan services are listening on ports $($Ports -join ', ')."
    exit 0
}

$processIds = @($connections | Select-Object -ExpandProperty OwningProcess -Unique)

foreach ($processId in $processIds) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    $ownedPorts = @(
        $connections |
            Where-Object { $_.OwningProcess -eq $processId } |
            Select-Object -ExpandProperty LocalPort -Unique
    )
    $portText = $ownedPorts -join ", "
    $processName = if ($process) { $process.ProcessName } else { "unknown process" }

    if (-not $process) {
        Write-Warning "PID $processId for port(s) $portText no longer exists."
        continue
    }

    if ($PSCmdlet.ShouldProcess("$processName (PID $processId, port(s) $portText)", "Stop")) {
        Stop-Process -Id $processId -Force -ErrorAction Stop
        Write-Host "Stopped $processName (PID $processId) on port(s) $portText." -ForegroundColor Green
    }
}

