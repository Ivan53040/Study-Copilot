<#
Registers a Windows Scheduled Task that runs the two-way vault sync every
5 minutes for the current user. Re-run to update; safe to run repeatedly.

    powershell -ExecutionPolicy Bypass -File scripts\install_sync_task.ps1
#>

$ErrorActionPreference = "Stop"

$root    = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$script  = Join-Path $root "scripts\sync_standalone.py"
$taskName = "StudyCopilot Vault Sync"
$intervalMinutes = 5

if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found at $pythonw (create the venv first)." }
if (-not (Test-Path $script))  { throw "sync_standalone.py not found at $script." }

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$script`"" -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $intervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 9999)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Two-way sync of StudyVault <-> iCloud every $intervalMinutes minutes" -Force | Out-Null

Write-Output "Registered scheduled task '$taskName' (every $intervalMinutes min)."
Write-Output "Runs: $pythonw `"$script`""
