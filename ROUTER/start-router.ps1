$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = 3270
$existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue

if ($existing) {
    Write-Host "AI Router is already running at http://localhost:$port/v1"
    exit 0
}

$process = Start-Process -FilePath 'node' `
    -ArgumentList 'server.js' `
    -WorkingDirectory $scriptDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $scriptDir 'router.out.log') `
    -RedirectStandardError (Join-Path $scriptDir 'router.err.log') `
    -PassThru

Start-Sleep -Seconds 2

if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "AI Router started at http://localhost:$port/v1 (PID $($process.Id))"
} else {
    Write-Host 'AI Router did not start. Check router.err.log.'
    exit 1
}
