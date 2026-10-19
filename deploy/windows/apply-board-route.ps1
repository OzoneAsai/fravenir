$ErrorActionPreference='Stop'
$stage='initialize'
$root='C:\ProgramData\Planet\reverse-proxy'; $routes=Join-Path $root 'routes.json'; $caddyfile=Join-Path $root 'Caddyfile'
$backup='C:\ProgramData\Fravenir\backups\human-board-ui-20261004'; $routeBackup=Join-Path $backup 'routes.json.before-global-totp'; $caddyBackup=Join-Path $backup 'Caddyfile.before-global-totp'
$result='C:\ProgramData\Fravenir\board-route.status'; $node='C:\Program Files\nodejs\node.exe'; $ctl=Join-Path $root 'bin\rproxyctl.js'; $caddy=Join-Path $root 'runtime\caddy-l4\caddy.exe'
try {
  $env:RPROXY_ROOT=$root
  $stage='backup'; Copy-Item -LiteralPath $routes -Destination $routeBackup -Force; Copy-Item -LiteralPath $caddyfile -Destination $caddyBackup -Force
  $stage='parse'; $cfg=Get-Content -LiteralPath $routes -Raw | ConvertFrom-Json
  $stage='find MCP'; $mcp=$cfg.routes | Where-Object {$_.name -eq 'planet-mcp'} | Select-Object -First 1; if(-not $mcp){throw 'planet-mcp route is missing'}
  $stage='modify MCP'; $mcp | Add-Member -MemberType NoteProperty -Name pathExact -Value '/mcp' -Force
  $stage='build routes'; $routesNext=@($cfg.routes | Where-Object {$_.name -ne 'fravenir-board-totp'})
  $routesNext+= [pscustomobject]@{name='fravenir-board-totp';host='prox042460.softether.net';target='http://127.0.0.1:8282';kind='web';groupByHost=$true;createdAt=(Get-Date).ToUniversalTime().ToString('o');source='fravenir-board-totp-gate'}
  $cfg.routes=$routesNext
  $stage='serialize'; $json=ConvertTo-Json -InputObject $cfg -Depth 50
  $stage='write routes'; [IO.File]::WriteAllText($routes,$json,[System.Text.UTF8Encoding]::new($false))
  $stage='render'; & $node $ctl render; if($LASTEXITCODE -ne 0){throw "rproxyctl render failed ($LASTEXITCODE)"}
  $stage='validate'; & $caddy validate --config $caddyfile --adapter caddyfile; if($LASTEXITCODE -ne 0){throw "Caddy validation failed ($LASTEXITCODE)"}
  $stage='start Planet-Caddy'; & schtasks.exe /run /TN Planet-Caddy; if($LASTEXITCODE -ne 0){throw "Planet-Caddy task start failed ($LASTEXITCODE)"}
  $ready=$false
  for($i=0;$i -lt 45;$i++){if(Get-NetTCPConnection -State Listen -LocalPort 443 -ErrorAction SilentlyContinue){$ready=$true;break};Start-Sleep -Seconds 1}
  if(-not $ready){throw 'Planet-Caddy task did not open port 443.'}
  $stage='reload'; & $node $ctl reload; if($LASTEXITCODE -ne 0){throw "rproxyctl reload failed ($LASTEXITCODE)"}
  Set-Content -LiteralPath $result -Value 'SUCCESS' -Encoding ASCII
} catch {
  Set-Content -LiteralPath $result -Value ("FAILED at "+$stage+": "+$_.Exception.Message) -Encoding UTF8
  try {
    Copy-Item -LiteralPath $routeBackup -Destination $routes -Force
    Copy-Item -LiteralPath $caddyBackup -Destination $caddyfile -Force
    & $node $ctl render | Out-Null
    if(Get-NetTCPConnection -State Listen -LocalPort 443 -ErrorAction SilentlyContinue){& $node $ctl reload | Out-Null}
  } catch {}
  exit 1
}
