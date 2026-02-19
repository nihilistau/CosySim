# 📊 Logging, Benchmarking & Monitoring Guide

## Overview

CosySim has a unified observability stack in `engine/logging/`:

| Module | Purpose |
|--------|---------|
| `cosy_logger.py` | Structured ring-buffer logger |
| `benchmark.py` | `@timed` decorator + BenchmarkStore |
| `monitor.py` | SystemMonitor (CPU/RAM/GPU/services) |

All three are exposed via `engine/__init__.py` and `engine/logging/__init__.py`.

---

## Quick Start

```python
from engine.logging import install_logger, timed, get_system_monitor, get_benchmarks

# 1. Install the logger (call once at startup)
install_logger(level="DEBUG", max_entries=5000)

# 2. Decorate functions to auto-track timing
@timed("llm_completion")
def call_llm(prompt):
    ...

# 3. Read benchmarks
stats = get_benchmarks()
# → {"llm_completion": {"count": 42, "avg_ms": 320, "p95_ms": 510, ...}}

# 4. Read system metrics
monitor = get_system_monitor()
snapshot = monitor.snapshot()
# → {"cpu_percent": 23, "ram_used_mb": 4096, "gpu": {...}, "services": {...}}
```

---

## @timed Decorator

The `@timed("operation_name")` decorator records every call's execution time in milliseconds.

```python
from engine.logging import timed

@timed("comfyui_generate_image")
def generate_image(prompt, width, height):
    ...
```

Timing data is stored in a global `BenchmarkStore` (max 5000 samples per operation).

### Reading Benchmarks

```python
from engine.logging import get_benchmarks, reset_benchmarks

stats = get_benchmarks()
# Returns dict of:
# {
#   "operation": {
#     "count": int,
#     "total_ms": float,
#     "min_ms": float,
#     "max_ms": float,
#     "avg_ms": float,
#     "p95_ms": float,
#   }
# }

reset_benchmarks()  # Clear all stored timings
```

### Where @timed Is Wired

| Operation | File |
|-----------|------|
| `comfyui_generate_image` | `content/simulation/services/comfyui_client.py` |
| `comfyui_generate_selfie` | `content/simulation/services/comfyui_client.py` |
| `character_agent_complete` | `engine/agents/character_agent.py` |
| `character_agent_act` | `engine/agents/character_agent.py` |

---

## SystemMonitor

Singleton that tracks hardware + service health.

```python
from engine.logging import get_system_monitor

monitor = get_system_monitor()
snap = monitor.snapshot()
```

### Snapshot Fields

```json
{
  "cpu_percent": 23.5,
  "ram_used_mb": 4096,
  "ram_total_mb": 16384,
  "ram_percent": 25.0,
  "gpu": {
    "name": "NVIDIA GeForce RTX 2060",
    "vram_used_mb": 3200,
    "vram_total_mb": 12288,
    "vram_percent": 26.0,
    "temperature_c": 55
  },
  "services": {
    "lmstudio": {"up": true, "latency_ms": 45},
    "comfyui": {"up": false, "latency_ms": null}
  }
}
```

GPU metrics use `nvidia-smi` (falls back gracefully if unavailable).

---

## Ring-Buffer Logger

The CosyLogger maintains an in-memory ring buffer of recent log entries (default 5000).

```python
from engine.logging.cosy_logger import get_logs

# Get recent entries (returns list of dicts)
entries = get_logs(limit=100, level="WARNING")
# → [{"timestamp": "...", "level": "WARNING", "message": "..."}]
```

The admin panel's **Logs** page reads from this buffer.

---

## Admin Panel Integration

All observability data feeds into the admin panel:

- **Dashboard** → SystemMonitor snapshot, benchmark summary table
- **Logs** → Ring buffer entries + file logs, level/search filters
- **Chains** → EventChain events (benchmark events can be logged here too)

---

## Resilience Layer

`engine/services/resilience.py` provides retry + circuit breaker:

```python
from engine.services.resilience import retry, CircuitBreaker

@retry(max_attempts=3, delay=1.0, backoff=2.0)
def flaky_call():
    ...

cb = CircuitBreaker("comfyui", failure_threshold=5, recovery_timeout=60)
with cb:
    response = call_comfyui()
```

States: `closed` → `open` (after N failures) → `half_open` (after timeout) → back to `closed` on success.
