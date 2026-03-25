# Operations

> CosySim Documentation -- v1.51.1 [2026-03-25]
>
> Launching, ports, monitoring, logging, scheduling, and admin panels.

---

## 1. Quick Start

CosySim runs as a constellation of Flask/Socket.IO scenes, Streamlit dashboards, FastAPI services, and Node.js apps. The launcher (`launcher.py`) and TUI (`tui.py`) are the two entry points.

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

### Common Recipes

```bash
# Minimal -- one scene
python launcher.py penthouse              # http://localhost:5556

# Recommended -- core auto-start targets
python launcher.py --core

# Everything
python launcher.py --all

# Interactive terminal dashboard
python tui.py
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
  lounge:
    auto_start: true
```

---

## 2. Three-Pillar Architecture

CosySim organizes its 32 launcher-managed targets into three pillars, defined in `engine/control_plane_registry.py`. Each target has a type, a port, an auto-start flag, and a pillar assignment.

```
+--------------------- External (manual) ----------------------+
|  LMStudio (:1234)             ComfyUI (:8188)                |
|  LLM inference                Image generation               |
+------------------------------+-------------------------------+
                               | REST / SSE
+------------------------------v-------------------------------+
|               CosySim Engine  (v1.50)                        |
|                                                              |
|  +- GAME PILLAR (15) ------------------------------------+   |
|  |  phone :5555      penthouse :5556    lounge :5557     |   |
|  |  tavern :5558     casino :5559       gallery :5560    |   |
|  |  arena :5561      realm :5562        neoncity :5563   |   |
|  |  coders :5564     heist :5565        games :5567      |   |
|  |  grid :5569       lab_break :5571    oracle :5572     |   |
|  +-------------------------------------------------------+   |
|                                                              |
|  +- SERVICE PILLAR (11) ---------------------------------+   |
|  |  Nexus KMS :8700 (auto, priority 0)                   |   |
|  |  Hub :8500          Nexus Panel :5570                 |   |
|  |  Dashboard :8501    Admin :8502                       |   |
|  |  TTS :8600          Bridge :8601                      |   |
|  |  NLM Proxy :8800    System Control :5575              |   |
|  |  Command Center :5566    Intel Hub :5580              |   |
|  +-------------------------------------------------------+   |
|                                                              |
|  +- CREATION PILLAR (6) ---------------------------------+   |
|  |  Canvas :5590       Canvas API :5595                  |   |
|  |  Assets :8503       Creator :8504                     |   |
|  |  Asset Studio :5568    Creation Kit :5592             |   |
|  +-------------------------------------------------------+   |
+--------------------------------------------------------------+
```

### Service Types

| Type | Framework | Port Range | Launch Method |
|------|-----------|------------|---------------|
| `flask` | Flask + Socket.IO | 5555--5580 | Daemon thread |
| `streamlit` | Streamlit | 8500--8504 | Subprocess |
| `fastapi` | Uvicorn | 8600--8601, 5595 | Daemon thread |
| `node` | Node.js | 5590 | Subprocess |
| `external` | Subprocess | 8700 | Subprocess (cwd) |

### Pillar Summary

| Pillar | Count | Description |
|--------|-------|-------------|
| **Game** | 15 | Interactive scenes -- each a Flask+Socket.IO app with Neon HUD |
| **Service** | 11 | Infrastructure -- KMS, dashboards, proxy, bridge, control panels |
| **Creation** | 6 | Authoring tools -- canvas, asset generators, scene creator, creation kit |

---

## 3. Port Registry

All ports are defined in `engine/port_registry.py`. Config overrides from `config/default.yaml` are applied at runtime by the `PortRegistry` singleton. Always use `get_port()` or `get_port_registry().get()` for lookups -- never hardcode port numbers.

### Game Pillar (15 targets)

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
| 5572 | oracle | THE ORACLE |

### Service Pillar (11 targets)

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

### Creation Pillar (6 targets)

| Port | ID | Label |
|------|----|-------|
| 5590 | canvas | Nexus Canvas |
| 5595 | canvas_api | Canvas API |
| 8503 | assets | Asset Generator |
| 8504 | creator | Scene Creator |
| 5568 | asset_studio | ASSET STUDIO |
| 5592 | creation_kit | CREATION KIT |

### External (Not Launcher-Managed)

| Port | Service | Required |
|------|---------|----------|
| 1234 | LMStudio | Yes -- local LLM inference |
| 8188 | ComfyUI | No -- image generation only |

### Sidecar Services

| Port | Service |
|------|---------|
| 5005 | Orpheus TTS |
| 5050 | CosyVoice TTS |
| 5051 | Whisper STT |
| 5591 | Canvas Sidecar |

### Legacy Aliases

Old service names map to canonical keys so either name resolves to the same port:

| Alias | Canonical |
|-------|-----------|
| `qwen3_tts` | `tts` |
| `web_bridge` | `bridge` |
| `nexus_canvas` | `canvas` |
| `notebooklm_proxy` | `nlm_proxy` |
| `nexus` | `nexus_kms` |

### Programmatic Access

```python
from engine.port_registry import get_port, get_service_url, get_port_registry

port = get_port("penthouse")                      # 5556
url = get_service_url("nexus_kms", path="/api/health")  # http://localhost:8700/api/health

registry = get_port_registry()
conflicts = registry.find_conflicts()              # [(svc_a, svc_b, port), ...]
all_ports = registry.all_ports()                   # {"phone": 5555, ...}
print(registry.summary())                          # Formatted table
```

---

## 4. Auto-Start & Service Dependencies

### Start Order

Nexus KMS is a **managed auto-start service** with priority 0 -- it launches automatically before all other targets. The full start sequence:

```
Step 0: Nexus KMS (:8700)    <-- auto-managed, starts first
Step 1: External (manual)
  +-- LMStudio    :1234      <-- required (LLM inference)
  +-- ComfyUI     :8188      <-- optional (image generation)
Step 2: CosySim Services     <-- auto_start=True targets
Step 3: CosySim Scenes       <-- auto_start=True targets
Step 4: WorldSim + Scheduler <-- auto-activated after scenes
```

### Default Auto-Start Targets

From `control_plane_registry.py`, these targets have `auto_start: True` by default:

**Services:** nexus_kms, hub, nexus_panel, bridge, nlm_proxy, system_control, canvas, canvas_api

**Scenes:** phone, penthouse, neoncity, intel_hub

All others start on demand via `python launcher.py <target>` or `--all`.

### PM2 Process Management

For persistent deployment, use PM2 with `ecosystem.config.js`:

```bash
pm2 start ecosystem.config.js                          # Start all processes
pm2 start ecosystem.config.js --only cosysim-nexus-kms  # Nexus only
pm2 start ecosystem.config.js --only cosysim-launcher   # CosySim core
pm2 stop all                                            # Stop everything
pm2 save                                                # Persist process list
pm2 resurrect                                           # Restore after reboot
```

PM2 process names follow the `cosysim-{target}` convention. Nexus KMS starts first via `scripts/pm2/start_nexus_kms.py`.

### Environment Requirements

- **Python 3.10+** (3.13 recommended)
- **Node.js 18+** (for Nexus Canvas)
- `pip install -r requirements.txt && npm install`

### External Services

| Service | Required | Install |
|---------|----------|---------|
| LMStudio | Yes | [lmstudio.ai](https://lmstudio.ai) -- load at least one model |
| ComfyUI | No | Only for image generation |

### Configuration Hierarchy

Layered YAML config system (see [CONFIGURATION.md](./CONFIGURATION.md)):

```
config/default.yaml       <-- base values (source of truth)
config/development.yaml   <-- dev overrides
config/production.yaml    <-- prod overrides
config/launcher.yaml      <-- auto_start overrides
config/game.yaml          <-- game pillar config
config/services.yaml      <-- service pillar config
config/creation.yaml      <-- creation pillar config
```

---

## 5. Health Checks

Every launcher-managed service exposes a health endpoint. The launcher, TUI, Hub, and System Control panel all use these for status monitoring.

### Health Endpoints

| Service Type | Default Health Path | Notes |
|--------------|-------------------|-------|
| Flask scenes | `GET :port/api/health` | Returns scene status JSON |
| Hub (Streamlit) | `GET :8500/health` | Streamlit health |
| Nexus KMS | `GET :8700/api/health` | Entry/rule counts |
| LMStudio | `GET :1234/api/v1/models` | Model list (v1 API) |
| TTS Server | `GET :8600/health` | TTS status |
| MCP Bridge | `GET :8601/health` | Bridge status |
| NLM Proxy | `GET :8800/health` | Proxy status |
| ComfyUI | `GET :8188/system_stats` | System stats |

### Health Path Overrides

Most targets use `/api/health`. These use custom paths (defined in `port_registry.py`):

| Target | Override Path |
|--------|--------------|
| `hub` | `/health` |
| `lmstudio` | `/api/v1/models` |
| `comfyui` | `/system_stats` |
| `tts` | `/health` |
| `nlm_proxy` | `/health` |

### Quick Health Check

```bash
python launcher.py --status    # Full system health across all targets
python launcher.py --list      # Port status table grouped by pillar
```

### Scene Registry Endpoint

Every Flask scene auto-serves `GET /api/scene-registry` (wired by `BaseSceneRoutesMixin`), returning all targets grouped by pillar with live status. The Hub uses this for its scene catalogue.

### Programmatic Health Checks

```python
from engine.port_registry import build_health_endpoints

endpoints = build_health_endpoints()
# [{"id": "nexus_kms", "name": "Nexus KMS", "url": "http://localhost:8700/api/health", "port": 8700}, ...]
```

---

## 6. Logging

### Architecture

```
engine/logging/
+-- __init__.py          Public API -- re-exports everything below
+-- cosy_logger.py       CosyLogger: ring-buffer handler + install_logger()
+-- benchmark.py         @timed decorator, LLM KPI tracking, timeseries
+-- monitor.py           SystemMonitor: CPU/RAM/GPU metrics, service health
```

| Subsystem | Module | Purpose |
|-----------|--------|---------|
| **CosyLogger** | `cosy_logger.py` | In-memory ring buffer (2,000 entries) for live log streaming |
| **Benchmark** | `benchmark.py` | `@timed` decorator and LLM KPI tracking |
| **SystemMonitor** | `monitor.py` | Hardware metrics and service health pings |

All three are exposed through a single import path:

```python
from engine.logging import (
    install_logger, get_logs, clear_logs,          # CosyLogger
    timed, get_benchmarks, reset_benchmarks,       # Benchmark
    record_llm_kpi, get_llm_kpis, get_kpi_timeseries,
    get_system_monitor,                            # SystemMonitor
)
```

### Configuration

In `config/default.yaml` under the `logging` key:

```yaml
logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: "./logs/cosysim.log"
  max_bytes: 10485760  # 10 MB
  backup_count: 5
```

| Key | Default | Description |
|-----|---------|-------------|
| `level` | `INFO` | Minimum log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `format` | see above | Python `logging.Formatter` pattern |
| `file` | `./logs/cosysim.log` | Log file path |
| `max_bytes` | `10485760` (10 MB) | Max size before rotation |
| `backup_count` | `5` | Number of rotated backups to keep |

The log directory is also set in `paths.logs_dir` (default: `./logs`).

### Per-Module Convention

Every module uses one logger, never `print()`:

```python
import logging
logger = logging.getLogger(__name__)
```

| Level | When to Use | Examples |
|-------|-------------|---------|
| `DEBUG` | Detailed diagnostic info, high-volume | Token counts, cache hits, state transitions |
| `INFO` | Significant operational events | Scene started, model loaded, skill registered |
| `WARNING` | Unexpected but recoverable situations | Missing optional dependency, falling back to default |
| `ERROR` | Operation failed, needs attention | LMStudio unreachable, database write failed |
| `CRITICAL` | System-level failure (rarely used) | Cannot start engine, data corruption |

Errors and critical messages are automatically forwarded to the **ActivityBus** as `log_error` events, making them visible in the admin panel without extra code.

Always use `exc_info=True` to capture tracebacks:

```python
try:
    result = client.chat(messages)
except Exception as e:
    logger.error("LLM call failed: %s", e, exc_info=True)
```

### CosyLogger Ring Buffer

Call `install_logger()` once at startup (idempotent):

```python
from engine.logging import install_logger
handler = install_logger(
    logger_name="",           # "" = root logger (captures everything)
    level=logging.DEBUG,
    propagate_root=True,
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
```

Query logs via:

```python
from engine.logging import get_logs, clear_logs

logs = get_logs()                             # Last 200 entries
errors = get_logs(level="ERROR", limit=50)    # Filter by level
new_logs = get_logs(since_id=last_seen_id)    # Long-polling
clear_logs()                                  # Clear buffer
```

Each entry is a dict with fields: `id` (monotonic), `ts` (HH:MM:SS.mmm), `level`, `logger`, `message`.

```
+-------------+    emit()    +------------------+
| Any module   |------------>| _RingHandler      |
| logger.info()|             | deque(maxlen=2000)|
+-------------+             +--------+---------+
                                     | if ERROR+
                                     v
                              +--------------+
                              | ActivityBus   |
                              | "log_error"   |
                              +--------------+
```

### Log Files and Rotation

| Item | Value |
|------|-------|
| Default directory | `./logs/` (`paths.logs_dir` in config) |
| Default file | `./logs/cosysim.log` |
| Max file size | 10 MB (`logging.max_bytes`) |
| Backup count | 5 (`logging.backup_count`) |

When `cosysim.log` reaches 10 MB it rotates, keeping up to 5 backups (`cosysim.log.1` through `.5`). The `logs/` directory is created automatically.

### SystemMonitor

The `SystemMonitor` singleton collects hardware metrics (cached 5 seconds) and pings external services.

```python
from engine.logging import get_system_monitor
monitor = get_system_monitor()

snap = monitor.snapshot()          # CPU%, RAM, GPU VRAM, GPU temp
health = monitor.check_services()  # Per-service up/down + latency
model = monitor.get_loaded_model() # Currently loaded LMStudio model
```

Monitored services:

| Service | Health Endpoint | Default URL |
|---------|-----------------|-------------|
| LMStudio | `/v1/models` | `http://localhost:1234` |
| ComfyUI | `/system_stats` | `http://localhost:8188` |
| TTS | `/status` | `http://localhost:8600` |
| Nexus KMS | `/health` | `http://localhost:8700` |

URLs are read from config (`lmstudio.base_url`, `comfyui.base_url`, etc.) with fallback to the defaults above.

### Benchmarking and KPIs

```python
from engine.logging import timed, get_benchmarks, record_llm_kpi

@timed("llm_generate")
def generate(prompt):
    return client.chat(messages)

record_llm_kpi("llm_generate", latency_ms=350, tokens_in=50, tokens_out=120)
stats = get_benchmarks()
```

See [KPI.md](./KPI.md) for full documentation of the `@timed` decorator, LLM KPI tracking, timeseries export, and the admin dashboard.

### Backward Compatibility

The shim at `content/simulation/services/cosylogger.py` re-exports the public API from `engine.logging.cosy_logger`. All new code should import directly from `engine.logging`.

---

## 7. Scheduler

> **Module:** `engine/nexus/scheduler_daemon.py` | **Tasks:** 61 recurring | **Tests:** `tests/test_scheduler_daemon.py`

The scheduler daemon manages recurring background tasks: Nexus maintenance, news ingestion, pipeline execution, training data collection, and system health monitoring. Tasks are plain Python callbacks registered with schedule strings. Execution state is persisted across restarts.

### Architecture

```
                    +------------------------------+
                    |     TaskSchedulerDaemon       |
                    |   get_scheduler_daemon()      |
                    +--------------+---------------+
                                   |
              +--------------------+--------------------+
              |                    |                    |
    +---------+----+      +--------+------+     +------+------+
    |  60s Tick    |      |  State File   |     | Nexus Log   |
    |  run_due()   |      |  (JSON)       |     | (history)   |
    +--------------+      +---------------+     +-------------+
```

### Task Registration

```python
from engine.nexus.scheduler_daemon import get_scheduler_daemon

daemon = get_scheduler_daemon()
daemon.register(
    task_id="my-task",
    name="My Task Description",
    schedule="every_4h",
    callback=my_callback,       # Zero-arg function -> Dict[str, Any]
    enabled=True,
)
```

### Schedule Strings

| String | Interval |
|--------|----------|
| `"every_5m"` | 5 minutes |
| `"every_15m"` | 15 minutes |
| `"every_1h"` | 1 hour |
| `"every_4h"` | 4 hours |
| `"every_6h"` | 6 hours |
| `"every_8h"` | 8 hours |
| `"every_12h"` | 12 hours |
| `"daily"` | 24 hours |
| `"weekly"` | 7 days |
| `"every_Nh"` / `"every_Nm"` | Arbitrary N hours/minutes |

### Callback Pattern

```python
def my_callback() -> Dict[str, Any]:
    try:
        from engine.nexus.client import get_nexus_client
        client = get_nexus_client()
        result = client.search("important things")
        return {"items_processed": len(result), "status": "ok"}
    except Exception as exc:
        logger.error("Task failed: %s", exc)
        return {"error": str(exc)}
```

### Task Catalog (61 Tasks)

**Nexus Maintenance (12 tasks)**

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `nexus-dedup` | daily | Deduplicate similar knowledge entries |
| `nexus-quality-scan` | daily | Score and flag low-quality entries |
| `nexus-stale-cleanup` | weekly | Archive stale entries |
| `nexus-stats` | every_4h | Collect database statistics |
| `nexus-backup` | daily | Backup Nexus database |
| `qa-quality-check` | daily | Validate Q&A pair quality |
| `qa-expander` | daily | Expand thin Q&A pairs with richer answers |
| `qa-generator` | daily | Generate Q&A from knowledge entries |
| `training-sync` | daily | Sync training data from Nexus |
| `auto-embedding` | every_4h | Batch-embed entries into ChromaDB |
| `doc-sync` | every_6h | Detect repo doc changes, sync to Nexus |
| `copilot-reseed` | daily | Reseed Copilot instruction mirrors |

**Workspace Pipeline (4 tasks)**

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `workspace-news-pipeline` | every_8h | RSS -> NLM -> Sheets -> Nexus |
| `workspace-news-to-knowledge` | daily | News -> NLM -> Docs -> Drive -> Nexus |
| `workspace-research-cycle` | every_12h | Research queued topics from Nexus |
| `workspace-pipeline-health` | every_6h | Client connectivity and stage health |

**News & Intelligence (4 tasks)**

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `news-fetch` | every_8h | RSS fetch, score, store, NLM distillation |
| `news-nlm-retry` | every_8h | Retry failed NLM distillation jobs |
| `news-source-health` | daily | Check RSS feed availability |
| `news-digest-publish` | daily | Publish daily digest to scenes |

**NotebookLM (6 tasks)**

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `notebook-rotation` | weekly | Rotate NLM notebooks by age/size |
| `notebook-health` | daily | Check notebook accessibility |
| `control-notebook-flywheel` | every_4h | Run control notebook follow-up tasks |
| `nlm-distil-queue` | every_8h | Process NLM distillation queue |
| `argus-nlm-distil` | weekly | Upload ARGUS discoveries, batch Q&A |
| `improvement-review` | weekly | NLM review of low-quality responses |

**System Health (8 tasks)**

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `metrics-collect` | every_4h | Collect system metrics |
| `test-monitor` | daily | Run test suite, track regressions |
| `scene-health` | every_6h | Check scene port availability |
| `lmstudio-health` | every_1h | Verify LMStudio server |
| `cookie-health-check` | daily | Check Google account pool freshness |
| `port-conflict-check` | every_4h | Detect port conflicts |
| `log-rotation` | daily | Rotate and compress log files |
| `error-digest` | every_4h | Summarize error patterns |

**Training & Data (6 tasks)**

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `flywheel-collect` | every_4h | Collect training data from sessions |
| `flywheel-quality` | daily | Score training example quality |
| `flywheel-export` | daily | Export training datasets |
| `benchmark-run` | daily | Run model benchmarks |
| `cdp-mine` | daily | Mine CDP logs for training data |
| `colab-pipeline-sync` | daily | NLM -> Drive -> Colab analysis sync |

**ARGUS & Browser (4 tasks)**

| Task ID | Schedule | Description |
|---------|----------|-------------|
| `argus-weekly-scan` | weekly | Full API surface scan |
| `argus-diff-report` | weekly | Compare scans, store deltas |
| `har-watchfolder` | every_4h | Process new HAR captures |
| `cdp-health` | every_4h | Check CDP endpoint availability |

**Other (17 tasks)** -- operator inbox, session logging, Copilot validation, inventory snapshots, etc.

### CLI Usage

```bash
python -m engine.nexus.scheduler_daemon status     # Show all task statuses
python -m engine.nexus.scheduler_daemon run <id>    # Run a task immediately
python -m engine.nexus.scheduler_daemon start       # Start daemon (checks every 60s)
```

### Python API

```python
from engine.nexus.scheduler_daemon import get_scheduler_daemon

daemon = get_scheduler_daemon()
result = daemon.run_task("workspace-news-pipeline")   # Run immediately
task = daemon._tasks.get("news-fetch")                # Inspect task state
task_ids = list(daemon._tasks.keys())                 # List all task IDs
daemon._tasks["my-task"].enabled = False              # Disable a task
```

### State Persistence

Task execution state is persisted to `data/scheduler_state.json`:

```json
{
  "news-fetch": {
    "last_run": 1710456000.0,
    "run_count": 42,
    "error_count": 1,
    "last_result": "{\"fetched\": 30, \"stored\": 25}"
  }
}
```

State survives restarts -- tasks resume from where they left off.

### Adding a New Task

1. Define the callback in `scheduler_daemon.py` (zero-arg, returns dict, lazy imports).
2. Register in `_register_builtin_tasks()`.
3. Add a test asserting the task_id appears in `_register_builtin_tasks`.
4. Update task count in `test_builtin_task_count`.

---

## 8. Admin Panels

CosySim has three operator interfaces for runtime control and diagnostics.

### Admin Panel (Streamlit) -- port 8502

**Launch:** `python launcher.py admin`

A Streamlit-based diagnostic and control center (`admin_panel.py`, ~120 lines) that delegates to 12 page modules in `content/scenes/admin/pages/`.

#### Page Modules

```
admin_panel.py          -> Sidebar navigation, session state init
pages/
+-- dashboard.py        -> System overview + health
+-- logs.py             -> Log viewer + benchmarks
+-- chains.py           -> EventChain browser
+-- config_editor.py    -> Interactive config editing
+-- rag_editor.py       -> RAG message editor
+-- god_mode.py         -> Full override access
+-- character_manager.py-> Character CRUD
+-- scene_manager.py    -> Scene registry
+-- media.py            -> Media gallery
+-- lmstudio.py         -> LMStudio management
+-- backup.py           -> Backup & restore
+-- assets.py           -> Asset browser
```

Each page exports a `render()` function.

#### Key Pages

**Dashboard** -- Service health indicators (LMStudio, ComfyUI, Database, EventChain), system metrics (CPU%, RAM, GPU VRAM), loaded model info, benchmark summary table.

**Logs** -- Three tabs: file logs from disk, ring buffer from CosyLogger, and benchmark timing table. Supports level filter, search, tail, export (JSON/CSV).

**EventChain Browser** -- Browse chains with filters (scene, character, event type, date). Tree view with causal hierarchy. Click to expand full JSON payload.

**Config Editor** -- Organized by YAML section. Type-aware inputs (booleans as toggles, numbers as sliders). Validation with red border on invalid values. Save & Apply writes to YAML and reloads ConfigManager singleton.

**GOD Mode** -- Password-protected (`cosysim`) full override access. Raw SQL, event injection, force state override, DB browser, danger zone (clear all events/tables). Red banner when active; all actions logged as `god_mode_action` events.

#### Session State

Shared via `st.session_state`:

| Key | Type | Purpose |
|-----|------|---------|
| `asset_manager` | AssetManager | Asset CRUD |
| `config` | ConfigManager | Configuration access |
| `god_mode` | bool | GOD mode toggle |

#### Adding a New Page

1. Create `pages/my_page.py` with a `render()` function.
2. Add to `_PAGES` dict in `admin_panel.py`.
3. Import at top of `admin_panel.py`.

### System Dashboard (Streamlit) -- port 8501

**Launch:** `python launcher.py dashboard`

High-level system overview with live metrics. Uses the same `engine.logging` subsystem as the admin panel but with a simplified read-only dashboard view. Shows CPU, RAM, GPU utilization, service health grid, and active scene summary.

### System Control Panel (Flask) -- port 5575

**Launch:** `python launcher.py system_control` (auto-starts with `--core`)

Open: [http://localhost:5575](http://localhost:5575)

The operator's runtime dashboard for CosySim. Nine tabs provide full operational control:

| Tab | Features |
|-----|----------|
| **Overview** | CPU, RAM, GPU utilization (live 30s refresh), uptime, quick links |
| **Services** | Health status for all services (parallel checks, 3s timeout) |
| **Config Editor** | Load/edit/validate/save YAML + JSON config files (`.bak` backups) |
| **Launcher** | Toggle `auto_start` per service/scene, persists to `config/launcher.yaml` |
| **NLM Proxy** | Status, BL age, cookie freshness, HAR import, CDP cookie capture, notebook list |
| **Nexus** | Entry/QA/rules counts, quick search, links to Nexus Panel (:5570) |
| **LMStudio** | Connection status, loaded models, quick model load |
| **Logs** | Log file dropdown, tail last N lines, auto-refresh every 10s |
| **Git** | Current branch, last 10 commits, working tree status |

Editable config files: `config/default.yaml`, `config/production.yaml`, `config/launcher.yaml`, `config/voices.yaml`, `config/skill_manifests.yaml`, `config/mcp.json`, `config/news_sources.yaml`.

#### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Scene health check |
| GET | `/api/metrics` | CPU/RAM/GPU stats |
| GET | `/api/services` | Health of all services |
| GET | `/api/configs` | List editable config files |
| GET | `/api/config/<name>` | Read a config file |
| POST | `/api/config/<name>` | Write a config file (validated) |
| GET | `/api/launcher` | Current auto-start settings |
| POST | `/api/launcher/<name>` | Toggle auto-start flag |
| GET | `/api/nlm/status` | NLM proxy status (proxies to :8800) |
| POST | `/api/nlm/import-har` | Import a HAR file into NLM proxy |
| POST | `/api/nlm/capture-cookies` | Trigger Chrome CDP cookie capture |
| GET | `/api/nlm/notebooks` | List NLM notebooks |
| GET | `/api/nexus/health` | Nexus health summary |
| GET | `/api/nexus/search` | Quick Nexus search (`?q=...`) |
| GET | `/api/lmstudio/status` | LMStudio connection + loaded models |
| GET | `/api/logs` | List available log files |
| GET | `/api/logs/<name>` | Tail a log file (`?lines=100`) |
| GET | `/api/git` | Git branch, commits, and status |

#### Architecture Notes

- All NLM operations proxy to `:8800` (never called directly).
- Config writes are atomic: validated then written; `.bak` backups created before each write.
- Service health checks run in a 10-thread pool.
- Metrics use `psutil` (CPU/RAM) and `pynvml` (GPU); both degrade gracefully if not installed.

---

## 9. Troubleshooting

### Port Already in Use

```powershell
Get-NetTCPConnection -LocalPort 5556 | Select-Object OwningProcess
Stop-Process -Id <PID> -Force
```

The scheduler task `port-conflict-check` (every 4 hours) also detects conflicts automatically. You can run it manually:

```bash
python -m engine.nexus.scheduler_daemon run port-conflict-check
```

### LMStudio Not Responding

1. Verify running: `curl http://localhost:1234/api/v1/models`
2. Ensure a model is loaded in the LMStudio UI
3. Check `config/default.yaml` -> `lmstudio.base_url` and `lmstudio.api_token`
4. LMStudio uses v1 API -- ensure `lmstudio.api_version: "v1"` in config
5. The `lmstudio-health` scheduler task checks every hour automatically

### Nexus KMS Won't Start

Nexus KMS is auto-managed (priority 0). If it fails:

1. Check manually: `cd C:\Files\Nexus && python -m nexus api`
2. Verify port 8700 is free: `Get-NetTCPConnection -LocalPort 8700`
3. Check logs: `python launcher.py --status`

### Unicode Console Errors (Windows)

```powershell
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

### Database Not Found

```bash
python launcher.py --init-db
```

### Scene Not Appearing in Hub

1. Verify the scene is registered in `engine/control_plane_registry.py` (`SCENE_DEFS`)
2. Verify its port is in `engine/port_registry.py` (`_DEFAULT_PORTS`)
3. Verify it has an entry in `config/default.yaml` under `scenes.<name>`
4. Check that it implements `get_plugin_info()` and `register_health_route()`

---

## 10. Cross-References

| Doc | Relevance |
|-----|-----------|
| [Architecture](./ARCHITECTURE.md) | System design, layers, data flow, interceptor pipeline |
| [Configuration](./CONFIGURATION.md) | All config files, `logging` and `news_system` sections |
| [KPI & Benchmarking](./KPI.md) | `@timed` decorator, LLM KPIs, admin dashboard metrics |
| [Nexus](./NEXUS.md) | Knowledge storage, query router, training flywheel |
| [LMStudio](./LMSTUDIO.md) | InferenceOrchestrator, ServerController, LMLink |
| [Testing](./TESTING.md) | Smart test system, fixtures, conventions |
| [Scenes](./SCENES.md) | Scene mechanics, APIs, routes |
| [Contributing](./CONTRIBUTING.md) | Development conventions, scene creation, code standards |
| [Agent Onboarding](./AGENT_ONBOARDING.md) | Copilot/local agent onboarding and session logging |

---

## 11. Change Log

| Version | Date | Description |
|---------|------|-------------|
| v1.50 | 2026-03-22 | Merged DEPLOYMENT.md into OPERATIONS.md; added oracle, creation_kit to port tables; updated pillar counts to 15/11/6 = 32 |
| v1.49 | 2026-03-21 | Added news pipeline, local agent operations, system control panel docs |
| v1.42 | 2026-03-21 | Three-pillar architecture, managed Nexus KMS auto-start |
| v1.41 | 2026-03-20 | ARGUS deep polish, extended rpcids |
| v1.40 | 2026-03-19 | Health check aggregator, service discovery registry |
