# Stop the live shadow monitor: write shadow\live\STOP, after which the monitor saves its state and exits within
# about a minute and does not start again while the file exists. Then remove its scheduled task (pass -KeepTask to
# keep it; run_live.ps1 removes the STOP file and starts the task again).
param([switch]$KeepTask)
$live = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")).Path "shadow\live")
Set-Content -Path (Join-Path $live "STOP") -Value "stop"
$pidFile = Join-Path $live "monitor.pid"
if (Test-Path $pidFile) {
    $p = [int](Get-Content $pidFile)
    $gone = $false
    for ($i = 0; $i -lt 150; $i++) {
        if (-not (Get-Process -Id $p -ErrorAction SilentlyContinue)) { $gone = $true; break }
        Start-Sleep -Seconds 1
    }
    if ($gone) { "monitor stopped" } else { "still running after 150 s (process $p)" }
}
if (-not $KeepTask -and (Get-ScheduledTask -TaskName "BridgeShadowMonitor" -ErrorAction SilentlyContinue)) {
    Unregister-ScheduledTask -TaskName "BridgeShadowMonitor" -Confirm:$false
    "scheduled task removed"
}
