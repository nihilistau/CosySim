# ══════════════════════════════════════════════════════════════
# CosySim Service Starter — v1.52.0 [2026-03-26]
# ══════════════════════════════════════════════════════════════
# Starts backend services only (Nexus KMS, Hub).
# Run this FIRST, then use start_scenes.ps1 to launch game scenes.
#
# Usage:
#   .\scripts\start_services.ps1            # Start services
#   .\scripts\start_services.ps1 -NoCanvas  # Skip Node.js Canvas
#
# Run from project root: C:\Files\Models\CosySim
# ══════════════════════════════════════════════════════════════

param(
    [switch]$NoCanvas
)

$ErrorActionPreference = "Continue"
$Root = "C:\Files\Models\CosySim"
$VenvPython = "$Root\.venv\Scripts\python.exe"
$NexusRoot = "C:\Files\Nexus"

Set-Location $Root

Write-Host ""
Write-Host "  CosySim Services" -ForegroundColor Cyan
Write-Host "  =================" -ForegroundColor DarkCyan
Write-Host ""

# ── Helper: Wait for port ─────────────────────────────────
function Wait-ForPort {
    param([int]$Port, [string]$Name, [int]$TimeoutSec = 30)
    $elapsed = 0
    while ($elapsed -lt $TimeoutSec) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect("localhost", $Port)
            $tcp.Close()
            Write-Host "  [OK] $Name on :$Port" -ForegroundColor Green
            return $true
        } catch {
            Start-Sleep -Seconds 2
            $elapsed += 2
        }
    }
    Write-Host "  [!!] $Name :$Port timeout" -ForegroundColor Red
    return $false
}

# ── Nexus KMS ─────────────────────────────────────────────
Write-Host "  Starting Nexus KMS..." -ForegroundColor Yellow
Start-Process -FilePath $VenvPython `
    -ArgumentList "-m", "nexus", "api" `
    -WorkingDirectory $NexusRoot `
    -WindowStyle Minimized
Wait-ForPort -Port 8700 -Name "Nexus KMS" -TimeoutSec 20

# ── Hub ───────────────────────────────────────────────────
Write-Host "  Starting Hub..." -ForegroundColor Yellow
Start-Process -FilePath $VenvPython `
    -ArgumentList "launcher.py", "hub" `
    -WorkingDirectory $Root `
    -WindowStyle Minimized
Wait-ForPort -Port 8500 -Name "Hub" -TimeoutSec 30

# ── Canvas (optional) ─────────────────────────────────────
if (-not $NoCanvas) {
    $canvasDir = "$Root\content\apps\notebook_canvas"
    if (Test-Path "$canvasDir\package.json") {
        Write-Host "  Starting Canvas..." -ForegroundColor Yellow
        Start-Process -FilePath "node" `
            -ArgumentList "server.js" `
            -WorkingDirectory $canvasDir `
            -WindowStyle Minimized -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "  [--] Canvas skipped" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "  Services ready! Now run:" -ForegroundColor Green
Write-Host "    .\scripts\start_scenes.ps1" -ForegroundColor White
Write-Host "    .\scripts\start_scenes.ps1 -Scene oracle" -ForegroundColor White
Write-Host ""
