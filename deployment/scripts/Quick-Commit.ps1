<#
.SYNOPSIS
    Quick git commit with conventional commit prompt.
.DESCRIPTION
    Shows input dialog for commit type and message, stages all changes, commits.
.NOTES
    Assign to Logitech gesture button + Right or Win+Shift+C hotkey.
#>

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$projectDir = "C:\Files\Models\CosySim"
Set-Location $projectDir

function Show-Toast {
    param([string]$Title, [string]$Message)
    $notify = New-Object System.Windows.Forms.NotifyIcon
    $notify.Icon = [System.Drawing.SystemIcons]::Information
    $notify.BalloonTipTitle = $Title
    $notify.BalloonTipText = $Message
    $notify.Visible = $true
    $notify.ShowBalloonTip(3000)
    Start-Sleep -Seconds 3
    $notify.Dispose()
}

# Check for changes
$status = git --no-pager status --porcelain 2>&1
if ([string]::IsNullOrWhiteSpace($status)) {
    Show-Toast "Git" "No changes to commit"
    exit
}

$changedCount = ($status -split "`n").Count

# Dialog
$form = New-Object System.Windows.Forms.Form
$form.Text = "Quick Commit ($changedCount files)"
$form.Size = New-Object System.Drawing.Size(450, 220)
$form.StartPosition = "CenterScreen"
$form.TopMost = $true
$form.FormBorderStyle = "FixedDialog"
$form.BackColor = [System.Drawing.Color]::FromArgb(26, 26, 46)
$form.ForeColor = [System.Drawing.Color]::White

# Type dropdown
$labelType = New-Object System.Windows.Forms.Label
$labelType.Text = "Type:"
$labelType.Location = New-Object System.Drawing.Point(10, 15)
$labelType.Size = New-Object System.Drawing.Size(50, 20)
$form.Controls.Add($labelType)

$combo = New-Object System.Windows.Forms.ComboBox
$combo.Location = New-Object System.Drawing.Point(65, 12)
$combo.Size = New-Object System.Drawing.Size(120, 25)
$combo.Items.AddRange(@("feat:", "fix:", "docs:", "test:", "chore:", "refactor:"))
$combo.SelectedIndex = 0
$combo.BackColor = [System.Drawing.Color]::FromArgb(22, 33, 62)
$combo.ForeColor = [System.Drawing.Color]::White
$form.Controls.Add($combo)

# Message
$labelMsg = New-Object System.Windows.Forms.Label
$labelMsg.Text = "Message:"
$labelMsg.Location = New-Object System.Drawing.Point(10, 50)
$labelMsg.Size = New-Object System.Drawing.Size(80, 20)
$form.Controls.Add($labelMsg)

$textbox = New-Object System.Windows.Forms.TextBox
$textbox.Location = New-Object System.Drawing.Point(10, 75)
$textbox.Size = New-Object System.Drawing.Size(410, 25)
$textbox.BackColor = [System.Drawing.Color]::FromArgb(22, 33, 62)
$textbox.ForeColor = [System.Drawing.Color]::White
$form.Controls.Add($textbox)

# Files label
$labelFiles = New-Object System.Windows.Forms.Label
$labelFiles.Text = "$changedCount file(s) changed"
$labelFiles.Location = New-Object System.Drawing.Point(10, 110)
$labelFiles.Size = New-Object System.Drawing.Size(200, 20)
$labelFiles.ForeColor = [System.Drawing.Color]::FromArgb(160, 160, 192)
$form.Controls.Add($labelFiles)

# Commit button
$button = New-Object System.Windows.Forms.Button
$button.Text = "Commit"
$button.Location = New-Object System.Drawing.Point(310, 140)
$button.Size = New-Object System.Drawing.Size(110, 30)
$button.BackColor = [System.Drawing.Color]::FromArgb(124, 58, 237)
$button.ForeColor = [System.Drawing.Color]::White
$button.FlatStyle = "Flat"
$button.DialogResult = [System.Windows.Forms.DialogResult]::OK
$form.AcceptButton = $button
$form.Controls.Add($button)

$result = $form.ShowDialog()

if ($result -eq [System.Windows.Forms.DialogResult]::OK -and $textbox.Text.Trim()) {
    $commitMsg = "$($combo.SelectedItem) $($textbox.Text.Trim())"
    try {
        git add -A 2>&1 | Out-Null
        git commit -m $commitMsg -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>" 2>&1 | Out-Null
        Show-Toast "Git ✓" "Committed: $commitMsg"
    } catch {
        Show-Toast "Git ✗" "Commit failed: $($_.Exception.Message)"
    }
}
