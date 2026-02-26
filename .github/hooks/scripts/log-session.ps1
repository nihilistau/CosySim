#!/usr/bin/env pwsh
# Hook script: Log session start/end events
# Called by cosysim-hooks.json sessionStart and sessionEnd hooks

param()

$logDir = Join-Path $PSScriptRoot ".." "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

$logFile = Join-Path $logDir "session.log"

try {
    $timestamp = Get-Date -Format o
    $inputData = $input | Out-String
    $event = "unknown"

    if ($inputData.Trim()) {
        $parsed = $inputData | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($parsed.event) { $event = $parsed.event }
    }

    Add-Content -Path $logFile -Value "[HOOK] $event at $timestamp"
} catch {
    # Silently fail
}
