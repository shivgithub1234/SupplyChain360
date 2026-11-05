$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
    ./.venv/Scripts/python.exe -m pip install -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
}
if (-not (Test-Path -LiteralPath 'runtime/source/inventory.csv')) {
    ./.venv/Scripts/python.exe -m app.cli demo
    if ($LASTEXITCODE -ne 0) { throw 'Demo initialization failed' }
}
Write-Host 'Open http://127.0.0.1:8000 . Press Ctrl+C to stop.'
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
