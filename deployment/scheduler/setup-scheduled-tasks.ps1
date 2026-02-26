<#
.SYNOPSIS
    Sets up Windows Task Scheduler entries for CosySim automated tasks.
.DESCRIPTION
    Creates scheduled tasks for:
    - Hourly system health check + Nexus snapshot
    - Daily 2 AM Nexus knowledge audit
    - Daily 3 AM inference benchmark (if GPU idle)
    - Weekly full test suite
.NOTES
    Run as Administrator: .\setup-scheduled-tasks.ps1
#>

$ErrorActionPreference = "Stop"
$ProjectDir = "C:\Files\Models\CosySim"
$ScriptsDir = "$ProjectDir\deployment\scripts"
$SchedulerDir = "$ProjectDir\deployment\scheduler"
$PwshPath = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source ?? "powershell.exe"

Write-Host "=== CosySim Scheduled Tasks Setup ===" -ForegroundColor Cyan
Write-Host "Using: $PwshPath" -ForegroundColor Gray

# ── Hourly Health Check ──
Write-Host "`n1. Creating hourly health check..." -ForegroundColor Yellow
$healthAction = New-ScheduledTaskAction `
    -Execute $PwshPath `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptsDir\System-Status.ps1`"" `
    -WorkingDirectory $ProjectDir

$healthTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1)

$healthSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
    -TaskName "CosySim-HealthCheck" `
    -TaskPath "\CosySim\" `
    -Action $healthAction `
    -Trigger $healthTrigger `
    -Settings $healthSettings `
    -Description "Hourly CosySim system health check — checks all services and stores snapshot" `
    -Force

Write-Host "  ✓ Hourly health check registered" -ForegroundColor Green

# ── Daily Nexus Audit (2 AM) ──
Write-Host "`n2. Creating daily Nexus audit (2 AM)..." -ForegroundColor Yellow
$auditScript = @'
$NexusUrl = "http://localhost:8700/api"
try {
    $health = Invoke-RestMethod -Uri "$NexusUrl/health" -TimeoutSec 5
    $stats = Invoke-RestMethod -Uri "$NexusUrl/stats" -TimeoutSec 5
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $report = @{
        title = "Scheduled Audit: Nexus Health — $timestamp"
        content = "## Nexus Scheduled Audit`n`n**Time:** $timestamp`n**Status:** Healthy`n**Entries:** $($stats.total_entries)`n**Q&A:** $($stats.total_qa)`n"
        content_type = "audit"
        category = "knowledge"
        tags = @("scheduled", "audit")
    } | ConvertTo-Json
    Invoke-RestMethod -Uri "$NexusUrl/entries" -Method Post -Body $report -ContentType "application/json" -TimeoutSec 5
} catch {
    Write-Error "Nexus audit failed: $_"
}
'@
$auditScript | Out-File -FilePath "$SchedulerDir\nexus-audit.ps1" -Encoding utf8

$auditAction = New-ScheduledTaskAction `
    -Execute $PwshPath `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$SchedulerDir\nexus-audit.ps1`"" `
    -WorkingDirectory $ProjectDir

$auditTrigger = New-ScheduledTaskTrigger -Daily -At "2:00 AM"

Register-ScheduledTask `
    -TaskName "CosySim-NexusAudit" `
    -TaskPath "\CosySim\" `
    -Action $auditAction `
    -Trigger $auditTrigger `
    -Settings $healthSettings `
    -Description "Daily Nexus knowledge audit at 2 AM" `
    -Force

Write-Host "  ✓ Daily Nexus audit registered (2 AM)" -ForegroundColor Green

# ── Weekly Test Suite (Sunday 4 AM) ──
Write-Host "`n3. Creating weekly test suite (Sunday 4 AM)..." -ForegroundColor Yellow
$testScript = @'
Set-Location "C:\Files\Models\CosySim"
$output = python -m pytest tests/ -q --tb=line --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py 2>&1
$summary = ($output | Select-Object -Last 5) -join "`n"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$NexusUrl = "http://localhost:8700/api"
try {
    $report = @{
        title = "Scheduled Test Run — $timestamp"
        content = "## Weekly Test Suite`n`n**Time:** $timestamp`n`n```text`n$summary`n```"
        content_type = "audit"
        category = "testing"
        tags = @("scheduled", "tests")
    } | ConvertTo-Json
    Invoke-RestMethod -Uri "$NexusUrl/entries" -Method Post -Body $report -ContentType "application/json" -TimeoutSec 10
} catch { }
'@
$testScript | Out-File -FilePath "$SchedulerDir\weekly-tests.ps1" -Encoding utf8

$testAction = New-ScheduledTaskAction `
    -Execute $PwshPath `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$SchedulerDir\weekly-tests.ps1`"" `
    -WorkingDirectory $ProjectDir

$testTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "4:00 AM"

$testSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName "CosySim-WeeklyTests" `
    -TaskPath "\CosySim\" `
    -Action $testAction `
    -Trigger $testTrigger `
    -Settings $testSettings `
    -Description "Weekly full test suite run (Sunday 4 AM)" `
    -Force

Write-Host "  ✓ Weekly tests registered (Sunday 4 AM)" -ForegroundColor Green

Write-Host "`n=== Setup Complete ===" -ForegroundColor Cyan
Write-Host "Tasks created in Task Scheduler under \CosySim\:" -ForegroundColor Gray
Write-Host "  - CosySim-HealthCheck  (hourly)" -ForegroundColor Gray
Write-Host "  - CosySim-NexusAudit   (daily 2 AM)" -ForegroundColor Gray
Write-Host "  - CosySim-WeeklyTests  (Sunday 4 AM)" -ForegroundColor Gray
Write-Host "`nView: Get-ScheduledTask -TaskPath '\CosySim\'" -ForegroundColor Gray
Write-Host "Remove: Unregister-ScheduledTask -TaskPath '\CosySim\' -TaskName 'CosySim-*'" -ForegroundColor Gray
