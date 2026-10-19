$ErrorActionPreference='Stop'
$root='C:\ProgramData\Fravenir'
$exe=Join-Path $root 'FravenirSupervisor.exe'
$new=Join-Path $root 'FravenirSupervisor.next.exe'
$backup='C:\ProgramData\Fravenir\backups\human-board-ui-20261004\FravenirSupervisor-before-admin-python.exe'
$result=Join-Path $root 'board-ui-install.status'
function Stop-FravenirChildren {
  $owners=Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {$_.LocalPort -in @(8001,8280,8281)} | Select-Object -ExpandProperty OwningProcess -Unique
  foreach($owner in $owners){ & taskkill.exe /PID $owner /T /F | Out-Null }
}
try {
  if(-not (Test-Path $new)){throw 'New supervisor executable is missing.'}
  Copy-Item -LiteralPath $exe -Destination $backup -Force
  & sc.exe stop FravenirMCP | Out-Null
  for($i=0;$i -lt 30;$i++){ if((Get-Service FravenirMCP).Status -eq 'Stopped'){break}; Start-Sleep -Seconds 1 }
  if((Get-Service FravenirMCP).Status -ne 'Stopped'){throw 'FravenirMCP did not stop.'}
  Stop-FravenirChildren
  Start-Sleep -Seconds 2
  Copy-Item -LiteralPath $new -Destination $exe -Force
  & sc.exe start FravenirMCP | Out-Null
  for($i=0;$i -lt 120;$i++){
    $ports=Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty LocalPort
    if(($ports -contains 8001) -and ($ports -contains 8280) -and ($ports -contains 8281)){Set-Content -LiteralPath $result -Value 'SUCCESS' -Encoding ASCII; exit 0}
    Start-Sleep -Seconds 1
  }
  throw 'The service started, but expected listeners did not all appear.'
} catch {
  Set-Content -LiteralPath $result -Value ('FAILED: '+$_.Exception.Message) -Encoding UTF8
  try {
    & sc.exe stop FravenirMCP | Out-Null
    Start-Sleep -Seconds 2
    Stop-FravenirChildren
    Copy-Item -LiteralPath $backup -Destination $exe -Force
    & sc.exe start FravenirMCP | Out-Null
  } catch {}
  exit 1
}
