<#
Removes the StudyCopilot vault-sync scheduled task.

    powershell -ExecutionPolicy Bypass -File scripts\uninstall_sync_task.ps1
#>

$ErrorActionPreference = "Stop"
$taskName = "StudyCopilot Vault Sync"

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -eq $existing) {
    Write-Output "Task '$taskName' is not registered; nothing to do."
} else {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "Removed scheduled task '$taskName'."
}
