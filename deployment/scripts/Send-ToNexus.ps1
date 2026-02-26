<#
.SYNOPSIS
    Sends clipboard content (text or URL) to Nexus Knowledge Management System.
.DESCRIPTION
    Detects whether clipboard contains a URL or text, then sends it to Nexus API.
    Shows a Windows toast notification with the result.
.NOTES
    Assign to Logitech M720 Back button or MX Keys shortcut.
#>

$NexusUrl = "http://localhost:8700/api"
$Category = "research"
$Tags = @("clipboard-capture", "quick-send")

function Show-Toast {
    param([string]$Title, [string]$Message)
    [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null
    $notify = New-Object System.Windows.Forms.NotifyIcon
    $notify.Icon = [System.Drawing.SystemIcons]::Information
    $notify.BalloonTipTitle = $Title
    $notify.BalloonTipText = $Message
    $notify.Visible = $true
    $notify.ShowBalloonTip(3000)
    Start-Sleep -Seconds 3
    $notify.Dispose()
}

try {
    Add-Type -AssemblyName System.Windows.Forms
    $clip = [System.Windows.Forms.Clipboard]::GetText()

    if ([string]::IsNullOrWhiteSpace($clip)) {
        Show-Toast "Nexus" "Clipboard is empty"
        exit
    }

    $isUrl = $clip -match "^https?://"
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    if ($isUrl) {
        $title = "Web: $($clip.Substring(0, [Math]::Min(60, $clip.Length)))"
        $content = "## URL Capture`n`n**URL:** $clip`n**Captured:** $timestamp"
        $contentType = "document"
    } else {
        $preview = $clip.Substring(0, [Math]::Min(60, $clip.Length))
        $title = "Note: $preview..."
        $content = "## Clipboard Capture`n`n$clip`n`n**Captured:** $timestamp"
        $contentType = "note"
    }

    $body = @{
        title = $title
        content = $content
        content_type = $contentType
        category = $Category
        tags = $Tags
    } | ConvertTo-Json

    $response = Invoke-RestMethod -Uri "$NexusUrl/entries" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 5

    Show-Toast "Nexus ✓" "Saved: $title"
} catch {
    Show-Toast "Nexus ✗" "Failed: $($_.Exception.Message)"
}
