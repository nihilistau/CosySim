# CosySim Deployment Guide

> Service architecture, startup procedures, port registry, and troubleshooting for CosySim v0.52b+.

---

## Service Architecture

CosySim runs as a constellation of services: Flask scenes, Streamlit apps, FastAPI microservices, and external dependencies. All services bind to `localhost` by default.

```
┌─────────────────────────── External Services ───────────────────────────┐
│                                                                         │
│  LMStudio (:1234)          ComfyUI (:8188)         Nexus KMS (:8700)   │
│  LLM inference             Image generation         Knowledge system    │
│                                                                         │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ REST / SSE
┌────────────────────────────────▼────────────────────────────────────────┐
│                         CosySim Engine                                  │
│                                                                         │
│  ┌─────────────────────┐  ┌─────────────────┐  ┌───────────────────┐   │
│  │  Flask Scenes        │  │ Streamlit Apps   │  │ FastAPI Services  │   │
│  │  :5555–5570          │  │ :8500–8504       │  │ :8600–8601        │   │
│  │  phone, penthouse,     │  │ hub, dashboard,  │  │ tts, mcp_bridge   │   │
│  │  lounge, tavern, ... │  │ admin, assets,   │  │                   │   │
│  │                      │  │ creator          │  │                   │   │
│  └─────────────────────┘  └─────────────────┘  └───────────────────┘   │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  TTS Servers                                                     │   │
│  │  Qwen3-TTS :8600  ·  Orpheus-FastAPI :5005  ·  Whisper STT :5051│   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Service Categories

| Category | Framework | Port Range | Managed By |
|----------|-----------|------------|------------|
| Flask scenes | Flask + SocketIO | 5555–5570 | `launcher.py` |
| Streamlit apps | Streamlit | 8500–8504 | `launcher.py` |
| FastAPI services | Uvicorn | 8600–8601 | `launcher.py` |
| CosyVoice TTS/STT | Python | 5050–5051 | `start_servers.ps1` |
| LMStudio | External | 1234 | Manual |
| ComfyUI | External | 8188 | Manual |
| Nexus KMS | External | 8700 | Manual |
| Orpheus TTS | FastAPI | 5005 | Manual |
| NotebookLM proxy | Node.js | 8800 | Optional |

---

## Start Order & Dependencies

Services must start in dependency order. Downstream services expect upstream APIs to be available.

```
Step 1: External Services (manual)
  ├── LMStudio         :1234   ← required (LLM inference)
  ├── ComfyUI          :8188   ← optional (image generation)
  └── Nexus KMS        :8700   ← optional (knowledge system)

Step 2: CosySim Infrastructure
  ├── TTS Server       :8600   ← optional (voice generation)
  └── MCP Bridge       :8601   ← optional (web MCP relay)

Step 3: CosySim Scenes
  ├── Flask Scenes     :5555+  ← one or more scenes
  └── Hub              :8500   ← central navigation
```

### Quick Start (Minimal)

```powershell
# 1. Start LMStudio (ensure a model is loaded)
# 2. Launch a single scene
python launcher.py --mode penthouse
```

### Full Stack Start

```powershell
# 1. Start LMStudio with a model loaded
# 2. Start Nexus (separate terminal)
cd C:\Files\Nexus
python -m nexus

# 3. Launch all CosySim services (single terminal)
python launcher.py --mode all
```

### CosyVoice TTS/STT (Separate Stack)

The `start_servers.ps1` script launches legacy CosyVoice3 TTS and Whisper STT servers for AnythingLLM integration. These are independent of the main `launcher.py` TTS service.

```powershell
# Both TTS + STT
.\start_servers.ps1

# TTS only on custom port
.\start_servers.ps1 -Mode tts -TTSPort 5050

# STT only with larger Whisper model
.\start_servers.ps1 -Mode stt -WhisperModel small
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-Mode` | `both` | `both`, `tts`, or `stt` |
| `-Host` | `0.0.0.0` | Bind address |
| `-TTSPort` | `5050` | TTS server port |
| `-STTPort` | `5051` | STT server port |
| `-WhisperModel` | `tiny` | Whisper model size (`tiny`, `small`, `medium`, `large`) |

---

## Launcher Usage

The unified entry point is `launcher.py` (aliased via `main.py`). Both are equivalent:

```bash
python launcher.py [options]
python main.py [options]
```

### CLI Arguments

| Argument | Description |
|----------|-------------|
| `--mode <name>` | Launch a specific scene, service, or `all` |
| `--list` | List all scenes and services with port status |
| `--status` | Full system health check (deps, databases, ports) |
| `--init-db` | Initialize the simulation database |
| `--housekeep` | Run housekeeping tasks (media ingest, health checks) |
| `--housekeep --watch` | Run housekeeping continuously |
| `--version` | Print version and exit |

### Mode Values

Any Flask scene, Streamlit app, or service name is a valid mode:

```bash
# Flask scenes
python launcher.py --mode phone
python launcher.py --mode penthouse
python launcher.py --mode lounge
python launcher.py --mode tavern
python launcher.py --mode casino
python launcher.py --mode gallery
python launcher.py --mode realm
python launcher.py --mode neoncity
python launcher.py --mode coders
python launcher.py --mode heist
python launcher.py --mode command_center
python launcher.py --mode games
python launcher.py --mode nexus_panel

# Streamlit apps
python launcher.py --mode hub
python launcher.py --mode dashboard
python launcher.py --mode admin
python launcher.py --mode assets
python launcher.py --mode creator

# FastAPI services
python launcher.py --mode tts
python launcher.py --mode bridge

# Multi-service
python launcher.py --mode all       # all Flask scenes + services + Hub
python launcher.py --mode test      # run pytest suite
```

### Interactive Menu

Running `python launcher.py` with no arguments opens an interactive menu:

```
╔══════════════════════════════════════════════════════════════╗
║                  CosySim v0.50b                              ║
║              AI Agent Simulation Framework                    ║
╠══════════════════════════════════════════════════════════════╣
║  Scenes:                                                     ║
║    1. phone     - CosyPhone OS           (port 5555)         ║
║    2. penthouse   - The Penthouse            (port 5556)         ║
║    ...                                                       ║
║  Services:                                                   ║
║    7. hub       - Central Hub             (port 8500)         ║
║    8. admin     - Admin Panel             (port 8502)         ║
║    9. all       - Launch everything                           ║
║  Tools:                                                      ║
║    s. status    - System health check                        ║
║    t. test      - Run test suite                             ║
║    l. list      - List all scenes + ports                    ║
║    q. quit                                                   ║
╚══════════════════════════════════════════════════════════════╝
```

### `--mode all` Behaviour

The `all` mode launches services in a single terminal:

1. **Flask scenes** — each starts in a daemon thread (0.8 s stagger)
2. **FastAPI services** — each starts in a daemon thread via Uvicorn
3. **Hub** — starts as a subprocess (Streamlit requires its own process)
4. **Health check** — runs after 5 seconds, prints port status
5. **Ctrl+C** — terminates all threads and subprocesses

---

## Health Checks

Every CosySim service exposes a health endpoint. Use these to verify services are running.

### Endpoints

| Service | Health URL | Response |
|---------|-----------|----------|
| LMStudio | `GET http://localhost:1234/api/v1/models` | Model list JSON |
| Nexus KMS | `GET http://localhost:8700/api/health` | `{"status": "ok"}` |
| Flask scenes | `GET http://localhost:{port}/api/health` | Scene health JSON |
| TTS Server | `GET http://localhost:8600/health` | Status JSON |
| MCP Bridge | `GET http://localhost:8601/health` | Status JSON |
| CosyVoice TTS | `GET http://localhost:5050/health` | Status JSON |
| CosyVoice STT | `GET http://localhost:5051/health` | Status JSON |
| Hub (Streamlit) | `GET http://localhost:8500/health` | Streamlit health |
| ComfyUI | `GET http://localhost:8188/` | Web UI |

### Quick Check Script

The `deployment/scripts/System-Status.ps1` script checks all core services and shows a toast notification:

```powershell
.\deployment\scripts\System-Status.ps1
```

### Programmatic Check

The launcher includes a port check utility:

```bash
# Show status of all known ports
python launcher.py --status

# List scenes with live status indicators (🟢 UP / ⚫ down)
python launcher.py --list
```

### `--status` Output

The `--status` command reports:

- Python version and CosySim version
- Dependency versions (Flask, Streamlit, PyTorch, ChromaDB, APScheduler, Requests)
- Database files and sizes
- Port status for all registered services
- Project directory statistics

### cURL Health Check Examples

```bash
# Check LMStudio
curl -s http://localhost:1234/api/v1/models | python -m json.tool

# Check a Flask scene
curl -s http://localhost:5556/api/health | python -m json.tool

# Check TTS server
curl -s http://localhost:8600/health

# Check Nexus
curl -s http://localhost:8700/api/health
```

---

## Port Registry

All ports used by CosySim, grouped by category. Ports are configured in `config/default.yaml` and `launcher.py`.

### Flask Scenes (5555–5570)

| Port | Scene | Label |
|------|-------|-------|
| 5555 | `phone` | CosyPhone OS |
| 5556 | `penthouse` | The Penthouse |
| 5557 | `lounge` | The Velvet Lounge |
| 5558 | `tavern` | Dragon's Flagon Tavern |
| 5559 | `casino` | Midnight Casino |
| 5560 | `gallery` | The Gallery |
| 5561 | `arena` | The Colosseum |
| 5562 | `realm` | The Realm |
| 5563 | `neoncity` | NeonCity |
| 5564 | `coders` | The Coders Room |
| 5565 | `heist` | The Heist |
| 5566 | `command_center` | Command Center |
| 5567 | `games` | Games Arcade |
| 5570 | `nexus_panel` | Nexus Control Panel |

### Streamlit Apps (8500–8504)

| Port | App | Label |
|------|-----|-------|
| 8500 | `hub` | Hub (central navigation) |
| 8501 | `dashboard` | Dashboard |
| 8502 | `admin` | Admin Panel |
| 8503 | `assets` | Asset Generator |
| 8504 | `creator` | Scene Creator |

### FastAPI Services (8600–8601)

| Port | Service | Label |
|------|---------|-------|
| 8600 | `tts` | Qwen3-TTS Server |
| 8601 | `bridge` | MCP Web Bridge |

### CosyVoice Legacy (5050–5051)

| Port | Service | Managed By |
|------|---------|------------|
| 5050 | CosyVoice3 TTS | `start_servers.ps1` |
| 5051 | Whisper STT | `start_servers.ps1` |

### External Services

| Port | Service | Notes |
|------|---------|-------|
| 1234 | LMStudio | LLM inference (required) |
| 8188 | ComfyUI | Image generation (optional) |
| 8700 | Nexus KMS / MCP Server | Knowledge system + MCP SSE endpoint |
| 8800 | NotebookLM Proxy | Optional NLM bridge |

### Reserved / Gap

Ports 5568–5569 and 8505–8599 are unassigned and available for new scenes or services.

---

## Environment Requirements

### Python

- **Python 3.10+** required
- Install dependencies: `pip install -r requirements.txt`
- CUDA 12.1 recommended for GPU inference (PyTorch, TTS models)

### Key Dependencies

| Package | Purpose |
|---------|---------|
| `flask` | Scene HTTP servers |
| `flask-socketio` | Real-time scene events |
| `streamlit` | Hub, dashboard, admin |
| `uvicorn` / `fastapi` | TTS and MCP bridge services |
| `torch` | LLM inference, TTS models |
| `chromadb` | Vector memory store |
| `openai` | LMStudio API client |
| `apscheduler` | Autonomous messaging |
| `psutil` | System monitoring |
| `lmstudio` | LMStudio SDK |

### External Services

| Service | Required | Install |
|---------|----------|---------|
| LMStudio | Yes | [lmstudio.ai](https://lmstudio.ai) — load at least one model |
| ComfyUI | No | Only for image generation (selfies, portraits) |
| Nexus | No | `cd C:\Files\Nexus && python -m nexus` |
| Node.js | No | Only for NotebookLM proxy |

### Configuration

CosySim uses a layered config system (see [CONFIGURATION.md](./CONFIGURATION.md)):

```
config/default.yaml      ← base values
config/development.yaml   ← dev overrides (COSYSIM_ENV=development)
config/production.yaml    ← prod overrides (COSYSIM_ENV=production)
```

Set environment with `COSYSIM_ENV`:

```powershell
$env:COSYSIM_ENV = "development"
python launcher.py --mode penthouse
```

### Database Initialization

On first run, initialize the simulation database:

```bash
python launcher.py --init-db
```

This creates SQLite tables for characters, personalities, roles, conversations, interactions, media, and character states.

---

## Troubleshooting

### Port Already in Use

**Symptom:** `OSError: [Errno 10048] address already in use` or scene fails to start.

```powershell
# Find what's using a port
Get-NetTCPConnection -LocalPort 5556 | Select-Object OwningProcess
Get-Process -Id <PID>

# Kill the process
Stop-Process -Id <PID> -Force
```

### LMStudio Not Responding

**Symptom:** Scenes start but agents return empty responses or timeout errors.

1. Verify LMStudio is running: `curl http://localhost:1234/api/v1/models`
2. Ensure at least one model is loaded in LMStudio
3. Check `config/default.yaml` → `lmstudio.base_url` matches LMStudio's address
4. If using API authentication, set `lmstudio.api_token` in config

### Scene Fails to Import

**Symptom:** `❌ <SceneName> failed: ModuleNotFoundError`

```bash
# Check dependencies
pip install -r requirements.txt

# Verify the scene module exists
python -c "from content.scenes.penthouse.penthouse_scene import PenthouseScene"
```

### Streamlit Apps Won't Start

**Symptom:** Hub or admin panel fails with `streamlit: command not found`.

```bash
pip install streamlit
streamlit --version
```

If installed but not on PATH, use the full path or activate your virtual environment.

### TTS Server Fails

**Symptom:** `❌ TTS server failed to start` or voice generation returns errors.

1. Check GPU availability: `python -c "import torch; print(torch.cuda.is_available())"`
2. TTS models require CUDA by default — set `tts.device: "cpu"` in config for CPU-only
3. Verify port 8600 is free before starting

### Database Not Found

**Symptom:** `sqlite3.OperationalError: no such table: characters`

```bash
python launcher.py --init-db
```

### Unicode Console Errors on Windows

**Symptom:** `UnicodeEncodeError` with emoji characters in console output.

The launcher auto-reconfigures stdout to UTF-8. If errors persist:

```powershell
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

### All Services Health Check

Run a full diagnostic:

```bash
python launcher.py --status
```

This checks Python version, all dependencies, database files, and port status in one command.

---

## Deployment Scripts

Helper scripts live in `deployment/scripts/`:

| Script | Purpose |
|--------|---------|
| `System-Status.ps1` | Toast notification with service health |
| `Quick-Commit.ps1` | Git commit helper |
| `Run-Tests.ps1` | Test runner |
| `Send-ToNexus.ps1` | Submit content to Nexus |
| `Quick-Search-Nexus.ps1` | Search Nexus knowledge base |

Additional deployment tooling:

| Path | Purpose |
|------|---------|
| `deployment/scheduler/` | Windows scheduled task setup |
| `deployment/autohotkey/` | CosySim keyboard hotkeys |
| `deployment/colab_lmstudio_setup.ipynb` | Google Colab remote GPU setup |

---

## See Also

- [Architecture](./ARCHITECTURE.md) — system layers and data flow
- [Configuration](./CONFIGURATION.md) — all config files and settings
- [LMStudio](./LMSTUDIO.md) — LLM inference setup and model management
- [TTS](./TTS.md) — Qwen3-TTS server and voice generation
- [Scenes](./SCENES.md) — scene mechanics and APIs
- [API Reference](./API.md) — REST endpoints and Socket.IO events
