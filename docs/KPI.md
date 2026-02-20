# KPI & Benchmarking Guide

CosySim includes a comprehensive benchmarking and KPI system for understanding LLM/agent performance.

## @timed Decorator

Every external call should be wrapped with `@timed`:

```python
from engine.logging import timed

@timed("llm_generate")
def generate(prompt):
    return client.chat(messages)

@timed("comfyui_render")
def render_image(prompt, width, height):
    return comfyui.generate(prompt, width, height)

@timed  # Uses function name as operation
def my_function():
    pass
```

The decorator records execution time in milliseconds with microsecond precision.

## Basic Benchmarks

```python
from engine.logging import get_benchmarks, get_operation_timings

# Summary stats for all operations
stats = get_benchmarks()
# {
#   "llm_generate": {
#     "count": 42,
#     "total_ms": 12300.5,
#     "min_ms": 80.2,
#     "max_ms": 1500.0,
#     "avg_ms": 292.9,
#     "p95_ms": 890.0
#   }
# }

# Raw timing samples
timings = get_operation_timings("llm_generate")  # [120.5, 350.2, ...]
```

## LLM KPIs

For detailed LLM performance tracking:

```python
from engine.logging import record_llm_kpi, get_llm_kpis, get_kpi_timeseries

# Record after each LLM call
record_llm_kpi(
    "llm_chat",
    latency_ms=350.0,
    tokens_in=50,
    tokens_out=120,
    first_token_ms=45.0,  # Time to first token
    model="qwen-7b",
)

# Get aggregated KPIs
kpis = get_llm_kpis("llm_chat")
# {
#   "count": 100,
#   "total_tokens_in": 5000,
#   "total_tokens_out": 12000,
#   "avg_tokens_in": 50.0,
#   "avg_tokens_out": 120.0,
#   "avg_latency_ms": 350.0,
#   "p95_latency_ms": 890.0,
#   "avg_tokens_per_sec": 42.5,
#   "p95_tokens_per_sec": 55.0,
#   "avg_first_token_ms": 45.0,
#   "models": ["qwen-7b"]
# }

# All operations combined
all_kpis = get_llm_kpis()

# Timeseries for charting
timeseries = get_kpi_timeseries("llm_chat", last_n=100)
# [{"latency_ms": 350, "tokens_per_sec": 42.5, "timestamp": 1234567890}, ...]
```

## KPI Dashboard (Admin Panel)

The admin panel includes a 4-tab KPI dashboard at **📈 KPI Dashboard**:

### Operations Tab
- Summary: total calls, total time, tracked operations
- Per-operation breakdown: count, avg, min, max, p95, total
- Mini line charts of recent timing samples

### LLM KPIs Tab
- Token throughput: avg tokens/sec, total tokens in/out
- Latency: avg, p95, time-to-first-token
- Models used across calls
- Live charts: tokens/sec and latency over time

### System Tab
- CPU, RAM, GPU utilization
- VRAM usage with progress bar
- GPU temperature
- Service health (LMStudio, ComfyUI)

### Chain Analytics Tab
- Recent chain count and lengths
- Event type distribution (user_message, llm_response, tool_call, etc.)
- Chain length statistics with bar chart

## Where @timed is Used

| Operation | Module | Description |
|-----------|--------|-------------|
| `lmstudio_chat` | client_v2.py | REST API chat completion |
| `llm.complete` | character_agent.py | SDK text completion |
| `llm.act` | character_agent.py | SDK agentic loop |
| `llm.rest_mcp` | character_agent.py | REST + MCP completion |

## Data Retention

- Timing samples: 5000 per operation (auto-prunes to 2500)
- LLM KPI samples: 2000 per operation (auto-prunes to 1000)
- All data is in-memory only — resets on restart
- For persistent history, events are logged to EventChain

## System Monitor

```python
from engine.logging import get_system_monitor

monitor = get_system_monitor()

# Hardware snapshot
snap = monitor.snapshot()
# {
#   "cpu_percent": 35.0,
#   "ram_total_gb": 32.0,
#   "ram_used_gb": 18.5,
#   "ram_percent": 57.8,
#   "gpu_vram_used_mb": 8500,
#   "gpu_vram_total_mb": 12288,
#   "gpu_name": "NVIDIA GeForce RTX 2060",
#   "gpu_temp_c": 65
# }

# Service health
services = monitor.check_services()
# {"lmstudio": {"up": true, "latency_ms": 12}, "comfyui": {"up": false}}
```

## Reset

```python
from engine.logging import reset_benchmarks

reset_benchmarks("llm_chat")  # Reset one operation
reset_benchmarks()             # Reset everything
```
