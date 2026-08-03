# Installs the repo's git hooks (currently: gitleaks pre-commit secret scan).
# Run once per clone, from anywhere inside the repo:
#   pwsh scripts/hooks/install-hooks.ps1

$ErrorActionPreference = 'Stop'

$repoRoot = git rev-parse --show-toplevel
if (-not $repoRoot) { throw "Not inside a git repository." }

git -C $repoRoot config core.hooksPath scripts/hooks
Write-Host "core.hooksPath -> scripts/hooks"

$gitleaks = Get-Command gitleaks -ErrorAction SilentlyContinue
if (-not $gitleaks) {
    $local = Join-Path $env:USERPROFILE '.local\bin\gitleaks.exe'
    if (Test-Path $local) {
        $gitleaks = $local
    }
}

if ($gitleaks) {
    Write-Host "gitleaks found — pre-commit secret scanning is active."
} else {
    Write-Warning "gitleaks not found on PATH or in ~/.local/bin."
    Write-Warning "Download: https://github.com/gitleaks/gitleaks/releases (put gitleaks.exe in ~\.local\bin)"
    Write-Warning "Until then the hook will block commits with an install hint."
}
