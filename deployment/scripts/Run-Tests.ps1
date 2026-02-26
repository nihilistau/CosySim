<#
.SYNOPSIS
    Runs CosySim test suite and shows notification with results.
.DESCRIPTION
    Runs pytest, counts pass/fail, shows Windows toast notification.
.NOTES
    Assign to Logitech gesture button + Left or Win+Shift+T hotkey.
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

$projectDir = "C:\Files\Models\CosySim"
Set-Location $projectDir

try {
    $output = python -m pytest tests/ -q --tb=line --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py 2>&1
    $lastLine = ($output | Select-Object -Last 3) -join " "

    if ($lastLine -match "(\d+) passed") {
        $passed = $Matches[1]
        $failed = if ($lastLine -match "(\d+) failed") { $Matches[1] } else { "0" }
        $title = if ($failed -eq "0") { "Tests ✓ All Passed" } else { "Tests ✗ $failed Failed" }
        Show-Toast $title "$passed passed, $failed failed"
    } else {
        Show-Toast "Tests" $lastLine
    }
} catch {
    Show-Toast "Tests ✗" "Error: $($_.Exception.Message)"
}
