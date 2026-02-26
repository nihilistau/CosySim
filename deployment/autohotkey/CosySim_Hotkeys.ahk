; CosySim Global Hotkeys — AutoHotkey v2
; Install: https://www.autohotkey.com/v2/
; Auto-start: Place shortcut in shell:startup
;
; Win+Shift+N  → Quick Nexus Search
; Win+Shift+S  → Send Clipboard to Nexus
; Win+Shift+T  → Run Tests
; Win+Shift+H  → System Health Check
; Win+Shift+C  → Quick Commit

#Requires AutoHotkey v2.0

ScriptsDir := "C:\Files\Models\CosySim\deployment\scripts"

; Win+Shift+N — Quick Nexus Search
#+n:: {
    Run('pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "' . ScriptsDir . '\Quick-Search-Nexus.ps1"',, "Hide")
}

; Win+Shift+S — Send Clipboard to Nexus
#+s:: {
    Run('pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "' . ScriptsDir . '\Send-ToNexus.ps1"',, "Hide")
}

; Win+Shift+T — Run Tests (shows notification)
#+t:: {
    Run('pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "' . ScriptsDir . '\Run-Tests.ps1"',, "Hide")
}

; Win+Shift+H — System Health Check
#+h:: {
    Run('pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "' . ScriptsDir . '\System-Status.ps1"',, "Hide")
}

; Win+Shift+C — Quick Commit
#+c:: {
    Run('pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "' . ScriptsDir . '\Quick-Commit.ps1"',, "Hide")
}
