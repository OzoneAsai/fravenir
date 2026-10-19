$ErrorActionPreference='Stop'
$root='C:\ProgramData\Fravenir'
$status=Join-Path $root 'service-install.status'
try {
  $csc=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
  $exe=Join-Path $root 'FravenirSupervisor.exe'
  & $csc /nologo /target:exe /out:$exe /reference:System.ServiceProcess.dll (Join-Path $root 'FravenirSupervisor.cs')
  if ($LASTEXITCODE -ne 0) { throw "C# compile failed with exit code $LASTEXITCODE" }
  $old=Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {$_.LocalPort -in @(8001,8280)} | Select-Object -ExpandProperty OwningProcess -Unique
  foreach($pidValue in $old) { Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
  & sc.exe create FravenirMCP binPath= $exe start= auto DisplayName= 'Fravenir MCP Supervisor'
  if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 1073) { throw "sc create failed with exit code $LASTEXITCODE" }
  & sc.exe description FravenirMCP 'Supervises the Fravenir MCP backend and Planet OAuth bridge.'
  & sc.exe failure FravenirMCP reset= 86400 actions= restart/5000/restart/15000/restart/30000
  & sc.exe start FravenirMCP
  if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 1056) { throw "sc start failed with exit code $LASTEXITCODE" }
  $ready=$false
  for($i=0;$i -lt 45;$i++){
    $ports=Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty LocalPort
    if(($ports -contains 8001) -and ($ports -contains 8280)){$ready=$true;break}
    Start-Sleep -Seconds 1
  }
  if(-not $ready){throw 'Service started but the MCP ports did not become ready.'}
  Set-Content -LiteralPath $status -Value 'SUCCESS' -Encoding ASCII
} catch {
  Set-Content -LiteralPath $status -Value ('FAILED: '+$_.Exception.Message) -Encoding UTF8
  exit 1
}
