$ErrorActionPreference = 'Stop'
try {
  Restart-Service -Name FravenirMCP -Force
  $deadline = (Get-Date).AddSeconds(30)
  do {
    Start-Sleep -Milliseconds 500
    $service = Get-Service -Name FravenirMCP
    $listener = Get-NetTCPConnection -State Listen -LocalPort 8282 -ErrorAction SilentlyContinue | Select-Object -First 1
  } until (($service.Status -eq 'Running') -and $listener -and ((Get-Date) -gt $deadline -or $listener))
  Set-Content -LiteralPath 'C:\ProgramData\Fravenir\board-auth-restart-elevated.status' -Value ('SUCCESS ' + (Get-Date -Format o))
} catch {
  Set-Content -LiteralPath 'C:\ProgramData\Fravenir\board-auth-restart-elevated.status' -Value ('FAILED ' + $_.Exception.Message)
  exit 1
}