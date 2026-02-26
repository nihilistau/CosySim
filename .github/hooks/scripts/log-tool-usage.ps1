#!/usr/bin/env pwsh
# Hook script: Log tool usage to JSONL audit trail
# Called by cosysim-hooks.json postToolUse hook
# Input: JSON object with toolName, timestamp, etc. via stdin

param()

$logDir = Join-Path $PSScriptRoot ".." "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

$logFile = Join-Path $logDir "tools.jsonl"

try {
    $inputData = $input | Out-String
    if ($inputData.Trim()) {
        $parsed = $inputData | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($parsed) {
            $entry = @{
                toolName  = $parsed.toolName
                timestamp = if ($parsed.timestamp) { $parsed.timestamp } else { (Get-Date -Format o) }
                session   = $parsed.sessionId
            } | ConvertTo-Json -Compress
            Add-Content -Path $logFile -Value $entry
        }
    }
} catch {
    # Silently fail — hooks must not block the agent
}
