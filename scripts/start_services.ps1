# ══════════════════════════════════════════════════════════════
# CosySim Service Starter — v1.52.0 [2026-03-26]
# ══════════════════════════════════════════════════════════════
# Starts all services in correct order, waits for health checks,
# then optionally launches game scenes.
#
# Usage:
#   .\scripts\start_services.ps1              # Services only
#   .\scripts\start_services.ps1 -WithScenes  # Services + auto-start scenes
#   .\scripts\start_services.ps1 -Scene oracle # Services + specific scene
#
# Run from project root: C:\Files\Models\CosySim
# ══════════════════════════════════════════════════════════════

param(
    [switch]$WithScenes,
    [string]$Scene = "",
    [switch]$NoCanvas
)

$ErrorActionPreference = "Continue"
$Root = "C:\Files\Models\CosySim"
$VenvPython = "$Root\.venv\Scripts\python.exe"
$NexusRoot = "C:\Files\Nexus"

Set-Location $Root

Write-Host ""
Write-Host "  CosySim Service Starter" -ForegroundColor Cyan
Write-Host "  ========================" -ForegroundColor DarkCyan
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
            Write-Host "  [OK] $Name is UP on port $Port" -ForegroundColor Green
            return $true
        } catch {
            Start-Sleep -Seconds 2
            $elapsed += 2
        }
    }
    Write-Host "  [!!] $Name failed to start on port $Port (timeout ${TimeoutSec}s)" -ForegroundColor Red
    return $false
}

# ── Step 1: Start Nexus KMS ──────────────────────────────
Write-Host "  Starting Nexus KMS (:8700)..." -ForegroundColor Yellow
$nexusProc = Start-Process -FilePath $VenvPython `
    -ArgumentList "-m", "nexus", "api" `
    -WorkingDirectory $NexusRoot `
    -WindowStyle Hidden `
    -PassThru

if (Wait-ForPort -Port 8700 -Name "Nexus KMS" -TimeoutSec 20) {
    # Verify API responds
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:8700/api/entries?limit=1" -TimeoutSec 5
        Write-Host "  [OK] Nexus API responding ($($health.data.Count) entries)" -ForegroundColor Green
    } catch {
        Write-Host "  [!!] Nexus API check failed: $_" -ForegroundColor Yellow
    }
}

# ── Step 2: Start Hub ────────────────────────────────────
Write-Host "  Starting Hub (:8500)..." -ForegroundColor Yellow
$hubProc = Start-Process -FilePath $VenvPython `
    -ArgumentList "launcher.py", "hub" `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -PassThru

Wait-ForPort -Port 8500 -Name "Hub" -TimeoutSec 30

# ── Step 3: Start Canvas (Node.js) ──────────────────────
if (-not $NoCanvas) {
    $canvasDir = "$Root\content\apps\notebook_canvas"
    if (Test-Path "$canvasDir\package.json") {
        Write-Host "  Starting Canvas (:5590)..." -ForegroundColor Yellow
        $canvasProc = Start-Process -FilePath "node" `
            -ArgumentList "server.js" `
            -WorkingDirectory $canvasDir `
            -WindowStyle Hidden `
            -PassThru -ErrorAction SilentlyContinue
        # Don't wait — Canvas is optional
    }
} else {
    Write-Host "  Skipping Canvas (--NoCanvas)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "  Services ready!" -ForegroundColor Green
Write-Host ""

# ── Step 4: Launch scenes if requested ───────────────────
if ($Scene) {
    Write-Host "  Starting scene: $Scene..." -ForegroundColor Yellow
    $sceneProc = Start-Process -FilePath $VenvPython `
        -ArgumentList "launcher.py", $Scene `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -PassThru

    # Get port for the scene
    $portCheck = & $VenvPython -c "from engine.port_registry import get_port; print(get_port('$Scene'))" 2>$null
    if ($portCheck) {
        Wait-ForPort -Port ([int]$portCheck) -Name $Scene -TimeoutSec 30
    }
}
elseif ($WithScenes) {
    Write-Host "  Starting auto-start scenes..." -ForegroundColor Yellow

    # Get auto-start scenes from registry
    $autoScenes = & $VenvPython -c "
from engine.control_plane_registry import SCENE_DEFS
for name, d in SCENE_DEFS.items():
    if d.get('auto_start'):
        print(name)
" 2>$null

    foreach ($s in $autoScenes -split "`n") {
        $s = $s.Trim()
        if ($s) {
            Write-Host "  Starting $s..." -ForegroundColor Yellow
            Start-Process -FilePath $VenvPython `
                -ArgumentList "launcher.py", $s `
                -WorkingDirectory $Root `
                -WindowStyle Hidden
            Start-Sleep -Seconds 2
        }
    }

    Write-Host ""
    Write-Host "  Waiting for scenes to initialize..." -ForegroundColor Yellow
    Start-Sleep -Seconds 15

    # Check which are up
    $sceneList = & $VenvPython -c "
from engine.control_plane_registry import SCENE_DEFS
from engine.port_registry import get_port
for name, d in SCENE_DEFS.items():
    if d.get('auto_start'):
        print(f'{name} {get_port(name)}')
" 2>$null

    foreach ($line in $sceneList -split "`n") {
        $parts = $line.Trim() -split " "
        if ($parts.Count -eq 2) {
            $name = $parts[0]
            $port = [int]$parts[1]
            try {
                $tcp = New-Object System.Net.Sockets.TcpClient
                $tcp.Connect("localhost", $port)
                $tcp.Close()
                Write-Host "  [OK] $name (:$port)" -ForegroundColor Green
            } catch {
                Write-Host "  [..] $name (:$port) still starting" -ForegroundColor DarkGray
            }
        }
    }
}

Write-Host ""
Write-Host "  Done! Open http://localhost:8500 for the Hub." -ForegroundColor Cyan
Write-Host ""
