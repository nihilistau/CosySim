#!/usr/bin/env pwsh
# Hook script: Log errors to JSONL
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
        }
    }
} catch {
    # Silently fail
}
