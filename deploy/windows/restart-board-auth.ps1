$ErrorActionPreference='Stop'
$log='C:\ProgramData\Fravenir\logs\supervisor.log'
$line=Get-Content $log | Select-String 'Started board-auth \(pid ([0-9]+)\)' | Select-Object -Last 1
if(-not $line){throw 'Could not find board-auth process in supervisor log.'}
$pidValue=[int]$line.Matches[0].Groups[1].Value
& taskkill.exe /PID $pidValue /T /F | Out-Null
$ready=$false
for($i=0;$i -lt 45;$i++){
  Start-Sleep -Seconds 1
  $listener=Get-NetTCPConnection -State Listen -LocalPort 8282 -ErrorAction SilentlyContinue
  if($listener){$ready=$true;break}
}
if(-not $ready){throw 'Supervisor did not restart the board-auth gate.'}
Set-Content -LiteralPath 'C:\ProgramData\Fravenir\board-auth-restart.status' -Value 'SUCCESS' -Encoding ASCII
