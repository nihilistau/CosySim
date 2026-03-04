#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Launches Chrome with remote debugging enabled on port 9222.
    Must close all existing Chrome instances first — the flag only works
    when passed to the INITIAL browser process, not inherited renderers.

.USAGE
    .\scripts\launch_chrome_debug.ps1           # close existing, reopen on 9222
    .\scripts\launch_chrome_debug.ps1 -KeepOpen  # don't kill existing Chrome
    .\scripts\launch_chrome_debug.ps1 -Port 9223  # use a different port

.NOTE
    After running, verify with: curl http://localhost:9222/json/version
#>
param(
    [int]$Port = 9222,
    [switch]$KeepOpen,
    [string]$Url = "http://localhost:5590",  # Open canvas by default
    [switch]$Quiet
)

$CHROME = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$USER_DATA = "$env:LOCALAPPDATA\Google\Chrome\User Data"

if (-not (Test-Path $CHROME)) {
    Write-Host "❌ Chrome not found at: $CHROME" -ForegroundColor Red
    exit 1
}

# ── Kill existing Chrome if needed ────────────────────────────────────────
if (-not $KeepOpen) {
    $existing = Get-Process -Name "chrome" -ErrorAction SilentlyContinue
    if ($existing) {
        if (-not $Quiet) { Write-Host "⏹  Closing $($existing.Count) Chrome processes..." -ForegroundColor Yellow }
        $existing | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 800
    }
}

# ── Check if port already open ─────────────────────────────────────────────
try {
    $check = Invoke-RestMethod "http://localhost:$Port/json/version" -TimeoutSec 2
    Write-Host "✅ Chrome already debugging on port $Port`: $($check.Browser)" -ForegroundColor Green
    exit 0
} catch { }

# ── Launch Chrome with debugging ───────────────────────────────────────────
if (-not $Quiet) { Write-Host "🚀 Launching Chrome with --remote-debugging-port=$Port" -ForegroundColor Cyan }

$args = @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=`"$USER_DATA`"",
    "--no-first-run",
    "--no-default-browser-check"
)
if ($Url) { $args += $Url }

Start-Process $CHROME -ArgumentList $args

# ── Wait for debug port to open ────────────────────────────────────────────
$timeout = 15
$elapsed = 0
while ($elapsed -lt $timeout) {
    Start-Sleep -Milliseconds 500
    $elapsed += 0.5
    try {
        $info = Invoke-RestMethod "http://localhost:$Port/json/version" -TimeoutSec 1
        if (-not $Quiet) {
            Write-Host ""
            Write-Host "✅ Chrome debugging ready!" -ForegroundColor Green
            Write-Host "   Browser : $($info.Browser)" -ForegroundColor White
            Write-Host "   Port    : $Port" -ForegroundColor White
            Write-Host "   DevTools: $($info.devtoolsFrontendUrl)" -ForegroundColor White
            Write-Host ""
            Write-Host "   Connect via: http://localhost:$Port/json/list" -ForegroundColor Cyan
        }
        exit 0
    } catch { }
    if (-not $Quiet) { Write-Host "." -NoNewline }
}

Write-Host ""
Write-Host "⚠️  Chrome launched but debug port not responding after ${timeout}s" -ForegroundColor Yellow
Write-Host "   Try opening: chrome://flags/#enable-devtools-experiments" -ForegroundColor Gray
