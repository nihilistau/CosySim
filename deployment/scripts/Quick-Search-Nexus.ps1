<#
.SYNOPSIS
    Quick Nexus search popup — enter a query, see results.
.DESCRIPTION
    Shows an input dialog, searches Nexus, displays results in a message box.
.NOTES
    Assign to Logitech M720 Forward button or Win+Shift+N hotkey.
#>

$NexusUrl = "http://localhost:8700/api"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Show-Toast {
    param([string]$Title, [string]$Message)
    $notify = New-Object System.Windows.Forms.NotifyIcon
    $notify.Icon = [System.Drawing.SystemIcons]::Information
    $notify.BalloonTipTitle = $Title
    $notify.BalloonTipText = $Message
    $notify.Visible = $true
    $notify.ShowBalloonTip(5000)
    Start-Sleep -Seconds 5
    $notify.Dispose()
}

# Input dialog
$form = New-Object System.Windows.Forms.Form
$form.Text = "Nexus Search"
$form.Size = New-Object System.Drawing.Size(420, 150)
$form.StartPosition = "CenterScreen"
$form.TopMost = $true
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.BackColor = [System.Drawing.Color]::FromArgb(26, 26, 46)
$form.ForeColor = [System.Drawing.Color]::White

$label = New-Object System.Windows.Forms.Label
$label.Text = "Search Nexus:"
$label.Location = New-Object System.Drawing.Point(10, 15)
$label.Size = New-Object System.Drawing.Size(100, 20)
$form.Controls.Add($label)

$textbox = New-Object System.Windows.Forms.TextBox
$textbox.Location = New-Object System.Drawing.Point(10, 40)
$textbox.Size = New-Object System.Drawing.Size(380, 25)
$textbox.BackColor = [System.Drawing.Color]::FromArgb(22, 33, 62)
$textbox.ForeColor = [System.Drawing.Color]::White
$form.Controls.Add($textbox)

$button = New-Object System.Windows.Forms.Button
$button.Text = "Search"
$button.Location = New-Object System.Drawing.Point(300, 75)
$button.Size = New-Object System.Drawing.Size(90, 30)
$button.BackColor = [System.Drawing.Color]::FromArgb(124, 58, 237)
$button.ForeColor = [System.Drawing.Color]::White
$button.FlatStyle = "Flat"
$button.DialogResult = [System.Windows.Forms.DialogResult]::OK
$form.AcceptButton = $button
$form.Controls.Add($button)

$result = $form.ShowDialog()

if ($result -eq [System.Windows.Forms.DialogResult]::OK -and $textbox.Text.Trim()) {
    $query = $textbox.Text.Trim()
    try {
        $response = Invoke-RestMethod -Uri "$NexusUrl/search?q=$([uri]::EscapeDataString($query))&limit=5" -Method Get -TimeoutSec 5

        if ($response.results -and $response.results.Count -gt 0) {
            $resultText = "Found $($response.results.Count) results:`n`n"
            foreach ($r in $response.results) {
                $title = if ($r.title) { $r.title } else { "Untitled" }
                $preview = if ($r.content) { $r.content.Substring(0, [Math]::Min(100, $r.content.Length)) } else { "" }
                $resultText += "• $title`n  $preview...`n`n"
            }
            [System.Windows.Forms.MessageBox]::Show($resultText, "Nexus Results: $query", "OK", "Information")
        } else {
            Show-Toast "Nexus" "No results for: $query"
        }
    } catch {
        Show-Toast "Nexus ✗" "Search failed: $($_.Exception.Message)"
    }
}
