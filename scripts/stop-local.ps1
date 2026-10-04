$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$stateFile = Join-Path $projectRoot 'data\local-processes.json'
if (-not (Test-Path $stateFile)) { Write-Output 'No local service is recorded.'; exit 0 }
$state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
foreach ($service in @('web', 'worker')) {
    $servicePid = $state."${service}_pid"
    $processInfo = Get-Process -Id $servicePid -ErrorAction SilentlyContinue
    if ($processInfo) {
        $recordedStart = $state."${service}_started"
        if ($processInfo.Path -ine $pythonPath -or ($recordedStart -and $processInfo.StartTime.ToUniversalTime().Ticks -ne ([datetime]$recordedStart).ToUniversalTime().Ticks)) {
            throw "PID $servicePid no longer belongs to this project's service; it was not stopped."
        }
        Stop-Process -Id $servicePid
    }
}
Remove-Item -LiteralPath $stateFile
Write-Output 'Local web service and task worker stopped. Data retained.'
