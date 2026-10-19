param([switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
$root = 'C:\ProgramData\PlanetOAuth'
$python = Join-Path $root 'venv\Scripts\python.exe'
$logs = Join-Path $root 'logs'
$stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')
$stdout = Join-Path $logs ("oauth-" + $stamp + ".stdout.log")
$stderr = Join-Path $logs ("oauth-" + $stamp + ".stderr.log")
if (!(Test-Path $python)) { throw 'OAuth Python interpreter is missing' }
if (!(Test-Path (Join-Path $root 'oauth.env'))) { throw 'OAuth env file is missing' }
$argsLine = if ($ValidateOnly) { '-m uvicorn --version' } else { '-m uvicorn app:app --host 127.0.0.1 --port 8002 --proxy-headers --forwarded-allow-ips 127.0.0.1 --env-file "C:\ProgramData\PlanetOAuth\oauth.env"' }
$p = Start-Process -FilePath $python -ArgumentList $argsLine -WorkingDirectory $root -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$code = $p.ExitCode
Add-Content -LiteralPath (Join-Path $logs 'oauth-runtime.log') -Encoding UTF8 -Value ("[{0:o}] mode={1} exitCode={2} stdout={3} stderr={4}" -f (Get-Date),$(if($ValidateOnly){'validate'}else{'run'}),$code,$stdout,$stderr)
exit $code
