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
                $governanceDeny = $false
                if (Test-Path $sessionFile) {
                    $session = Get-Content $sessionFile -Raw | ConvertFrom-Json -ErrorAction SilentlyContinue
                    if ($session.nexus_consulted) { $nexusUsed = $true }
                }

                # Run governance validation on file edits
                $governanceMsg = ""
                if ($parsed.input -and $parsed.input.path) {
                    try {
                        $filePath = $parsed.input.path
                        $valResult = python -c "
import json, sys
try:
    from engine.nexus.governance_rules import get_governance_manager
    gm = get_governance_manager()
    r = gm.validate_file('$filePath')
    print(json.dumps(r))
except Exception as e:
    print(json.dumps({'valid': True, 'note': str(e)}))
" 2>$null
                        if ($valResult) {
                            $val = $valResult | ConvertFrom-Json -ErrorAction SilentlyContinue
                            if ($val -and -not $val.valid) {
                                $rejectCount = 0
                                foreach ($v in $val.violations) {
                                    if ($v.severity -eq "reject" -or $v.severity -eq "block") {
                                        $rejectCount++
                                    }
                                }
                                $governanceMsg = "Governance: " + ($val.violations | ForEach-Object { $_.message } | Select-Object -First 5) -join "; "
                                if ($rejectCount -gt 0) {
                                    $governanceDeny = $true
                                }
                            }
                        }
                    } catch {
                        # Governance check failed — don't block
                    }
                }

                if (-not $nexusUsed) {
                    $msg = "Reminder: Consider searching Nexus before editing code (nexus_search or nlm_ask)."
                    if ($governanceMsg) { $msg = $msg + " " + $governanceMsg }
                    if ($governanceDeny) {
                        Write-Output ('{"decision": "deny", "reason": "' + $governanceMsg + '"}')
                    } else {
                        Write-Output ('{"decision": "approve", "message": "' + $msg + '"}')
                    }
                } else {
                    if ($governanceDeny) {
                        Write-Output ('{"decision": "deny", "reason": "' + $governanceMsg + '"}')
                    } elseif ($governanceMsg) {
                        Write-Output ('{"decision": "approve", "message": "' + $governanceMsg + '"}')
                    } else {
                        Write-Output '{"decision": "approve"}'
                    }
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
