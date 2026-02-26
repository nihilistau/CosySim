# CosySim Logging & Monitoring Guide

> Centralised logging, benchmarking, and system monitoring for the CosySim engine.

---

## Architecture

```
engine/logging/
├── __init__.py          Public API — re-exports everything below
├── cosy_logger.py       CosyLogger: ring-buffer handler + install_logger()
├── benchmark.py         @timed decorator, LLM KPI tracking, timeseries
└── monitor.py           SystemMonitor: CPU/RAM/GPU metrics, service health
```

CosySim uses Python's standard `logging` module everywhere. On top of that it adds
three subsystems:

| Subsystem | Module | Purpose |
|-----------|--------|---------|
| **CosyLogger** | `cosy_logger.py` | In-memory ring buffer for live log streaming |
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

---

## Configuration

Logging is configured in `config/default.yaml` under the `logging` key:

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

---

## Using Logging in Modules

Every module follows the same pattern — **one logger per module, never `print()`**:

```python
import logging

logger = logging.getLogger(__name__)
```

Then use the logger throughout the module:

```python
logger.debug("Loading model %s with context %d", model_key, ctx_len)
logger.info("Scene '%s' started on port %d", scene_id, port)
logger.warning("ChromaDB not available, falling back to in-memory store")
logger.error("LMStudio connection failed: %s", str(e))
```

> **Convention:** Use `logger = logging.getLogger(__name__)` — this gives each
> module a hierarchical logger name like `engine.agents.character_agent`,
> making it easy to filter logs by subsystem.

### What NOT to do

```python
# ❌ Don't use print for operational output
print("Starting server...")

# ❌ Don't create named loggers manually
logger = logging.getLogger("my_custom_name")

# ❌ Don't use basicConfig in library modules (only in standalone scripts)
logging.basicConfig(level=logging.INFO)
```

`logging.basicConfig()` is acceptable only in standalone scripts under `training/`
or in `if __name__ == "__main__":` blocks of scene files.

---

## Log Levels

| Level | When to Use | Examples |
|-------|-------------|---------|
| `DEBUG` | Detailed diagnostic info, high-volume | Token counts, cache hits, state transitions |
| `INFO` | Significant operational events | Scene started, model loaded, skill registered |
| `WARNING` | Unexpected but recoverable situations | Missing optional dependency, falling back to default |
| `ERROR` | Operation failed, needs attention | LMStudio unreachable, database write failed |
| `CRITICAL` | System-level failure (rarely used) | Cannot start engine, data corruption |

### ERROR and ActivityBus

Errors and critical messages are automatically forwarded to the **ActivityBus**
by the CosyLogger ring-buffer handler. This makes them visible in the admin panel
activity feed without any extra code:

```python
# This automatically publishes to ActivityBus as a "log_error" activity
logger.error("LMStudio connection timeout after %dms", timeout_ms)
```

### Suppressed Exceptions

Throughout the codebase, best-effort operations use this pattern:

```python
try:
    from engine.services.activity_bus import get_activity_bus
    get_activity_bus().publish(...)
except Exception:
    logger.debug("Suppressed exception", exc_info=True)
```

This logs the full traceback at `DEBUG` level without crashing the caller.

---

## CosyLogger — Ring Buffer

CosyLogger captures log records into a thread-safe, in-memory ring buffer
(max 2,000 entries). This powers the admin panel's live log terminal.

### Installation

Call `install_logger()` once at startup. It's idempotent — safe to call
multiple times:

```python
from engine.logging import install_logger

handler = install_logger(
    logger_name="",           # "" = root logger (captures everything)
    level=logging.DEBUG,      # capture all levels
    propagate_root=True,      # also attach to root for 3rd-party libs
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
```

The handler is a singleton — subsequent calls return the same instance.

### Querying Logs

```python
from engine.logging import get_logs, clear_logs

# Get last 200 entries at any level
logs = get_logs()

# Filter by level and limit
errors = get_logs(level="ERROR", limit=50)

# Poll for new entries (long-polling pattern)
new_logs = get_logs(since_id=last_seen_id)

# Clear the buffer
clear_logs()
```

Each log entry is a dict:

```python
{
    "id": 42,                              # monotonic sequence number
    "ts": "14:32:05.123",                  # HH:MM:SS.mmm
    "level": "INFO",                       # DEBUG/INFO/WARNING/ERROR
    "logger": "engine.agents.agent_loop",  # module name
    "message": "AgentLoop tick completed", # formatted message
}
```

### How It Works

```
┌─────────────┐    emit()    ┌──────────────────┐
│ Any module   │────────────►│ _RingHandler      │
│ logger.info()│             │ deque(maxlen=2000)│
└─────────────┘             └────────┬─────────┘
                                     │ if ERROR+
                                     ▼
                              ┌──────────────┐
                              │ ActivityBus   │
                              │ "log_error"   │
                              └──────────────┘
```

---

## System Monitor

The `SystemMonitor` singleton collects hardware metrics and pings external services.

### Hardware Snapshot

```python
from engine.logging import get_system_monitor

monitor = get_system_monitor()
snap = monitor.snapshot()
# {
#   "cpu_percent": 35.0,
#   "ram_total_gb": 32.0,
#   "ram_used_gb": 18.5,
#   "ram_percent": 57.8,
#   "ram": {"used_gb": 18.5, "total_gb": 32.0, "percent": 57.8},
#   "gpu_vram_used_mb": 8500,
#   "gpu_vram_total_mb": 12288,
#   "gpu_name": "NVIDIA GeForce RTX 2060",
#   "gpu_temp_c": 65,
#   "gpu": {"available": true, "vram_used_mb": 8500, ...}
# }
```

Snapshots are cached for **5 seconds** to avoid hammering `nvidia-smi` and `psutil`.

### Service Health Checks

```python
health = monitor.check_services()
# {
#   "lmstudio": {"up": true, "status_code": 200, "latency_ms": 12.3, "error": null},
#   "comfyui":  {"up": false, "latency_ms": null, "error": "Connection refused"},
#   "tts":      {"up": true, "status_code": 200, "latency_ms": 45.0, "error": null},
#   "mcp":      {"up": true, "status_code": 200, "latency_ms": 5.2, "error": null},
# }
```

Monitored services:

| Service | Health Endpoint | Default URL |
|---------|-----------------|-------------|
| LMStudio | `/v1/models` | `http://localhost:1234` |
| ComfyUI | `/system_stats` | `http://localhost:8188` |
| TTS | `/status` | `http://localhost:8600` |
| MCP (CosySim) | `/health` | `http://localhost:8700` |

URLs are read from config (`lmstudio.base_url`, `comfyui.base_url`, etc.)
with fallback to the defaults above.

### Loaded Model Query

```python
model_name = monitor.get_loaded_model()
# "qwen3-8b-instruct" or None
```

Asks LMStudio's `/v1/models` endpoint which model is currently loaded.

---

## Log File Location and Rotation

| Item | Value |
|------|-------|
| Default directory | `./logs/` (`paths.logs_dir` in config) |
| Default file | `./logs/cosysim.log` |
| Max file size | 10 MB (`logging.max_bytes`) |
| Backup count | 5 (`logging.backup_count`) |

When `cosysim.log` reaches 10 MB the system rotates it, keeping up to 5 backups
(`cosysim.log.1` through `cosysim.log.5`). The `logs/` directory is created
automatically if it doesn't exist.

### Admin Panel Log Viewer

The admin panel (`content/scenes/admin/pages/logs.py`) provides three tabs:

| Tab | Source | Features |
|-----|--------|----------|
| 📋 File Logs | `logs/*.log` on disk | Level filter, search, tail, export |
| 🔄 Ring Buffer | CosyLogger in-memory buffer | Level filter, clear, live view |
| ⏱️ Benchmarks | `@timed` decorator data | Operation table, reset, JSON export |

---

## Structured Logging Patterns

CosySim uses several structured patterns throughout the codebase.

### Key-Value Context in Messages

```python
logger.info("Model loaded: key=%s ctx=%d gpu=%.1f", model_key, ctx_len, gpu_frac)
logger.warning("Queue depth exceeded threshold: depth=%d max=%d", depth, max_depth)
```

### Structured Dict Entries (Ring Buffer)

The CosyLogger ring buffer stores entries as dicts with consistent fields
(`id`, `ts`, `level`, `logger`, `message`), making them easy to filter,
serialize, and stream to frontends.

### ActivityBus Integration

All `ERROR`+ log records are automatically published to the ActivityBus as
structured events:

```python
{
    "activity_type": "log_error",
    "description": "[ERROR] engine.lmstudio.client: Connection timeout",
    "agent_id": "engine.lmstudio.client",  # logger name
    "scene": "system",
    "data": {"level": "ERROR", "logger": "engine.lmstudio.client"},
}
```

### Exception Logging

Always use `exc_info=True` to capture tracebacks:

```python
try:
    result = client.chat(messages)
except Exception as e:
    logger.error("LLM call failed: %s", e, exc_info=True)
```

For non-critical failures, log at `DEBUG` to keep noise low:

```python
except Exception:
    logger.debug("Suppressed exception", exc_info=True)
```

---

## Benchmarking and KPIs

The benchmarking system is documented separately in [KPI.md](./KPI.md).
Key entry points:

```python
from engine.logging import timed, get_benchmarks, record_llm_kpi

@timed("llm_generate")
def generate(prompt):
    return client.chat(messages)

record_llm_kpi("llm_generate", latency_ms=350, tokens_in=50, tokens_out=120)
stats = get_benchmarks()
```

See [KPI & Benchmarking Guide](./KPI.md) for full documentation of the `@timed`
decorator, LLM KPI tracking, timeseries export, and the admin dashboard.

---

## Quick Reference

### Common Imports

```python
# Per-module logging (every module)
import logging
logger = logging.getLogger(__name__)

# CosyLogger setup (startup only)
from engine.logging import install_logger
install_logger()

# Query logs (admin/API)
from engine.logging import get_logs, clear_logs

# System monitoring
from engine.logging import get_system_monitor
monitor = get_system_monitor()

# Benchmarking (see KPI.md)
from engine.logging import timed, get_benchmarks
```

### Backward Compatibility

The shim at `content/simulation/services/cosylogger.py` re-exports the public
API from `engine.logging.cosy_logger`. All new code should import directly from
`engine.logging`.

---

## See Also

- [Configuration](./CONFIGURATION.md) — `logging` section in `default.yaml`
- [KPI & Benchmarking](./KPI.md) — `@timed`, LLM KPIs, admin dashboard
- [Architecture](./ARCHITECTURE.md) — `engine/logging/` in the system diagram
- [Admin Guide](./ADMIN_GUIDE.md) — Log viewer and KPI dashboard panels
