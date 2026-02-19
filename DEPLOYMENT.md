# 📦 Deployment Package Guide
**How to package and deploy the entire AI assistant system**

---

## Package Contents

This deployment package includes everything needed to run the CosyVoice3 AI Assistant system:

### Core System Files
```
✅ warm_start_demo.py          - Main conversation system (2.7s latency)
✅ wake_word_listener.py       - Always-on wake word detection
✅ pregenerate_greetings.py    - Audio asset generator
✅ control_panel.py            - Jupyter notebook controller
✅ INSTALL.ps1                 - One-click installer script
```

### Documentation
```
✅ QUICK_START.md              - 5-minute setup guide
✅ FINAL_STATUS.md             - Complete system overview
✅ WARM_START_ARCHITECTURE.md  - Technical architecture
✅ LMSTUDIO_ADVANCED_GUIDE.md  - Advanced LMStudio features
✅ LMSTUDIO_INTEGRATION.md     - LMStudio integration details
✅ INTEL_GNA_GUIDE.md          - Wake word detection guide
✅ RDP_AUDIO_FIX.md            - Audio troubleshooting
✅ TTS_OPTIMIZATION_ANALYSIS.md - Performance analysis
✅ DEPLOYMENT.md               - This file
```

### Pre-generated Assets
```
✅ cache/warm_start/           - 12 audio files (greetings, fillers, connection sound)
   ├── greeting_1.wav through greeting_5.wav
   ├── filler_1.wav through filler_5.wav
   ├── connection_sound.wav
   └── warm_start_manifest.json
```

### Supporting Files
```
✅ requirements.txt            - Python dependencies
✅ conversation_history.db     - SQLite database (created on first run)
✅ presets/                    - Character preset configurations
✅ logs/                       - System logs directory
```

---

## Deployment Methods

### Method 1: Full System Package (Recommended)

**Create a complete deployment ZIP with all dependencies:**

#### Step 1: Prepare Directory Structure

```powershell
# Create deployment package
$packageName = "CosyVoice3-Assistant-$(Get-Date -Format 'yyyy-MM-dd')"
$packageDir = "deploy\$packageName"

New-Item -ItemType Directory -Path $packageDir -Force

# Copy core files
$coreFiles = @(
    "warm_start_demo.py",
    "wake_word_listener.py",
    "pregenerate_greetings.py",
    "control_panel.py",
    "INSTALL.ps1",
    "requirements.txt"
)

foreach ($file in $coreFiles) {
    Copy-Item $file -Destination $packageDir
}

# Copy documentation
$docFiles = Get-ChildItem -Filter "*.md"
foreach ($doc in $docFiles) {
    Copy-Item $doc.FullName -Destination $packageDir
}

# Copy cache directory (if assets are generated)
if (Test-Path "cache\warm_start") {
    Copy-Item "cache\warm_start" -Destination "$packageDir\cache" -Recurse
}

# Copy preset templates
if (Test-Path "presets") {
    Copy-Item "presets" -Destination $packageDir -Recurse
}
```

#### Step 2: Generate Requirements File

```powershell
# Create comprehensive requirements.txt
@"
# Core Dependencies
lmstudio>=1.3.0
pvporcupine>=3.0.0
sounddevice>=0.4.6
numpy>=1.24.0
scipy>=1.11.0

# Notebook Interface
ipywidgets>=8.0.0
jupyter>=1.0.0

# Utilities
psutil>=5.9.0
pydantic>=2.0.0
tqdm>=4.66.0
requests>=2.31.0

# Audio Processing
librosa>=0.10.0  # Optional, for advanced audio processing

# Database
# sqlite3 is built into Python

# Note: CosyVoice3 must be installed separately in the target environment
"@ | Out-File -FilePath "$packageDir\requirements.txt" -Encoding UTF8
```

#### Step 3: Create Installation Guide

```powershell
@"
CosyVoice3 AI Assistant - Installation Instructions
====================================================

Prerequisites:
1. Windows 10/11 (64-bit)
2. Python 3.9 or higher
3. Conda (recommended) or venv
4. LM Studio installed and running
5. 16GB+ RAM (32GB recommended)
6. NVIDIA GPU with 6GB+ VRAM (12GB recommended)
7. 20GB+ free disk space

Quick Installation:
1. Extract this ZIP to desired location
2. Open PowerShell in extracted directory
3. Run: .\INSTALL.ps1
4. Follow on-screen instructions
5. Configure Picovoice access key (optional, for wake word)
6. Start LM Studio and load a model
7. Launch: python warm_start_demo.py

For detailed instructions, see QUICK_START.md

System Requirements:
- Minimum: i5-8th gen, 16GB RAM, GTX 1060 6GB
- Recommended: i7-10th gen+, 32GB RAM, RTX 2060 12GB+
- Optimal: i9-11th gen+, 32GB RAM, RTX 3080 12GB+

Expected Performance:
- Wake word → First audio: ~2.7 seconds
- Speculative hit rate: ~33% (instant responses)
- TTS RTF: 1.4-6.6x (depending on audio length)
- LLM response time: 3-4 seconds (varies by model)

Support:
- Documentation: See included .md files
- Issues: Check troubleshooting sections in docs
- Updates: Visit project repository

Version: 1.0.0
Date: $(Get-Date -Format 'yyyy-MM-dd')
"@ | Out-File -FilePath "$packageDir\INSTALLATION_GUIDE.txt" -Encoding UTF8
```

#### Step 4: Create Verification Script

```powershell
# Create verification script
@"
# verify_installation.ps1
# Quick verification script to check installation completeness

Write-Host "Verifying Installation..." -ForegroundColor Cyan

`$allGood = `$true

# Check core files
`$requiredFiles = @(
    "warm_start_demo.py",
    "wake_word_listener.py",
    "pregenerate_greetings.py",
    "control_panel.py",
    "requirements.txt"
)

foreach (`$file in `$requiredFiles) {
    if (Test-Path `$file) {
        Write-Host "[OK] `$file" -ForegroundColor Green
    } else {
        Write-Host "[MISSING] `$file" -ForegroundColor Red
        `$allGood = `$false
    }
}

# Check Python
try {
    `$pythonVersion = python --version 2>&1
    Write-Host "[OK] Python: `$pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python not found" -ForegroundColor Red
    `$allGood = `$false
}

# Check dependencies
try {
    `$packages = @("lmstudio", "pvporcupine", "sounddevice")
    foreach (`$package in `$packages) {
        python -c "import `$package" 2>`$null
        if (`$LASTEXITCODE -eq 0) {
            Write-Host "[OK] Package: `$package" -ForegroundColor Green
        } else {
            Write-Host "[MISSING] Package: `$package" -ForegroundColor Yellow
            `$allGood = `$false
        }
    }
} catch {
    Write-Host "[WARNING] Could not verify packages" -ForegroundColor Yellow
}

if (`$allGood) {
    Write-Host "`nVerification Complete: All checks passed!" -ForegroundColor Green
} else {
    Write-Host "`nVerification Complete: Some issues found" -ForegroundColor Yellow
    Write-Host "Run INSTALL.ps1 to fix missing components" -ForegroundColor Cyan
}
"@ | Out-File -FilePath "$packageDir\verify_installation.ps1" -Encoding UTF8
```

#### Step 5: Create ZIP Package

```powershell
# Create deployment ZIP
Compress-Archive -Path $packageDir -DestinationPath "deploy\$packageName.zip" -Force

Write-Host "✅ Deployment package created: deploy\$packageName.zip" -ForegroundColor Green
```

---

### Method 2: Minimal Package (Scripts Only)

**For environments where CosyVoice3 is already installed:**

```powershell
# Minimal deployment (scripts + docs only)
$minimalDir = "deploy\CosyVoice3-Scripts-Minimal"
New-Item -ItemType Directory -Path $minimalDir -Force

# Copy essential scripts
Copy-Item "warm_start_demo.py" -Destination $minimalDir
Copy-Item "wake_word_listener.py" -Destination $minimalDir
Copy-Item "pregenerate_greetings.py" -Destination $minimalDir
Copy-Item "control_panel.py" -Destination $minimalDir

# Copy key documentation
Copy-Item "QUICK_START.md" -Destination $minimalDir
Copy-Item "FINAL_STATUS.md" -Destination $minimalDir
Copy-Item "requirements.txt" -Destination $minimalDir

# Create ZIP
Compress-Archive -Path $minimalDir -DestinationPath "deploy\CosyVoice3-Scripts-Minimal.zip" -Force
```

---

### Method 3: Git Repository Clone

**For developers who want version control:**

```bash
# Clone the repository
git clone <your-repo-url> CosyVoice3-Assistant
cd CosyVoice3-Assistant

# Install dependencies
pip install -r requirements.txt

# Generate audio assets
python pregenerate_greetings.py

# Configure
# Edit wake_word_listener.py (add Picovoice key)

# Test
python warm_start_demo.py
```

---

## Installation on Target System

### Option A: Automated Installation (Recommended)

```powershell
# 1. Extract ZIP package
Expand-Archive -Path "CosyVoice3-Assistant-*.zip" -DestinationPath "C:\AI\CosyVoice3"

# 2. Navigate to directory
cd "C:\AI\CosyVoice3"

# 3. Run automated installer
.\INSTALL.ps1

# 4. Follow on-screen instructions
```

### Option B: Manual Installation

```powershell
# 1. Extract ZIP

# 2. Create conda environment
conda create -n cosyvoice python=3.9 -y
conda activate cosyvoice

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install CosyVoice3 (if not included)
# Follow CosyVoice3 installation instructions

# 5. Generate audio assets
python pregenerate_greetings.py

# 6. Configure Picovoice key
# Edit wake_word_listener.py line 30

# 7. Start LM Studio
lms server start

# 8. Test system
python warm_start_demo.py
```

---

## Configuration Files

### Character Presets

Create custom character presets in `presets/`:

```json
{
  "name": "My Custom Character",
  "description": "A helpful assistant",
  "systemPrompt": "You are a helpful AI assistant...",
  "parameters": {
    "temperature": 0.8,
    "maxTokens": 300,
    "topP": 0.9
  }
}
```

### Environment Variables (Optional)

```powershell
# Set environment variables for configuration
$env:LMSTUDIO_URL = "http://localhost:1234"
$env:PICOVOICE_ACCESS_KEY = "your-key-here"
$env:COSYVOICE_MODEL = "pretrained_models/Fun-CosyVoice3-0.5B"
```

---

## Deployment Checklist

### Pre-Deployment
- [ ] Test on source system
- [ ] Generate all audio assets
- [ ] Verify all scripts run without errors
- [ ] Document any custom modifications
- [ ] Test with fresh environment
- [ ] Update version numbers
- [ ] Create changelog

### Package Contents
- [ ] All Python scripts included
- [ ] Documentation complete and updated
- [ ] Requirements.txt accurate
- [ ] Installer script tested
- [ ] Audio assets generated
- [ ] Example presets included
- [ ] Verification script included
- [ ] README with quick start

### Post-Deployment
- [ ] Extract package on target system
- [ ] Run verification script
- [ ] Install dependencies
- [ ] Configure LM Studio
- [ ] Test basic functionality
- [ ] Test wake word detection
- [ ] Verify audio playback
- [ ] Check performance metrics

---

## Troubleshooting Common Deployment Issues

### Issue: "CosyVoice3 not found"

**Solution:**
```powershell
# Ensure CosyVoice3 is in Python path
$env:PYTHONPATH = "C:\Path\To\CosyVoice3;$env:PYTHONPATH"

# Or install as package
pip install -e /path/to/cosyvoice
```

### Issue: "LM Studio connection refused"

**Solution:**
```powershell
# Start LM Studio server
lms server start

# Or verify server is running
curl http://localhost:1234/v1/models
```

### Issue: "Audio playback errors"

**Solution:**
```powershell
# Install/reinstall sounddevice
pip uninstall sounddevice -y
pip install sounddevice --force-reinstall

# Test audio
python -c "import sounddevice as sd; print(sd.query_devices())"
```

### Issue: "Picovoice wake word not working"

**Solution:**
```powershell
# Verify access key is set
# Edit wake_word_listener.py line 30

# Test wake word detection
python wake_word_listener.py  # (test mode, no integration)

# Check microphone access
# Windows Settings > Privacy > Microphone
```

---

## Updates and Maintenance

### Updating the System

```powershell
# 1. Backup current configuration
Copy-Item "presets" -Destination "presets.backup" -Recurse
Copy-Item "conversation_history.db" -Destination "conversation_history.db.backup"

# 2. Extract new package
Expand-Archive -Path "CosyVoice3-Assistant-NEW.zip" -DestinationPath "temp"

# 3. Copy scripts (overwrite)
Copy-Item "temp\*.py" -Destination "." -Force

# 4. Restore configuration
# (presets and database are preserved)

# 5. Update dependencies
pip install -r requirements.txt --upgrade

# 6. Test
python warm_start_demo.py
```

### Version History

Track versions in `VERSION.txt`:
```
v1.0.0 - 2024-02-16
- Initial release
- 2.7s latency
- Speculative generation
- Wake word detection
- Jupyter control panel

v1.1.0 - Future
- Improved speculative accuracy
- Additional character presets
- Multi-language support
```

---

## Distribution Options

### Internal Deployment (Company/Team)

```powershell
# Share via network drive
Copy-Item "deploy\CosyVoice3-Assistant-*.zip" -Destination "\\network\share\AI-Tools\"

# Or use corporate package manager
# (e.g., Chocolatey, WinGet, SCCM)
```

### Public Release (GitHub, etc.)

```bash
# Create release on GitHub
gh release create v1.0.0 \
  deploy/CosyVoice3-Assistant-*.zip \
  --title "CosyVoice3 AI Assistant v1.0.0" \
  --notes "See CHANGELOG.md for details"
```

### Cloud Deployment (Optional)

For running on cloud VMs:
```bash
# AWS EC2, Azure VM, GCP Compute Engine
# 1. Launch GPU instance (g4dn, NV series, etc.)
# 2. Install NVIDIA drivers
# 3. Deploy package
# 4. Expose via API (future feature)
```

---

## License and Distribution

**Important:** Ensure compliance with:
- CosyVoice3 license (check original repository)
- LM Studio terms of service
- Picovoice Porcupine license (free tier restrictions)
- Any model licenses (e.g., Qwen model license)

Include appropriate LICENSE file in package.

---

## Support and Documentation

### For End Users
- See `QUICK_START.md` for setup
- See `FINAL_STATUS.md` for overview
- See `TROUBLESHOOTING.md` for issues (if created)

### For Developers
- See `WARM_START_ARCHITECTURE.md` for technical details
- See `LMSTUDIO_ADVANCED_GUIDE.md` for advanced features
- See source code comments for implementation details

---

## Automated Deployment Script

**Complete deployment automation:**

```powershell
# deploy.ps1 - Complete deployment automation

param(
    [string]$OutputDir = "deploy",
    [switch]$IncludeAssets,
    [switch]$CreateInstaller
)

Write-Host "CosyVoice3 Deployment Builder" -ForegroundColor Cyan
Write-Host "="*60

# Create output directory
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

# Generate package name with timestamp
$timestamp = Get-Date -Format "yyyy-MM-dd-HHmm"
$packageName = "CosyVoice3-Assistant-$timestamp"
$packageDir = "$OutputDir\$packageName"

# Create package structure
New-Item -ItemType Directory -Path $packageDir -Force | Out-Null

# Copy files
Write-Host "Copying files..." -ForegroundColor Yellow

# Scripts
Copy-Item "*.py" -Destination $packageDir
Copy-Item "*.ps1" -Destination $packageDir

# Documentation
Copy-Item "*.md" -Destination $packageDir

# Configuration
Copy-Item "requirements.txt" -Destination $packageDir

# Assets (optional)
if ($IncludeAssets -and (Test-Path "cache\warm_start")) {
    Write-Host "Including pre-generated assets..." -ForegroundColor Yellow
    Copy-Item "cache" -Destination $packageDir -Recurse
}

# Create ZIP
Write-Host "Creating ZIP package..." -ForegroundColor Yellow
Compress-Archive -Path $packageDir -DestinationPath "$OutputDir\$packageName.zip" -Force

# Calculate size
$zipSize = (Get-Item "$OutputDir\$packageName.zip").Length / 1MB
Write-Host "✅ Package created: $packageName.zip ($([math]::Round($zipSize, 2)) MB)" -ForegroundColor Green

# Create installer (optional)
if ($CreateInstaller) {
    Write-Host "Creating installer..." -ForegroundColor Yellow
    # (Would use NSIS, Inno Setup, or similar here)
}

Write-Host "`nDeployment package ready!" -ForegroundColor Green
```

---

## Final Notes

✅ **Package is ready for deployment**
✅ **All dependencies documented**
✅ **Automated installer included**
✅ **Comprehensive documentation provided**
✅ **Verification tools included**

**Next Steps:**
1. Test package on clean system
2. Update version numbers
3. Create release notes
4. Distribute via chosen method
5. Provide support documentation

**Questions?**
- Check included documentation
- See troubleshooting guides
- Contact support (if applicable)
