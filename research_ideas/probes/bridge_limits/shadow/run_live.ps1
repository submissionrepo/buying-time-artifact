# Start the live shadow monitor (shadow/live_monitor.py) through a scheduled task of the current user,
# "BridgeShadowMonitor". The task runs pythonw, so no console window opens, at logon and every 10 minutes; a run
# while the monitor is up is skipped, so the task also restarts the monitor after a crash or a restart of the
# computer. The monitor resumes from shadow/raw/live/state.json; blocks it missed while stopped are read in backfill
# mode. Stop it, and remove the task, with stop_live.ps1.
$ErrorActionPreference = "Stop"
$dir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pyw = (Get-Command pythonw.exe -ErrorAction Stop).Source
$name = "BridgeShadowMonitor"
$stop = Join-Path $dir "shadow\live\STOP"
if (Test-Path $stop) { Remove-Item $stop }
$action = New-ScheduledTaskAction -Execute $pyw -Argument "-I shadow\live_monitor.py run --log shadow\raw\live\monitor.out" `
    -WorkingDirectory $dir
$triggers = @((New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME),
              (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10) `
                   -RepetitionDuration (New-TimeSpan -Days 60)))
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Days 60) -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers -Settings $settings `
    -Description "Live shadow run of the deposit-backing check (bridge withdrawal limits paper); stop with shadow\stop_live.ps1" `
    -Force | Out-Null
Start-ScheduledTask -TaskName $name
"task $name registered and started; the monitor writes its process id to shadow\live\monitor.pid"
