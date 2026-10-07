param([ValidateRange(1024, 65535)][int]$Port = 9090)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$dataPath = Join-Path $projectRoot 'data'
if (-not (Test-Path $pythonPath) -or -not (Test-Path "$dataPath\db.sqlite3")) {
    throw 'Run scripts\setup-local.ps1 first.'
}
$stateFile = Join-Path $dataPath 'local-processes.json'
if (Test-Path $stateFile) {
    throw 'A previous startup is recorded. Run scripts\stop-local.ps1 before starting again.'
}
$probe = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
try { $probe.Start() } catch { throw "Port $Port is busy; choose -Port with a different value." }
finally { $probe.Stop() }
$webProcess = $null
$workerProcess = $null
try {
    # Use a predictable child environment; project overrides belong in local_settings.py.
    $systemRootArgument = '"' + $env:SystemRoot + '"'
    $webProcess = Start-Process -FilePath $pythonPath -ArgumentList @('scripts/local_service.py', 'web', '--system-root', $systemRootArgument, '--port', $Port) -WorkingDirectory $projectRoot -WindowStyle Hidden -UseNewEnvironment -RedirectStandardOutput "$dataPath\web.stdout.log" -RedirectStandardError "$dataPath\web.stderr.log" -PassThru
    $workerProcess = Start-Process -FilePath $pythonPath -ArgumentList @('scripts/local_service.py', 'worker', '--system-root', $systemRootArgument) -WorkingDirectory $projectRoot -WindowStyle Hidden -UseNewEnvironment -RedirectStandardOutput "$dataPath\worker.stdout.log" -RedirectStandardError "$dataPath\worker.stderr.log" -PassThru
    @{ web_pid = $webProcess.Id; worker_pid = $workerProcess.Id; web_started = $webProcess.StartTime.ToUniversalTime().ToString('o'); worker_started = $workerProcess.StartTime.ToUniversalTime().ToString('o'); port = $Port } | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        $webProcess.Refresh(); $workerProcess.Refresh()
        if ($webProcess.HasExited -or $workerProcess.HasExited) { throw 'A service exited. Inspect data\*.stderr.log.' }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($health.status -eq 'healthy') { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) { throw 'Service did not become healthy. Inspect data\web.stderr.log.' }
    & $pythonPath (Join-Path $PSScriptRoot 'check-worker.py')
    if ($LASTEXITCODE -ne 0) { throw 'Task worker verification failed. Inspect data\worker.stderr.log.' }
    Write-Output "Yuanjian is running: http://127.0.0.1:$Port"
    Write-Output 'Login credentials: data\local-access.json'
} catch {
    if ($webProcess -and -not $webProcess.HasExited) { $webProcess.Kill() }
    if ($workerProcess -and -not $workerProcess.HasExited) { $workerProcess.Kill() }
    if (Test-Path $stateFile) { Remove-Item -LiteralPath $stateFile }
    throw
}
