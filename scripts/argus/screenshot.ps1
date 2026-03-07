# Save desktop screenshots to the ignored ARGUS artifact root.
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$saveFolder = Join-Path $repoRoot "artifacts\argus\screenshots"
if (!(Test-Path $saveFolder)) { New-Item -ItemType Directory -Path $saveFolder | Out-Null }

Add-Type -AssemblyName System.Windows.Forms, System.Drawing

$code = @"
    using System;
    using System.Runtime.InteropServices;
    public class WinAPI {
        [DllImport("user32.dll")]
        public static extern bool SetForegroundWindow(IntPtr hWnd);
    }
"@
Add-Type -TypeDefinition $code

$chrome = Get-Process -Name "chrome" | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if ($chrome) {
    [WinAPI]::SetForegroundWindow($chrome.MainWindowHandle)
    Start-Sleep -Milliseconds 500
} else {
    Write-Error "Chrome is not running."
    exit
}

$screen = [Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object Drawing.Bitmap $screen.Width, $screen.Height
$graphics = [Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.X, $screen.Y, 0, 0, $bitmap.Size)

$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$filePath = Join-Path $saveFolder "Chrome_Capture_$timestamp.png"
$bitmap.Save($filePath, [Drawing.Imaging.ImageFormat]::Png)

$graphics.Dispose()
$bitmap.Dispose()
Write-Host "Screenshot saved to: $filePath"
