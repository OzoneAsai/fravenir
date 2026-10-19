$ErrorActionPreference = 'Stop'
$root = 'C:\ProgramData\Fravenir'
$app = Join-Path $root 'app'
$cli = Join-Path $root 'venv\Scripts\fravenir.exe'
$python = Join-Path $root 'venv\Scripts\python.exe'
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
if (-not (Test-Path $python) -or -not (Test-Path $cli)) { throw 'Fravenir Python environment is missing.' }
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

function Wait-ForPort([int]$Port) {
    for ($i = 0; $i -lt 45; $i++) {
        if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) { return }
        Start-Sleep -Seconds 1
    }
    throw "Fravenir did not open local port $Port. See logs in $logs."
}

if (-not (Get-NetTCPConnection -State Listen -LocalPort 8280 -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $cli -ArgumentList @('serve','--character','main','--transport','streamable-http','--host','127.0.0.1','--port','8280') -WorkingDirectory $app -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'mcp.out.log') -RedirectStandardError (Join-Path $logs 'mcp.err.log')
}
Wait-ForPort 8280

if (-not (Get-NetTCPConnection -State Listen -LocalPort 8001 -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','deploy.windows.oauth_bridge:app','--host','127.0.0.1','--port','8001','--workers','1') -WorkingDirectory $app -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'bridge.out.log') -RedirectStandardError (Join-Path $logs 'bridge.err.log')
}
Wait-ForPort 8001
'Fravenir MCP backend and OAuth bridge are listening on loopback.'
