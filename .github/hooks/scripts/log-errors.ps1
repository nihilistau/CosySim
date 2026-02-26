#!/usr/bin/env pwsh
# Hook script: Log errors to JSONL and optionally store in Nexus
# Called by cosysim-hooks.json errorOccurred hook

param()

$logDir = Join-Path $PSScriptRoot ".." "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

$logFile = Join-Path $logDir "errors.jsonl"

try {
    $inputData = $input | Out-String
    if ($inputData.Trim()) {
        $parsed = $inputData | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($parsed) {
            $entry = @{
                error     = $parsed.error
                toolName  = $parsed.toolName
                timestamp = if ($parsed.timestamp) { $parsed.timestamp } else { (Get-Date -Format o) }
            } | ConvertTo-Json -Compress
            Add-Content -Path $logFile -Value $entry

            # Store recurring errors in Nexus for pattern analysis (non-blocking)
            $errMsg = if ($parsed.error) { ($parsed.error -replace "'", "''").Substring(0, [Math]::Min(200, $parsed.error.Length)) } else { "" }
            $tool = if ($parsed.toolName) { $parsed.toolName -replace "'", "''" } else { "unknown" }
            if ($errMsg) {
                python -c "
try:
    from engine.nexus.copilot_bridge import get_copilot_bridge
    get_copilot_bridge().track_error('$tool', '$errMsg')
except Exception:
    pass
" 2>$null
            }
        }
    }
} catch {
    # Silently fail
}
