# 🎨 NEXUS CANVAS Startup Script
# Starts the Notebook-Canvas Express frontend (5590) and Python sidecar (5591)
# Usage: .\scripts\start_canvas.ps1

param(
    [int]$CanvasPort = 5590,
    [int]$SidecarPort = 5591,
    [switch]$SidecarOnly,
    [switch]$CanvasOnly
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$CanvasDir = Join-Path $ProjectRoot "content\apps\notebook_canvas"

Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host "  🎨 NEXUS CANVAS Startup" -ForegroundColor Green
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host ""

function Test-PortFree([int]$Port) {
    $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($conn) {
        Write-Host "  ⚠️  Port $Port already in use by PID $($conn[0].OwningProcess)" -ForegroundColor Red
        return $false
    }
    return $true
}

# ── Python Sidecar (5591) ─────────────────────────────────────────────────
if (-not $CanvasOnly) {
    Write-Host "Starting Canvas API Sidecar..." -ForegroundColor Yellow
    if (-not (Test-PortFree $SidecarPort)) {
        Write-Host "  ❌ Sidecar port $SidecarPort occupied — skipping" -ForegroundColor Red
    } else {
        try {
            $sidecarJob = Start-Process python -ArgumentList "-m engine.nexus.canvas_api --port $SidecarPort" `
                -PassThru -NoNewWindow -WorkingDirectory $ProjectRoot
            Start-Sleep -Seconds 2
            if ($sidecarJob.HasExited) {
                Write-Host "  ❌ Sidecar failed (exit code: $($sidecarJob.ExitCode))" -ForegroundColor Red
            } else {
                Write-Host "  ✅ Sidecar running at http://localhost:$SidecarPort (PID: $($sidecarJob.Id))" -ForegroundColor Green
            }
        } catch {
            Write-Host "  ❌ Sidecar error: $_" -ForegroundColor Red
        }
    }
    Write-Host ""
}

# ── Express Frontend (5590) ───────────────────────────────────────────────
if (-not $SidecarOnly) {
    Write-Host "Starting Nexus Canvas Express Server..." -ForegroundColor Yellow

    # Install deps if node_modules missing
    $nodeModules = Join-Path $CanvasDir "node_modules"
    if (-not (Test-Path $nodeModules)) {
        Write-Host "  📦 Installing npm dependencies..." -ForegroundColor Yellow
        Push-Location $CanvasDir
        npm install --silent
        Pop-Location
        Write-Host "  ✅ Dependencies installed" -ForegroundColor Green
    }

    if (-not (Test-PortFree $CanvasPort)) {
        Write-Host "  ❌ Canvas port $CanvasPort occupied — skipping" -ForegroundColor Red
    } else {
        try {
            $env:PORT = $CanvasPort
            $env:CANVAS_SIDECAR_URL = "http://localhost:$SidecarPort"
            $canvasJob = Start-Process node -ArgumentList "server.ts" `
                -PassThru -NoNewWindow -WorkingDirectory $CanvasDir `
                -Environment @{ PORT = "$CanvasPort"; CANVAS_SIDECAR_URL = "http://localhost:$SidecarPort" }
            Start-Sleep -Seconds 3
            if ($canvasJob.HasExited) {
                Write-Host "  ❌ Canvas server failed — trying tsx..." -ForegroundColor Red
                # Fallback: use tsx if registered
                $tsxPath = Join-Path $CanvasDir "node_modules\.bin\tsx.cmd"
                if (Test-Path $tsxPath) {
                    $canvasJob = Start-Process $tsxPath -ArgumentList "server.ts" `
                        -PassThru -NoNewWindow -WorkingDirectory $CanvasDir
                    Start-Sleep -Seconds 3
                }
            }
            if (-not $canvasJob.HasExited) {
                Write-Host "  ✅ Canvas server at http://localhost:$CanvasPort (PID: $($canvasJob.Id))" -ForegroundColor Green
            } else {
                Write-Host "  ❌ Canvas server failed to start" -ForegroundColor Red
            }
        } catch {
            Write-Host "  ❌ Canvas server error: $_" -ForegroundColor Red
        }
    }
    Write-Host ""
}

Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host "  🎨 NEXUS CANVAS Ready" -ForegroundColor Green
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host ""
Write-Host "  Canvas UI  : http://localhost:$CanvasPort" -ForegroundColor Cyan
Write-Host "  API Sidecar: http://localhost:$SidecarPort/api/health" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Connected to:" -ForegroundColor Yellow
Write-Host "    Nexus KMS   : http://localhost:8700" -ForegroundColor White
Write-Host "    LMStudio    : http://localhost:1234" -ForegroundColor White
Write-Host "    NotebookLM  : via canvas_api.py sidecar" -ForegroundColor White
Write-Host ""
