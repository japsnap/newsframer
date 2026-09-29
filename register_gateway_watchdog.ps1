# register_gateway_watchdog.ps1
# Run this ONCE in an ELEVATED PowerShell (Run as administrator).
# It registers the independent NewsFramer gateway-liveness watchdog as a Windows Scheduled Task that
# runs every 20 minutes OUTSIDE the OpenClaw gateway — so if the gateway dies, this restarts it and
# alerts your Telegram, instead of the outage going silent (the 2026-06-25 incident).
$ErrorActionPreference = "Stop"
$taskName = "NewsFramer Gateway Watchdog"
$base   = $PSScriptRoot
$py     = Join-Path $base "venv\Scripts\python.exe"
$script = Join-Path $base "gateway_watchdog.py"

if (-not (Test-Path $py))     { Write-Error "venv python not found: $py"; exit 1 }
if (-not (Test-Path $script)) { Write-Error "gateway_watchdog.py not found: $script"; exit 1 }

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed pre-existing task."
}

$action  = New-ScheduledTaskAction -Execute $py -Argument "`"$script`"" -WorkingDirectory $base
# Daily trigger that repeats every 20 min for 24h => continuous coverage, re-armed each day.
$trigger = New-ScheduledTaskTrigger -Daily -At "00:02"
$rep     = New-ScheduledTaskTrigger -Once -At "00:02" -RepetitionInterval (New-TimeSpan -Minutes 20) -RepetitionDuration (New-TimeSpan -Hours 24)
$trigger.Repetition = $rep.Repetition
# S4U => runs whether or not you are logged on (same as the gateway task).
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description "Independent gateway-liveness watchdog (NewsFramer): restarts the OpenClaw gateway if down + alerts Telegram. Runs outside the gateway so a dead gateway cannot go silent." | Out-Null

Write-Host "REGISTERED OK: '$taskName' (every 20 min, S4U)."
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 6
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object LastRunTime, LastTaskResult, NextRunTime | Format-List
Write-Host "Done.  LastTaskResult of 0 = the watchdog ran successfully."
