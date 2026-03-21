# CosySim Deployment Guide

> Service architecture, startup procedures, port registry, and troubleshooting — v1.42+.

---

## Three-Pillar Architecture

CosySim runs as a constellation of services organized into three pillars, defined in `engine/control_plane_registry.py`:

```
┌──────────────── External (manual) ────────────────┐
│  LMStudio (:1234)          ComfyUI (:8188)        │
│  LLM inference             Image generation       │
└───────────────────────┬───────────────────────────┘
                        │ REST / SSE
┌───────────────────────▼───────────────────────────┐
│              CosySim Engine (v1.42)                │
│                                                    │
│  ┌─ SERVICE PILLAR (11) ──────────────────────┐   │
│  │  Nexus KMS :8700 (auto, priority 0)        │   │
│  │  Hub :8500 · Nexus Panel :5570             │   │
│  │  Bridge :8601 · NLM Proxy :8800            │   │
│  │  System Control :5575 · Intel Hub :5580    │   │
│  │  Dashboard :8501 · Admin :8502 · TTS :8600 │   │
│  │  Command Center :5566                      │   │
│  └────────────────────────────────────────────┘   │
│                                                    │
│  ┌─ GAME PILLAR (14) ────────────────────────┐    │
│  │  phone :5555 · penthouse :5556             │    │
│  │  lounge :5557 · tavern :5558               │    │
│  │  casino :5559 · gallery :5560              │    │
│  │  arena :5561 · realm :5562                 │    │
│  │  neoncity :5563 · coders :5564             │    │
│  │  heist :5565 · games :5567                 │    │
│  │  grid :5569 · lab_break :5571              │    │
│  └────────────────────────────────────────────┘    │
│                                                    │
│  ┌─ CREATION PILLAR (5) ─────────────────────┐    │
│  │  Canvas :5590 · Canvas API :5595           │    │
│  │  Assets :8503 · Creator :8504              │    │
│  │  Asset Studio :5568                        │    │
│  └────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────┘
```

### Service Types

| Type | Framework | Port Range | Launch Method |
|------|-----------|------------|---------------|
| `flask` | Flask + Socket.IO | 5555–5580 | Daemon thread |
| `streamlit` | Streamlit | 8500–8504 | Subprocess |
| `fastapi` | Uvicorn | 8600–8601 | Daemon thread |
| `node` | Node.js | 5590–5595 | Subprocess |
| `external` | Subprocess | 8700 | Subprocess (cwd) |

---

## Start Order & Dependencies

Nexus KMS is a **managed auto-start service** (priority 0). It launches automatically before all other services.

```
Step 0: Nexus KMS (:8700)    ← auto-managed, starts first
Step 1: External (manual)
  ├── LMStudio    :1234      ← required (LLM inference)
  └── ComfyUI     :8188      ← optional (image generation)
Step 2: CosySim Services     ← auto_start=True targets
Step 3: CosySim Scenes       ← auto_start=True targets
Step 4: WorldSim + Scheduler ← auto-activated after scenes
```

### Quick Start

```bash
# Minimal — one scene
python launcher.py penthouse

# Recommended — all auto-start targets
python launcher.py --core

# Everything
python launcher.py --all

# By pillar
python launcher.py --game
python launcher.py --creation

# TUI (interactive dashboard)
python tui.py
```

### Launcher CLI

```bash
python launcher.py [target]           # Single target by name
python launcher.py --core             # auto_start services + scenes
python launcher.py --services         # auto_start services only
python launcher.py --scenes           # auto_start scenes only
python launcher.py --all              # every known target
python launcher.py --game             # game pillar only
python launcher.py --creation         # creation pillar only
python launcher.py --list             # show all targets + port status
python launcher.py --status           # system health check
python launcher.py --test             # run test suite
python launcher.py --init-db          # initialize simulation database
python launcher.py --housekeep        # housekeeping tasks
```

### Auto-Start Overrides

Edit `config/launcher.yaml` to toggle which targets launch with `--core`:

```yaml
services:
  nexus_kms:
    auto_start: true
  hub:
    auto_start: true
scenes:
  penthouse:
    auto_start: false
```

---

## PM2 Process Management

For persistent deployment, use PM2 with `ecosystem.config.js`:

```bash
pm2 start ecosystem.config.js              # Start all processes
pm2 start ecosystem.config.js --only cosysim-nexus-kms  # Nexus only
pm2 start ecosystem.config.js --only cosysim-launcher   # CosySim core
pm2 stop all                                # Stop everything
pm2 save                                    # Persist process list
pm2 resurrect                               # Restore after reboot
```

PM2 process names follow the `cosysim-{target}` convention. Nexus KMS starts first via `scripts/pm2/start_nexus_kms.py`.

---

## Health Checks

Every service exposes a health endpoint:

| Service | Health URL | Notes |
|---------|-----------|-------|
| Flask scenes | `GET :port/api/health` | Returns scene status JSON |
| Hub | `GET :8500/health` | Streamlit health |
| Nexus KMS | `GET :8700/api/health` | Entry/rule counts |
| LMStudio | `GET :1234/api/v1/models` | Model list (v1 API) |
| TTS Server | `GET :8600/health` | TTS status |
| MCP Bridge | `GET :8601/health` | Bridge status |
| NLM Proxy | `GET :8800/health` | Proxy status |
| ComfyUI | `GET :8188/system_stats` | System stats |

### Pillar-Grouped Scene Registry

Every Flask scene auto-serves `GET /api/scene-registry` (wired by `BaseSceneRoutesMixin`), returning all targets grouped by pillar with live status.

### Quick Check

```bash
python launcher.py --status    # Full system health
python launcher.py --list      # Port status table by pillar
```

---

## Port Registry

All ports are defined in `engine/port_registry.py` with config overrides from `config/default.yaml`.

### Game Pillar (5555–5571)

| Port | ID | Label |
|------|----|-------|
| 5555 | phone | SIGNAL |
| 5556 | penthouse | THE PENTHOUSE |
| 5557 | lounge | THE VELVET PIT |
| 5558 | tavern | THE RUSTY ANCHOR |
| 5559 | casino | CLUB NOIR |
| 5560 | gallery | THE OBSCURA |
| 5561 | arena | THE COLOSSEUM |
| 5562 | realm | THE SHATTERED THRONE |
| 5563 | neoncity | NEON CITY |
| 5564 | coders | THE LAB |
| 5565 | heist | THE SCORE |
| 5567 | games | THE ARCADE |
| 5569 | grid | THE GRID |
| 5571 | lab_break | LAB BREAK |

### Service Pillar

| Port | ID | Label |
|------|----|-------|
| 8700 | nexus_kms | Nexus KMS |
| 8500 | hub | CosySim Hub |
| 5570 | nexus_panel | Nexus Control Panel |
| 8501 | dashboard | System Dashboard |
| 8502 | admin | Admin Panel |
| 8600 | tts | TTS Server |
| 8601 | bridge | MCP Bridge |
| 8800 | nlm_proxy | NLM Live Proxy |
| 5575 | system_control | System Control Panel |
| 5566 | command_center | Command Center |
| 5580 | intel_hub | THE BRIEFING ROOM |

### Creation Pillar

| Port | ID | Label |
|------|----|-------|
| 5590 | canvas | Nexus Canvas |
| 5595 | canvas_api | Canvas API |
| 8503 | assets | Asset Generator |
| 8504 | creator | Scene Creator |
| 5568 | asset_studio | ASSET STUDIO |

### External (Manual)

| Port | Service |
|------|---------|
| 1234 | LMStudio (required) |
| 8188 | ComfyUI (optional) |

---

## Environment Requirements

- **Python 3.10+** (3.13 recommended)
- **Node.js 18+** (for Nexus Canvas)
- `pip install -r requirements.txt && npm install`

### External Services

| Service | Required | Install |
|---------|----------|---------|
| LMStudio | Yes | [lmstudio.ai](https://lmstudio.ai) — load at least one model |
| ComfyUI | No | Only for image generation |

### Configuration

Layered YAML config system (see [CONFIGURATION.md](./CONFIGURATION.md)):

```
config/default.yaml       ← base values (source of truth)
config/development.yaml   ← dev overrides
config/production.yaml    ← prod overrides
config/launcher.yaml      ← auto_start overrides
config/game.yaml          ← game pillar config
config/services.yaml      ← service pillar config
config/creation.yaml      ← creation pillar config
```

---

## Troubleshooting

### Port Already in Use

```powershell
Get-NetTCPConnection -LocalPort 5556 | Select-Object OwningProcess
Stop-Process -Id <PID> -Force
```

### LMStudio Not Responding

1. Verify running: `curl http://localhost:1234/api/v1/models`
2. Ensure a model is loaded
3. Check `config/default.yaml` → `lmstudio.base_url` and `lmstudio.api_token`
4. LMStudio uses v1 API — ensure `lmstudio.api_version: "v1"` in config

### Unicode Console Errors (Windows)

```powershell
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

### Database Not Found

```bash
python launcher.py --init-db
```

---

## See Also

- [Architecture](./ARCHITECTURE.md) — system layers and data flow
- [Configuration](./CONFIGURATION.md) — all config files and settings
- [LMStudio](./LMSTUDIO.md) — LLM inference setup
- [Testing](./TESTING.md) — smart test system
- [Scenes](./SCENES.md) — scene mechanics and APIs
