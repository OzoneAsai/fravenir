$ErrorActionPreference = 'Stop'
$statusPath = 'C:\ProgramData\PlanetOAuth\totp-rotation-admin.status'
try {
  $task = Get-ScheduledTask -TaskName 'Planet-OAuth' -TaskPath '\' -ErrorAction Stop
  Stop-Service -Name FravenirMCP -Force -ErrorAction Stop
  $deadline = (Get-Date).AddSeconds(30)
  do { Start-Sleep -Milliseconds 500; $fr = Get-Service FravenirMCP } until ($fr.Status -eq 'Stopped' -or (Get-Date) -gt $deadline)
  if ($fr.Status -ne 'Stopped') { throw 'FravenirMCP did not stop cleanly' }
  try { Stop-ScheduledTask -InputObject $task -ErrorAction Stop } catch { }
  Start-Sleep -Seconds 2
  $deadline = (Get-Date).AddSeconds(20)
  do {
    $oauth = Get-NetTCPConnection -State Listen -LocalPort 8002 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($oauth) { Stop-Process -Id $oauth.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 500
  } until (-not (Get-NetTCPConnection -State Listen -LocalPort 8002 -ErrorAction SilentlyContinue) -or (Get-Date) -gt $deadline)
  if (Get-NetTCPConnection -State Listen -LocalPort 8002 -ErrorAction SilentlyContinue) { throw 'OAuth listener did not stop' }
  $result = & 'C:\ProgramData\PlanetOAuth\venv\Scripts\python.exe' 'C:\ProgramData\PlanetOAuth\rotate_totp_account.py'
  if ($LASTEXITCODE -ne 0) { throw 'TOTP rotation helper failed' }
  Start-Service -Name FravenirMCP -ErrorAction Stop
  Start-ScheduledTask -InputObject $task -ErrorAction Stop
  $deadline = (Get-Date).AddSeconds(40)
  do {
    Start-Sleep -Milliseconds 500
    $fr = Get-Service FravenirMCP
    $oauth = Get-NetTCPConnection -State Listen -LocalPort 8002 -ErrorAction SilentlyContinue | Select-Object -First 1
    $gate = Get-NetTCPConnection -State Listen -LocalPort 8282 -ErrorAction SilentlyContinue | Select-Object -First 1
  } until (($fr.Status -eq 'Running') -and $oauth -and $gate -or (Get-Date) -gt $deadline)
  if (($fr.Status -ne 'Running') -or -not $oauth -or -not $gate) { throw 'Services did not return to ready state' }
  Set-Content -LiteralPath $statusPath -Value ('SUCCESS ' + (Get-Date -Format o))
} catch {
  Set-Content -LiteralPath $statusPath -Value ('FAILED ' + $_.Exception.Message)
  exit 1
}