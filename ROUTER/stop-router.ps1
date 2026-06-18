$ErrorActionPreference = 'Stop'

$port = 3270
$connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue

if (-not $connections) {
    Write-Host "AI Router is not running on port $port"
    exit 0
}

$connections | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
    Stop-Process -Id $_ -Force
    Write-Host "Stopped AI Router process PID $_"
}
