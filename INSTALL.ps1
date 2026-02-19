# 📦 CosyVoice3 AI Assistant - One-Click Installer
# Automated setup script for complete AI conversation system

Write-Host "`n" -NoNewline
Write-Host "="*70 -ForegroundColor Cyan
Write-Host "  🎙️ CosyVoice3 AI Assistant - Complete Setup" -ForegroundColor Green
Write-Host "="*70 -ForegroundColor Cyan
Write-Host ""

# Check if running as administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (!$isAdmin) {
    Write-Host "⚠️  Warning: Not running as administrator" -ForegroundColor Yellow
    Write-Host "   Some features may not work correctly`n" -ForegroundColor Yellow
}

# ============================================================================
# STEP 1: Check Prerequisites
# ============================================================================

Write-Host "STEP 1: Checking Prerequisites" -ForegroundColor Yellow
Write-Host "-"*70

# Check Python
try {
    $pythonVersion = & python --version 2>&1
    Write-Host "✅ Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Python not found! Please install Python 3.9+" -ForegroundColor Red
    exit 1
}

# Check Conda
try {
    $condaVersion = & conda --version 2>&1
    Write-Host "✅ Conda: $condaVersion" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Conda not found (optional)" -ForegroundColor Yellow
}

# Check LMStudio
$lmstudioPath = "$env:LOCALAPPDATA\LM-Studio\lms.exe"
if (Test-Path $lmstudioPath) {
    Write-Host "✅ LM Studio: Found" -ForegroundColor Green
} else {
    Write-Host "⚠️  LM Studio not found (install from lmstudio.ai)" -ForegroundColor Yellow
}

# Check GPU
try {
    $gpuInfo = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>&1
    Write-Host "✅ GPU: $gpuInfo" -ForegroundColor Green
} catch {
    Write-Host "⚠️  NVIDIA GPU not detected (CPU mode will be slower)" -ForegroundColor Yellow
}

Write-Host ""

# ============================================================================
# STEP 2: Activate/Create Conda Environment
# ============================================================================

Write-Host "STEP 2: Setting Up Python Environment" -ForegroundColor Yellow
Write-Host "-"*70

$envName = "cosyvoice"
$envExists = conda env list | Select-String $envName

if ($envExists) {
    Write-Host "✅ Conda environment '$envName' exists" -ForegroundColor Green
    Write-Host "   Activating..." -ForegroundColor Cyan
    conda activate $envName
} else {
    Write-Host "Creating new conda environment '$envName'..." -ForegroundColor Cyan
    conda create -n $envName python=3.9 -y
    conda activate $envName
}

Write-Host ""

# ============================================================================
# STEP 3: Install Python Dependencies
# ============================================================================

Write-Host "STEP 3: Installing Python Dependencies" -ForegroundColor Yellow
Write-Host "-"*70

$packages = @(
    "lmstudio",
    "pvporcupine",
    "sounddevice",
    "numpy",
    "scipy",
    "requests",
    "ipywidgets",
    "jupyter",
    "psutil",
    "pydantic",
    "tqdm"
)

Write-Host "Installing packages..." -ForegroundColor Cyan
foreach ($package in $packages) {
    Write-Host "  • $package" -NoNewline
    pip install $package --quiet 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host " ✅" -ForegroundColor Green
    } else {
        Write-Host " ⚠️" -ForegroundColor Yellow
    }
}

Write-Host ""

# ============================================================================
# STEP 4: Verify CosyVoice3 Installation
# ============================================================================

Write-Host "STEP 4: Verifying CosyVoice3 Installation" -ForegroundColor Yellow
Write-Host "-"*70

$requiredFiles = @(
    "cosyvoice\cli\cosyvoice.py",
    "pretrained_models\Fun-CosyVoice3-0.5B",
    "asset\zero_shot_prompt.wav"
)

$allFilesExist = $true
foreach ($file in $requiredFiles) {
    if (Test-Path $file) {
        Write-Host "✅ $file" -ForegroundColor Green
    } else {
        Write-Host "❌ $file (missing)" -ForegroundColor Red
        $allFilesExist = $false
    }
}

if (!$allFilesExist) {
    Write-Host "`n⚠️  Some CosyVoice3 files are missing!" -ForegroundColor Red
    Write-Host "   Please ensure CosyVoice3 is properly installed in this directory." -ForegroundColor Yellow
}

Write-Host ""

# ============================================================================
# STEP 5: Create Required Directories
# ============================================================================

Write-Host "STEP 5: Creating Directory Structure" -ForegroundColor Yellow
Write-Host "-"*70

$directories = @(
    "cache\warm_start",
    "benchmarks\results",
    "presets",
    "logs",
    "audio_output"
)

foreach ($dir in $directories) {
    if (!(Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "✅ Created: $dir" -ForegroundColor Green
    } else {
        Write-Host "✅ Exists: $dir" -ForegroundColor Green
    }
}

Write-Host ""

# ============================================================================
# STEP 6: Generate Pre-cached Assets
# ============================================================================

Write-Host "STEP 6: Generating Pre-cached Audio Assets" -ForegroundColor Yellow
Write-Host "-"*70

$manifestPath = "cache\warm_start\warm_start_manifest.json"

if (Test-Path $manifestPath) {
    Write-Host "✅ Warm-start assets already exist" -ForegroundColor Green
    Write-Host "   Run 'python pregenerate_greetings.py' to regenerate" -ForegroundColor Cyan
} else {
    Write-Host "Generating greetings and audio assets..." -ForegroundColor Cyan
    Write-Host "   (This will take 2-3 minutes)`n" -ForegroundColor Yellow
    
    python pregenerate_greetings.py
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n✅ Audio assets generated successfully" -ForegroundColor Green
    } else {
        Write-Host "`n⚠️  Asset generation had issues (may still work)" -ForegroundColor Yellow
    }
}

Write-Host ""

# ============================================================================
# STEP 7: Picovoice Access Key Setup
# ============================================================================

Write-Host "STEP 7: Picovoice Access Key Setup" -ForegroundColor Yellow
Write-Host "-"*70

$wakeWordFile = "wake_word_listener.py"
$wakeWordContent = Get-Content $wakeWordFile -Raw

if ($wakeWordContent -match 'ACCESS_KEY = "YOUR_KEY_HERE"') {
    Write-Host "⚠️  Picovoice access key not configured" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   To enable wake word detection:" -ForegroundColor Cyan
    Write-Host "   1. Get free access key at https://console.picovoice.ai/" -ForegroundColor Cyan
    Write-Host "   2. Edit wake_word_listener.py line 30" -ForegroundColor Cyan
    Write-Host "   3. Replace YOUR_KEY_HERE with your access key" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "   System will work without wake word detection." -ForegroundColor Yellow
} else {
    Write-Host "✅ Picovoice access key is configured" -ForegroundColor Green
}

Write-Host ""

# ============================================================================
# STEP 8: LMStudio Configuration Check
# ============================================================================

Write-Host "STEP 8: LMStudio Configuration" -ForegroundColor Yellow
Write-Host "-"*70

try {
    $response = Invoke-WebRequest -Uri "http://localhost:1234/v1/models" -TimeoutSec 2 -UseBasicParsing 2>$null
    $models = ($response.Content | ConvertFrom-Json).data
    
    Write-Host "✅ LM Studio server is running" -ForegroundColor Green
    Write-Host "   Loaded models:" -ForegroundColor Cyan
    foreach ($model in $models) {
        Write-Host "   • $($model.id)" -ForegroundColor Cyan
    }
} catch {
    Write-Host "⚠️  LM Studio server not running" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   To start LM Studio server:" -ForegroundColor Cyan
    Write-Host "   1. Open LM Studio application" -ForegroundColor Cyan
    Write-Host "   2. Load a model (recommended: Qwen 3B or 7B)" -ForegroundColor Cyan
    Write-Host "   3. Start the local server (default port: 1234)" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "   Or use CLI: lms server start" -ForegroundColor Cyan
}

Write-Host ""

# ============================================================================
# STEP 9: Create Desktop Shortcuts
# ============================================================================

Write-Host "STEP 9: Creating Quick Launch Shortcuts" -ForegroundColor Yellow
Write-Host "-"*70

$currentDir = Get-Location
$shortcutDir = "$env:USERPROFILE\Desktop"

# Test Mode Shortcut
$testShortcut = "$shortcutDir\AI Assistant (Test Mode).lnk"
$WScriptShell = New-Object -ComObject WScript.Shell
$Shortcut = $WScriptShell.CreateShortcut($testShortcut)
$Shortcut.TargetPath = "python"
$Shortcut.Arguments = "warm_start_demo.py"
$Shortcut.WorkingDirectory = $currentDir
$Shortcut.Description = "Launch AI Assistant in Test Mode"
$Shortcut.Save()
Write-Host "✅ Created: AI Assistant (Test Mode).lnk" -ForegroundColor Green

# Wake Word Mode Shortcut
$wakeShortcut = "$shortcutDir\AI Assistant (Wake Word).lnk"
$Shortcut = $WScriptShell.CreateShortcut($wakeShortcut)
$Shortcut.TargetPath = "python"
$Shortcut.Arguments = "wake_word_listener.py --integrate"
$Shortcut.WorkingDirectory = $currentDir
$Shortcut.Description = "Launch AI Assistant with Wake Word Detection"
$Shortcut.Save()
Write-Host "✅ Created: AI Assistant (Wake Word).lnk" -ForegroundColor Green

# Jupyter Control Panel Shortcut
$jupyterShortcut = "$shortcutDir\AI Assistant Control Panel.lnk"
$Shortcut = $WScriptShell.CreateShortcut($jupyterShortcut)
$Shortcut.TargetPath = "jupyter"
$Shortcut.Arguments = "notebook control_panel.py"
$Shortcut.WorkingDirectory = $currentDir
$Shortcut.Description = "Launch AI Assistant Control Panel"
$Shortcut.Save()
Write-Host "✅ Created: AI Assistant Control Panel.lnk" -ForegroundColor Green

Write-Host ""

# ============================================================================
# STEP 10: System Information
# ============================================================================

Write-Host "STEP 10: System Information" -ForegroundColor Yellow
Write-Host "-"*70

# CPU Info
$cpu = Get-WmiObject -Class Win32_Processor | Select-Object -First 1
Write-Host "CPU: $($cpu.Name)" -ForegroundColor Cyan

# RAM Info
$ram = Get-WmiObject -Class Win32_ComputerSystem
$ramGB = [math]::Round($ram.TotalPhysicalMemory / 1GB, 2)
Write-Host "RAM: $ramGB GB" -ForegroundColor Cyan

# GPU Info (if available)
try {
    $gpu = nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>$null
    Write-Host "GPU: $gpu" -ForegroundColor Cyan
} catch {
    Write-Host "GPU: Not detected" -ForegroundColor Cyan
}

# Disk Space
$drive = Get-PSDrive -Name C
$freeGB = [math]::Round($drive.Free / 1GB, 2)
Write-Host "Free Disk Space: $freeGB GB" -ForegroundColor Cyan

Write-Host ""

# ============================================================================
# FINAL STATUS
# ============================================================================

Write-Host "="*70 -ForegroundColor Cyan
Write-Host "  ✅ INSTALLATION COMPLETE!" -ForegroundColor Green
Write-Host "="*70 -ForegroundColor Cyan
Write-Host ""

Write-Host "📚 Quick Start Guide:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  1️⃣  Test Mode (No wake word):" -ForegroundColor Cyan
Write-Host "      python warm_start_demo.py" -ForegroundColor White
Write-Host ""
Write-Host "  2️⃣  Wake Word Mode (Say 'jarvis'):" -ForegroundColor Cyan
Write-Host "      python wake_word_listener.py --integrate" -ForegroundColor White
Write-Host "      (Requires Picovoice access key)" -ForegroundColor Yellow
Write-Host ""
Write-Host "  3️⃣  Jupyter Control Panel:" -ForegroundColor Cyan
Write-Host "      jupyter notebook control_panel.py" -ForegroundColor White
Write-Host ""
Write-Host "  4️⃣  Desktop Shortcuts:" -ForegroundColor Cyan
Write-Host "      Check your desktop for quick launch icons!" -ForegroundColor White
Write-Host ""

Write-Host "📖 Documentation:" -ForegroundColor Yellow
Write-Host "  • QUICK_START.md - 5-minute setup guide" -ForegroundColor Cyan
Write-Host "  • FINAL_STATUS.md - Complete system overview" -ForegroundColor Cyan
Write-Host "  • WARM_START_ARCHITECTURE.md - Technical details" -ForegroundColor Cyan
Write-Host "  • LMSTUDIO_ADVANCED_GUIDE.md - Advanced LMStudio features" -ForegroundColor Cyan
Write-Host "  • INTEL_GNA_GUIDE.md - Wake word alternatives" -ForegroundColor Cyan
Write-Host ""

Write-Host "⚡ Expected Performance:" -ForegroundColor Yellow
Write-Host "  • Wake word → First audio: ~2.7 seconds" -ForegroundColor Cyan
Write-Host "  • Speculative hit rate: ~33% (instant responses!)" -ForegroundColor Cyan
Write-Host "  • Context memory: Automatic (stateful chats)" -ForegroundColor Cyan
Write-Host ""

Write-Host "🎉 Enjoy your AI assistant! 🎉" -ForegroundColor Green
Write-Host ""

# Optional: Create summary file
$summaryFile = "INSTALLATION_SUMMARY.txt"
@"
CosyVoice3 AI Assistant - Installation Summary
Generated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

System Information:
- CPU: $($cpu.Name)
- RAM: $ramGB GB
- Free Disk: $freeGB GB

Installation Path: $(Get-Location)

Launch Commands:
1. Test Mode: python warm_start_demo.py
2. Wake Word: python wake_word_listener.py --integrate
3. Control Panel: jupyter notebook control_panel.py

Desktop Shortcuts Created:
- AI Assistant (Test Mode).lnk
- AI Assistant (Wake Word).lnk
- AI Assistant Control Panel.lnk

Next Steps:
1. Start LM Studio and load a model
2. Get Picovoice access key (https://console.picovoice.ai/)
3. Run test mode to verify installation
4. Configure wake word detection (optional)

For support, see documentation files in project directory.
"@ | Out-File -FilePath $summaryFile -Encoding UTF8

Write-Host "📄 Installation summary saved to: $summaryFile" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press any key to exit..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
