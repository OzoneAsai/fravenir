$ErrorActionPreference = 'Stop'
$root = 'C:\ProgramData\Fravenir'
$startup = Join-Path $root 'start-fravenir.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$startup`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Fravenir memory MCP, protected by the existing Planet OAuth service.'
Register-ScheduledTask -TaskName 'Planet-MCP' -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName 'Planet-MCP'
'Planet-MCP task now starts Fravenir behind the existing OAuth endpoint.'
