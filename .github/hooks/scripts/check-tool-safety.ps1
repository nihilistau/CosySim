#!/usr/bin/env pwsh
# Hook script: Check tool safety + remind about Nexus-first workflow
# Called by cosysim-hooks.json preToolUse hook
# Returns JSON with "decision": "approve" or "deny"

param()

function Get-ObjectField {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($null -eq $Object) {
        return $null
    }
    if ($Object -is [hashtable]) {
        return $Object[$Name]
    }
    $prop = $Object.PSObject.Properties[$Name]
    if ($prop) {
        return $prop.Value
    }
    return $null
}

function Add-UniquePath {
    param(
        [System.Collections.Generic.List[string]]$Paths,
        [string]$Path
    )

    if (-not [string]::IsNullOrWhiteSpace($Path) -and -not $Paths.Contains($Path)) {
        $Paths.Add($Path) | Out-Null
    }
}

function Get-PatchPaths {
    param([string]$PatchText)

    $paths = New-Object 'System.Collections.Generic.List[string]'
    if ([string]::IsNullOrWhiteSpace($PatchText)) {
        return $paths
    }

    foreach ($line in ($PatchText -split "`r?`n")) {
        $trimmed = $line.Trim()
        if ($trimmed -match '^\*\*\* (?:(?:Add|Delete|Update) File|Move to): (.+)$') {
            Add-UniquePath -Paths $paths -Path $Matches[1].Trim()
        }
    }
    return $paths
}

function Get-ToolAssessment {
    param(
        [string]$ToolName,
        [object]$Payload
    )

    $assessment = @{
        isCodeChange = $false
        consultedKnowledge = $false
        paths = New-Object 'System.Collections.Generic.List[string]'
    }

    if ([string]::IsNullOrWhiteSpace($ToolName)) {
        return $assessment
    }

    $toolLower = $ToolName.ToLowerInvariant()
    if ($toolLower -match 'nexus|notebooklm|nlm') {
        $assessment.consultedKnowledge = $true
    }

    if ($toolLower -match 'parallel') {
        $toolUses = Get-ObjectField -Object $Payload -Name 'tool_uses'
        foreach ($toolUse in ($toolUses ?? @())) {
            $nestedName = Get-ObjectField -Object $toolUse -Name 'recipient_name'
            if (-not $nestedName) {
                $nestedName = Get-ObjectField -Object $toolUse -Name 'toolName'
            }
            $nestedPayload = Get-ObjectField -Object $toolUse -Name 'parameters'
            if ($null -eq $nestedPayload) {
                $nestedPayload = Get-ObjectField -Object $toolUse -Name 'input'
            }
            $nested = Get-ToolAssessment -ToolName ([string]$nestedName) -Payload $nestedPayload
            if ($nested.isCodeChange) {
                $assessment.isCodeChange = $true
            }
            if ($nested.consultedKnowledge) {
                $assessment.consultedKnowledge = $true
            }
            foreach ($path in $nested.paths) {
                Add-UniquePath -Paths $assessment.paths -Path $path
            }
        }
        return $assessment
    }

    foreach ($candidate in @('edit', 'create', 'write', 'apply_patch')) {
        if ($toolLower -match [Regex]::Escape($candidate)) {
            $assessment.isCodeChange = $true
            break
        }
    }

    if ($Payload -is [string]) {
        foreach ($path in (Get-PatchPaths -PatchText $Payload)) {
            $assessment.isCodeChange = $true
            Add-UniquePath -Paths $assessment.paths -Path $path
        }
        return $assessment
    }

    foreach ($key in @('path', 'file_path', 'target_file', 'filepath')) {
        $candidatePath = Get-ObjectField -Object $Payload -Name $key
        if ($candidatePath -is [string]) {
            Add-UniquePath -Paths $assessment.paths -Path $candidatePath
        }
    }

    $patchText = ''
    foreach ($key in @('input', 'patch', 'content')) {
        $value = Get-ObjectField -Object $Payload -Name $key
        if ($value -is [string] -and -not [string]::IsNullOrWhiteSpace($value)) {
            $patchText = $value
            break
        }
    }
    foreach ($path in (Get-PatchPaths -PatchText $patchText)) {
        $assessment.isCodeChange = $true
        Add-UniquePath -Paths $assessment.paths -Path $path
    }

    return $assessment
}

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
            # Check if this is a code-changing tool and Nexus hasn't been consulted
            $payload = if ($parsed.input) { $parsed.input } else { $null }
            $assessment = Get-ToolAssessment -ToolName $toolName -Payload $payload
            $isCodeChange = [bool]$assessment.isCodeChange

            if ($isCodeChange) {
                $sessionFile = Join-Path $PSScriptRoot ".." "logs" "current_session.json"
                $nexusUsed = $false
                $governanceDeny = $false
                if (Test-Path $sessionFile) {
                    $session = Get-Content $sessionFile -Raw | ConvertFrom-Json -ErrorAction SilentlyContinue
                    if ($session.nexus_consulted) { $nexusUsed = $true }
                }

                # Consensus gate — architecture/config-changing operations
                $archPatterns = @("engine/nexus", "engine/mcp", "engine/agents", "config/default", ".github/hooks", "engine/skills/builtin")
                $isArchChange = $false
                foreach ($editedPath in $assessment.paths) {
                    $normalizedPath = $editedPath -replace "\\", "/"
                    foreach ($p in $archPatterns) {
                        if ($normalizedPath -match [Regex]::Escape($p)) {
                            $isArchChange = $true; break
                        }
                    }
                    if ($isArchChange) { break }
                }
                if ($isArchChange) {
                    try {
                        $primaryPath = if ($assessment.paths.Count -gt 0) { $assessment.paths[0] } else { "" }
                        $escapedPath = if ($primaryPath) { $primaryPath -replace "'", "" } else { "" }
                        $gateOut = python -c "
import json
try:
    from engine.nexus.copilot_bridge import get_copilot_bridge
    allowed = get_copilot_bridge().consensus_gate('edit:$escapedPath', 'Modifying core architecture file')
    print(json.dumps({'allowed': bool(allowed)}))
except Exception:
    print(json.dumps({'allowed': True}))
" 2>$null
                        if ($gateOut) {
                            $gate = $gateOut | ConvertFrom-Json -ErrorAction SilentlyContinue
                            if ($gate -and -not $gate.allowed) {
                                Write-Output '{"decision": "deny", "reason": "Consensus gate: architecture change blocked by governance rule"}'
                                exit 0
                            }
                        }
                    } catch { }
                }

                # Run governance validation on file edits
                $governanceMsg = ""
                if ($assessment.paths.Count -gt 0) {
                    try {
                        $violations = New-Object 'System.Collections.Generic.List[string]'
                        $rejectCount = 0
                        foreach ($filePath in $assessment.paths) {
                            $escapedFilePath = $filePath -replace "'", ""
                            $valResult = python -c "
import json, sys
try:
    from engine.nexus.governance_rules import get_governance_manager
    gm = get_governance_manager()
    r = gm.validate_file('$escapedFilePath')
    print(json.dumps(r))
except Exception as e:
    print(json.dumps({'valid': True, 'note': str(e)}))
" 2>$null
                            if ($valResult) {
                                $val = $valResult | ConvertFrom-Json -ErrorAction SilentlyContinue
                                if ($val -and -not $val.valid) {
                                    foreach ($v in $val.violations) {
                                        if ($v.severity -eq "reject" -or $v.severity -eq "block") {
                                            $rejectCount++
                                        }
                                        if ($v.message) {
                                            $violations.Add($v.message) | Out-Null
                                        }
                                    }
                                }
                            }
                        }
                        if ($violations.Count -gt 0) {
                            $governanceMsg = "Governance: " + (($violations | Select-Object -Unique | Select-Object -First 5) -join "; ")
                        }
                        if ($rejectCount -gt 0) {
                            $governanceDeny = $true
                        }
                    } catch {
                        # Governance check failed — don't block
                    }
                }

                if (-not $nexusUsed) {
                    $msg = "Nexus-first required before code-changing tools. Consult Nexus or NLM before editing code."
                    if ($governanceMsg) { $msg = $msg + " " + $governanceMsg }
                    Write-Output ('{"decision": "deny", "reason": "' + $msg + '"}')
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
