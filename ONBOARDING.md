# CosySim — Onboarding Guide

Getting up and running with CosySim in 5 minutes.

## Prerequisites

- **Python 3.11+** with pip
- **Node.js 18+** with npm
- **LMStudio** running on `:1234` with a loaded model (e.g. Qwen3-8B)
- **ComfyUI** (optional) on `:8188` for image/video generation

## Install

```powershell
# Clone and install
pip install -r requirements.txt
npm install
```

## Launch

```powershell
# Launch all scenes
python launcher.py --mode all

# Or launch individual scenes
python launcher.py --mode phone      # Phone OS      → :5555
python launcher.py --mode bedroom    # Bedroom       → :5556
python launcher.py --mode casino     # Casino        → :5559
python launcher.py --mode realm      # Realm LitRPG  → :5562
python launcher.py --mode hub        # Hub dashboard → :8500
python launcher.py --mode admin      # Admin panel   → :8502
python launcher.py --mode tts        # TTS server    → :8600
python launcher.py --mode bridge     # MCP bridge    → :8601
```

## Verify

```powershell
python -m pytest tests/ -q --tb=short --ignore=tests/test_agent_loop.py --ignore=tests/live_wire_test.py
```

## Next Steps

- **[README](README.md)** — Project overview and architecture
- **[Scenes Guide](docs/SCENES.md)** — All 11 game scenes with mechanics
- **[Architecture](docs/ARCHITECTURE.md)** — System design and data flow
- **[MCP Framework](docs/MCP_FRAMEWORK.md)** — Tools, interceptors, governance
- **[Configuration](docs/CONFIGURATION.md)** — Config files and settings
- **[Full Documentation Index](docs/INDEX.md)** — All docs in one place
