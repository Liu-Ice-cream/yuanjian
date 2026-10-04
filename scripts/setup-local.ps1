$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.13+ is required.' }
    }
    $pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
    & $pythonPath scripts\local_admin.py --prepare
    if ($LASTEXITCODE -ne 0) { throw 'Local data initialization failed.' }
    if (-not (Test-Path local_settings.py)) {
        Copy-Item -LiteralPath scripts\local_settings.template.py -Destination local_settings.py
    }
    & $pythonPath -m pip install -r requirements-windows-dev.txt --cache-dir data\pip-cache
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    npm.cmd ci --cache data\npm-cache
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    & $pythonPath manage.py check --settings=local_settings
    if ($LASTEXITCODE -ne 0) { throw 'Django system check failed.' }
    & $pythonPath manage.py migrate --settings=local_settings --noinput
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
    & $pythonPath scripts\local_admin.py
    if ($LASTEXITCODE -ne 0) { throw 'Administrator initialization failed.' }
    Write-Output 'Setup complete. Run scripts\start-local.ps1.'
} finally { Pop-Location }
