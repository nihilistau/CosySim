#!/usr/bin/env pwsh
# Hook script: Check if a tool operation is allowed
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
            Write-Output '{"decision": "approve"}'
        }
    } else {
        Write-Output '{"decision": "approve"}'
    }
} catch {
    # On error, approve to avoid blocking the agent
    Write-Output '{"decision": "approve"}'
}
