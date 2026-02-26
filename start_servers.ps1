# 🚀 CosyVoice3 Server Launcher
# Starts TTS and STT servers for AnythingLLM integration

param(
    [string]$Mode = "both",  # both, tts, stt
    [string]$Host = "0.0.0.0",
    [int]$TTSPort = 5050,
    [int]$STTPort = 5051,
    [string]$WhisperModel = "tiny"
)

Write-Host "`n"
Write-Host "="*70 -ForegroundColor Cyan
Write-Host "  🎙️ CosyVoice3 Server Launcher" -ForegroundColor Green
Write-Host "="*70 -ForegroundColor Cyan
Write-Host ""

# Get local IP address
$localIP = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "Ethernet*", "Wi-Fi*" | 
            Where-Object {$_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.*"} | 
            Select-Object -First 1).IPAddress

if (-not $localIP) {
    $localIP = "127.0.0.1"
}

Write-Host "Network Configuration:" -ForegroundColor Yellow
Write-Host "  Local IP: $localIP" -ForegroundColor Cyan
Write-Host "  TTS Port: $TTSPort" -ForegroundColor Cyan
Write-Host "  STT Port: $STTPort" -ForegroundColor Cyan
Write-Host ""

# Check port availability
function Test-PortFree([int]$Port) {
    $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($conn) {
        Write-Host "  ⚠️  Port $Port already in use by PID $($conn[0].OwningProcess)" -ForegroundColor Red
        return $false
    }
    return $true
}

# Start TTS Server
if ($Mode -eq "both" -or $Mode -eq "tts") {
    Write-Host "Starting TTS Server..." -ForegroundColor Yellow
    if (-not (Test-PortFree $TTSPort)) {
        Write-Host "  ❌ TTS port $TTSPort is occupied — skipping" -ForegroundColor Red
    } else {
        Write-Host "  Endpoint: http://${localIP}:${TTSPort}/v1/audio/speech" -ForegroundColor Cyan
        Write-Host "  Model: CosyVoice3-0.5B" -ForegroundColor Cyan
        
        try {
            $ttsJob = Start-Process python -ArgumentList "tts_server.py --host $Host --port $TTSPort" -PassThru -NoNewWindow
            Start-Sleep -Seconds 2
            
            if ($ttsJob.HasExited) {
                Write-Host "  ❌ TTS server failed to start (exit code: $($ttsJob.ExitCode))" -ForegroundColor Red
            } else {
                Write-Host "  ✅ TTS server started (PID: $($ttsJob.Id))" -ForegroundColor Green
            }
        } catch {
            Write-Host "  ❌ TTS server error: $_" -ForegroundColor Red
        }
    }
    Write-Host ""
}

# Start STT Server
if ($Mode -eq "both" -or $Mode -eq "stt") {
    Write-Host "Starting STT Server..." -ForegroundColor Yellow
    if (-not (Test-PortFree $STTPort)) {
        Write-Host "  ❌ STT port $STTPort is occupied — skipping" -ForegroundColor Red
    } else {
        Write-Host "  Endpoint: http://${localIP}:${STTPort}/v1/audio/transcriptions" -ForegroundColor Cyan
        Write-Host "  Model: Whisper $WhisperModel" -ForegroundColor Cyan
        
        try {
            $sttJob = Start-Process python -ArgumentList "stt_server.py --host $Host --port $STTPort --model $WhisperModel" -PassThru -NoNewWindow
            Start-Sleep -Seconds 2
            
            if ($sttJob.HasExited) {
                Write-Host "  ❌ STT server failed to start (exit code: $($sttJob.ExitCode))" -ForegroundColor Red
            } else {
                Write-Host "  ✅ STT server started (PID: $($sttJob.Id))" -ForegroundColor Green
            }
        } catch {
            Write-Host "  ❌ STT server error: $_" -ForegroundColor Red
        }
    }
    Write-Host ""
}

Write-Host "="*70 -ForegroundColor Cyan
Write-Host "  🎉 Servers Running!" -ForegroundColor Green
Write-Host "="*70 -ForegroundColor Cyan
Write-Host ""

Write-Host "📝 AnythingLLM Configuration:" -ForegroundColor Yellow
Write-Host ""

if ($Mode -eq "both" -or $Mode -eq "tts") {
    Write-Host "Text-to-Speech (TTS):" -ForegroundColor Cyan
    Write-Host "  Provider: OpenAI Compatible" -ForegroundColor White
    Write-Host "  Base URL: http://${localIP}:${TTSPort}/v1/audio/speech" -ForegroundColor White
    Write-Host "  API Key: (leave empty or use 'sk-dummy')" -ForegroundColor White
    Write-Host "  TTS Model: cosy-voice-3" -ForegroundColor White
    Write-Host "  Voice: alloy (or any name)" -ForegroundColor White
    Write-Host ""
}

if ($Mode -eq "both" -or $Mode -eq "stt") {
    Write-Host "Speech-to-Text (STT):" -ForegroundColor Cyan
    Write-Host "  Provider: Local Whisper (or OpenAI Compatible)" -ForegroundColor White
    Write-Host "  Base URL: http://${localIP}:${STTPort}/v1/audio/transcriptions" -ForegroundColor White
    Write-Host "  Model: whisper-$WhisperModel" -ForegroundColor White
    Write-Host ""
}

Write-Host "🔗 Quick Test URLs:" -ForegroundColor Yellow
if ($Mode -eq "both" -or $Mode -eq "tts") {
    Write-Host "  TTS Health: http://${localIP}:${TTSPort}/health" -ForegroundColor Cyan
}
if ($Mode -eq "both" -or $Mode -eq "stt") {
    Write-Host "  STT Health: http://${localIP}:${STTPort}/health" -ForegroundColor Cyan
}
Write-Host ""

Write-Host "🛑 To stop servers:" -ForegroundColor Yellow
Write-Host "  Press Ctrl+C or close this window" -ForegroundColor White
Write-Host "  Or kill processes with PIDs shown above" -ForegroundColor White
Write-Host ""

Write-Host "Press Ctrl+C to stop servers..." -ForegroundColor Gray

# Wait for user interrupt
try {
    while ($true) {
        Start-Sleep -Seconds 1
    }
} finally {
    Write-Host "`nStopping servers..." -ForegroundColor Yellow
    if ($ttsJob) { Stop-Process -Id $ttsJob.Id -Force -ErrorAction SilentlyContinue }
    if ($sttJob) { Stop-Process -Id $sttJob.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "✅ Servers stopped" -ForegroundColor Green
}
