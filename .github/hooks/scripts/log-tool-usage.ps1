#!/usr/bin/env pwsh
# Hook script: Log tool usage and track Nexus consultation
# Called by cosysim-hooks.json postToolUse hook
# Tracks tool calls + stores LLM answers in Nexus cache

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

            # Track tool usage in CopilotBridge (non-blocking)
            $tool = $parsed.toolName
            if ($tool) {
                $escaped = $tool -replace "'", "''"
                python -c "
try:
    from engine.nexus.copilot_bridge import get_copilot_bridge
    get_copilot_bridge().track_tool_use('$escaped')
except Exception:
    pass
" 2>$null
            }
        }
    }
} catch {
    # Silently fail — hooks must not block the agent
}
