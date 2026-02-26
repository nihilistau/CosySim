# Logitech Options+ Setup Guide for CosySim

> Configure your Logitech MX Keys Mini and M720 Triathlon for CosySim workflows.

## Prerequisites

- Logitech Options+ installed (`C:\Program Files\LogiOptionsPlus`)
- MX Keys Mini paired via Bluetooth/Unifying
- M720 Triathlon paired via Bluetooth/Unifying
- PowerShell 7+ installed
- CosySim scripts in `deployment/scripts/`

## Important Note

Logitech Options+ is a signed, sandboxed application. We **cannot** programmatically
inject custom actions into its process or modify its config database reliably.
All configuration must be done through the Options+ UI.

However, Options+ supports **Smart Actions** that can launch applications and run
scripts, which is how we connect Logitech buttons to CosySim functionality.

---

## M720 Triathlon — Button Mapping

### Available Buttons
| Button | Default | CosySim Assignment |
|--------|---------|-------------------|
| Back (thumb) | Browser Back | **Send to Nexus** — clipboard → Nexus |
| Forward (thumb) | Browser Forward | **Quick Nexus Search** — search popup |
| Middle click | Middle click | **System Status** — health check |
| Gesture button | Gesture mode | Hold + direction for actions |
| Gesture + Left | — | **Run Tests** — notification |
| Gesture + Right | — | **Quick Commit** — git commit dialog |

### Setup Steps

1. Open **Logitech Options+**
2. Select your **M720 Triathlon** from the device list
3. Click on the button you want to configure

#### Back Button → Send to Nexus
1. Click the **Back button** in the device diagram
2. Select **Smart Actions** (or **Application/Shortcut**)
3. Choose **Launch Application**
4. Browse to: `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`
5. Add arguments: `-NoProfile -ExecutionPolicy Bypass -File "C:\Files\Models\CosySim\deployment\scripts\Send-ToNexus.ps1"`
6. Or use pwsh.exe for PowerShell 7

#### Forward Button → Quick Nexus Search
1. Click the **Forward button**
2. Same as above but with: `Quick-Search-Nexus.ps1`

#### Middle Click → System Status
1. Click **Middle click** (scroll wheel press)
2. Launch: `System-Status.ps1`

### Gesture Button Actions
If your M720 supports gesture button customization:
1. Hold the **gesture button** and swipe **left** → Run-Tests.ps1
2. Hold the **gesture button** and swipe **right** → Quick-Commit.ps1

**Note:** If gesture directions aren't available in Options+ for M720,
use the AutoHotkey hotkeys instead (Win+Shift+T and Win+Shift+C).

---

## MX Keys Mini — Keyboard Shortcuts

### Available Custom Keys
| Key | Default | CosySim Assignment |
|-----|---------|-------------------|
| F1 (Fn+F1) | Brightness down | No change (keep default) |
| F2 (Fn+F2) | Brightness up | No change (keep default) |
| F4 (Fn+F4) | Dictation | **Nexus Search** (if not using dictation) |
| F5 (Fn+F5) | Emoji picker | No change |
| F6 (Fn+F6) | Screenshot | No change |
| Dictation key | Windows dictation | **Voice → CosySim TTS** (optional) |

### Setup Steps

1. Open **Logitech Options+**
2. Select your **MX Keys Mini**
3. Click on the key you want to customize

#### F4 → Nexus Search (optional)
1. Click **F4** in the keyboard diagram
2. Select **Smart Actions** → **Launch Application**
3. Path: `Quick-Search-Nexus.ps1`

---

## Alternative: AutoHotkey (Recommended)

For the most reliable global hotkeys, use AutoHotkey v2 instead of
(or alongside) Logitech Options+:

| Hotkey | Action | Script |
|--------|--------|--------|
| Win+Shift+N | Nexus Search | Quick-Search-Nexus.ps1 |
| Win+Shift+S | Send to Nexus | Send-ToNexus.ps1 |
| Win+Shift+T | Run Tests | Run-Tests.ps1 |
| Win+Shift+H | System Health | System-Status.ps1 |
| Win+Shift+C | Quick Commit | Quick-Commit.ps1 |

### Install AutoHotkey Hotkeys
1. Install AutoHotkey v2 from https://www.autohotkey.com/v2/
2. Run `deployment/autohotkey/CosySim_Hotkeys.ahk`
3. To auto-start: create shortcut in `shell:startup`

---

## Combined Setup (Recommended)

Use **both** Logitech buttons **and** AutoHotkey hotkeys:
- Logitech: physical buttons for the 3 most-used actions (Send, Search, Status)
- AutoHotkey: keyboard shortcuts for all 5 actions
- This gives you redundancy — hotkeys work even when Options+ isn't running

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Script doesn't run from button | Check execution policy: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| No toast notification | Check Windows notification settings for PowerShell |
| Nexus unreachable | Ensure Nexus is running: `python -m nexus all` (from C:\Files\Nexus) |
| AutoHotkey conflicts | Check for conflicting hotkeys in other apps |
| Options+ not showing Smart Actions | Update Logitech Options+ to latest version |
