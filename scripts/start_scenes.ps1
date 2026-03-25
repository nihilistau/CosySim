# ══════════════════════════════════════════════════════════════
# CosySim Scene Launcher — v1.52.0 [2026-03-26]
# ══════════════════════════════════════════════════════════════
# Launches game scenes AFTER services are running.
# Run start_services.ps1 first!
#
# Usage:
#   .\scripts\start_scenes.ps1                # All auto-start scenes
#   .\scripts\start_scenes.ps1 -Scene oracle  # Single scene
#   .\scripts\start_scenes.ps1 -Core          # Core scenes only
#   .\scripts\start_scenes.ps1 -List          # Show available scenes
#
# Run from project root: C:\Files\Models\CosySim
# ══════════════════════════════════════════════════════════════

param(
    [string]$Scene = "",
    [switch]$Core,
    [switch]$List
)

$ErrorActionPreference = "Continue"
$Root = "C:\Files\Models\CosySim"
$VenvPython = "$Root\.venv\Scripts\python.exe"

Set-Location $Root

# ── Check services are running ────────────────────────────
function Test-Port {
    param([int]$Port)
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("localhost", $Port)
        $tcp.Close()
        return $true
    } catch { return $false }
}

$nexusUp = Test-Port 8700
$hubUp = Test-Port 8500

if (-not $nexusUp) {
    Write-Host "  [!!] Nexus KMS not running. Run start_services.ps1 first!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "  CosySim Scenes" -ForegroundColor Cyan
Write-Host "  ===============" -ForegroundColor DarkCyan
Write-Host "  Nexus: $(if ($nexusUp) { 'UP' } else { 'DOWN' })  Hub: $(if ($hubUp) { 'UP' } else { 'DOWN' })" -ForegroundColor DarkGray
Write-Host ""

# ── List mode ─────────────────────────────────────────────
if ($List) {
    & $VenvPython launcher.py --list
    exit 0
}

# ── Helper: Kill zombie on port ───────────────────────────
function Clear-Port {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($conn) {
        $pid = $conn.OwningProcess | Select-Object -First 1
        if ($pid -and $pid -ne 0) {
            Write-Host "  [!!] Killing zombie on :$Port (PID $pid)" -ForegroundColor Yellow
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        }
    }
}

# ── Single scene mode ─────────────────────────────────────
if ($Scene) {
    # Get port first so we can clear zombies
    $port = & $VenvPython -c "from engine.port_registry import get_port; print(get_port('$Scene'))" 2>$null
    if ($port) { Clear-Port -Port ([int]$port) }

    Write-Host "  Starting $Scene..." -ForegroundColor Yellow
    Start-Process -FilePath $VenvPython `
        -ArgumentList "launcher.py", $Scene `
        -WorkingDirectory $Root `
        -WindowStyle Minimized
    if ($port) {
        $elapsed = 0
        while ($elapsed -lt 30) {
            if (Test-Port ([int]$port)) {
                Write-Host "  [OK] $Scene on :$port" -ForegroundColor Green
                Write-Host "       http://localhost:$port" -ForegroundColor White
                break
            }
            Start-Sleep -Seconds 2
            $elapsed += 2
        }
        if ($elapsed -ge 30) {
            Write-Host "  [..] $Scene :$port still starting (check manually)" -ForegroundColor DarkGray
        }
    }
    Write-Host ""
    exit 0
}

# ── Auto-start scenes ────────────────────────────────────
Write-Host "  Launching auto-start scenes..." -ForegroundColor Yellow

$scenes = & $VenvPython -c "
from engine.control_plane_registry import SCENE_DEFS
from engine.port_registry import get_port
for name, d in SCENE_DEFS.items():
    if d.get('auto_start'):
        print(f'{name} {get_port(name)}')
" 2>$null

$launched = @()
foreach ($line in $scenes -split "`n") {
    $parts = $line.Trim() -split " "
    if ($parts.Count -eq 2) {
        $name = $parts[0]
        $port = $parts[1]
        Write-Host "  Starting $name (:$port)..." -ForegroundColor Yellow
        Start-Process -FilePath $VenvPython `
            -ArgumentList "launcher.py", $name `
            -WorkingDirectory $Root `
            -WindowStyle Minimized
        $launched += @{ name = $name; port = [int]$port }
        Start-Sleep -Seconds 2
    }
}

# Wait and check
Write-Host ""
Write-Host "  Waiting for scenes..." -ForegroundColor Yellow
Start-Sleep -Seconds 15

foreach ($s in $launched) {
    if (Test-Port $s.port) {
        Write-Host "  [OK] $($s.name) on :$($s.port)" -ForegroundColor Green
    } else {
        Write-Host "  [..] $($s.name) :$($s.port) still starting" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "  Open http://localhost:8500 for the Hub" -ForegroundColor Cyan
Write-Host ""
