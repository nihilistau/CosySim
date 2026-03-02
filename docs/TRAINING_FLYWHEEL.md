# CosySim Training Flywheel

> Self-improving routing pipeline — captures every inference decision, exports training data, and
> retrains the ML router weekly. Added in v0.72b "The Asset Studio".

---

## Overview

Every time CosySim routes an LLM request — choosing between the GPU primary tier, CPU utility tier,
or CPU router tier — that decision is a potential training sample. The Training Flywheel is the
automated pipeline that converts live routing decisions into fine-tuning data, retrains a compact
routing model (Qwen2.5-0.5B), and promotes the best-performing checkpoint back into production.

The compound effect: **more decisions → better training data → better routing → lower latency →
better user experience → more decisions**. The system improves automatically as it is used.

---

## Components

### RouterDataCollector (`engine/lmstudio/router_data.py`)

Captures every routing decision made by `InferenceOrchestrator` and stores it in a local SQLite
database (`data/router_decisions.db`). Each record includes:

| Field | Description |
|-------|-------------|
| `task_type` | Inferred task category (chat, classify, act, …) |
| `priority` | Routing priority (`interactive`, `background`, …) |
| `prompt_tokens` | Token count of the input prompt |
| `has_tools` | Whether the request included tool definitions |
| `has_system_prompt` | Whether a system prompt was present |
| `tier_selected` | Routing decision (`gpu_primary`, `cpu_utility`, `cpu_router`) |
| `model_used` | Actual model identifier that handled the request |
| `latency_ms` | End-to-end request latency |
| `tokens_generated` | Output token count |
| `tokens_per_sec` | Measured throughput |
| `success` | 1 = successful completion, 0 = error |
| `quality_score` | Optional user feedback score (0–5, -1 if not rated) |

```python
from engine.lmstudio.router_data import get_router_data_collector
collector = get_router_data_collector()

# Log a decision (called automatically by InferenceOrchestrator)
collector.log_decision(
    task_type="chat",
    priority="interactive",
    prompt_tokens=512,
    has_tools=False,
    tier_selected="gpu_primary",
    model_used="qwen2.5-7b-instruct",
    latency_ms=340.0,
    tokens_generated=128,
    success=True,
)

# Export training data (called by scheduler task)
count = collector.export_alpaca("training/datasets/router_v3_latest.jsonl")
```

---

### RouterV3Client (`engine/lmstudio/router_v3_client.py`)

Production client for the fine-tuned Qwen2.5-0.5B router model. Replaces the rule-based tier
selector with ML-based prediction. Lazy-loads the model on first call; falls back to rule-based
routing if the model is unavailable or inference fails.

```python
from engine.lmstudio.router_v3_client import get_router_v3_client
client = get_router_v3_client()

# Predict routing tier for a request
tier = client.predict_tier(
    task_type="classify",
    priority="background",
    has_tools=False,
)
# → "cpu_router"
```

**Label → Tier mapping:**

| Model output | Routing tier |
|-------------|-------------|
| `gpu_primary` / `t1` / `gpu` | GPU primary (large model, full context) |
| `cpu_utility` / `t2` / `cpu` | CPU utility (small model, fast) |
| `cpu_router` / `t3` / `router` | CPU router (270M classifier) |

**Rule-based fallback table** (used when model unavailable):

| Task type | Fallback tier |
|-----------|--------------|
| `classify`, `route`, `validate`, `tag_extract` | `cpu_router` |
| `act`, `chat`, `narrative` | `gpu_primary` |

---

### Model Registry (`training/model_registry.json`)

Tracks all fine-tuned router models — registered, benchmarked, and promoted checkpoints. Each entry
records the base model, adapter path, merged path, benchmark score, and promotion timestamp.

```json
{
  "models": [
    {
      "model_id": "817cdafd",
      "model_type": "router_v3",
      "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
      "adapter_path": "training/models/router_v3_6dade8aa/adapter",
      "active": false,
      "benchmark_score": null
    }
  ],
  "active_model_id": null
}
```

Only one model is active at a time (`"active": true`). `RouterV3Client` loads the active model at
startup. Promoting a checkpoint sets it as active and restarts the client.

---

## Scheduler Tasks

Two tasks in `SchedulerDaemon` drive the flywheel automatically:

| Task ID | Interval | Action |
|---------|----------|--------|
| `router-data-export` | Every 4 hours | Export new decisions to Alpaca JSONL |
| `router-v3-retrain` | Weekly | Fine-tune on latest dataset, register result |

```yaml
# config/default.yaml — scheduler section
scheduler:
  tasks:
    router-data-export:
      interval: every_4h
      enabled: true
    router-v3-retrain:
      interval: weekly
      enabled: true
```

Both tasks appear in the admin overlay **[SCHEDULER]** tab with last-run time and row counts.

---

## Training Data Format

Exported data uses the **Alpaca instruction format** — the standard expected by the fine-tuning
pipeline and compatible with Unsloth / TRL:

```
### Instruction
Route the following LLM request to the correct inference tier.

### Input
task_type: chat
priority: interactive
prompt_tokens: 512
has_tools: false
has_system_prompt: true

### Response
gpu_primary
```

Each export run appends only new records (since last export timestamp) to avoid duplicate samples.
The dataset path is `training/datasets/router_v3_<timestamp>.jsonl`.

---

## Triggering a Manual Retrain

```bash
# From the CosySim root:
python -m training.router_v3_trainer \
    --dataset training/datasets/router_v3_latest.jsonl \
    --output training/models/router_v3_manual \
    --epochs 3

# Register and promote the result:
python -m training.model_registry promote \
    --adapter training/models/router_v3_manual/adapter \
    --benchmark 0.91
```

Or via the System Control Panel (port 5575) → **Training** tab → "Trigger Router Retrain".

---

## The Compound Effect

```
Session 1:  1,000 routing decisions logged
  └─ Export: 1,000 training samples
     └─ Retrain: model accuracy 78%

Session 10: 50,000 routing decisions logged
  └─ Export: 50,000 training samples
     └─ Retrain: model accuracy 91%
        └─ Better routing → lower GPU tier usage
           └─ Faster responses → more interactions
              └─ More training data → cycle repeats
```

The key insight: rule-based routing is static. ML routing improves with every decision the system
makes. After ~10,000 decisions, RouterV3 typically outperforms hand-tuned rules on tail cases
(multi-tool requests, mixed-priority batches, long-context edge cases).

---

## Config Keys

| Key | Default | Description |
|-----|---------|-------------|
| `lmstudio.router_v3.enabled` | `true` | Use ML routing (false = rule-based only) |
| `lmstudio.router_v3.confidence_threshold` | `0.7` | Min confidence to use ML prediction |
| `training.export_path` | `training/datasets/` | Output directory for JSONL exports |
| `training.router_db_path` | `data/router_decisions.db` | SQLite database path |
