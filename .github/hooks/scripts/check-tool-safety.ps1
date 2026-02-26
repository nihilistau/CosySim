#!/usr/bin/env pwsh
# Hook script: Check tool safety + remind about Nexus-first workflow
# Called by cosysim-hooks.json preToolUse hook
# Returns JSON with "decision": "approve" or "deny"

param()

try {
    $inputData = $input | Out-String
    if ($inputData.Trim()) {
        $parsed = $inputData | ConvertFrom-Json -ErrorAction SilentlyContinue
        $toolName = if ($parsed.toolName) { $parsed.toolName } else { "" }

        # Block destructive operations without explicit approval
        $blocked = @("delete", "remove", "drop", "truncate", "destroy", "purge")
        $isBlocked = $false
        foreach ($word in $blocked) {
            if ($toolName -match $word) {
                $isBlocked = $true
                break
            }
        }

        if ($isBlocked) {
            Write-Output '{"decision": "deny", "reason": "Destructive operations require manual approval"}'
        } else {
            # Check if this is a code-editing tool and Nexus hasn't been consulted
            $editTools = @("edit", "create", "write")
            $isEdit = $false
            foreach ($t in $editTools) {
                if ($toolName -match $t) { $isEdit = $true; break }
            }

            if ($isEdit) {
                $sessionFile = Join-Path $PSScriptRoot ".." "logs" "current_session.json"
                $nexusUsed = $false
                if (Test-Path $sessionFile) {
                    $session = Get-Content $sessionFile -Raw | ConvertFrom-Json -ErrorAction SilentlyContinue
                    if ($session.nexus_consulted) { $nexusUsed = $true }
                }
                if (-not $nexusUsed) {
                    Write-Output '{"decision": "approve", "message": "Reminder: Consider searching Nexus before editing code (nexus_search or nlm_ask)."}'
                } else {
                    Write-Output '{"decision": "approve"}'
                }
            } else {
                # Track nexus tool usage
                if ($toolName -match "nexus|nlm") {
                    $sessionFile = Join-Path $PSScriptRoot ".." "logs" "current_session.json"
                    @{ nexus_consulted = $true; timestamp = (Get-Date -Format o) } | ConvertTo-Json -Compress | Set-Content $sessionFile
                }
                Write-Output '{"decision": "approve"}'
            }
        }
    } else {
        Write-Output '{"decision": "approve"}'
    }
} catch {
    # On error, approve to avoid blocking the agent
    Write-Output '{"decision": "approve"}'
}
