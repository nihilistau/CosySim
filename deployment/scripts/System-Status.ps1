<#
.SYNOPSIS
    Quick system health check for all CosySim services.
.DESCRIPTION
    Checks LMStudio, Nexus, TTS, Hub, and ComfyUI. Shows toast notification.
.NOTES
    Assign to Logitech M720 Middle click or Win+Shift+H hotkey.
#>

function Show-Toast {
    param([string]$Title, [string]$Message)
    [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null
    $notify = New-Object System.Windows.Forms.NotifyIcon
    $notify.Icon = [System.Drawing.SystemIcons]::Information
    $notify.BalloonTipTitle = $Title
    $notify.BalloonTipText = $Message
    $notify.Visible = $true
    $notify.ShowBalloonTip(5000)
    Start-Sleep -Seconds 5
    $notify.Dispose()
}

$services = @(
    @{ Name = "LMStudio"; Url = "http://localhost:1234/api/v1/models" },
    @{ Name = "Nexus"; Url = "http://localhost:8700/api/health" },
    @{ Name = "TTS"; Url = "http://localhost:8600/health" },
    @{ Name = "Hub"; Url = "http://localhost:8500/health" },
    @{ Name = "ComfyUI"; Url = "http://localhost:8188/" }
)

$results = @()
foreach ($svc in $services) {
    try {
        $r = Invoke-WebRequest -Uri $svc.Url -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        $results += "✓ $($svc.Name)"
    } catch {
        $results += "✗ $($svc.Name)"
    }
}

$up = ($results | Where-Object { $_ -like "✓*" }).Count
$total = $services.Count
$status = $results -join "`n"

Show-Toast "System: $up/$total online" $status
