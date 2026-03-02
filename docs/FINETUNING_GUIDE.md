# CosySim Fine-Tuning Guide

> End-to-end guide for training micro-models on CosySim data. v0.69b.
> Covers: dataset generation → MicroDatasetManager → FinetuneOrchestrator →
> ModelRegistry → BenchmarkRunner → auto-promote → InferenceRouter.

---

## Overview

CosySim trains a fleet of **micro-models** — small, fast, task-specific models that
run alongside the main LLM to handle classification, routing, and quality-evaluation
tasks at low latency. The full pipeline is automated via the `SchedulerDaemon` but
can also be run manually.

### Micro-Model Fleet

| Model Type | Task | Recommended Base | Dataset |
|------------|------|-----------------|---------|
| `qa_evaluator` | Score Q&A pair quality (0–1) | Qwen2.5-0.5B-Instruct | `qa_evaluator_train.jsonl` |
| `conversation_analyzer` | Classify conversation quality | Qwen2.5-0.5B-Instruct | `conversation_analyzer_train.jsonl` |
| `syntax_fixer` | Fix malformed JSON/YAML/code | Qwen2.5-1.5B-Instruct | `syntax_fixer_train.jsonl` |
| `router_v2` | 8-class intent classification | Qwen2.5-0.5B-Instruct | `router_v2_train.jsonl` |
| `router_v3` | 16-class intent classification | Qwen2.5-0.5B-Instruct | `router_v3_train.jsonl` |
| `knowledge_synthesizer` | Synthesise knowledge from context | Qwen2.5-1.5B-Instruct | `knowledge_synthesizer_train.jsonl` |

### Base Model Aliases

| Alias | HuggingFace ID |
|-------|---------------|
| `qwen-270m` | `Qwen/Qwen2.5-0.5B-Instruct` |
| `qwen-1.7b` | `Qwen/Qwen2.5-1.5B-Instruct` |
| `llama-3b` | `meta-llama/Llama-3.2-3B-Instruct` |
| `qwen-7b` | `Qwen/Qwen2.5-7B-Instruct` |

---

## Pipeline Architecture

```
training/datasets/           training/                    engine/lmstudio/
┌─────────────────┐         ┌──────────────────────┐     ┌────────────────────┐
│ router_v3.jsonl │         │  FinetuneOrchestrator │     │  InferenceRouter   │
│ router_v2.jsonl │──────►  │  (Unsloth QLoRA)      │──►  │  (3-tier routing)  │
│ qa_eval*.jsonl  │         │                        │     │                    │
│ syntax_*.jsonl  │         │  LoRA Adapter          │     │  T1: game_master   │
│ etc.            │         │       │                │     │  T2: small         │
└─────────────────┘         │       ▼                │     │  T3: classify/route│
        ▲                   │  Merge to 16-bit       │     └────────────────────┘
        │                   └──────────────────────┘              ▲
┌───────────────────┐              │                              │
│ MicroDatasetManager│             ▼                    ┌─────────────────────┐
│ (NLM teacher gen) │    ┌──────────────────────┐      │  ModelRegistry       │
└───────────────────┘    │  BenchmarkRunner      │─────►│  (promotion logic)  │
                         │  (accuracy/F1/exact)  │      └─────────────────────┘
                         └──────────────────────┘
```

---

## Step 1: Dataset Generation

### Synthetic Seed Datasets

The `MicroDatasetManager` uses the **TeacherPipeline** (Gemini 3.0 via NLM) to generate
training examples at scale.

```python
from training.micro_datasets import MicroDatasetManager

mgr = MicroDatasetManager()

# Build a single dataset
result = mgr.build("qa_evaluator", count=1000)
print(result)  # {"model_type": "qa_evaluator", "count": 1000, "path": "training/datasets/qa_evaluator_train.jsonl"}

# Build all datasets
results = mgr.build_all(count_per_model=500)
```

**Supported model types:** `qa_evaluator`, `conversation_analyzer`, `syntax_fixer`,
`router_v2`, `router_v3`, `knowledge_synthesizer`

### Live Data Collection

`RouterDataCollector` captures real inference traffic for use as training data:

```python
from training.data_manager import get_data_manager

mgr = get_data_manager()
mgr.seed_datasets()          # generate synthetic seed data
mgr.prepare_for_training()   # combine live + synthetic, deduplicate
status = mgr.get_pipeline_status()
```

---

## Step 2: Router v3 Dataset — 16-Class Taxonomy

The router v3 dataset is the most comprehensive intent classifier. As of v0.69b:

- **Total examples**: 2,080
- **Train split**: 1,872 (90%)
- **Validation split**: 208 (10%)
- **Test split**: 100 (held-out)
- **Files**: `training/datasets/router_v3_{train,val,test}.jsonl`

### 16 Classes

| Class | Description |
|-------|-------------|
| `small_talk` | Casual conversation, greetings |
| `game_action` | Combat, items, crafting, skills |
| `story_narrative` | Story progression, lore, quest dialogue |
| `character_emotion` | Character feelings, reactions, relationships |
| `world_query` | Questions about world, lore, factions |
| `skill_call` | Direct tool/skill invocation by agent |
| `memory_recall` | Remembering past events or conversations |
| `scene_transition` | Moving between scenes or locations |
| `system_command` | Admin/system commands, config queries |
| `creative_generation` | Writing, poetry, descriptions, art direction |
| `information_lookup` | Factual queries, knowledge search |
| `emotional_support` | Empathy, comfort, mental health conversations |
| `adult_content` | Mature themes — violence, romance, dark themes |
| `combat_narrative` | Combat narration, battle descriptions |
| `economic_action` | Trading, buying, selling, economy actions |
| `investigation` | Clues, mysteries, detective work |

### Dataset Format (JSONL)

Each line is a JSON object:

```json
{"input": "Attack the guard with my sword.", "output": "game_action"}
{"input": "How does she feel about what I did?", "output": "character_emotion"}
{"input": "Buy the stolen data chip.", "output": "economic_action"}
```

### Regenerating the Dataset

```bash
cd C:\Files\Models\CosySim
python training/datasets/generate_router_v3.py
```

The generator produces balanced examples across all 16 classes using template expansion
and random variation. Output is automatically split 90/10 train/val.

---

## Step 3: FinetuneOrchestrator

`FinetuneOrchestrator` manages the QLoRA training job queue, progress tracking,
checkpoint management, and auto-merge of LoRA adapters on completion.

### Submitting a Job

```python
from training.finetune_orchestrator import get_finetune_orchestrator

orch = get_finetune_orchestrator()

# Submit a new job
job = orch.submit(
    "router_v3",
    base_model="qwen-270m",   # alias or full HuggingFace ID
    config={
        "num_epochs": 3,
        "learning_rate": 2e-4,
        "batch_size": 4,
        "max_seq_length": 512,
        "lora_rank": 16,
        "lora_alpha": 32,
    }
)
print(job.job_id)   # "job-abc123"

# Run the next pending job
orch.run_next()

# Check status
status = orch.get_job(job.job_id)
print(status.status)    # "running" | "done" | "failed"
print(status.progress)  # 0.0 → 1.0
print(status.loss)      # current training loss
```

### FinetuneJob Lifecycle

```
PENDING → RUNNING → DONE
                 ↓
            adapter saved to training/models/{job_id}/adapter/
                 ↓
            auto-merge: 16-bit model at training/models/{job_id}/merged/
                 ↓
            ModelRegistry.register() called automatically
```

### QLoRA Configuration

Default recommended settings per model type:

| Parameter | qwen-270m | qwen-1.7b |
|-----------|-----------|-----------|
| `lora_rank` | 16 | 8 |
| `lora_alpha` | 32 | 16 |
| `num_epochs` | 3 | 2 |
| `learning_rate` | 2e-4 | 1e-4 |
| `batch_size` | 4 | 2 |
| `max_seq_length` | 512 | 512 |

### Running in Google Colab

For GPU training, use the provided notebook:

```
training/gemma_router_finetune.ipynb
```

1. Upload the JSONL dataset to Google Drive via `upload_to_drive.py`
2. Open the notebook in Colab (T4 or better)
3. Run all cells — the notebook uses Unsloth for 4-bit QLoRA
4. Download the adapter `.zip` and place in `training/models/`
5. Run `merge_adapters.py` to produce the merged 16-bit model

---

## Step 4: ModelRegistry

`ModelRegistry` tracks all registered fine-tuned models, their benchmark scores, and
which model is currently active for each type.

```python
from training.model_registry import get_model_registry

registry = get_model_registry()

# Register a new model
model = registry.register(
    model_type="router_v3",
    adapter_path="training/models/router_v3_abc123/adapter",
    base_model="Qwen/Qwen2.5-0.5B-Instruct",
    merged_path="training/models/router_v3_abc123/merged",
    job_id="job-abc123",
    notes="First v3 run, 3 epochs",
)

# Promote to active (makes it the routing target)
registry.promote("router_v3", model.model_id)

# Get the currently active model
active = registry.get_active("router_v3")
print(active.adapter_path)
print(active.benchmark_score)  # set by BenchmarkRunner

# List all registered models for a type
all_models = registry.list("router_v3")
```

### Registry Storage

The registry is persisted as JSON at `training/model_registry.json`:

```json
{
  "router_v3_abc123": {
    "model_id": "router_v3_abc123",
    "model_type": "router_v3",
    "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
    "adapter_path": "training/models/...",
    "merged_path": "training/models/...",
    "benchmark_score": 0.923,
    "active": true,
    "promoted_at": "2026-03-01T10:00:00Z"
  }
}
```

---

## Step 5: BenchmarkRunner

`BenchmarkRunner` evaluates fine-tuned models against their held-out test splits,
computes accuracy/F1/exact-match, and optionally auto-promotes if the score beats
the current active model.

```python
from training.benchmark_runner import get_benchmark_runner

runner = get_benchmark_runner()

# Benchmark the active model for a type
result = runner.run("router_v3", auto_promote=True)
print(result.summary())
# → "router_v3/abc123: acc=0.923 f1=0.918 exact=0.910 score=0.917 latency=12ms"

# Run all micro-model benchmarks
results = runner.run_all()
```

### BenchmarkResult Fields

```python
@dataclass
class BenchmarkResult:
    model_id: str
    model_type: str
    accuracy: float          # correct / total
    f1: float                # macro F1 across all classes
    exact_match: float       # exact string match rate
    total_examples: int
    correct: int
    latency_ms_avg: float    # average inference latency
    aggregate_score: float   # 0.5×accuracy + 0.3×f1 + 0.2×exact_match
    promoted: bool           # True if auto-promoted in this run
```

### Auto-Promote Logic

If `auto_promote=True` and `result.aggregate_score > current_active.benchmark_score`,
the new model is automatically promoted:

```python
if result.aggregate_score > current_best:
    registry.promote(model_type, model_id)
    result.promoted = True
```

Results are stored in `training/benchmarks.jsonl` and in Nexus for historical tracking.

---

## Step 6: InferenceRouter

Once a model is promoted, `InferenceRouter` (in `engine/lmstudio/router.py`) routes
inference requests to the correct model using a **3-tier priority queue**:

```
Request arrives
     │
     ▼
Tier 1 (T1): role=="game_master"  → large model (primary LLM)
     │
     ▼
Tier 2 (T2): task_type=="small"   → small model
     │
     ▼
Tier 3 (T3): task_type=="classify" or "route"  → micro-model (fine-tuned)
```

### FinetunedRouter Integration

`FinetunedRouter` (`engine/lmstudio/finetuned_router.py`) wraps the active fine-tuned
models and is called by `InferenceRouter` for T3 requests:

```python
from engine.lmstudio.finetuned_router import get_finetuned_router

router = get_finetuned_router()

# Classify an intent
label = router.classify("Attack the guard", model_type="router_v3")
print(label)  # "game_action"

# Route a request to the appropriate model
result = router.route(request_context)
```

---

## Scheduler Automation

The `SchedulerDaemon` automates the full pipeline via 6 training-related builtin tasks:

| Task ID | Name | Schedule | Action |
|---------|------|----------|--------|
| `teacher-dataset-gen` | NLM Teacher Dataset Generation | Weekly | Runs `MicroDatasetManager.build_all(count_per_model=500)` |
| `finetune-if-ready` | Auto Fine-tune When Dataset ≥ 500 examples | Weekly | Submits finetune job if new data available |
| `model-benchmark` | Daily Micro-Model Benchmarks | Daily | Runs `BenchmarkRunner.run_all()` |
| `router-finetune-cycle` | Router v2 Full Finetune Cycle | Weekly | Full dataset→train→benchmark→promote cycle |
| `dataset-augment` | Dataset Augmentation | Weekly | Re-augments all datasets with new session data |
| `conversation-analyze` | Post-Session Conversation Analysis | Daily | Generates training candidates from recent sessions |

To trigger a task manually:

```python
from engine.nexus.scheduler_daemon import get_scheduler_daemon

daemon = get_scheduler_daemon()
daemon.run_task("teacher-dataset-gen")
daemon.run_task("finetune-if-ready")
daemon.run_task("model-benchmark")
```

Or via MCP tool:

```
scheduler_run_now("teacher-dataset-gen")
```

---

## Full Pipeline Walkthrough

### Manual end-to-end run

```python
# 1. Generate/refresh dataset
from training.micro_datasets import MicroDatasetManager
mgr = MicroDatasetManager()
mgr.build("router_v3", count=2000)

# 2. Prepare combined dataset
from training.data_manager import get_data_manager
dm = get_data_manager()
dm.prepare_for_training()
print(dm.get_pipeline_status())

# 3. Submit fine-tune job
from training.finetune_orchestrator import get_finetune_orchestrator
orch = get_finetune_orchestrator()
job = orch.submit("router_v3", base_model="qwen-270m")
orch.run_next()  # blocks until done (use Colab for GPU)

# 4. Register and benchmark
from training.model_registry import get_model_registry
from training.benchmark_runner import get_benchmark_runner
registry = get_model_registry()
runner = get_benchmark_runner()

result = runner.run("router_v3", auto_promote=True)
print(result.summary())

# 5. Verify InferenceRouter uses new model
from engine.lmstudio.finetuned_router import get_finetuned_router
router = get_finetuned_router()
print(router.classify("Buy the stolen data chip", model_type="router_v3"))
# → "economic_action"
```

### Automated overnight run

```bash
# Start the scheduler daemon
python -m engine.nexus.scheduler_daemon start

# Check status
python -m engine.nexus.scheduler_daemon status

# Force-run a specific task
python -m engine.nexus.scheduler_daemon run teacher-dataset-gen
```

---

## Dataset Directory Reference

```
training/
├── datasets/
│   ├── router_v3.jsonl               # 2,080 examples (full)
│   ├── router_v3_train.jsonl         # 1,872 examples (90%)
│   ├── router_v3_val.jsonl           # 208 examples (10%)
│   ├── router_v3_test.jsonl          # 100 examples (held-out)
│   ├── router_v2_train.jsonl         # 364 examples, 8-class
│   ├── qa_evaluator_train.jsonl      # QA quality scoring
│   ├── conversation_analyzer_train.jsonl
│   ├── syntax_fixer_train.jsonl
│   ├── knowledge_synthesizer_train.jsonl
│   ├── tag_extraction_train.jsonl
│   ├── tool_routing_train.jsonl
│   ├── priority_classify_train.jsonl
│   ├── decision_classify_train.jsonl
│   ├── response_validate_train.jsonl
│   └── combined_multitask_train.jsonl  # merged multi-task dataset
├── models/                            # fine-tuned adapter outputs
├── model_registry.json                # active model registry
├── jobs.jsonl                         # fine-tune job history
├── benchmarks.jsonl                   # benchmark result history
├── finetune_orchestrator.py
├── model_registry.py
├── benchmark_runner.py
├── micro_datasets.py
├── data_manager.py
├── deploy_router.py
└── gemma_router_finetune.ipynb       # Colab training notebook
```

---

## Troubleshooting

### Dataset too small

```python
# Check current dataset sizes
from training.data_manager import get_data_manager
mgr = get_data_manager()
status = mgr.get_pipeline_status()
print(status.synthetic_counts)  # {"router_v3": 2080, "qa_evaluator": 450, ...}
```

If a dataset has < 200 examples, run `mgr.seed_datasets()` to regenerate.

### Fine-tune job stuck

```python
from training.finetune_orchestrator import get_finetune_orchestrator
orch = get_finetune_orchestrator()
# List all jobs
for job in orch.list_jobs():
    print(job.job_id, job.status, job.error)
# Cancel a stuck job
orch.cancel(job_id)
```

### Model not routing to fine-tuned model

Verify the model is active in the registry:

```python
from training.model_registry import get_model_registry
registry = get_model_registry()
active = registry.get_active("router_v3")
if active is None:
    print("No active model — run BenchmarkRunner.run() first")
else:
    print(f"Active: {active.model_id} score={active.benchmark_score}")
```

### Running benchmarks without GPU

`BenchmarkRunner` can use LMStudio for inference (`use_lmstudio=True`, the default)
or fall back to a rule-based baseline for initial validation. Set `use_lmstudio=False`
to run the rule-based baseline offline.

---

*See [TRAINING.md](./TRAINING.md) for the Gemma/Qwen Colab notebook workflow.*
*See [LMSTUDIO.md](./LMSTUDIO.md) for InferenceRouter and FinetunedRouter architecture.*
*See [NEXUS_INTEGRATION.md](./NEXUS_INTEGRATION.md) for how Nexus stores benchmark results.*
