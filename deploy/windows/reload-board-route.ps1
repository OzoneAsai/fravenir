$ErrorActionPreference='Stop'
$root='C:\ProgramData\Planet\reverse-proxy'
$env:RPROXY_ROOT=$root
$node='C:\Program Files\nodejs\node.exe'
$ctl=Join-Path $root 'bin\rproxyctl.js'
$caddy=Join-Path $root 'runtime\caddy-l4\caddy.exe'
$status='C:\ProgramData\Fravenir\board-route.status'
try {
  & $node $ctl render
  if($LASTEXITCODE -ne 0){throw "render failed ($LASTEXITCODE)"}
  & $caddy validate --config (Join-Path $root 'Caddyfile') --adapter caddyfile
  if($LASTEXITCODE -ne 0){throw "validate failed ($LASTEXITCODE)"}
  & $node $ctl reload
  if($LASTEXITCODE -ne 0){throw "reload failed ($LASTEXITCODE)"}
  Set-Content -LiteralPath $status -Value 'SUCCESS' -Encoding ASCII
} catch {
  Set-Content -LiteralPath $status -Value ('FAILED: '+$_.Exception.Message) -Encoding UTF8
  exit 1
}
