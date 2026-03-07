#!/usr/bin/env pwsh
# Hook script: Log tool usage and mark successful Nexus consultation
# Called by cosysim-hooks.json postToolUse hook
# Tracks successful tool calls for later safety checks

param()

function Get-SessionState {
    param([string]$Path)

    if (Test-Path $Path) {
        try {
            $raw = Get-Content $Path -Raw
            if ($raw.Trim()) {
                $state = $raw | ConvertFrom-Json -AsHashtable -ErrorAction SilentlyContinue
                if ($state -is [hashtable]) {
                    return $state
                }
            }
        } catch {
        }
    }
    return @{}
}

function Update-SessionState {
    param(
        [string]$Path,
        [hashtable]$Updates
    )

    $state = Get-SessionState -Path $Path
    foreach ($key in $Updates.Keys) {
        $state[$key] = $Updates[$key]
    }
    $state | ConvertTo-Json -Compress | Set-Content $Path
}

$logDir = Join-Path $PSScriptRoot ".." "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

$logFile = Join-Path $logDir "tools.jsonl"
$sessionFile = Join-Path $logDir "current_session.json"

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

            $tool = if ($parsed.toolName) { [string]$parsed.toolName } else { "" }
            if ($tool -match "nexus|notebooklm|nlm") {
                Update-SessionState -Path $sessionFile -Updates @{
                    nexus_consulted = $true
                    nexus_last_tool = $tool
                    nexus_last_success_at = if ($parsed.timestamp) { $parsed.timestamp } else { (Get-Date -Format o) }
                }
            }
        }
    }
} catch {
    # Silently fail — hooks must not block the agent
}
