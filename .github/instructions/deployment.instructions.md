---
description: 'CosySim deployment and startup conventions — service ordering, launcher usage, health checks, port verification'
applyTo: 'start_servers.ps1,launcher.py,main.py,deployment/**'
---

# Deployment & Startup

## Service Start Order
1. LMStudio (external — must be running)
2. ComfyUI (external — if image generation needed)
3. Nexus KMS: `cd C:\Files\Nexus && python -m nexus`
4. CosySim TTS: `python start_servers.ps1`
5. CosySim Scenes: `python launcher.py --scene bedroom`
6. CosySim Hub: `python launcher.py --hub`

## Launcher Usage
```bash
python launcher.py --scene <name>     # Start single scene
python launcher.py --hub              # Start hub + admin
python launcher.py --all              # Start everything
python launcher.py --list             # List available scenes
```

## Health Checks
- LMStudio: `GET http://localhost:1234/api/v1/models`
- Nexus: `GET http://localhost:8700/api/health`
- Scene: `GET http://localhost:{port}/health`
- Hub: `GET http://localhost:8500/health`

## PowerShell Scripts
- Use PowerShell 7+ syntax
- Include error handling with `try/catch`
- Log to console with timestamps
- Check port availability before starting services
- Use `Start-Process` for background services, not `&`
