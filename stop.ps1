$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (Test-Path -LiteralPath 'runtime/server.pid') {
    $serverId = [int](Get-Content -LiteralPath 'runtime/server.pid')
    $serverInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $serverId"
    if ($serverInfo -and $serverInfo.CommandLine -match 'uvicorn app.main:app') {
        Stop-Process -Id $serverId
        Write-Host 'SupplyChain360 background server stopped.'
    } else {
        Write-Host 'The original background server is no longer running.'
    }
} else {
    Write-Host 'For a foreground server, press Ctrl+C in its terminal.'
}
