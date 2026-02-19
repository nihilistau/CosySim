# Migration from CosyVoice to CosySim

## Overview
This project was cleaned up and renamed from "CosyVoice" to "CosySim" (Virtual Companion Simulation System).

## What Changed

### Project Name
- **Old**: CosyVoice
- **New**: CosySim
- Package name: `cosysim`

### Directory Location
- **Old**: `C:\Files\Models\CosyVoice`
- **New**: `C:\Files\Models\CosySim`

### What Was Kept (Essential Files)
✅ **Core Systems:**
- `engine/` - TTS, assets, audio/video processing, deployment
- `content/` - Simulation system, scenes, characters, database
- `config/` - YAML configuration files
- `docs/` - Complete documentation (ARCHITECTURE, DEVELOPMENT, API_REFERENCE)
- `tests/` - Integration and unit tests
- `deployment/` - Docker and systemd files
- `.github/` - CI/CD workflows

✅ **Core Scripts:**
- `launcher.py` - Main unified entry point
- `launch_simulation.py` - Quick launcher
- `start_servers.ps1` - Server startup
- `main.py` - Core application

✅ **Configuration:**
- `pyproject.toml` - Updated package name to "cosysim"
- `requirements.txt` - Dependencies
- `.env.example` - Environment template
- `docker-compose.prod.yml` - Production Docker

✅ **Documentation:**
- `README.md` - Updated with CosySim branding
- `QUICK_START.md` - Getting started
- `DEPLOYMENT.md` - Deployment guide
- GitHub standard files (CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, LICENSE)

### What Was Removed (Cleaned Up)
❌ **Test Files**: test_*.py scripts in root (bedroom, phone, parallel pipeline tests)
❌ **Conversion Scripts**: convert_to_openvino.py, validate_openvino.py, inspect_openvino_models.py
❌ **Experimental Files**: dual_backend.py, wake_word_listener.py, fix_inference_calls.py, inference_nocast.py
❌ **Old Examples**: example.py, vllm_example.py, comfyui_generator.py
❌ **Generated Outputs**: demo_output/, generated_images/, outputs/, audio_output/, test*.wav files
❌ **Caches & Temp**: cache/, logs/, .pytest_cache/, __pycache__, kernel.errors.txt
❌ **User Data**: conversation_history.db, asset_registry.db (fresh start)
❌ **Old Notebooks**: Untitled.ipynb

### Symlinks (Save Space)
To avoid duplicating large model files, these directories are **symlinked** to the original CosyVoice folder:

```
C:\Files\Models\CosySim\pretrained_models → C:\Files\Models\CosyVoice\pretrained_models
C:\Files\Models\CosySim\asset → C:\Files\Models\CosyVoice\asset
```

**Note**: If you delete the original CosyVoice folder, these symlinks will break. Either:
1. Keep the original folder for the models
2. Or copy `pretrained_models/` and `asset/` to CosySim before deleting

## Updated References

### Package Name
- pyproject.toml: `name = "cosysim"`
- Coverage config: `source = ["cosysim"]`

### Dependencies Fixed (Windows Compatibility)
- ❌ Removed: `tensorrt-llm==1.0.0` (Linux-only)
- ❌ Removed: `nvidia-cufile-cu12==1.11.1.6` (no Windows wheels)

### Documentation
- README.md: Updated branding to "CosySim"
- Banner: CosySim Virtual Companion System
- Git URLs: Updated clone instructions

## Installation

### Fresh Install
```bash
cd C:\Files\Models\CosySim
pip install -e .
```

### Verify Installation
```python
from engine.assets import AssetManager
from content.simulation.database.db import Database
print("✅ CosySim imported successfully!")
```

### Launch
```bash
python launcher.py
# Select option 1: Central Hub
# Navigate to http://localhost:8500
```

## Project Statistics

| Category | Before | After | Change |
|----------|--------|-------|--------|
| Root files | 80+ | ~40 | ✅ 50% reduction |
| Size (without models) | ~500MB | ~300MB | ✅ 40% smaller |
| Documentation | Scattered | Organized in docs/ | ✅ Consolidated |
| Test outputs | ~50MB | 0 | ✅ Clean |
| Experimental scripts | ~20 | 0 | ✅ Focused |

## Next Steps

1. ✅ Project renamed and cleaned
2. ⏭️ Install with `pip install -e .`
3. ⏭️ Test all scenes (hub, phone, bedroom, admin)
4. ⏭️ Update GitHub repository if publishing
5. ⏭️ Run tests: `pytest tests/`

## Support

- 📖 Full docs: `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md`
- 🚀 Quick start: `QUICK_START.md`
- 🐛 Issues: See CONTRIBUTING.md
